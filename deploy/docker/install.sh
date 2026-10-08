#!/usr/bin/env bash
# Ubuntu Docker installer. pack.py can attach a checked source snapshot.
set -Eeuo pipefail
umask 077
BASE=/opt/kratos-docker
APP=$BASE/app
WORK=/var/lib/kratos/workspace
CONTAINER_HOME=/var/lib/kratos/docker-home
SOURCE_REVISION=local-checkout
SOURCE_SHA256=__ARCHIVE_SHA256__
PORT=21128
temp_dir=
old_service_active=false
old_workspace_owner=
new_container_attempted=false

fail() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }
compose() { docker compose --project-directory "$BASE" -f "$BASE/compose.yaml" "$@"; }
finish() {
    code=$?
    trap - EXIT
    if (( code != 0 )); then
        printf '\nDocker setup failed. Existing workspace data is at %s.\n' "$WORK" >&2
        if [[ "$new_container_attempted" == true ]]; then
            compose logs --tail 60 2>/dev/null || true
            if [[ "$old_service_active" == true ]]; then
                compose stop kratos 2>/dev/null || true
                chown -R "$old_workspace_owner" "$WORK"
                systemctl start kratos.service || true
            fi
        fi
    fi
    if [[ "$temp_dir" == /tmp/kratos-docker.* && -d "$temp_dir" && ! -L "$temp_dir" ]]; then
        rm -rf -- "$temp_dir"
    fi
    exit "$code"
}
trap finish EXIT
[[ $(id -u) == 0 ]] || fail 'Run as root on the Ubuntu server.'
. /etc/os-release
[[ "$ID" == ubuntu ]] || fail 'This installer targets Ubuntu.'
[[ "$VERSION_ID" == 24.04 || "$VERSION_ID" == 26.04 ]] || fail 'Ubuntu 24.04 or 26.04 is required.'
[[ $(uname -m) == x86_64 ]] || fail 'This bundled deployment targets x86_64.'
[[ $(ps -p 1 -o comm=) == systemd ]] || fail 'A systemd Ubuntu host is required.'
[[ ! -L "$BASE" && ! -L "$WORK" && ! -L "$CONTAINER_HOME" ]] || fail 'Deployment directories must not be symbolic links.'

printf '\n[1/5] Preparing Docker Engine and Compose...\n'
export DEBIAN_FRONTEND=noninteractive
if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
    apt-get update
    apt-get install -y --no-install-recommends ca-certificates curl
    install -d -m 0755 /etc/apt/keyrings
    curl --fail --location --retry 4 --connect-timeout 30 \
        https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    cat > /etc/apt/sources.list.d/docker.sources <<REPO
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${UBUNTU_CODENAME:-$VERSION_CODENAME}
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
REPO
    apt-get update
    if command -v docker >/dev/null 2>&1; then
        apt-get install -y docker-buildx-plugin docker-compose-plugin
    else
        apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    fi
fi
systemctl enable --now docker
docker info >/dev/null
docker compose version

# The gateway build needs more memory than a small VPS usually provides.
memory_kb=$(awk '/MemTotal:/ {print $2}' /proc/meminfo)
swap_kb=$(awk '/SwapTotal:/ {print $2}' /proc/meminfo)
if (( memory_kb + swap_kb < 8388608 )); then
    install -d -m 0755 /var/swap
    swap_file=/var/swap/kratos.swap
    if [[ ! -e "$swap_file" ]]; then
        available_kb=$(df -Pk /var/swap | awk 'NR == 2 {print $4}')
        (( available_kb >= 25165824 )) || fail 'At least 24 GB free disk is required for the build and swap.'
        printf 'Preparing 8 GB swap for the first image build...\n'
        fallocate -l 8G "$swap_file"
        chmod 0600 "$swap_file"
        mkswap "$swap_file"
    fi
    swapon --show=NAME --noheadings | grep -Fxq "$swap_file" || swapon "$swap_file"
    if ! grep -qF "$swap_file " /etc/fstab; then
        printf '%s none swap sw 0 0\n' "$swap_file" >> /etc/fstab
    fi
fi

printf '\n[2/5] Preparing the bundled Kratos source...\n'
temp_dir=$(mktemp -d /tmp/kratos-docker.XXXXXX)
mkdir "$temp_dir/source"
if grep -qx '__KRATOS_SOURCE_PAYLOAD_BEGIN__' "$0"; then
    awk '
        $0 == "__KRATOS_SOURCE_PAYLOAD_END__" { exit }
        found { print }
        $0 == "__KRATOS_SOURCE_PAYLOAD_BEGIN__" { found = 1 }
    ' "$0" | base64 --decode > "$temp_dir/source.tar.gz"
    printf '%s  %s\n' "$SOURCE_SHA256" "$temp_dir/source.tar.gz" | sha256sum --check -
    tar -xzf "$temp_dir/source.tar.gz" -C "$temp_dir/source"
else
    script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
    source_root=$(cd -- "$script_dir/../.." && pwd)
    [[ -f "$source_root/src/kratos_agent/product.py" && -f "$source_root/Dockerfile" ]] \
        || fail 'Use the packaged installer, or run deploy/docker/install.sh from the merged repository.'
    cp -a "$source_root/." "$temp_dir/source/"
fi
[[ -f "$temp_dir/source/src/kratos_agent/product.py" && -f "$temp_dir/source/compose.yaml" ]] \
    || fail 'The source snapshot is incomplete.'
install -d -m 0700 "$BASE"
[[ ! -L "$APP" ]] || fail 'The app directory must not be a symbolic link.'
if [[ -e "$APP" ]]; then
    [[ -f "$APP/.kratos-docker-snapshot" ]] || fail "$APP already exists; move it aside before installation."
    if [[ $(cat "$APP/.kratos-docker-snapshot") != "$SOURCE_REVISION:$SOURCE_SHA256" ]]; then
        [[ ! -L "$BASE/backups" ]] || fail 'The backup directory must not be a symbolic link.'
        install -d -m 0700 "$BASE/backups"
        previous_source="$BASE/backups/app.$(date +%Y%m%d-%H%M%S)-$$"
        mv -- "$APP" "$previous_source"
        printf 'Previous source retained at %s\n' "$previous_source"
    fi
fi
if [[ ! -e "$APP" ]]; then
    mv "$temp_dir/source" "$APP"
    printf '%s\n' "$SOURCE_REVISION:$SOURCE_SHA256" > "$APP/.kratos-docker-snapshot"
fi
cp "$APP/compose.yaml" "$BASE/compose.yaml"

printf '\n[3/5] Creating the persistent configuration...\n'
if [[ ! -e "$BASE/.env" ]]; then
    if [[ -f /etc/kratos/kratos.env ]]; then
        cp /etc/kratos/kratos.env "$BASE/.env"
    else
        cp "$APP/deploy/docker/.env.example" "$BASE/.env"
        password=$(od -An -N20 -tx1 /dev/urandom | tr -d ' \n')
        sed -i "s/^INITIAL_PASSWORD=.*/INITIAL_PASSWORD=$password/" "$BASE/.env"
    fi
    cat >> "$BASE/.env" <<ENV

KRATOS_BUILD_CONTEXT=$APP
KRATOS_WORKSPACE_PATH=$WORK
KRATOS_HOME_PATH=$CONTAINER_HOME
KRATOS_PORT=$PORT
KRATOS_AGENT_PORT=7860
ENV
fi
chmod 0600 "$BASE/.env"
compose config --quiet

printf '\n[4/5] Building the Docker image; first build can take several minutes...\n'
compose build
# Build first, then release the old service's ports. Preserve its data in place.
if systemctl is-active --quiet kratos.service; then
    old_service_active=true
    old_workspace_owner=$(stat -c '%u:%g' "$WORK")
    systemctl stop kratos.service
fi
install -d -m 0700 "$WORK" "$CONTAINER_HOME"
new_container_attempted=true
chown -R 10001:10001 "$WORK" "$CONTAINER_HOME"

printf '\n[5/5] Starting Kratos and waiting for both services...\n'
compose up -d --wait --wait-timeout 900
if systemctl cat kratos.service >/dev/null 2>&1; then
    systemctl disable kratos.service
    if [[ -f /etc/systemd/system/kratos.service && ! -L /etc/systemd/system/kratos.service ]]; then
        install -d -m 0700 "$BASE/backups"
        mv /etc/systemd/system/kratos.service "$BASE/backups/kratos.service.$(date +%Y%m%d-%H%M%S)"
        systemctl daemon-reload
    fi
fi
login_password=$(compose exec -T kratos python -c \
    'import json; print(json.load(open("/workspace/.kratos/studio/gateway/studio-secrets.json"))["INITIAL_PASSWORD"])')
printf '\nKratos Docker is healthy and starts automatically after reboot.\n'
printf 'Initial dashboard password: %s\n' "$login_password"
printf 'Configuration: %s/.env\nWorkspace: %s\n' "$BASE" "$WORK"
cat <<SUMMARY

Open a NEW Windows PowerShell window and keep this tunnel running:
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -p 2222 -L 21128:127.0.0.1:21128 root@160.250.204.20

Open: http://127.0.0.1:21128/dashboard/kratos
Connect your provider accounts under Providers after signing in.
For job applications: open Jobs, save your applicant profile and resume, then Start auto-apply.

Status:  docker compose --project-directory $BASE ps
Logs:    docker compose --project-directory $BASE logs -f --tail 100
Restart: docker compose --project-directory $BASE restart kratos
Stop:    docker compose --project-directory $BASE stop
Start:   docker compose --project-directory $BASE up -d --wait
SUMMARY
old_service_active=false
exit 0
