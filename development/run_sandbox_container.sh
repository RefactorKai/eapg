#!/usr/bin/env bash
set -euo pipefail

if (( $# == 0 )); then
    echo "Usage: bash development/run_sandbox_container.sh COMMAND [ARGS...]" >&2
    exit 2
fi
cd "$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"

if [[ $(uname -sm) != 'Linux x86_64' || $(stat -f -c %T /sys/fs/cgroup) != cgroup2fs ]]; then
    echo "Gate 1 requires an x86_64 Linux Docker host with cgroup v2." >&2
    exit 1
fi

docker build --platform linux/amd64 --file docker/gate1.Dockerfile --tag eapg-gate1 . >&2
# systemd is PID 1 and owns a writable, private cgroup v2 subtree.
container=$(docker run --rm --detach --privileged --cgroupns private --network none \
    --tmpfs /run --tmpfs /tmp:mode=1777 eapg-gate1)
trap 'docker rm -f "$container" >/dev/null 2>&1 || true' EXIT

run_as_eapg() {
    docker exec --user eapg --env HOME=/home/eapg --env XDG_RUNTIME_DIR=/run/user/1000 \
        --env DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus "$@"
}

ready=false
for _ in {1..45}; do
    if docker exec "$container" systemctl start user@1000.service &&
        run_as_eapg "$container" systemctl --user show-environment >/dev/null; then
        ready=true
        break
    fi
    sleep 1
done
if ! "$ready"; then
    docker logs "$container"
    echo "Gate 1 user systemd and session bus did not start." >&2
    exit 1
fi

# Use only tracked files and do not expose any host path to the container.
git archive HEAD | run_as_eapg -i "$container" tar -xf -
run_as_eapg -i "$container" "$@"
