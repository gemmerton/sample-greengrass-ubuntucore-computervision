# Model Management - Status & Next Steps

## Status: Shadow-driven model provisioning working end-to-end (2026-05-19)

The `ModelManagerCore` Greengrass component now successfully orchestrates model
installation on a sideloaded `ovms-engine` snap via the IoT Device Shadow.

### What works

1. **Shadow-driven flow**: Setting `desired.models.faster-rcnn.source = "snap"` in
   the `model-config` named shadow triggers the full install pipeline
2. **Sideloaded snap detection**: Automatically detects `ovms-engine` is not from
   the Snap Store and falls back to S3-based component download
3. **S3 .comp download**: Downloads `ovms-engine+model-faster-rcnn.comp` from
   `s3://gg-ge-test/components/`
4. **snapd sideload**: Installs the component via multipart POST to the snapd API
5. **S3 manifest fallback**: Reads `manifest.json` from S3 when snap confinement
   prevents direct file access to the component path
6. **OVMS config generation**: Writes `models_config.json` via the content
   interface to `/var/snap/ovms-engine/common/config/`
7. **Model weights on device**: Verified `.xml` and `.bin` OpenVINO IR files at
   `/snap/ovms-engine/components/x1/model-faster-rcnn/1/`

### S3 bucket layout

```
s3://gg-ge-test/components/
├── manifests/
│   ├── model-faster-rcnn.json
│   └── model-efficientnet.json
├── ovms-engine+model-faster-rcnn.comp    (1.3 MB, person-detection-retail-0013 FP16)
├── ovms-engine+model-efficientnet.comp   (3.2 MB, age-gender-recognition-retail-0013 FP16)
├── ovms-engine+ovms-cpu.comp             (85 MB)
├── ovms-engine+ovms-gpu.comp             (85 MB)
└── ovms-engine+ovms-npu.comp             (85 MB)
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
            "input_name": "data",
            "output_names": ["detection_out"],
            "input_shape": [1, 3, 320, 544],
            "labels_file": "labels.txt",
            "local_path": "/snap/ovms-engine/components/x1/model-faster-rcnn"
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
they are small and available for direct download. They prove the pipeline works but
should be replaced with production models.

## Known issues

1. **Shadow reported state not syncing to cloud**: The local Shadow Manager
   persists reported state locally but it does not appear in the AWS Console.
   Likely a named-shadow sync configuration issue in the Greengrass Shadow Manager
   component config (needs `synchronize` config for the `model-config` shadow).

2. **OVMS service inactive**: The `ovms-engine.server` snap service is not running.
   The engine component (`ovms-cpu`) needs to be installed and `modelctl use-engine`
   needs to complete successfully for the server to start.

3. **Multiple component revisions accumulating**: Each sideload creates a new
   revision under `/snap/ovms-engine/components/mnt/model-faster-rcnn/x<N>`.
   Old revisions should be cleaned up periodically.

## Next steps

### Immediate (get OVMS serving inference)

1. **Start OVMS service**: Install the `ovms-cpu` engine component (it's in S3)
   and run `modelctl use-engine --auto` to initialise the server. Alternatively,
   start OVMS directly:
   ```bash
   sudo snap start ovms-engine.server
   ```

2. **Fix shadow sync**: Add `model-config` to the Shadow Manager's `synchronize`
   configuration so reported state syncs to the cloud. Check the
   `aws.greengrass.ShadowManager` component config for the
   `coreThing.namedShadows` list.

3. **Verify inference**: Once OVMS is running, test with:
   ```bash
   curl -X POST http://localhost:9001/v1/models/faster_rcnn:predict -d @test.json
   ```

### Short-term (production models)

4. **Replace placeholder models**: Build `.comp` files with real production models
   (e.g., from Kaggle or custom-trained). The current models are Intel's demo
   retail models that prove the pipeline but aren't suitable for the actual
   computer vision use case.

5. **Build proper .comp files**: Use `snapcraft pack --component` on a Linux
   build machine rather than manually creating squashfs archives. This ensures
   proper snap metadata.

### Medium-term (store publishing)

6. **Publish ovms-engine to Snap Store**: Once published, the `"source": "snap"`
   path works without S3 fallback - snapd pulls components directly from the store.
   The S3 fallback remains for custom/private models not in the store.
