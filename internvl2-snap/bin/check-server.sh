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
