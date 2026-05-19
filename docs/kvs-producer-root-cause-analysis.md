# KVSProducer Component — Root Cause Analysis and Fix Plan

**Date:** 2026-05-18  
**Status:** Analysis complete — fixes not yet applied (read-only session)  
**Scope:** Why `com.example.KvsProducer` fails to stream video to KVS on Ubuntu Core  

---

## Executive Summary

There are **six distinct issues** stacked on top of each other, which is why the component has resisted every individual fix attempted today.

**Confirmed fact:** The Greengrass snap running on the device already has the `gstreamer-kvs` content interface plug. The connection can be made with `snap connect aws-iot-greengrass:gstreamer-kvs kvs-gstreamer:gstreamer-kvs`. Issue 7 (originally listed as "CRITICAL BLOCKER") is **not an issue** — the custom snap already has this plug.

**Issue 1 is the hardest remaining blocker:** a **fundamental design error** in the original design document assumed `kvssink` uses the AWS SDK credential chain (picking up `AWS_CONTAINER_CREDENTIALS_FULL_URI` automatically). It does not — the KVS C Producer SDK has its own credential provider that reads env vars only at element construction time and does not refresh them. Every credential-debugging attempt today stems from this one wrong assumption.

**Issue 2** (missing `libcproducer.so` due to `-maxdepth 1` in the find command) means kvssink's dependency chain is broken in the snap, causing `Gst.parse_launch()` to fail even if credentials were correctly set. This is only resolved after rebuilding the kvs-gstreamer snap with the current `snapcraft.yaml`.

The remaining issues (libdw naming, log path, restart counter never resetting) are secondary but must also be fixed for a robust component.

---

## Issue Analysis

### Issue 1 — CRITICAL (Root Cause): Wrong Design Assumption About kvssink Credentials

**What was assumed in the design doc (`.kiro/specs/kvs-video-streaming/design.md`, line 27):**

> "TES credentials via AWS credential provider chain — Greengrass automatically sets `AWS_CONTAINER_CREDENTIALS_RELATIVE_URI` for components that declare `aws.greengrass.TokenExchangeService` as a dependency. The AWS SDK credential chain picks this up, so `kvssink` inherits automatic credential refresh with no explicit refresh thread required."

**What is actually true (confirmed via AWS documentation and KVS SDK source code):**

The `kvssink` GStreamer element is built on the **KVS C Producer SDK**, which implements its **own** credential provider — NOT the AWS SDK for Python or the AWS SDK for C++ credential chain. The KVS C Producer SDK credential provider evaluates sources in this priority order:

1. `iot-certificate` element property → `IotCertCredentialProvider` (automatic refresh ✓)
2. `access-key` / `secret-key` element properties, or `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_SESSION_TOKEN` env vars → `StaticCredentialProvider` (no refresh ✗)
3. `credential-path` element property → file-based provider (refresh when file is updated by external process ✓)

**What `AWS_CONTAINER_CREDENTIALS_FULL_URI` / `AWS_CONTAINER_CREDENTIALS_RELATIVE_URI` does:**
These are standard AWS container credentials environment variables read by the **AWS SDK for Python (boto3)** and **AWS SDK for C++ with CRT**. They are NOT read by the KVS C SDK credential provider. kvssink has **no native support** for these variables.

**Consequences:**
- When the component starts, `AWS_ACCESS_KEY_ID` is not set (because Greengrass only provides `AWS_CONTAINER_CREDENTIALS_FULL_URI`)
- kvssink initialises with no credentials → PutMedia call to KVS returns 401
- The pipeline transitions to ERROR state
- `_check_pipeline_health()` sees the error and attempts restarts (max 3)
- After 3 failed restarts, the component stays in error state indefinitely

**Evidence in today's git history:**
- "cred debug" commit (d0b3fce, 17:11) added `_fetch_tes_credentials()` to manually pre-fetch from TES and set `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_SESSION_TOKEN` as env vars before calling `Gst.parse_launch()`. This is the correct workaround direction but is incomplete (see Issue 5 below).
- The STARTUP ENV debugging block was added specifically to determine whether Greengrass is injecting the TES environment variables — confirming uncertainty about whether the env vars are even present.

---

### Issue 2 — CRITICAL: libcproducer.so Missing from kvs-gstreamer Snap

**Location:** `kvs-gstreamer-snap/snap/snapcraft.yaml`, `override-build` section

**The original code (before 892d46e commit at 10:30 today):**
```bash
find "${KVS_BUILD}" -maxdepth 1 -name "*.so*" \
  ! -name "libgstkvssink.so" \
  -exec install {} "${CRAFT_PART_INSTALL}/gstreamer-kvs/lib/" \;
```

**The problem:** `libcproducer.so` (the KVS C Producer SDK library) is **not** in the top level of `${KVS_BUILD}`. It is built in a subdirectory:
```
${KVS_BUILD}/dependency/libkvscproducer/kvscproducer-src/libcproducer.so
```

With `-maxdepth 1`, this library is never found and never installed into the snap. When the Greengrass component later loads `libKinesisVideoProducer.so`, that library has a `DT_NEEDED` entry for `libcproducer.so` (or `libkvscproducer.so`). The dynamic linker searches `LD_LIBRARY_PATH` (`${GST_KVS_MOUNT}/lib`), doesn't find it, and fails.

**The failure mode:** `Gst.parse_launch()` throws a `GLib.Error` when the kvssink element factory fails to instantiate because `libgstkvssink.so` can't load its own dependency (`libKinesisVideoProducer.so` → `libcproducer.so`). The debug logging added in the "yaftww" commit (97b3882) would show "calling Gst.parse_launch()" but then an exception rather than "Gst.parse_launch() done".

**The fix (committed in 892d46e):**
```bash
find "${KVS_BUILD}" -name "*.so*" \
  ! -name "libgstkvssink.so" \
  ! -path "*/CMakeFiles/*" \
  -exec install {} "${CRAFT_PART_INSTALL}/gstreamer-kvs/lib/" \;
```

**CRITICAL NOTE: This fix is only in the source code. The snap on the device must be REBUILT and REINSTALLED for this fix to take effect.** The snapcraft.yaml change does not automatically update the running snap.

---

### Issue 3 — CRITICAL: Snap Rebuild Required After Every snapcraft.yaml Change

The `kvs-gstreamer` snap is a pre-built binary artifact. Changes to `kvs-gstreamer-snap/snap/snapcraft.yaml` only take effect after:
1. `snapcraft` is run (builds the `.snap` file)
2. The `.snap` file is copied to the device
3. `snap install --dangerous kvs-gstreamer_*.snap` is run on the device
4. The content interface is reconnected: `snap connect aws-iot-greengrass:gstreamer-kvs kvs-gstreamer:gstreamer-kvs`

Today's session committed **two separate rounds of snapcraft.yaml fixes** (505d675 at 08:17 and 892d46e at 10:30). If the snap was only rebuilt once (e.g., after 505d675 but before 892d46e), it is missing:
- The `-maxdepth 1` fix (libcproducer.so)
- The `libdw*.so*` glob fix (see Issue 4)
- The libcurl transitive dependency packages and organize entries

The iterative recipe changes (paths, platform, logging) all deploy via Greengrass and don't require a snap rebuild. But library issues require a snap rebuild.

**How to tell which snap is running:**
```bash
snap info kvs-gstreamer
# Look at the "installed" date/time
```

---

### Issue 4 — SIGNIFICANT: libdw Naming Convention (elfutils Dash-Version Format)

**What was in 505d675's organize section:**
```yaml
usr/lib/x86_64-linux-gnu/libdw.so*: gstreamer-kvs/lib/
```

**What Ubuntu 24.04 actually provides:**
The elfutils library uses an unusual naming convention: `libdw-0.190.so` (with a **dash** before the version, not a dot). The glob `libdw.so*` matches `libdw.so`, `libdw.so.1`, `libdw.so.1.0` but **does NOT match** `libdw-0.190.so`.

Result: `libdw-0.190.so` is not organized into `gstreamer-kvs/lib/`, so it is not in the snap, so `libunwind8` fails to load its optional DWARF dependency.

**The fix (committed in 892d46e):**
```yaml
usr/lib/x86_64-linux-gnu/libdw*.so*: gstreamer-kvs/lib/
```

This glob matches `libdw-0.190.so` (dash-version) as well as any `libdw.so.*` symlinks.

**Impact if missing:** `libunwind8` may still function (libdw is used for DWARF stack trace details, not core unwind). However, if `libunwind8` fails to load at all (linker error on startup), then `libglib-2.0.so` → `libunwind` chain breaks → `Gst.init(None)` fails before the pipeline is ever created.

---

### Issue 5 — SIGNIFICANT: TES Credentials Expire, No Refresh Mechanism

Even after the `_fetch_tes_credentials()` fix, TES credentials are temporary (IAM session tokens typically expire in **15 minutes to 1 hour**). The current implementation fetches credentials **once** at startup and sets them as env vars. Once kvssink is initialised with a `StaticCredentialProvider`, it does **not** re-read environment variables after initialisation.

**The failure sequence:**
1. Component starts → `_fetch_tes_credentials()` → credentials set → kvssink initialises ✓
2. Streaming begins ✓
3. Credentials expire (15–60 minutes)
4. KVS API rejects PutMedia with 401 Unauthorized
5. GStreamer bus gets an ERROR message
6. `pop_error()` catches it → `_check_pipeline_health()` triggers a restart
7. On restart, `_fetch_tes_credentials()` is called again → fresh credentials ✓
8. kvssink re-initialises with fresh credentials ✓
9. Streaming resumes

**BUT:** `MAX_PIPELINE_RESTARTS = 3` and `PIPELINE_RESTART_INTERVAL_SECONDS = 30`. After 3 restarts the component gives up permanently. For a stream running for hours, 3 credential-expiry restarts exhaust the budget quickly.

**Additionally:** The `StaticCredentialProvider` does not know the expiry time (not communicated to the KVS SDK). It treats the session token as non-expiring and does not proactively refresh before the credentials become invalid. Errors only surface when KVS API calls fail.

**The correct solution** is the `credential-path` file approach: write credentials to a file in the format kvssink expects, set `credential-path` on the kvssink element, and have a background thread refresh the file from TES **before** the current credentials expire.

kvssink credential-path file format:
```
CREDENTIALS {AccessKeyId} {Expiration} {SecretAccessKey} {SessionToken}
```
Where `{Expiration}` is ISO 8601 UTC: `2026-05-18T18:30:00Z`

kvssink checks the credential file when the current credentials approach expiry (within approximately 38 seconds of the expiration timestamp). If the file has been updated with a fresh set, it reads them automatically — no pipeline restart required.

**Alternative:** Use the `iot-certificate` kvssink property with the device's X.509 IoT certificate. This provides fully automatic credential refresh with no background thread or file management. However it requires the Greengrass device to have X.509 certificates accessible on the filesystem, and the IoT credential endpoint and role alias to be configured.

---

### Issue 6 — MINOR: kvs_log_configuration File Path Mismatch

**What the Install script does:**
```bash
cp {artifacts:path}/kvs_log_configuration {work:path}/kvs_log_configuration
```

**What the Run script does:**
```bash
cd {work:path}/run && python3 {artifacts:path}/kvs_producer.py
```

**What the KVS SDK does:** When initialising log4cplus, the KVS SDK looks for `kvs_log_configuration` in the **current working directory**. With `cd {work:path}/run`, the CWD is `{work:path}/run/`, but the file is at `{work:path}/kvs_log_configuration`.

**Result:** The KVS SDK can't find the log configuration file and falls back to its built-in default, which logs at DEBUG level. This generates **enormous** output to stderr on every Gst.parse_launch() and kvssink operation:
- `log4cplus:ERROR No appenders could be found for logger (root).`
- Thousands of DEBUG-level KVS SDK log lines

This does not prevent streaming, but it floods the component log and makes finding real errors harder.

**Fix options:**
- Copy the file to `{work:path}/run/kvs_log_configuration` in the Install script
- Set `KVS_LOG4CPLUS_CONFIG={work:path}/kvs_log_configuration` before starting Python
- Don't `cd {work:path}/run` (the directory was created for this purpose but Python doesn't require it)

---

### Issue 7 — NOT AN ISSUE: Greengrass Snap Already Has gstreamer-kvs Content Plug

**Confirmed resolved:** A custom-built Greengrass snap (not the standard one from the Snap Store) is running on the device. It declares the `gstreamer-kvs` content interface plug and the connection has been successfully established. The Greengrass snap uses `base: core24` (Python 3.12), which matches the `python3-gi` extension (`_gi.cpython-312-x86_64-linux-gnu.so`) staged from the kvs-gstreamer snap. No Python version mismatch.

**Important — how snap content interface mounts work:**

The `snap connect` command sets up a bind mount from `/snap/kvs-gstreamer/current/gstreamer-kvs/` to `/var/snap/aws-iot-greengrass/common/gstreamer-kvs`. This bind mount is applied by `snap-confine` **within the Greengrass snap's private mount namespace only** — it is not visible in the host's mount namespace. Running `ls /var/snap/aws-iot-greengrass/common/gstreamer-kvs/` from the host shell will **always** show an empty directory regardless of whether the content interface is working correctly. This caused significant confusion during debugging; the empty directory is expected and correct.

**Correct verification commands:**

```bash
# 1. Confirm the connection is recorded by snapd
snap connections aws-iot-greengrass | grep gstreamer-kvs
# Expected: content[gstreamer-kvs]  aws-iot-greengrass:gstreamer-kvs  kvs-gstreamer:gstreamer-kvs

# 2. Confirm the mount is active by entering the Greengrass process namespace
GGPID=$(pgrep -f "Greengrass.jar" | head -1)
nsenter -m --target $GGPID -- ls /var/snap/aws-iot-greengrass/common/gstreamer-kvs/lib/ | head
```

If (1) shows the connection and (2) shows library files, the GStreamer libraries are accessible and `from gi.repository import Gst` should succeed. The presence of STARTUP ENV lines in the component log provides a further confirmation that the gi/GStreamer import chain completed successfully.

**Note on the repo source:** The `greengrass-snap/snap/snapcraft.yaml` in this repository does not yet include the `gstreamer-kvs` plug declaration. If the Greengrass snap is ever rebuilt from the repo source, the plug must be added:

```yaml
plugs:
  gstreamer-kvs:
    interface: content
    content: gstreamer-kvs
    target: $SNAP_COMMON/gstreamer-kvs
```

The `greengrass-daemon` app's `plugs` list also needs `- gstreamer-kvs` added, otherwise the daemon process won't have the mount active even if the snap-level plug is declared.

---

## Dependency Chain Between Issues

```
Issue 7 (snap plug) — CONFIRMED RESOLVED on this device
    ↓
Issue 3 (snap rebuild with current snapcraft.yaml fixes)
    ↓ (without this, libcproducer.so is missing in the snap)
Issue 2 (libcproducer.so from -maxdepth fix) + Issue 4 (libdw glob)
    ↓ (without these, Gst.parse_launch() fails with "no element 'kvssink'" or linker error)
Issue 1 (credentials at startup)
    ↓ (without this, kvssink connects but auth fails immediately)
Issue 5 (credential refresh)
    ↓ (without this, stream works initially but fails after 15-60 minutes)
Issue 6 (log config path)
    → non-fatal but creates noise that hides real errors
```

---

## Interpretation of Today's Debugging History

| Time | Commit | What was being fixed | Likely root issue at that point |
|------|--------|---------------------|--------------------------------|
| 08:17 | 505d675 | Added GStreamer plugin deps to snap | Missing libraries causing GStreamer import failure |
| 10:30 | 892d46e | Fixed libdw glob, libcurl deps, -maxdepth 1, added log config | libcproducer.so missing; log config not found |
| 10:39 | 59aae9d | Updated KVS stream name and region | Wrong stream/region in defaults |
| 11:00 | b2ccec4 | Log path fixes | kvs_log_configuration CWD mismatch |
| 11:41 | 215ddfd | Removed CameraHandlerCore dependency | CameraHandlerCore not deployed; SOFT dep still caused issues |
| 12:13 | df06513 | Recipe platform fix; ShadowManager sync config | Platform matching failure on Ubuntu Core (os: linux not matching) |
| 12:24–12:46 | fe9e8b0, 5ef4f17, 255d95a | Deploy and path fixes | venv path was wrong (relative vs absolute) |
| 13:27 | dacaf33 | Logging added | Component crashing before logging visible |
| 15:00 | 948bbff | More path fixes | Work path references |
| 16:42 | baa0470 | Platform: `os: all`, `runtime: '*'` | Platform manifest not matching Ubuntu Core |
| 16:52 | 97b3882 | Step-by-step debug logging in EncodingPipeline | Unknown — where does start() hang/fail? |
| 17:11 | d0b3fce | TES credential fetch; STARTUP ENV logging | kvssink failing to authenticate (credential issue confirmed) |

The progression shows the team worked through library loading issues (Issues 2, 3, 4), path issues (Issue 6 and venv), and has now reached the credential layer (Issue 1). The "STARTUP ENV" logging will determine whether Greengrass is injecting `AWS_CONTAINER_CREDENTIALS_FULL_URI` — which is the **next diagnostic milestone**.

---

## Specific Code Problems

### Problem A: `_fetch_tes_credentials()` — incomplete but directionally correct

**File:** `greengrass-components/artifacts/com.example.KvsProducer/1.0.0/gstreamer_pipeline.py`

```python
def _fetch_tes_credentials():
    uri = os.environ.get("AWS_CONTAINER_CREDENTIALS_FULL_URI", "")
    if not uri:
        rel = os.environ.get("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "")
        if rel:
            uri = f"http://127.0.0.1:2113{rel}"  # ← Port 2113 is hardcoded GUESS; TES port is dynamic
    ...
    os.environ["AWS_ACCESS_KEY_ID"] = creds["AccessKeyId"]
    os.environ["AWS_SECRET_ACCESS_KEY"] = creds["SecretAccessKey"]
    os.environ["AWS_SESSION_TOKEN"] = creds.get("Token", creds.get("SessionToken", ""))
    # ← Missing: creds["Expiration"] is not stored anywhere
    # ← Missing: AWS_CREDENTIAL_EXPIRATION is not set (NOT supported by KVS SDK anyway)
    # ← The credential-path approach should be used instead of env vars
```

The function correctly uses `AWS_CONTAINER_CREDENTIALS_FULL_URI` as the primary path (Greengrass sets this). The port-2113 fallback is incorrect (TES port is embedded in the FULL_URI, not fixed). The missing element is that credentials are set as env vars which kvssink reads only at element construction time — there is no mechanism to push new credentials into a running kvssink element.

### Problem B: kvssink pipeline string — no credential-path property

**File:** `greengrass-components/artifacts/com.example.KvsProducer/1.0.0/gstreamer_pipeline.py`

```python
pipeline_str = (
    f"appsrc name=src ... "
    f"! h264parse ! kvssink stream-name={self._stream_name} "
    f"aws-region={self._region}"
    # ← Missing: credential-path={cred_file_path}
)
```

The kvssink element has no `credential-path` property set, which means it uses the static env var provider. To enable credential refresh, this property must point to a file that a background thread keeps updated.

### Problem C: MAX_PIPELINE_RESTARTS too low for credential-expiry restarts

**File:** `greengrass-components/artifacts/com.example.KvsProducer/1.0.0/kvs_producer.py`

```python
MAX_PIPELINE_RESTARTS = 3
```

With the current env-var approach, each credential expiry causes a pipeline error → restart → new credential fetch. With only 3 restarts and hourly credentials, the component would go permanently offline after 3–4 hours.

### Problem D: Gst.parse_launch() return value not validated

**File:** `greengrass-components/artifacts/com.example.KvsProducer/1.0.0/gstreamer_pipeline.py`

```python
self._pipeline = Gst.parse_launch(pipeline_str)
self._appsrc = self._pipeline.get_by_name("src")  # ← would AttributeError if pipeline is None
```

`Gst.parse_launch()` raises `GLib.Error` if the pipeline string is invalid. This propagates up correctly. However, if `Gst.parse_launch()` returns a `Gst.Bin` rather than a `Gst.Pipeline` (for multi-element strings without a top-level pipeline wrapper — unlikely here but possible), `get_by_name()` would still work but `set_state()` behaviour might differ.

More importantly, if `kvssink` is not in the plugin registry (because the content interface isn't connected), `Gst.parse_launch()` throws with "no element 'kvssink'" which would appear in logs.

### Problem E: ShadowManager sync config — merge payload format

**File:** `deploy_greengrass_components.py`

```python
sync_config = _json.dumps({
    "synchronize": {
        "coreThing": {
            "namedShadows": ["kvs-config", "model-config"]
        }
    }
})
component_config['aws.greengrass.ShadowManager']['configurationUpdate'] = {
    'merge': sync_config
}
```

The `merge` value must be a **JSON string** (not a dict) when passed to the Greengrass deployment API. This looks correct — `sync_config` is already `json.dumps(...)`. However, the ShadowManager configuration schema requires the merge to be under a specific key path. Verify against the ShadowManager documentation that this structure is correct for the version being deployed.

---

## Required Fix Plan

### Step 1: Confirm Snap Content Interface Is Connected

The custom Greengrass snap on the device has the `gstreamer-kvs` plug. Confirm the connection is active:

```bash
snap connections aws-iot-greengrass | grep gstreamer-kvs
# Expected: content[gstreamer-kvs]  aws-iot-greengrass:gstreamer-kvs  kvs-gstreamer:gstreamer-kvs
```

If the connection was dropped (e.g., after a snap refresh), reconnect it:
```bash
snap connect aws-iot-greengrass:gstreamer-kvs kvs-gstreamer:gstreamer-kvs
```

To confirm the libraries are actually visible from within the Greengrass process namespace (not from the host — see Issue 7 for why the host view is always empty):
```bash
GGPID=$(pgrep -f "Greengrass.jar" | head -1)
nsenter -m --target $GGPID -- ls /var/snap/aws-iot-greengrass/common/gstreamer-kvs/lib/ | head
```

If the connection is present and the nsenter command shows library files, proceed to Step 2.

### Step 2: Rebuild kvs-gstreamer Snap with Current snapcraft.yaml

The current `kvs-gstreamer-snap/snap/snapcraft.yaml` contains all the required fixes. Run:

```bash
cd kvs-gstreamer-snap
snapcraft  # requires snapcraft + LXD/multipass
scp kvs-gstreamer_1.0.0_amd64.snap ubuntu@<device>:~
```

On device:
```bash
snap install --dangerous ~/kvs-gstreamer_1.0.0_amd64.snap
snap connect aws-iot-greengrass:gstreamer-kvs kvs-gstreamer:gstreamer-kvs
```

After reinstall, verify the key libraries are present by entering the Greengrass process namespace (the host-side path always appears empty — see Issue 7):
```bash
GGPID=$(pgrep -f "Greengrass.jar" | head -1)
nsenter -m --target $GGPID -- ls /var/snap/aws-iot-greengrass/common/gstreamer-kvs/lib/
# Must show: libgstreamer-1.0.so*, libcproducer.so*, libKinesisVideoProducer.so*, etc.
nsenter -m --target $GGPID -- ls /var/snap/aws-iot-greengrass/common/gstreamer-kvs/lib/gstreamer-1.0/
# Must show: libgstkvssink.so
```

### Step 3: Verify TES Credential Injection

Deploy the current component code (with STARTUP ENV logging) and check the component log:

```bash
cat /var/snap/aws-iot-greengrass/common/greengrass/v2/logs/com.example.KvsProducer.log | grep "STARTUP ENV"
```

Expected output:
```
STARTUP ENV: AWS_ACCESS_KEY_ID=UNSET       ← expected (Greengrass provides FULL_URI, not direct keys)
STARTUP ENV: AWS_CONTAINER_CREDENTIALS_FULL_URI=http://localhost:XXXXX/2016-11-01/credentialprovider/
STARTUP ENV: AWS_CONTAINER_CREDENTIALS_RELATIVE_URI=UNSET
STARTUP ENV: AWS_CONTAINER_AUTHORIZATION_TOKEN=<some-token>
STARTUP ENV: AWS_DEFAULT_REGION=eu-west-1
```

If `AWS_CONTAINER_CREDENTIALS_FULL_URI` is UNSET, TES is not injecting env vars. This would indicate a Greengrass nucleus configuration issue or the TES component is not running correctly.

Also check for TES credential fetch result:
```bash
cat /var/snap/aws-iot-greengrass/common/greengrass/v2/logs/com.example.KvsProducer.log | grep "TES:"
```

### Step 4: Implement Credential-Path Refresh (Code Change Required)

Replace the env-var credential approach with the `credential-path` file approach for reliable long-running streaming.

**Changes needed in `gstreamer_pipeline.py`:**

1. Modify `EncodingPipeline.__init__()` to accept a `credential_path` parameter
2. Write initial credentials to the file in kvssink format before `Gst.parse_launch()`
3. Add `credential-path={credential_path}` to the kvssink pipeline string
4. Add a background thread to `EncodingPipeline` that periodically refreshes the credential file from TES before expiry

Credential file format (must be exact):
```
CREDENTIALS {AccessKeyId} {Expiration} {SecretAccessKey} {SessionToken}
```

Where `{Expiration}` is from the TES response's `Expiration` field, formatted as `YYYY-MM-DDTHH:mm:SSZ`.

The background refresh thread should:
- Parse the expiration time from the TES response
- Sleep until 120 seconds before expiry
- Call TES again to get fresh credentials
- Overwrite the credential file with the new credentials
- kvssink detects the file change at its ~38-second pre-expiry check interval and picks up the new credentials

**The credential file should be placed at:** `{work:path}/run/kvs_credentials`

5. Increase `MAX_PIPELINE_RESTARTS` in `kvs_producer.py` (e.g., from 3 to 10) as a safety net for cases where the credential refresh thread fails.

### Step 5: Fix kvs_log_configuration Path

**Option A (simplest):** In the Install script, also copy to the run directory:
```bash
mkdir -p {work:path}/run && \
cp {artifacts:path}/kvs_log_configuration {work:path}/run/kvs_log_configuration && \
```

**Option B:** Set `KVS_LOG4CPLUS_CONFIG` in the Run script before `cd {work:path}/run`:
```bash
export KVS_LOG4CPLUS_CONFIG="{work:path}/kvs_log_configuration" && \
cd {work:path}/run && \
```

### Step 6: Add Error Handling After Gst.parse_launch()

In `EncodingPipeline.start()`:
```python
self._pipeline = Gst.parse_launch(pipeline_str)
if self._pipeline is None:
    raise RuntimeError("Gst.parse_launch() returned None — check GST_PLUGIN_PATH for kvssink")
```

And similarly in `CapturePipeline.start()`.

---

## Verification Checklist

After implementing all fixes, verify in order:

1. `snap connections aws-iot-greengrass | grep gstreamer-kvs` → shows connected interface
2. `nsenter -m --target $(pgrep -f "Greengrass.jar" | head -1) -- ls /var/snap/aws-iot-greengrass/common/gstreamer-kvs/lib/libcproducer.so*` → file exists (must be checked from within the Greengrass process namespace; host-side `ls` of that path always shows empty)
3. STARTUP ENV log shows `AWS_CONTAINER_CREDENTIALS_FULL_URI` is set (not UNSET)
4. TES log line shows "TES: credentials fetched OK"
5. GStreamer debug: "calling Gst.parse_launch()" → "Gst.parse_launch() done" → "set_state(PLAYING) returned" — all four lines visible
6. No kvssink errors in the log within the first 5 minutes
7. KVS stream shows video in the AWS Console
8. After 20+ minutes, stream still active (credential refresh working)

---

## Confirmed Non-Issues (Initially Suspected)

### Python Version — Resolved

**Confirmed:** The `aws-iot-greengrass` snap uses `base: core24`, which provides Python 3.12. The kvs-gstreamer snap also uses `base: core24` and stages `python3-gi` from Ubuntu 24.04, providing `_gi.cpython-312-x86_64-linux-gnu.so`. These match. **No Python version mismatch.**

### GStreamer Plugin Registry and gst-plugin-scanner Subprocess

The Run script sets `GST_PLUGIN_SCANNER` to the binary inside the snap content interface. This binary will be invoked as a subprocess by GStreamer on the first run (to build the plugin registry). Inside strict snap confinement, executing arbitrary binaries from the content interface path may be restricted by AppArmor.

If `gst-plugin-scanner` fails (AppArmor denial), GStreamer falls back to in-process plugin loading, which should work. However, in-process loading of a broken plugin (e.g., a GL plugin missing EGL libs) could crash the entire process instead of being isolated.

**Monitor for:** AppArmor denial messages in `dmesg` or `/var/log/syslog` when the component starts.

---

## Summary Table

| Issue | Severity | Status | Action Required |
|-------|----------|--------|-----------------|
| Greengrass snap missing gstreamer-kvs plug | NOT AN ISSUE | Confirmed present — connection works on device | None required |
| kvssink credential design error + no refresh | CRITICAL | Partial fix (d0b3fce), needs credential-path approach | Change `gstreamer_pipeline.py` to use credential-path + refresh thread |
| libcproducer.so missing (-maxdepth 1) | CRITICAL | Fix in source (892d46e), needs snap rebuild | Rebuild + reinstall kvs-gstreamer snap |
| libdw wrong glob (libdw.so* vs libdw*.so*) | SIGNIFICANT | Fix in source (892d46e), needs snap rebuild | Same snap rebuild as above |
| kvs_log_configuration path mismatch | MINOR | Open | Fix Install script to also copy to `{work:path}/run/` |
| MAX_PIPELINE_RESTARTS too low | MINOR | Open | Increase from 3 to ≥10 in `kvs_producer.py` |
| _pipeline_restart_count never resets | SIGNIFICANT | Open | Reset counter to 0 after sustained healthy streaming |
| GStreamer buffer unmap not in finally block | MINOR | Open | Wrap callback body in try/finally to ensure buf.unmap() always called |
| update_bitrate() never called | MINOR | Open | Call from push_frame() in EncodingPipeline for accurate health metrics |
| opencv-python-headless unpinned | MINOR | Open | Pin to tested version in requirements.txt |
| Python version mismatch | NOT AN ISSUE | Both snaps use core24 (Python 3.12) | None required |

---

## Addendum: Secondary Code Review Findings

This section documents additional observations from a full review of the remaining source files (`shadow_config.py`, `health_monitor.py`, `frame_annotator.py`, `requirements.txt`). None of these findings are primary blockers, but they are worth addressing for robustness.

### Finding A: `update_bitrate()` Is Never Called — Bitrate Metric Always 0.0

**File:** `health_monitor.py`

`HealthMonitor.update_bitrate(bytes_sent, elapsed_seconds)` is defined but never called from `kvs_producer.py`. The `bitrate_kbps` field in every health metrics message published to `camera/kvs-status` is always `0.0`.

This is a monitoring gap, not a streaming failure. However, it means operators cannot detect bandwidth issues or abnormal encoding bitrates from the health metric topic. If bitrate monitoring is needed downstream, `push_frame()` in `EncodingPipeline` would be the right place to track bytes sent and call `update_bitrate()`.

### Finding B: requirements.txt Has Unpinned Dependencies

**File:** `requirements.txt`

```
awsiotsdk==1.21.0
opencv-python-headless
numpy
```

`awsiotsdk` is correctly pinned. `opencv-python-headless` and `numpy` have no version pins. This means `pip install` resolves whatever is current on PyPI at install time. A future breaking release of either package could cause the Install lifecycle step to fail, or cause subtle runtime incompatibilities.

**Recommendation:** Pin both packages to known-good versions. The current install should be tested to confirm which versions were resolved, and those pinned:
```
awsiotsdk==1.21.0
numpy==1.26.4
opencv-python-headless==4.9.0.80
```
(Verify actual compatible versions for Python 3.12 + manylinux2014_x86_64.)

This does not explain today's failures.

### Finding C: GStreamer Callback Buffer Lifecycle — No Exception Guard on unmap()

**File:** `gstreamer_pipeline.py`, `CapturePipeline._on_raw_sample()`

```python
success, map_info = buf.map(Gst.MapFlags.READ)
if success:
    frame = np.frombuffer(map_info.data, dtype=np.uint8).reshape((h, w, 3))
    if self._on_raw_frame_cb:
        self._on_raw_frame_cb(frame.copy(), time.time())
    buf.unmap(map_info)
return Gst.FlowReturn.OK
```

The `buf.unmap(map_info)` call sits inside `if success:` but is not guarded by `try/finally`. If `_on_raw_frame_cb` raises an uncaught exception, `buf.unmap(map_info)` is never called, leaking the GStreamer buffer mapping.

The consequence: GStreamer's buffer pool may eventually exhaust mapped slots, causing the pipeline to stall or go into FLUSHING state. This would surface as frames stopping but no ERROR bus message.

**Fix:** Wrap with `try/finally`:
```python
if success:
    frame = np.frombuffer(map_info.data, dtype=np.uint8).reshape((h, w, 3))
    try:
        if self._on_raw_frame_cb:
            self._on_raw_frame_cb(frame.copy(), time.time())
    finally:
        buf.unmap(map_info)
```

The same pattern applies to `_on_snapshot_sample()`.

### Finding D: PYTHONPATH + venv Interaction Is Correct By Design

The Run script sets `PYTHONPATH` before activating the venv:
```bash
export PYTHONPATH="${GST_KVS_MOUNT}/lib/python3" && \
source {work:path}/venv/bin/activate && \
```

This is intentional and correct. The venv's `activate` script does not reset `PYTHONPATH` — it only modifies `PATH` and `VIRTUAL_ENV`. After activation:

- `import gi` → resolved from `PYTHONPATH` (the snap content interface — correct, `gi` is not pip-installable without header files)
- `import awsiot`, `import cv2`, `import numpy` → resolved from venv site-packages

This separation is the only way to use the snap-provided `python3-gi` (which is a native extension that requires the GStreamer libraries at `LD_LIBRARY_PATH`) together with pip-installed packages. No issue here.

### Finding E: Shadow Delta Subscription Via MQTT Proxy, Not Local IPC

`kvs_producer.py` subscribes to shadow delta updates via `subscribe_to_iot_core()` (MQTT proxy) rather than via a Greengrass local shadow subscription:

```python
delta_topic = f"$aws/things/{self._thing_name}/shadow/name/kvs-config/update/delta"
self._ipc_client.subscribe_to_iot_core(topic_name=delta_topic, ...)
```

This works, but has two implications:

1. **Round-trip through IoT Core:** The delta travels from the cloud shadow service to IoT Core, to the Greengrass MQTT proxy, and back to the component. This introduces latency (seconds) compared to local shadow notification.

2. **Requires MQTT connectivity:** If the device loses internet connectivity temporarily, delta updates are buffered and may arrive in burst when connectivity is restored. The `_on_shadow_delta` handler processes them one at a time, which is fine.

A more robust alternative is to subscribe to `aws.greengrass#SubscribeToNamedShadowDeltaUpdate` via local IPC (using ShadowManager), which would deliver updates even without cloud connectivity. However, this requires the `aws.greengrass#SubscribeToNamedShadowDeltaUpdate` IPC operation to be added to the recipe's accessControl, and ShadowManager must be running locally. The current approach is functional but not offline-resilient.

This does not explain today's failures.

### Finding F: STARTUP ENV Presence/Absence Is the Fastest Diagnostic Gate

**File:** `greengrass-components/artifacts/com.example.KvsProducer/1.0.0/kvs_producer.py` and `gstreamer_pipeline.py`

`gstreamer_pipeline.py` runs these statements at **module import time** (before `main()` is ever called):

```python
import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst
```

`kvs_producer.py` imports `gstreamer_pipeline` at the top:

```python
from gstreamer_pipeline import CapturePipeline, EncodingPipeline
```

This means the GStreamer/gi import chain runs **before** the STARTUP ENV block in `main()`. If `LD_LIBRARY_PATH` is wrong, `GI_TYPELIB_PATH` is missing, or the snap content interface is not connected, Python raises an `ImportError` and the process dies before `main()` is ever reached — meaning **no STARTUP ENV log lines appear at all**.

This gives an unambiguous diagnostic gate:

| What the log shows | Conclusion |
|---|---|
| No STARTUP ENV lines, no output | Python import failed — gi/GStreamer unavailable. Issue 7 (snap plug) or missing snap libraries is the active blocker |
| STARTUP ENV lines present, TES log present | gi import succeeded, snap content interface is working. Credential or pipeline issue is the active blocker |
| STARTUP ENV lines present, "calling Gst.parse_launch()" present, "Gst.parse_launch() done" ABSENT | `Gst.parse_launch()` itself failed — likely "no element 'kvssink'" (Issue 2: libcproducer.so missing, snap not rebuilt) |
| "Gst.parse_launch() done" present, "set_state(PLAYING) returned" present, then ERROR | Pipeline created but kvssink auth failed (Issue 1: credentials) |

**The most important diagnostic action on the device is:**
```bash
grep "STARTUP ENV" /var/snap/aws-iot-greengrass/common/greengrass/v2/logs/com.example.KvsProducer.log
```
If that returns nothing, check the snap connection first, not credentials.

### Finding G: Pipeline Restart Counter Never Resets — Restarts Are Permanently Exhausted After 3 Errors

**File:** `greengrass-components/artifacts/com.example.KvsProducer/1.0.0/kvs_producer.py`

`_pipeline_restart_count` increments on each restart but is **never reset to zero**, even when the pipeline runs successfully:

```python
def _check_pipeline_health(self):
    ...
    if self._pipeline_restart_count >= MAX_PIPELINE_RESTARTS:
        logger.error("Max pipeline restarts (%d) reached, giving up", MAX_PIPELINE_RESTARTS)
        return
    ...
    self._stop_pipelines()
    self._start_pipelines()
    self._pipeline_restart_count += 1  # ← incremented, never decremented/reset
    self._last_pipeline_restart = now
```

Scenario with the env-var credential approach (TES tokens valid for ~1 hour):

| Time | Event |
|------|-------|
| T+0h | Component starts, credentials fetched, streaming begins |
| T+1h | Credentials expire → pipeline ERROR → restart 1 (count=1) → fresh credentials → streaming OK |
| T+2h | Credentials expire → restart 2 (count=2) → streaming OK |
| T+3h | Credentials expire → restart 3 (count=3) → streaming OK |
| T+4h | Credentials expire → **count=3 ≥ MAX (3)** → "giving up" → permanently offline |

Even if the pipeline was healthy for hours between restarts, the counter keeps climbing. A transient camera disconnect (restart 1) followed by a GStreamer bus error from a codec issue (restart 2) and one credential expiry (restart 3) exhausts the budget in less than an hour.

**The immediate fix** (before implementing credential-path): Reset `_pipeline_restart_count` after the pipeline has been running successfully for some time — for example, after `ERROR_THRESHOLD_SECONDS` of successful frames:

```python
# In the main loop, after checking frame sent time:
if (self._last_frame_sent_time > 0
        and now - self._last_frame_sent_time < ERROR_THRESHOLD_SECONDS):
    # Pipeline is healthy — reset restart counter so transient errors don't exhaust budget
    if self._pipeline_restart_count > 0:
        self._pipeline_restart_count = 0
```

Or more simply, always reset the count when a restart succeeds (i.e., when a new `_start_pipelines()` call completes without exception and the next health check sees PLAYING state).

### Finding H: ROLLBACK Deployment Policy Creates a Diagnostic Trap

**File:** `deploy_greengrass_components.py`, `create_deployment()`:

```python
deploymentPolicies={
    'failureHandlingPolicy': 'ROLLBACK',
    ...
}
```

With `ROLLBACK` policy: if the component crashes immediately on the new deployment (which it does for all versions when the snap plug is missing), Greengrass marks the deployment as FAILED and **rolls back to the previous deployment**. The previous deployment also uses a component version that crashes (since the snap plug was never present). This creates a cycle:

1. Deploy v1.0.X → crashes at import → FAILED → rollback to v1.0.X-1
2. v1.0.X-1 also crashes → no further rollback possible → stuck
3. Next deploy attempt → same cycle

**The consequence:** When debugging, you may be looking at logs from a rolled-back version rather than the latest version you just deployed. The component log shows the version that's actually running, which may be older than expected.

**How to verify which version is actually running:**
```bash
# Check which component version is currently active
cat /var/snap/aws-iot-greengrass/common/greengrass/v2/logs/greengrass.log | grep "com.example.KvsProducer" | grep "version"
```

Or check the deployment status via the AWS console → IoT Core → Greengrass → Deployments.

**This is not a bug in the deploy script** — ROLLBACK is the correct policy for production. But it means that during debugging, each failed deployment attempt may revert to older code, making it appear that new logging or fixes haven't taken effect.
