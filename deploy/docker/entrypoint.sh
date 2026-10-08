#!/bin/sh
set -eu
umask 077

log_dir=/workspace/.kratos/studio/logs
mkdir -p "$log_dir"
touch "$log_dir/gateway.log" "$log_dir/agent.log" "$HOME/.Xauthority"
app_pid=
display_pid=
log_pid=
cleanup() {
    code=$?
    trap - EXIT TERM INT
    if [ -n "$app_pid" ]; then
        kill -TERM "$app_pid" 2>/dev/null || true
        wait "$app_pid" 2>/dev/null || true
    fi
    if [ -n "$log_pid" ]; then kill "$log_pid" 2>/dev/null || true; fi
    if [ -n "$display_pid" ]; then kill "$display_pid" 2>/dev/null || true; fi
    exit "$code"
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

export DISPLAY=:99
# The X display is private to this container and never listens on TCP.
Xvfb "$DISPLAY" -screen 0 1920x1080x24 -nolisten tcp -ac &
display_pid=$!
attempt=0
while [ ! -S /tmp/.X11-unix/X99 ]; do
    kill -0 "$display_pid" 2>/dev/null || { echo 'Virtual display failed.' >&2; exit 1; }
    attempt=$((attempt + 1))
    [ "$attempt" -lt 50 ] || { echo 'Virtual display startup timed out.' >&2; exit 1; }
    sleep 0.1
done
tail -n 0 -F "$log_dir/gateway.log" "$log_dir/agent.log" &
log_pid=$!
kratos-studio run --workspace /workspace \
    --port "${KRATOS_PORT:-21128}" --agent-port "${KRATOS_AGENT_PORT:-7860}" \
    --no-browser --startup-timeout 600 &
app_pid=$!
wait "$app_pid"
