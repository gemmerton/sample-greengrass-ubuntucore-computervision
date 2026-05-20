#!/bin/bash -eu
# OVMS server startup wrapper
# Determines the active engine and executes its server script directly.

engine="$(modelctl show-engine --format=json | jq -r .name)"
exec "$SNAP/engines/$engine/server"
