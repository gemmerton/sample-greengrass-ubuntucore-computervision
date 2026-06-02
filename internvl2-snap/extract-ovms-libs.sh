#!/bin/bash
set -euo pipefail

OVMS_VERSION="2025.0"
OVMS_IMAGE="openvino/model_server:${OVMS_VERSION}"

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
