# Model Management - Status & Next Steps

## Status: OVMS serving inference, content interface broken (2026-05-20)

The full model management pipeline is working from cloud shadow through to OVMS
serving inference — with one critical gap: the snap content interface between
Greengrass and ovms-engine is not relaying config files, so OVMS doesn't pick
up model changes written by ModelManagerCore.

### What works

1. **Shadow sync to cloud**: Reported state from the device appears in the AWS
   IoT Console immediately (IoT policy fixed 2026-05-20)
2. **Shadow-driven model install**: Setting `desired.models.faster-rcnn.source = "snap"`
   triggers download from S3, sideload via snapd, manifest download, and
   shadow reported state update — all automated
3. **OVMS server running**: OpenVINO Model Server starts, loads models from
   `models_config.json`, and serves gRPC (9000) + REST (9001)
4. **Model loaded and available**: `faster_rcnn` model loaded with status
   `AVAILABLE` and serving inference requests
5. **S3 .comp download + sideload**: ModelManagerCore downloads `.comp` from
   `s3://gg-ge-test/components/` and sideloads via snapd REST API
6. **S3 manifest fallback**: Reads model metadata from S3 when snap confinement
   prevents direct file access to the sideloaded component path

### What does NOT work

1. **Content interface not relaying config to OVMS** (BLOCKING):
   ModelManagerCore writes `models_config.json` to
   `/var/snap/aws-iot-greengrass/current/ovms-engine-config/` (the Greengrass
   side of the `inference-config` content interface). This should appear at
   `/var/snap/ovms-engine/common/config/` (where OVMS reads). It does not.
   Writes to the Greengrass side are invisible to OVMS. Disconnecting and
   reconnecting the interface doesn't fix it.

   **Impact**: Model switching doesn't work. When ModelManagerCore installs a
   new model and regenerates the OVMS config, OVMS never sees the update. The
   demo requires hot-swapping models via the shadow, so this must be fixed.

   **Workaround applied today**: Wrote the config directly to
   `/var/snap/ovms-engine/common/config/models_config.json` — this proved
   inference works but is not a viable solution for the demo.

2. **Model base_path uses stale snap revision**: The ModelManagerCore config
   `SnapComponentsPath` is set to `/snap/ovms-engine/components/x1` but the
   snap is now at a higher revision. Sideloaded model components go to
   `/snap/ovms-engine/components/mnt/model-<id>/x<N>`. The `_find_component_path`
   logic handles this via fallback search, but the `base_path` written to the
   OVMS config may not match what OVMS can access from within its snap
   confinement.

### S3 bucket layout

```
s3://gg-ge-test/components/
├── manifests/
│   ├── model-faster-rcnn.json
│   └── model-efficientnet.json
├── ovms-engine+model-faster-rcnn.comp    (1.3 MB, person-detection-retail-0013 FP16)
├── ovms-engine+model-efficientnet.comp   (3.2 MB, age-gender-recognition-retail-0013 FP16)
├── ovms-engine+ovms-cpu.comp             (83 MB, with full deps + Python stdlib)
├── ovms-engine+ovms-gpu.comp             (83 MB)
└── ovms-engine+ovms-npu.comp             (83 MB)
```

### Shadow document structure

```json
{
  "state": {
    "desired": {
      "models": {
        "faster-rcnn": { "source": "snap" }
      }
    },
    "reported": {
      "models": {
        "faster-rcnn": {
          "status": "ready",
          "model_metadata": {
            "model_name": "faster_rcnn",
            "version": "1.0.0",
            "input_name": "data",
            "output_names": ["detection_out"],
            "input_shape": [1, 3, 320, 544],
            "labels_file": "labels.txt",
            "local_path": "/snap/ovms-engine/components/mnt/model-faster-rcnn/x1"
          }
        }
      }
    }
  }
}
```

### Current models (placeholder for demo)

| Model ID | Actual Model | Purpose | Input | Size |
|----------|-------------|---------|-------|------|
| faster-rcnn | person-detection-retail-0013 | Person detection | [1,3,320,544] NCHW | 1.4 MB |
| efficientnet | age-gender-recognition-retail-0013 | Age/gender classification | [1,3,62,62] NCHW | 4.3 MB |

These are Intel-optimised FP16 models from the OpenVINO Model Zoo, chosen because
they are small and available for direct download.

## Resolved issues (2026-05-20)

1. ~~**Shadow reported state not syncing to cloud**~~: IoT policy was missing
   shadow actions. Fixed in live policy and `iot-greengrass-setup.py`.

2. ~~**OVMS missing shared libraries**~~: The extraction script now uses
   `tar --dereference` to resolve symlinks and includes 13 system libraries
   not present in core24, plus the Python 3.10 stdlib and OVMS Python deps.
   See `ovms-engine/extract-ovms-libs.sh`.

3. ~~**OVMS server startup failures**~~: Fixed by:
   - Removing `--target_device` CLI flag (conflicts with `--config_path`)
   - Bypassing `modelctl run` wrapper (required `OPENAI_BASE_PATH` env)
   - Setting `LD_LIBRARY_PATH` in engine server scripts
   - Setting `PYTHONHOME`/`PYTHONPATH` for the embedded Python interpreter
   - Including OVMS Python deps (`/ovms/python_deps/` and `/ovms/lib/python/`)

4. ~~**modelctl config.poll_seconds not supported**~~: Server scripts now use
   defaults with `|| echo <value>` fallback when `modelctl get` fails.

## Known issues

1. **Content interface not relaying** (see "What does NOT work" above)

2. **Multiple component revisions accumulating**: Each sideload creates a new
   revision under `/snap/ovms-engine/components/mnt/model-faster-rcnn/x<N>`.
   Old revisions should be cleaned up periodically.

## Next steps

### Immediate (fix content interface for model switching)

1. **Fix the content interface**: Investigate why writes to the Greengrass plug
   side don't appear at the ovms-engine slot side. Possible causes:
   - The slot `write` path in snapcraft.yaml (`$SNAP_COMMON/config`) may not
     resolve to what we expect after snap reinstall
   - The plug target (`$SNAP_DATA/ovms-engine-config`) may be mounting to a
     different location than ModelManagerCore writes to
   - Alternatively: have ModelManagerCore write directly to the OVMS config
     path if the content interface proves unreliable

### Short-term (production models)

2. **Replace placeholder models**: Build `.comp` files with real production
   models. The current models are Intel's demo retail models.

3. **Verify model hot-swap**: Install faster-rcnn, switch to efficientnet via
   shadow, verify OVMS unloads one and loads the other without restart.

### Medium-term (store publishing)

4. **Publish ovms-engine to Snap Store**: Once published, the `"source": "snap"`
   path works without S3 fallback — snapd pulls components directly from the
   store.
