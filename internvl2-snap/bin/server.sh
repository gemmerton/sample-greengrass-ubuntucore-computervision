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
