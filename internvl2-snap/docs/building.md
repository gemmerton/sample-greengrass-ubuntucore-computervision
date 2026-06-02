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
