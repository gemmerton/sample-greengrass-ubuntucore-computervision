# KVS Video Streaming — Fix Log and Lessons Learned

**Date:** 2026-05-19  
**Status:** ✅ LIVE H.264 VIDEO STREAMING TO KVS CONFIRMED WORKING  
**Device:** Ubuntu Core 24, amd64, Logitech BRIO 4K USB camera at `/dev/video1`  
**Component version at first successful stream:** `com.example.KvsProducer` 1.0.27  

This document records every code change that was required to get from "component crashes immediately" to "live video visible in the KVS console", in the order they were applied. Each entry explains what was broken, what the symptom was, and why the fix works. This is the authoritative reference for understanding the current state of the component and for diagnosing regressions.

---

## Fix 1 — Silent Install abort due to read-only `kvs_log_configuration`

**File:** `greengrass-components/recipes/com.example.KvsProducer-1.0.0.yaml` (Install script)  
**Symptom:** The `gst-plugins/` directory in the work path was always empty after Install, causing GStreamer to fail at import or pipeline creation with "no element" errors. No error was visible in the log because the script exited silently.  
**Root cause:** The Install script used `set -e`. It tried to `cp kvs_log_configuration {work:path}/kvs_log_configuration`. On a re-deployment, that file already existed with permissions `440` (read-only) from a previous install. The `cp` failed with `Permission denied`, and `set -e` aborted the entire script at that line — before the plugin copy loop ever ran.  
**Fix:** Add `rm -f {work:path}/kvs_log_configuration` immediately before the `cp`.  
**Lesson:** With `set -e` in lifecycle scripts, any failing command silently aborts the rest of the script. Always `rm -f` before overwriting files in `{work:path}` because a previous deployment may have left them with restrictive permissions.

---

## Fix 2 — Stale `gst-plugins` and `gst-registry` directories

**File:** `greengrass-components/recipes/com.example.KvsProducer-1.0.0.yaml` (Install script)  
**Symptom:** After a deployment, old plugin `.so` files from a previous version remained in the work path. GStreamer loaded the stale registry and either crashed or used the wrong plugins.  
**Fix:** Add `rm -rf {work:path}/gst-plugins` and `rm -rf {work:path}/gst-registry` before recreating those directories.  
**Lesson:** `{work:path}` persists across deployments. Treat every Install as needing a clean slate for directories that are populated by the script itself.

---

## Fix 3 — Orc JIT SIMD crash in `libgstvideoconvertscale.so`

**File:** `greengrass-components/recipes/com.example.KvsProducer-1.0.0.yaml` (Run script)  
**Symptom:** The component crashed with a segfault (faulthandler traceback) inside `libgstvideoconvertscale.so` during `Gst.init()` or pipeline creation.  
**Root cause:** GStreamer's `liborc` generates SIMD (SSE/AVX) machine code at runtime using `orc_program_compile()`. On this device's hardware configuration, the JIT-compiled code caused a SIMD fault.  
**Fix:** Set `ORC_CODE=backup` in the Run script environment before starting Python. This tells liborc to skip JIT compilation and use the pure-C fallback implementations.  
**Lesson:** `ORC_CODE=backup` is a safe performance trade-off for headless edge devices. The pure-C path is measurably slower (~10–20%) for pixel operations but eliminates the crash. If the device is upgraded or the snap is rebuilt, test without this env var first; on most hardware it is not needed.

---

## Fix 4 — numpy/opencv not importable in venv (PYTHONPATH clobbered)

**File:** `greengrass-components/recipes/com.example.KvsProducer-1.0.0.yaml` (Run script)  
**Symptom:** `ModuleNotFoundError: No module named 'numpy'` at startup even though numpy was listed in `requirements.txt`.  
**Root cause:** The Greengrass snap provides numpy and opencv via `PYTHONPATH` (pointing to `/snap/aws-iot-greengrass/x1/lib/python3.12/site-packages`). The Run script had `export PYTHONPATH="${GST_KVS_MOUNT}/lib/python3"` which **replaced** the entire `PYTHONPATH`, discarding the snap's packages path. pip's "Requirement already satisfied" at install time masked this: pip saw numpy in `PYTHONPATH` and skipped installation, but `PYTHONPATH` was then overwritten at runtime.  
**Fix:** Append rather than replace: `export PYTHONPATH="${GST_KVS_MOUNT}/lib/python3${PYTHONPATH:+:${PYTHONPATH}}"`. The `${VAR:+:${VAR}}` shell idiom appends `:$PYTHONPATH` only when `PYTHONPATH` is already set, avoiding a trailing colon on first boot.  
**Lesson:** Always append to `PYTHONPATH`, `LD_LIBRARY_PATH`, and similar path variables — never assign. The Greengrass snap injects its own paths into the environment; overwriting them breaks packages it ships. The `${PYTHONPATH:+:${PYTHONPATH}}` pattern is the safe idiom.

---

## Fix 5 — Wrong camera device path

**File:** `greengrass-components/recipes/com.example.KvsProducer-1.0.0.yaml` (DefaultConfiguration)  
**Symptom:** GStreamer error: `Cannot identify device '/dev/video0': No such file or directory`  
**Root cause:** The Logitech BRIO 4K creates four `/dev/videoN` entries (`video1`–`video4`) on this system. There is no `/dev/video0`. The recipe defaulted to `/dev/video0`.  
**Fix:** Change `CameraDevice` default to `/dev/video1`.  
**Lesson:** `/dev/video0` is not guaranteed. USB cameras that expose multiple virtual interfaces (e.g., the BRIO's multiple aspect-ratio views) consume multiple `/dev/videoN` slots. The first entry may not be 0 if other video devices exist or were registered first. Check `cat /sys/class/video4linux/videoN/name` to identify the correct node. On this device: `video1` = "Logitech BRIO" (index 0, main capture).

---

## Fix 6 — Greengrass `config.tlog` retains old `CameraDevice` value across deployments

**File:** `deploy_greengrass_components.py` (`create_deployment` method)  
**Symptom:** Even after changing `CameraDevice` in the recipe's `DefaultConfiguration`, the component kept using `/dev/video0`. The expanded Run script in `config.tlog` showed the old value.  
**Root cause:** Greengrass stores component configuration in `config.tlog`. `DefaultConfiguration` in the recipe only sets the initial value at first deployment. Subsequent deployments that send no `configurationUpdate` inherit whatever was in `config.tlog` — the old value. Once a value is written to `config.tlog` it persists until explicitly overwritten by a deployment merge.  
**Fix:** In `create_deployment` and `get_components_from_recipes`, extract non-`accessControl` fields from `DefaultConfiguration` and include them as `configurationUpdate.merge` in the deployment. This ensures every deployment explicitly sets configuration values, so recipe changes reach the device.  
**Important caveat:** A root `reset: ['']` was deliberately avoided — it wipes lifecycle scripts from the config tree before the recipe content is restored, leaving Greengrass with no Run script. Field-level resets and merges are safe.  
**Lesson:** Changing `DefaultConfiguration` in a recipe is not enough to change configuration on a device that has already been deployed. The deployment must include a `configurationUpdate.merge` with the new values. Think of `DefaultConfiguration` as "first-boot defaults", not "always current truth". The deployment script now automatically propagates recipe defaults on every deploy.

---

## Fix 7 — Capture pipeline `not-negotiated`: camera outputs MJPEG, not raw YUV

**File:** `greengrass-components/artifacts/com.example.KvsProducer/1.0.0/gstreamer_pipeline.py` (`CapturePipeline.start`)  
**Symptom:** GStreamer error: `streaming stopped, reason not-negotiated (-4)` from `GstV4l2Src`. The pipeline was starting, reaching PLAYING, then immediately failing.  
**Root cause:** The original capture pipeline placed `video/x-raw,width=640,height=480,framerate=15/1` caps directly on v4l2src output. The Logitech BRIO negotiates **MJPEG** (`image/jpeg`) by default — it does not offer raw YUV as its first-preference format. GStreamer tried to satisfy the `video/x-raw` caps constraint directly from v4l2src, found no compatible format, and returned `NOT_NEGOTIATED`.  
**Fix:** Replace `video/x-raw,...` with `image/jpeg,width=640,height=480,framerate=15/1 ! jpegdec`. The `jpegdec` element decodes MJPEG to raw I420/YV12, which downstream elements can work with.  
**Why MJPEG is better:** MJPEG is decoded on-device (CPU) but uses significantly less USB bandwidth than raw YUV at the same resolution. The BRIO supports MJPEG up to 90fps at 640×480.  
**Lesson:** Modern UVC cameras (especially Logitech) prefer MJPEG. Never assume a USB camera supports `video/x-raw` as its primary negotiated format. Check with `v4l2-ctl --list-formats-ext` or start without explicit caps and observe what GStreamer negotiates. `libgstjpeg.so` (already in the plugin set) provides both `jpegenc` and `jpegdec`.

---

## Fix 8 — KVS rejects stream: missing buffer timestamps (PTS)

**File:** `greengrass-components/artifacts/com.example.KvsProducer/1.0.0/gstreamer_pipeline.py` (`EncodingPipeline.start`)  
**Symptom:** KVS console showed "Live" timer ticking (data arriving) but no video rendered. Logs showed `Status: 0x52000062` (`STATUS_DUPLICATE_FRAGMENT_COUNT_LIMIT_REACHED`) at a fixed timecode, repeating endlessly.  
**Root cause:** `push_frame()` created buffers with no PTS set. Without `do-timestamp=true` on `appsrc`, pushed buffers retain `GST_CLOCK_TIME_NONE`. KVS fragments were either at timecode 0 or had invalid timing, causing the same fragment to be submitted repeatedly and rejected by KVS until the duplicate-fragment limit was hit.  
**Fix:** Add `do-timestamp=true` to the appsrc element. This instructs appsrc to stamp each pushed buffer with the pipeline's running time at the moment of push.  
**Lesson:** `appsrc` with `format=time is-live=true` does NOT automatically timestamp buffers unless `do-timestamp=true` is also set. KVS is strict about fragment timecodes — a stream without proper PTS will appear to "arrive" (bytes reach the service) but will produce no playable video.

---

## Fix 9 — KVS rejects fragments: no keyframe at fragment boundary

**File:** `greengrass-components/artifacts/com.example.KvsProducer/1.0.0/gstreamer_pipeline.py` (`EncodingPipeline.start`)  
**Symptom:** Same `0x52000062` errors as Fix 8 (present alongside the timestamp issue).  
**Root cause:** KVS creates a new fragment every ~2 seconds. Each fragment must start with an H.264 IDR (keyframe). Without a `key-int-max` setting, x264enc with `tune=zerolatency` may not place keyframes at intervals that align with KVS fragment boundaries.  
**Fix:** Add `key-int-max={framerate * 2}` to x264enc (30 frames at 15fps = keyframe every 2 seconds). Also add `config-interval=-1` to `h264parse` to repeat SPS/PPS NAL units before every keyframe. The SPS/PPS carry the codec initialisation data the player needs to start decoding mid-stream.  
**Lesson:** KVS requires each fragment to begin with an IDR frame and the decoder must have seen the SPS/PPS before it can decode. Set `key-int-max` to a value that divides evenly into KVS's fragment duration (default 2s). `config-interval=-1` on h264parse is standard practice for any HLS/DASH/KVS streaming pipeline.

---

## Fix 10 — KVS rejects stream: H.264 Hi444PP profile unsupported

**File:** `greengrass-components/artifacts/com.example.KvsProducer/1.0.0/gstreamer_pipeline.py` (`EncodingPipeline.start`)  
**Symptom:** KVS console error: "Unsupported codec, codec ID: avc.f40016 (H.264 ???@2.2)"  
**Root cause:** `videoconvert ! x264enc` with BGR input. BGR is a 4:4:4 chroma format. `videoconvert` produced Y444 output (also 4:4:4). `x264enc` saw Y444 input and automatically selected **H.264 High 4:4:4 Predictive profile** (profile_idc=244, `0xf4` in the AVC codec tag). KVS only supports H.264 **Baseline (66), Main (77), and High (100)** profiles. Profile 244 is rejected outright.  
**Fix:** Insert `video/x-raw,format=I420` caps between `videoconvert` and `x264enc`. This forces `videoconvert` to produce standard YUV 4:2:0 output. x264enc then encodes as H.264 High profile (profile_idc=100), which KVS accepts.  
**Lesson:** Any time BGR/RGB frames are fed into x264enc via videoconvert, explicitly request I420 output. Without the caps constraint, GStreamer preserves the 4:4:4 chroma of the source, resulting in a profile that most streaming services (KVS, HLS, WebRTC) reject. The codec ID in the KVS error message decodes as: first byte = profile_idc in hex (`f4` = 244 = Hi444PP; `64` = 100 = High).

---

## Final Working Pipeline Configuration

### Capture pipeline (`CapturePipeline.start`)

```
v4l2src device=/dev/video1
! image/jpeg,width=640,height=480,framerate=15/1
! jpegdec
! tee name=t
  t. ! queue ! videoconvert ! video/x-raw,format=BGR ! appsink name=raw_sink emit-signals=true
  t. ! queue ! videorate ! video/x-raw,framerate=1/10 ! jpegenc ! appsink name=snapshot_sink emit-signals=true
```

### Encoding pipeline (`EncodingPipeline.start`)

```
appsrc name=src format=time is-live=true do-timestamp=true
  caps=video/x-raw,format=BGR,width=640,height=480,framerate=15/1
! videoconvert
! video/x-raw,format=I420
! x264enc tune=zerolatency key-int-max=30
! h264parse config-interval=-1
! kvssink stream-name=ge-demo-stream aws-region=eu-west-1
```

---

## Previously Known Issues — All Resolved

All production reliability issues identified at initial streaming milestone have been fixed (commit `5e51ea6`, 2026-05-19).

### ✅ Fix 11: TES credential refresh via credential file

**Was:** `gstreamer_pipeline.py` fetched TES credentials once at startup, set them as env vars, and kvssink used a `StaticCredentialProvider` that never refreshed. Credential expiry (~15–60 min) triggered a pipeline restart. With `MAX_PIPELINE_RESTARTS = 3`, a 24/7 device would go permanently dark within 3–4 hours.

**Fix:** Replaced with `TesCredentialProvider` class. On startup it writes a KVS credential file at `{work:path}/kvs_credentials`:
```
CREDENTIALS {AccessKeyId} {Expiration} {SecretAccessKey} {SessionToken}
```
A daemon thread wakes 5 minutes before the `Expiration` timestamp and rewrites the file. kvssink reads the `credential-path=` property and re-reads the file ~38s before expiry — credentials rotate with zero pipeline restarts.

### ✅ Fix 12: Pipeline restart counter reset after sustained healthy streaming

**Was:** `_pipeline_restart_count` incremented on every restart but was never reset. Unrelated transient errors spread over hours of uptime could exhaust `MAX_PIPELINE_RESTARTS = 3`.

**Fix:** `_check_pipeline_health` now resets `_pipeline_restart_count = 0` after `RESTART_RESET_HEALTHY_SECONDS` (300 s) of healthy streaming since the last restart.

### ✅ Fix 13: KVS SDK log configuration

**Was:** The KVS SDK searched for `kvs_log_configuration` in the CWD (`{work:path}/run`), but the file lived at `{work:path}/kvs_log_configuration`. The SDK fell back to DEBUG logging, generating very high log volume.

**Fix:** Added `export KVS_LOG4CPLUS_CONFIG="{work:path}/kvs_log_configuration"` to the component Run script.

---

## Ubuntu Core / Greengrass Operational Notes

### Checking snap content interface mounts

The `gstreamer-kvs` content interface bind-mount from `kvs-gstreamer` snap is applied inside the Greengrass snap's **private mount namespace only**. Running `ls /var/snap/aws-iot-greengrass/common/gstreamer-kvs/` from the host always shows an empty directory — this is expected and correct.

To verify the mount is active:
```bash
GGPID=$(pgrep -f "Greengrass.jar" | head -1)
sudo nsenter -m --target $GGPID -- ls /var/snap/aws-iot-greengrass/common/gstreamer-kvs/lib/
```

### Checking which component version is actually running after a deployment

Greengrass ROLLBACK policy reverts to the previous working deployment when a new component crashes. After a failed deployment the device may be running an older version than expected. Check:
```bash
GGPID=$(pgrep -f "Greengrass.jar" | head -1)
sudo nsenter -m --target $GGPID -- grep "1\.0\." /var/snap/aws-iot-greengrass/common/greengrass/v2/logs/com.example.KvsProducer.log | grep artifacts | tail -1
```

### `DefaultConfiguration` changes require a new `configurationUpdate.merge` deployment

Changing a value in `DefaultConfiguration` in the recipe has no effect on devices where that key already exists in `config.tlog` (i.e., any device that has received at least one previous deployment). The `deploy_greengrass_components.py` script now automatically propagates all non-`accessControl` DefaultConfiguration values as `configurationUpdate.merge` on every deployment. If you bypass the script and create deployments manually (e.g., via the AWS console), you must explicitly set configuration values in the component merge — do not rely on recipe defaults to override existing device state.

### Diagnosing the component startup sequence

The most useful diagnostic gate in the log:

| What you see | What it means |
|---|---|
| No output at all | Python process crashed before `main()` — GStreamer import chain failed. Check snap connection: `snap connections aws-iot-greengrass \| grep gstreamer-kvs` |
| `STARTUP ENV:` lines present | GStreamer import succeeded. Snap content interface is working. |
| `TES: credentials fetched OK` | TES credentials were obtained successfully. |
| `Gst.parse_launch() done` | kvssink element loaded correctly from the snap. |
| `Both pipelines started` | Pipelines reached PLAYING state. |
| No errors after `KvsProducer running` | **Streaming is working.** Check KVS console. |
