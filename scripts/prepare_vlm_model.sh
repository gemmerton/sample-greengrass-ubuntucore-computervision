#!/bin/bash
set -e

# Prepare a VLM model for deployment to the edge device.
# Converts InternVL2-1B to OpenVINO IR format, creates manifest.json,
# and uploads to S3 for provisioning via ModelManagerCore.
#
# Usage: ./scripts/prepare_vlm_model.sh
#
# Requirements: Python 3.10+, ~8GB disk space, internet access
# Time: ~5-10 minutes depending on download speed

MODEL_ID="OpenGVLab/InternVL2-1B"
MODEL_NAME="internvl2-1b"
S3_BUCKET="gg-ge-test"
S3_PREFIX="components/models/${MODEL_NAME}/"
REGION="eu-west-1"
OUTPUT_DIR="$(pwd)/vlm-models/${MODEL_NAME}"
VENV_DIR="$(pwd)/vlm-models/.venv"

echo "=== VLM Model Preparation ==="
echo "Model: ${MODEL_ID}"
echo "Output: ${OUTPUT_DIR}"
echo ""

# Step 1: Create venv and install dependencies
if [ ! -d "${VENV_DIR}" ]; then
    echo ">>> Creating Python venv..."
    python3 -m venv "${VENV_DIR}"
fi

source "${VENV_DIR}/bin/activate"

echo ">>> Installing conversion dependencies..."
pip install --quiet --upgrade pip
pip install --quiet "optimum[openvino]" "openvino-genai" "transformers" "torch" "Pillow"

# Step 2: Convert model to OpenVINO IR format
echo ""
echo ">>> Converting ${MODEL_ID} to OpenVINO IR format..."
echo "    This downloads the model (~2GB) and converts it. May take 5-10 minutes."
echo ""

mkdir -p "${OUTPUT_DIR}"

# Use optimum-cli to export the model
optimum-cli export openvino \
    --model "${MODEL_ID}" \
    --weight-format int4 \
    --task image-text-to-text \
    "${OUTPUT_DIR}"

echo ""
echo ">>> Conversion complete. Output directory:"
ls -lh "${OUTPUT_DIR}"

# Step 3: Create manifest.json
echo ""
echo ">>> Creating manifest.json..."

cat > "${OUTPUT_DIR}/manifest.json" << 'MANIFEST'
{
  "model_name": "internvl2-1b",
  "version": "1.0.0",
  "type": "vlm",
  "architecture": "internvl2",
  "max_tokens": 256,
  "default_system_prompt": "You are a workplace safety analyst. Analyse the image and return a JSON object with: risk_level (HIGH/MEDIUM/LOW/NONE), summary (one sentence), and risks (array of {description, severity, category}). Only return the JSON object, no other text.",
  "default_user_prompt": "Assess workplace safety risks visible in this scene."
}
MANIFEST

echo "    Created: ${OUTPUT_DIR}/manifest.json"

# Step 4: Upload to S3
echo ""
echo ">>> Uploading to s3://${S3_BUCKET}/${S3_PREFIX}..."

aws s3 sync "${OUTPUT_DIR}" "s3://${S3_BUCKET}/${S3_PREFIX}" \
    --region "${REGION}" \
    --quiet

echo "    Upload complete."

# Step 5: Print the shadow command to provision the model
echo ""
echo "=== Model ready for deployment ==="
echo ""
echo "To provision on the device, run:"
echo ""
echo "  aws iot-data update-thing-shadow \\"
echo "    --thing-name ucore-kvs-3 \\"
echo "    --shadow-name model-config \\"
echo "    --region ${REGION} \\"
echo "    --cli-binary-format raw-in-base64-out \\"
echo "    --payload '{\"state\":{\"desired\":{\"models\":{\"${MODEL_NAME}\":{\"source\":\"s3\",\"type\":\"vlm\",\"s3_uri\":\"s3://${S3_BUCKET}/${S3_PREFIX}\"}}}}}' \\"
echo "    /dev/stdout"
echo ""
echo "Then set it as active:"
echo ""
echo "  aws iot-data update-thing-shadow \\"
echo "    --thing-name ucore-kvs-3 \\"
echo "    --shadow-name model-config \\"
echo "    --region ${REGION} \\"
echo "    --cli-binary-format raw-in-base64-out \\"
echo "    --payload '{\"state\":{\"desired\":{\"active_vlm_model\":\"${MODEL_NAME}\"}}}' \\"
echo "    /dev/stdout"
echo ""

deactivate
