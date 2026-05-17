# Building the Snaps

This project ships two snaps that must be built before deploying to an Ubuntu Core device:

| Snap | Directory | Purpose |
|------|-----------|---------|
| `kvs-gstreamer` | `kvs-gstreamer-snap/` | GStreamer runtime + `libgstkvssink.so`; exposed via content interface |
| `ovms-engine` | `ovms-engine/` | OpenVINO Model Server inference engine |

## Prerequisites

- **snapcraft** ≥ 8.x (`sudo snap install snapcraft --classic`)
- **LXD** initialised (`sudo lxd init --auto`) — snapcraft uses LXD for isolated builds
- **Docker** — required to extract the OVMS binary before building `ovms-engine`

## Building `kvs-gstreamer`

```bash
cd kvs-gstreamer-snap
snapcraft build
```

The build clones the [KVS Producer SDK](https://github.com/awslabs/amazon-kinesis-video-streams-producer-sdk-cpp) at build time and compiles `libgstkvssink.so`.  Internet access is required inside the LXD instance.

Output: `kvs-gstreamer_1.0.0_amd64.snap`

## Building `ovms-engine`

The OVMS snap uses a pre-built binary extracted from the official Docker image rather than compiling from source (the Bazel build takes 30+ minutes). **Run the extraction once before the first build, and again whenever you upgrade the OVMS version.**

### Step 1 — Extract the binary from Docker

```bash
cd ovms-engine

OVMS_VERSION="2024.5"
docker pull openvino/model_server:${OVMS_VERSION}
docker create --name ovms-tmp openvino/model_server:${OVMS_VERSION}
docker cp ovms-tmp:/ovms/bin/ovms ./ovms
docker cp ovms-tmp:/ovms/lib/ ./lib
docker rm ovms-tmp
```

This places `ovms-engine/ovms` (~40 MB) and `ovms-engine/lib/` on disk.  Both paths are listed in `.gitignore` and must not be committed.

> **Why `source-type: local`?**  The `ovms-engine/` directory lives inside a git repository.  Without an explicit `source-type: local` directive snapcraft auto-detects git and only copies tracked files into the build container, silently omitting the untracked `ovms` binary and `lib/` directory.  The `source-type: local` in `snap/snapcraft.yaml` forces a plain directory copy.

### Step 2 — Build the snap

```bash
snapcraft pack
```

Output: `ovms-engine_1.0.0_amd64.snap` plus component snaps (`ovms-engine+ovms-cpu.comp`, etc.)

## Installing on device

```bash
# Transfer snaps to the Ubuntu Core device, then:
sudo snap install --dangerous kvs-gstreamer_*.snap
sudo snap install --dangerous ovms-engine_*.snap

# Wire up the content interface so Greengrass can reach GStreamer + kvssink
sudo snap connect aws-iot-greengrass:gstreamer-kvs kvs-gstreamer:gstreamer-kvs
```

## Troubleshooting

### `Stage package not found: libgirepository-1.0-X`

Ubuntu 24.04 (core24) ships `libgirepository-1.0-1` (soname bump from `-0`).  The `kvs-gstreamer` snap already references the correct name.  If you see this error after a snapcraft upgrade, check the package name with `apt-cache search libgirepository`.

### `Could NOT find Log4cplus`

The KVS SDK CMake script requires `log4cplus` when `BUILD_DEPENDENCIES=OFF`.  The `kvs-gstreamer` snap includes `liblog4cplus-dev` in `build-packages` to satisfy this.  If you see this error after updating the SDK version, verify the package is still present in the `kvs-producer-sdk` part.

### OVMS binary not found in container

If `snapcraft pack` exits with `ERROR: OVMS binary not found` even though `ovms-engine/ovms` exists on disk, the most likely cause is a stale build cache that pre-dates the extraction.  Run:

```bash
snapcraft clean ovms
snapcraft pack
```
