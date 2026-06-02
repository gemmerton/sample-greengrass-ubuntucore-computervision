# InternVL2-4B Custom VLM Snap — Design Spec

## Overview

Add a self-packaged VLM (InternVL2-4B) that deploys from S3 in the same way the existing qwen-vl and gemma3 snaps work, but without requiring the snap store. Uses Intel OpenVINO/OVMS for inference, consistent with the partnership demo requirements.

## Architecture

Mirrors the qwen-vl snap pattern exactly:
- A lightweight parent snap (~10MB) containing engine scripts and configuration
- Two snap components sideloaded from S3: OVMS runtime and model weights
- Serves OpenAI-compatible API at `/v3/chat/completions` on port 9090
- Managed by VlmModelManager identically to store-installed VLM snaps

## Snap Structure

### Parent Snap (`internvl2`, ~10MB)

```
internvl2-snap/
├── snap/
│   └── snapcraft.yaml
├── engines/
│   └── intel-gpu/
│       └── server              # Shell: sets LD_LIBRARY_PATH, execs OVMS from component
├── bin/
│   └── server.sh              # Entry point: waits for components, selects engine, execs
├── extract-ovms-libs.sh       # Pull OVMS binary from Docker image
└── docs/
    └── building.md
```

### Components (sideloaded from S3)

| Component | Contents | Size |
|-----------|----------|------|
| `internvl2+openvino-model-server` | OVMS binary + OpenVINO libraries | ~300MB |
| `internvl2+model-internvl2-4b-ov-int4` | InternVL2-4B in OpenVINO INT4 format | ~4GB |

### snapcraft.yaml

```yaml
name: internvl2
version: '1.0.0'
summary: InternVL2-4B Vision Language Model (OpenVINO)
description: |
  Self-packaged VLM snap serving InternVL2-4B via OpenVINO Model Server.
  Intel GPU accelerated inference with OpenAI-compatible chat API.

base: core24
confinement: strict
grade: stable
architectures:
  - amd64

environment:
  SNAP_COMPONENTS: /snap/$SNAP_INSTANCE_NAME/components/$SNAP_REVISION
  ARCH_TRIPLET: x86_64-linux-gnu
  LD_LIBRARY_PATH: ${SNAP_LIBRARY_PATH}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}:$SNAP/lib:$SNAP/usr/lib:$SNAP/usr/lib/x86_64-linux-gnu

apps:
  internvl2:
    command: bin/internvl2-cli
    plugs:
      - network
  server:
    command: bin/server.sh
    daemon: simple
    plugs:
      - network-bind
      - network
      - hardware-observe
      - opengl
    environment:
      ARCH_TRIPLET: x86_64-linux-gnu

plugs:
  home:
    read: all

hooks:
  install:
    plugs:
      - hardware-observe
      - opengl

layout:
  /etc/OpenCL/vendors:
    bind: $SNAP/etc/OpenCL/vendors
  /usr/lib/x86_64-linux-gnu/intel-opencl:
    bind: $SNAP/usr/lib/x86_64-linux-gnu/intel-opencl

components:
  openvino-model-server:
    type: standard
    summary: OpenVINO Model Server
    description: OVMS binary and libraries for VLM text generation serving
  model-internvl2-4b-ov-int4:
    type: standard
    summary: InternVL2-4B OpenVINO INT4
    description: InternVL2-4B vision-language model in OpenVINO IR format, INT4 quantized
```

### Engine Script (`engines/intel-gpu/server`)

Reads configuration via `snapctl get` (the snap-internal equivalent of `snap get`), which
is how VlmModelManager configures port/host at runtime via the snapd conf API.

```bash
#!/bin/bash -eu

server_path="$SNAP_COMPONENTS/openvino-model-server"
model_path="$SNAP_COMPONENTS/model-internvl2-4b-ov-int4"

if [ ! -d "$server_path" ]; then
    echo "Missing component: openvino-model-server"
    exit 1
fi

if [ ! -d "$model_path" ]; then
    echo "Missing component: model-internvl2-4b-ov-int4"
    exit 1
fi

LD_LIBRARY_PATH="$LD_LIBRARY_PATH:$server_path/lib"
LD_LIBRARY_PATH="$LD_LIBRARY_PATH:$server_path/lib/python"
LD_LIBRARY_PATH="$LD_LIBRARY_PATH:$server_path/usr/lib/$ARCH_TRIPLET"
export LD_LIBRARY_PATH

export OCL_ICD_VENDORS=$SNAP/etc/OpenCL/vendors
export PYTHONPATH="$server_path/lib/python:$server_path/lib/python3.12/site-packages"

# Read port/host from snap configuration (set by VlmModelManager via snapd API)
port="$(snapctl get http.port)"
port="${port:-9090}"
host="$(snapctl get http.host)"
host="${host:-0.0.0.0}"

exec "$server_path/bin/ovms" \
    --rest_port "$port" \
    --rest_bind_address "$host" \
    --source_model "InternVL2-4B-ov-int4" \
    --model_repository_path "$model_path" \
    --target_device GPU \
    --task text_generation \
    --cache_size 2 \
    "$@"
```

### Snap Configuration (managed by VlmModelManager)

The VlmModelManager configures port/host by calling the snapd conf API:
```
PUT /v2/snaps/internvl2/conf → {"http.port": 9090, "http.host": "0.0.0.0"}
```

The engine script reads these via `snapctl get http.port` / `snapctl get http.host`.
This is the same mechanism qwen-vl uses (via its CLI wrapper around `snapctl`).

The snap also needs default config values in `snapcraft.yaml`:
```yaml
hooks:
  configure:
    plugs:
      - network
```

And a default-configure hook or snap config defaults to set initial values.

---

## VlmModelManager Changes

### New Source Type: `s3-snap`

Shadow config for the new model:

```json
{
  "internvl2": {
    "source": "s3-snap",
    "s3_uri": "s3://gg-ge-test/vlm-snaps/internvl2.snap",
    "components_s3": {
      "openvino-model-server": "s3://gg-ge-test/vlm-snaps/internvl2+openvino-model-server.comp",
      "model-internvl2-4b-ov-int4": "s3://gg-ge-test/vlm-snaps/internvl2+model-internvl2-4b-ov-int4.comp"
    }
  }
}
```

### Install Flow for `s3-snap`

```python
def _install_s3_snap(self, model_id, config):
    """Install a VLM snap and its components from S3."""
    snap_s3_uri = config["s3_uri"]
    components_s3 = config.get("components_s3", {})

    # 1. Download and sideload the parent snap
    local_snap = self._download_from_s3(snap_s3_uri, f"/tmp/{model_id}.snap")
    self.snapd.sideload_snap(local_snap, timeout=300)
    os.remove(local_snap)

    # 2. Download and sideload each component
    for comp_name, comp_s3_uri in components_s3.items():
        local_comp = self._download_from_s3(comp_s3_uri, f"/tmp/{model_id}+{comp_name}.comp")
        self.snapd.sideload_component(local_comp, timeout=600)
        os.remove(local_comp)

    # 3. Configure port (same as store snaps)
    self._configure_vlm_port(model_id)
```

After installation, start/stop/health-check work identically to store snaps.

### SnapdClient Addition

One new method needed:

```python
def sideload_snap(self, snap_file_path, timeout=300):
    """Sideload a .snap file via snapd API (same mechanism as sideload_component)."""
    # POST /v2/snaps with multipart form: action=install, dangerous=true, snap=<file>
```

This is functionally identical to `sideload_component` — same API endpoint, same multipart upload, same async polling. The only difference is the file extension.

---

## Build Process

On the amd64 build machine:

### Step 1: Convert InternVL2-4B to OpenVINO

```bash
pip install optimum[openvino]
optimum-cli export openvino --model OpenGVLab/InternVL2-4B --weight-format int4 ./model/InternVL2-4B-ov-int4
```

### Step 2: Extract OVMS binary

```bash
cd internvl2-snap/
./extract-ovms-libs.sh  # Same approach as ovms-engine, pulls from openvino/model_server Docker
```

### Step 3: Build snap

```bash
snapcraft pack
```

Produces:
- `internvl2_1.0.0_amd64.snap` (~10MB)
- `internvl2+openvino-model-server.comp` (~300MB)
- `internvl2+model-internvl2-4b-ov-int4.comp` (~4GB)

### Step 4: Upload to S3

```bash
aws s3 cp internvl2_1.0.0_amd64.snap s3://gg-ge-test/vlm-snaps/
aws s3 cp internvl2+openvino-model-server.comp s3://gg-ge-test/vlm-snaps/
aws s3 cp internvl2+model-internvl2-4b-ov-int4.comp s3://gg-ge-test/vlm-snaps/
```

### Step 5: Update shadow

Add `internvl2` to the `vlm-config` shadow desired.models with `source: "s3-snap"`.

---

## What Changes in Existing Code

| File | Change |
|------|--------|
| `VlmModelManager/vlm_model_manager.py` | Add `_install_s3_snap()` method, branch on `source == "s3-snap"` in reconciliation |
| `VlmModelManager/snapd_client.py` | Add `sideload_snap()` method (same as `sideload_component`) |
| `deploy_greengrass_components.py` | Add `internvl2` to default VLM shadow config |

No changes needed to:
- VlmInferenceHandler (OVMS API is identical)
- React UI (model appears in selector automatically from shadow)
- InferenceHandler (CV side unaffected)

---

## Out of Scope

- Snap store publishing (this snap is S3-only)
- Multiple engine support (only intel-gpu for now)
- Automatic OVMS version updates
- Model fine-tuning or custom weights
