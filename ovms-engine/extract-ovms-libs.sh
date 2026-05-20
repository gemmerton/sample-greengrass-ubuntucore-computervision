#!/bin/bash
set -euo pipefail

# Extract the OVMS binary and ALL runtime shared libraries from the official
# Docker image. This must be run before `snapcraft pack`.
#
# The script extracts:
#   1. /ovms/bin/ovms         -> ./ovms
#   2. /ovms/lib/*            -> ./lib/  (OpenVINO, OpenCV, TBB, etc.)
#   3. System libs from /lib/x86_64-linux-gnu/ that are NOT provided by core24
#
# The system libraries were determined by running ldd on the binary and all
# /ovms/lib/*.so inside the container, then checking which resolved paths do
# NOT exist in the core24 base snap. This list must be re-validated if the
# OVMS_VERSION is changed.

OVMS_VERSION="2024.5"
OVMS_IMAGE="openvino/model_server:${OVMS_VERSION}"
CONTAINER_NAME="ovms-extract-$$"

# System libraries required by OVMS that are NOT in core24 (Ubuntu 24.04 base).
# Determined by cross-referencing `ldd` output with /snap/core24/current/usr/lib/.
SYSTEM_LIBS=(
    libcurl.so.4
    libicudata.so.70
    libicuuc.so.70
    liblber-2.5.so.0
    libldap-2.5.so.0
    libnghttp2.so.14
    libpsl.so.5
    libpython3.10.so.1.0
    librtmp.so.1
    libsasl2.so.2
    libssh.so.4
    libunistring.so.2
    libxml2.so.2
)

cd "$(dirname "$0")"

echo "=== Extracting OVMS ${OVMS_VERSION} binary and libraries ==="
echo "Image: ${OVMS_IMAGE}"

# Clean previous extraction
rm -f ./ovms
rm -rf ./lib

# Create a container (doesn't start it)
echo "Pulling image..."
docker pull "${OVMS_IMAGE}"
echo "Creating container..."
docker create --name "${CONTAINER_NAME}" "${OVMS_IMAGE}" >/dev/null

cleanup() {
    docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# Extract binary
echo "Extracting ovms binary..."
docker cp "${CONTAINER_NAME}:/ovms/bin/ovms" ./ovms
chmod +x ./ovms

# Extract OVMS libraries (OpenVINO, OpenCV, TBB, custom nodes, etc.)
echo "Extracting OVMS libraries..."
docker cp "${CONTAINER_NAME}:/ovms/lib/" ./lib/

# Extract system libraries not present in core24.
# Many of these are symlinks (e.g. libxml2.so.2 -> libxml2.so.2.9.13).
# `docker cp` copies symlinks as-is without their targets, so we use a
# separate `docker run` with tar --dereference to get real files.
echo "Extracting system libraries (${#SYSTEM_LIBS[@]} files, dereferencing symlinks)..."
LIB_PATHS=""
for lib in "${SYSTEM_LIBS[@]}"; do
    LIB_PATHS="${LIB_PATHS} lib/x86_64-linux-gnu/${lib}"
done
docker run --rm --entrypoint tar "${OVMS_IMAGE}" \
    ch --dereference -C / ${LIB_PATHS} \
    | tar x --strip-components=2 -C ./lib/
for lib in "${SYSTEM_LIBS[@]}"; do
    if [ -f "./lib/${lib}" ] && [ ! -L "./lib/${lib}" ]; then
        echo "  ${lib} ($(du -h ./lib/${lib} | cut -f1))"
    else
        echo "  ERROR: ${lib} not extracted as a regular file!"
        exit 1
    fi
done

# Extract Python 3.10 standard library (required by OVMS Python interpreter module)
echo "Extracting Python 3.10 stdlib..."
docker run --rm --entrypoint tar "${OVMS_IMAGE}" \
    ch --dereference -C / usr/lib/python3.10 \
    | tar x --strip-components=2 -C ./lib/
echo "  python3.10/ ($(du -sh ./lib/python3.10 | cut -f1))"

# Extract OVMS Python dependencies (jinja2, markupsafe, openvino bindings)
echo "Extracting OVMS Python deps..."
docker run --rm --entrypoint tar "${OVMS_IMAGE}" \
    ch --dereference -C /ovms python_deps \
    | tar x -C ./lib/
docker run --rm --entrypoint tar "${OVMS_IMAGE}" \
    ch --dereference -C /ovms/lib python \
    | tar x -C ./lib/
echo "  python_deps/ ($(du -sh ./lib/python_deps | cut -f1))"
echo "  python/ ($(du -sh ./lib/python | cut -f1))"

echo ""
echo "=== Extraction complete ==="
echo "Binary: ./ovms ($(du -h ./ovms | cut -f1))"
echo "Libraries: ./lib/ ($(du -sh ./lib | cut -f1), $(ls ./lib | wc -l | tr -d ' ') files)"
echo ""
echo "Run 'snapcraft pack' to build the snap."
