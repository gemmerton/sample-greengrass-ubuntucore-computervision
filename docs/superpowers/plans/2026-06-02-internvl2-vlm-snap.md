# InternVL2-4B Custom VLM Snap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a self-packaged VLM (InternVL2-4B on OpenVINO) deployed from S3, managed by VlmModelManager alongside qwen-vl and gemma3.

**Architecture:** A standalone snap mirroring qwen-vl's pattern (thin parent snap + two sideloaded components: OVMS runtime and model weights). VlmModelManager gets a new `s3-snap` source type that downloads and sideloads the snap + components from S3.

**Tech Stack:** snapcraft (snap build), OpenVINO/OVMS (inference), optimum-intel (model conversion), Python (VlmModelManager), AWS S3 (artifact storage)

---

## File Structure

### New Files (snap source)

| File | Responsibility |
|------|---------------|
| `internvl2-snap/snap/snapcraft.yaml` | Snap declaration: components, apps, plugs, hooks |
| `internvl2-snap/engines/intel-gpu/server` | Engine script: env setup, launches OVMS with correct args |
| `internvl2-snap/bin/server.sh` | Entry point: waits for components, selects engine |
| `internvl2-snap/bin/check-server.sh` | Health check script for OVMS readiness |
| `internvl2-snap/extract-ovms-libs.sh` | Extracts OVMS binary from Docker (same pattern as ovms-engine) |
| `internvl2-snap/docs/building.md` | Build instructions for amd64 machine |

### Modified Files (Greengrass components)

| File | Responsibility |
|------|---------------|
| `greengrass-components/artifacts/com.example.VlmModelManager/1.0.0/vlm_model_manager.py` | Add `_install_s3_snap()` method, branch on `source == "s3-snap"` |
| `greengrass-components/artifacts/com.example.VlmModelManager/1.0.0/snapd_client.py` | Rename/alias `sideload_component` → `sideload` (works for both .snap and .comp) |
| `deploy_greengrass_components.py` | Add internvl2 to default VLM shadow config |

---

## Task 1: Snap Skeleton — snapcraft.yaml

**Files:**
- Create: `internvl2-snap/snap/snapcraft.yaml`

- [ ] **Step 1: Create the snapcraft.yaml**

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

platforms:
  amd64:

environment:
  SNAP_COMPONENTS: /snap/$SNAP_INSTANCE_NAME/components/$SNAP_REVISION
  ARCH_TRIPLET: x86_64-linux-gnu
  LD_LIBRARY_PATH: ${SNAP_LIBRARY_PATH}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}:$SNAP/lib:$SNAP/usr/lib:$SNAP/usr/lib/x86_64-linux-gnu
  PATH: $SNAP/usr/sbin:$SNAP/usr/bin:$SNAP/sbin:$SNAP/bin:$PATH

parts:
  scripts:
    source: .
    plugin: dump
    organize:
      engines/**: engines/
      bin/**: bin/
    stage:
      - engines/**
      - bin/**

  opencl-icd:
    plugin: nil
    stage-packages:
      - intel-opencl-icd
    organize:
      etc/OpenCL/vendors/intel.icd: etc/OpenCL/vendors/intel.icd

apps:
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
      OCL_ICD_VENDORS: $SNAP/etc/OpenCL/vendors

hooks:
  configure:
    plugs:
      - network

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

- [ ] **Step 2: Commit**

```bash
git add internvl2-snap/snap/snapcraft.yaml
git commit -m "feat(internvl2-snap): add snapcraft.yaml skeleton"
```

---

## Task 2: Engine and Server Scripts

**Files:**
- Create: `internvl2-snap/engines/intel-gpu/server`
- Create: `internvl2-snap/bin/server.sh`
- Create: `internvl2-snap/bin/check-server.sh`

- [ ] **Step 1: Create the engine script**

`internvl2-snap/engines/intel-gpu/server`:

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

# Add OVMS libraries to path
LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}:$server_path/lib"
LD_LIBRARY_PATH="$LD_LIBRARY_PATH:$server_path/lib/python"
LD_LIBRARY_PATH="$LD_LIBRARY_PATH:$server_path/usr/lib/$ARCH_TRIPLET"
export LD_LIBRARY_PATH
echo "LD_LIBRARY_PATH: $LD_LIBRARY_PATH"

# OpenCL for Intel GPU
export OCL_ICD_VENDORS=$SNAP/etc/OpenCL/vendors

# Python dependencies for OVMS
export PYTHONPATH="$server_path/lib/python:$server_path/lib/python3.12/site-packages"
echo "PYTHONPATH: $PYTHONPATH"

# Read port/host from snap configuration (set by VlmModelManager via snapd API)
port="$(snapctl get http.port)"
port="${port:-9090}"
host="$(snapctl get http.host)"
host="${host:-0.0.0.0}"

# Run model init script if present
if [ -f "$model_path/init" ]; then
    "$model_path/init"
fi

set -x
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

- [ ] **Step 2: Create the server entry point**

`internvl2-snap/bin/server.sh`:

```bash
#!/bin/bash -eu

# Wait for required components to be sideloaded
max=600
interval=10
elapsed=0

while [ ! -d "$SNAP_COMPONENTS/openvino-model-server" ] || \
      [ ! -d "$SNAP_COMPONENTS/model-internvl2-4b-ov-int4" ]; do
    if [ "$elapsed" -ge "$max" ]; then
        echo "Error: timed out waiting for components after ${elapsed}s"
        echo "Required: openvino-model-server, model-internvl2-4b-ov-int4"
        snapctl stop internvl2
        exit 1
    fi
    echo "Waiting for components... ($elapsed/${max}s)"
    sleep "$interval"
    ((elapsed+=interval))
done

echo "All components present, starting engine"
exec "$SNAP/engines/intel-gpu/server" "$@"
```

- [ ] **Step 3: Create the health check script**

`internvl2-snap/bin/check-server.sh`:

```bash
#!/bin/bash -u

set +e

port="$(snapctl get http.port)"
port="${port:-9090}"

# Check if OVMS process is running
if ! (pgrep -x "ovms" > /dev/null); then
    exit 2
fi

# Check if port is open
if ! (nc -z localhost "$port" 2>/dev/null); then
    exit 1
fi

# Check v1/config for model loading status
api_config=$(wget "http://localhost:$port/v1/config" --timeout=10 --tries=1 -O- 2>/dev/null)
if [ -z "$api_config" ]; then
    exit 1
fi

empty_json=$(echo "$api_config" | grep -c '{}')
if [ "$empty_json" -gt 0 ]; then
    exit 1
fi

if echo "$api_config" | grep -q "FAILED_PRECONDITION"; then
    exit 2
fi

exit 0
```

- [ ] **Step 4: Make scripts executable and commit**

```bash
chmod +x internvl2-snap/engines/intel-gpu/server
chmod +x internvl2-snap/bin/server.sh
chmod +x internvl2-snap/bin/check-server.sh
git add internvl2-snap/engines/ internvl2-snap/bin/
git commit -m "feat(internvl2-snap): add engine and server scripts"
```

---

## Task 3: OVMS Extraction Script

**Files:**
- Create: `internvl2-snap/extract-ovms-libs.sh`

- [ ] **Step 1: Create the extraction script**

This script extracts the OVMS binary and libraries from the official Docker image, to be packaged as the `openvino-model-server` component.

```bash
#!/bin/bash
set -euo pipefail

OVMS_VERSION="2025.0"
OVMS_IMAGE="openvino/model_server:${OVMS_VERSION}"
CONTAINER_NAME="ovms-extract-$$"

OUTPUT_DIR="./components/openvino-model-server"

echo "=== Extracting OVMS ${OVMS_VERSION} for internvl2 snap component ==="
echo "Image: ${OVMS_IMAGE}"
echo "Output: ${OUTPUT_DIR}"

rm -rf "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR/bin" "$OUTPUT_DIR/lib" "$OUTPUT_DIR/meta"

# Pull image
docker pull "${OVMS_IMAGE}"

# Extract OVMS binary
echo "Extracting OVMS binary..."
docker run --rm --entrypoint cat "${OVMS_IMAGE}" /ovms/bin/ovms > "$OUTPUT_DIR/bin/ovms"
chmod +x "$OUTPUT_DIR/bin/ovms"

# Extract OVMS libraries
echo "Extracting OVMS libraries..."
docker run --rm --entrypoint tar "${OVMS_IMAGE}" \
    ch --dereference -C /ovms lib \
    | tar x -C "$OUTPUT_DIR/"

# Extract system libraries needed by OVMS
echo "Extracting system libraries..."
SYSTEM_LIBS=(
    libcurl.so.4
    libicudata.so.74
    libicuuc.so.74
    liblber.so.2
    libldap.so.2
    libnghttp2.so.14
    libpsl.so.5
    libpython3.12.so.1.0
    librtmp.so.1
    libsasl2.so.2
    libssh.so.4
    libxml2.so.2
)

for lib in "${SYSTEM_LIBS[@]}"; do
    docker run --rm --entrypoint sh "${OVMS_IMAGE}" -c \
        "find /lib/x86_64-linux-gnu -name '${lib}*' -exec cat {} \;" > "$OUTPUT_DIR/lib/$lib" 2>/dev/null || true
done

# Extract Python stdlib and OVMS Python deps
echo "Extracting Python 3.12 stdlib..."
docker run --rm --entrypoint tar "${OVMS_IMAGE}" \
    ch --dereference -C / usr/lib/python3.12 \
    | tar x --strip-components=2 -C "$OUTPUT_DIR/lib/"

echo "Extracting OVMS Python deps..."
docker run --rm --entrypoint tar "${OVMS_IMAGE}" \
    ch --dereference -C /ovms/lib python \
    | tar x -C "$OUTPUT_DIR/lib/"

# Create component metadata
cat > "$OUTPUT_DIR/meta/component.yaml" << 'EOF'
component: internvl2+openvino-model-server
type: standard
summary: OpenVINO Model Server
description: OVMS binary and libraries for VLM text generation serving
EOF

echo "=== OVMS extraction complete ==="
echo "Binary: $(du -h "$OUTPUT_DIR/bin/ovms" | cut -f1)"
echo "Libraries: $(du -sh "$OUTPUT_DIR/lib" | cut -f1)"
```

- [ ] **Step 2: Commit**

```bash
chmod +x internvl2-snap/extract-ovms-libs.sh
git add internvl2-snap/extract-ovms-libs.sh
git commit -m "feat(internvl2-snap): add OVMS extraction script"
```

---

## Task 4: Model Conversion Script

**Files:**
- Create: `internvl2-snap/convert-model.sh`

- [ ] **Step 1: Create the model conversion script**

This converts InternVL2-4B from Hugging Face to OpenVINO INT4 format.

```bash
#!/bin/bash
set -euo pipefail

OUTPUT_DIR="./components/model-internvl2-4b-ov-int4"

echo "=== Converting InternVL2-4B to OpenVINO INT4 ==="

# Install optimum-intel if not present
pip install --quiet optimum[openvino] 2>/dev/null || pip install --quiet optimum-intel

rm -rf "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR/meta"

# Export model to OpenVINO format with INT4 quantization
optimum-cli export openvino \
    --model OpenGVLab/InternVL2-4B \
    --weight-format int4 \
    "$OUTPUT_DIR/InternVL2-4B-ov-int4"

# Create component metadata
cat > "$OUTPUT_DIR/meta/component.yaml" << 'EOF'
component: internvl2+model-internvl2-4b-ov-int4
type: standard
summary: InternVL2-4B OpenVINO INT4
description: InternVL2-4B vision-language model in OpenVINO IR format, INT4 quantized
EOF

echo "=== Model conversion complete ==="
echo "Model size: $(du -sh "$OUTPUT_DIR/InternVL2-4B-ov-int4" | cut -f1)"
```

- [ ] **Step 2: Commit**

```bash
chmod +x internvl2-snap/convert-model.sh
git add internvl2-snap/convert-model.sh
git commit -m "feat(internvl2-snap): add model conversion script"
```

---

## Task 5: Build Documentation

**Files:**
- Create: `internvl2-snap/docs/building.md`

- [ ] **Step 1: Create build documentation**

```markdown
# Building the InternVL2 Snap

## Prerequisites

- amd64 machine (same as ovms-engine builds)
- snapcraft >= 8.x (`sudo snap install snapcraft --classic`)
- LXD initialised (`sudo lxd init --auto`)
- Docker (for OVMS binary extraction)
- Python 3.10+ with pip (for model conversion)
- ~20GB free disk space

## Build Steps

### 1. Extract OVMS binary and libraries

```bash
cd internvl2-snap
./extract-ovms-libs.sh
```

This creates `components/openvino-model-server/` with OVMS binary + libs.

### 2. Convert model to OpenVINO format

```bash
./convert-model.sh
```

This creates `components/model-internvl2-4b-ov-int4/` with the model weights.
Takes ~10-20 minutes (downloads from Hugging Face + quantises).

### 3. Build the snap

```bash
snapcraft pack
```

Produces:
- `internvl2_1.0.0_amd64.snap` (parent snap, ~10MB)
- `internvl2+openvino-model-server.comp` (OVMS, ~300MB)
- `internvl2+model-internvl2-4b-ov-int4.comp` (model, ~4GB)

### 4. Upload to S3

```bash
aws s3 cp internvl2_1.0.0_amd64.snap s3://gg-ge-test/vlm-snaps/internvl2.snap --region eu-west-1
aws s3 cp internvl2+openvino-model-server.comp s3://gg-ge-test/vlm-snaps/internvl2+openvino-model-server.comp --region eu-west-1
aws s3 cp internvl2+model-internvl2-4b-ov-int4.comp s3://gg-ge-test/vlm-snaps/internvl2+model-internvl2-4b-ov-int4.comp --region eu-west-1
```

### 5. Update device shadow

Add `internvl2` to the `vlm-config` shadow desired.models on the target device.

## Troubleshooting

### Model conversion fails with OOM
InternVL2-4B requires ~16GB RAM during conversion. Use a machine with sufficient memory.

### OVMS extraction: library not found
If the Docker image version changes, the system library list in `extract-ovms-libs.sh`
may need updating. Check `ldd` output on the target device.
```

- [ ] **Step 2: Commit**

```bash
git add internvl2-snap/docs/building.md
git commit -m "docs(internvl2-snap): add build instructions"
```

---

## Task 6: VlmModelManager — Add s3-snap Source Type

**Files:**
- Modify: `greengrass-components/artifacts/com.example.VlmModelManager/1.0.0/vlm_model_manager.py`

- [ ] **Step 1: Add `_install_s3_snap` method after `_install_vlm_snap`**

```python
def _install_s3_snap(self, model_id, config):
    """Install a VLM snap and its components from S3.

    Downloads the .snap file and .comp files from S3, sideloads
    them via the snapd API. After installation the snap behaves
    identically to a store-installed snap.

    Args:
        model_id: Snap name (e.g. 'internvl2')
        config: Dict with 's3_uri' and 'components_s3' fields
    """
    snap_s3_uri = config.get("s3_uri")
    components_s3 = config.get("components_s3", {})

    if not snap_s3_uri:
        logger.error("s3-snap model '%s' missing 's3_uri' field", model_id)
        self._report_model_status(model_id, "failed", reason="Missing s3_uri")
        return

    if self.snapd.is_installed(model_id):
        logger.info("Snap '%s' already installed", model_id)
        self._configure_vlm_port(model_id)
        self._report_model_status(model_id, "ready")
        if model_id != self.active_model:
            try:
                self.snapd.stop_snap_service(model_id)
            except Exception:
                pass
        return

    self._report_model_status(model_id, "installing")

    # Download and sideload the parent snap
    try:
        local_snap = self._download_from_s3(snap_s3_uri, model_id, ".snap")
        self.snapd.sideload_component(local_snap, timeout=300)
        os.remove(local_snap)
        logger.info("Sideloaded snap '%s' from S3", model_id)
    except Exception as e:
        logger.error("Failed to sideload snap '%s': %s", model_id, e)
        self._report_model_status(model_id, "failed", reason=f"Snap sideload failed: {e}")
        return

    # Download and sideload each component
    for comp_name, comp_s3_uri in components_s3.items():
        try:
            local_comp = self._download_from_s3(comp_s3_uri, model_id, f"+{comp_name}.comp")
            self.snapd.sideload_component(local_comp, timeout=900)
            os.remove(local_comp)
            logger.info("Sideloaded component '%s+%s' from S3", model_id, comp_name)
        except Exception as e:
            logger.error("Failed to sideload component '%s+%s': %s", model_id, comp_name, e)
            self._report_model_status(model_id, "failed", reason=f"Component sideload failed: {e}")
            return

    # Configure and report ready
    self._configure_vlm_port(model_id)
    self._report_model_status(model_id, "ready")

    if model_id != self.active_model:
        try:
            self.snapd.stop_snap_service(model_id)
        except Exception:
            pass

    logger.info("S3-snap model '%s' installed successfully", model_id)

def _download_from_s3(self, s3_uri, model_id, suffix):
    """Download a file from S3 to a temporary local path."""
    import boto3
    from urllib.parse import urlparse

    parsed = urlparse(s3_uri)
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    local_path = f"/tmp/{model_id}{suffix}"

    logger.info("Downloading s3://%s/%s -> %s", bucket, key, local_path)
    s3_client = boto3.client("s3")
    s3_client.download_file(bucket, key, local_path)
    return local_path
```

- [ ] **Step 2: Update `_reconcile_models` to branch on source type**

In the `_reconcile_models` method, change line 170-171 from:

```python
        for model_id, config in to_install.items():
            self._install_vlm_snap(model_id, config)
```

to:

```python
        for model_id, config in to_install.items():
            source = config.get("source", "snap")
            if source == "s3-snap":
                self._install_s3_snap(model_id, config)
            else:
                self._install_vlm_snap(model_id, config)
```

- [ ] **Step 3: Add `import os` at the top if not present**

Check if `os` is already imported. If not, add it.

- [ ] **Step 4: Commit**

```bash
git add greengrass-components/artifacts/com.example.VlmModelManager/1.0.0/vlm_model_manager.py
git commit -m "feat(vlm-model-manager): add s3-snap source type for self-packaged VLMs"
```

---

## Task 7: Update Deploy Script Defaults

**Files:**
- Modify: `deploy_greengrass_components.py`

- [ ] **Step 1: Add internvl2 to default VLM shadow config**

In the `ensure_device_shadows` method, in the `vlm-config` shadow's `models` dict, add:

```python
'internvl2': {
    'source': 's3-snap',
    's3_uri': 's3://gg-ge-test/vlm-snaps/internvl2.snap',
    'components_s3': {
        'openvino-model-server': 's3://gg-ge-test/vlm-snaps/internvl2+openvino-model-server.comp',
        'model-internvl2-4b-ov-int4': 's3://gg-ge-test/vlm-snaps/internvl2+model-internvl2-4b-ov-int4.comp',
    },
},
```

- [ ] **Step 2: Commit**

```bash
git add deploy_greengrass_components.py
git commit -m "feat(deploy): add internvl2 s3-snap to default VLM shadow config"
```

---

## Task 8: Build, Upload, and Test

This task is performed on the **amd64 build machine** and then verified on the device.

- [ ] **Step 1: On build machine — extract OVMS**

```bash
cd internvl2-snap
./extract-ovms-libs.sh
```

- [ ] **Step 2: On build machine — convert model**

```bash
./convert-model.sh
```

- [ ] **Step 3: On build machine — build snap**

```bash
snapcraft pack
```

Verify outputs:
- `internvl2_1.0.0_amd64.snap`
- `internvl2+openvino-model-server.comp`
- `internvl2+model-internvl2-4b-ov-int4.comp`

- [ ] **Step 4: Upload to S3**

```bash
aws s3 cp internvl2_1.0.0_amd64.snap s3://gg-ge-test/vlm-snaps/internvl2.snap --region eu-west-1
aws s3 cp internvl2+openvino-model-server.comp s3://gg-ge-test/vlm-snaps/internvl2+openvino-model-server.comp --region eu-west-1
aws s3 cp internvl2+model-internvl2-4b-ov-int4.comp s3://gg-ge-test/vlm-snaps/internvl2+model-internvl2-4b-ov-int4.comp --region eu-west-1
```

- [ ] **Step 5: Update device shadow**

```bash
aws iot-data update-thing-shadow --thing-name nuc-pro15 --shadow-name vlm-config --region eu-west-1 --cli-binary-format raw-in-base64-out --payload '{
  "state": {
    "desired": {
      "models": {
        "gemma3": {"source": "snap", "channel": "stable"},
        "qwen-vl": {"source": "snap", "channel": "beta"},
        "internvl2": {
          "source": "s3-snap",
          "s3_uri": "s3://gg-ge-test/vlm-snaps/internvl2.snap",
          "components_s3": {
            "openvino-model-server": "s3://gg-ge-test/vlm-snaps/internvl2+openvino-model-server.comp",
            "model-internvl2-4b-ov-int4": "s3://gg-ge-test/vlm-snaps/internvl2+model-internvl2-4b-ov-int4.comp"
          }
        }
      }
    }
  }
}'
```

- [ ] **Step 6: Deploy VlmModelManager with new code**

```bash
python3 deploy_greengrass_components.py --stage full --thing-name nuc-pro15 --s3-bucket gg-ge-test --region eu-west-1
```

- [ ] **Step 7: Verify installation**

Check device logs:
```bash
ssh gemmerton@192.168.50.244 "sudo grep internvl2 /var/snap/aws-iot-greengrass/common/greengrass/v2/logs/com.example.VlmModelManager.log | tail -10"
```

Check shadow reports model as ready:
```bash
aws iot-data get-thing-shadow --thing-name nuc-pro15 --shadow-name vlm-config --region eu-west-1 /tmp/check.json
python3 -c "import json; f=open('/tmp/check.json'); s=json.load(f); print(s['state']['reported']['models'].get('internvl2'))"
```

- [ ] **Step 8: Switch to internvl2 and verify inference**

Switch active model via UI or shadow, then check:
```bash
ssh gemmerton@192.168.50.244 "sudo tail -5 /var/snap/aws-iot-greengrass/common/greengrass/v2/logs/com.example.VlmInferenceHandler.log"
```

Expected: `Published VLM result: risk=..., time=...`

---

## Verification

After all tasks complete:

1. **Model appears in UI** — VLM model selector shows internvl2 alongside qwen-vl and gemma3
2. **Switching works** — can switch to internvl2, get inference results, switch back to qwen-vl
3. **Alerts work** — CV-triggered VLM assessment with alert rules functions on internvl2
4. **Scene query works** — interactive queries produce answers
5. **Robustness** — after device reboot, VlmModelManager correctly stops non-active models and internvl2 is available
