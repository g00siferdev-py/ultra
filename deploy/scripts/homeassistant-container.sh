#!/usr/bin/env bash
# Manage the bundled Home Assistant container on Linux Ultra.
set -euo pipefail

IMAGE="${ULTRA_HA_IMAGE:-ghcr.io/home-assistant/home-assistant:stable}"
NAME="${ULTRA_HA_CONTAINER:-homeassistant}"
CONFIG_DIR="${ULTRA_HA_CONFIG:-/var/lib/homeassistant}"
READY_FLAG="${CONFIG_DIR}/.docker-image-ready"

usage() {
  echo "Usage: ultra-homeassistant {pull|start|stop|status}" >&2
  exit 1
}

require_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "docker is not installed" >&2
    exit 1
  fi
  if ! docker info >/dev/null 2>&1; then
    echo "docker daemon is not running" >&2
    exit 1
  fi
}

cmd_pull() {
  require_docker
  mkdir -p "${CONFIG_DIR}"
  echo "Pulling ${IMAGE} (first run may take several minutes)..."
  docker pull "${IMAGE}"
  touch "${READY_FLAG}"
  echo "Home Assistant image ready."
}

cmd_start() {
  require_docker
  mkdir -p "${CONFIG_DIR}"
  if ! docker ps -a --format '{{.Names}}' | grep -qx "${NAME}"; then
    if [ ! -f "${READY_FLAG}" ]; then
      cmd_pull
    fi
    exec docker run --name "${NAME}" \
      --privileged \
      --network=host \
      -v "${CONFIG_DIR}:/config" \
      -v /etc/localtime:/etc/localtime:ro \
      -v /run/dbus:/run/dbus:ro \
      "${IMAGE}"
  fi
  exec docker start -a "${NAME}"
}

cmd_stop() {
  require_docker
  docker stop "${NAME}" 2>/dev/null || true
}

cmd_status() {
  require_docker
  if docker ps --format '{{.Names}}' | grep -qx "${NAME}"; then
    echo "running"
    docker ps --filter "name=^${NAME}$" --format 'image={{.Image}} uptime={{.Status}}'
    exit 0
  fi
  if docker ps -a --format '{{.Names}}' | grep -qx "${NAME}"; then
    echo "stopped"
    exit 1
  fi
  echo "not-created"
  exit 2
}

case "${1:-}" in
  pull) cmd_pull ;;
  start) cmd_start ;;
  stop) cmd_stop ;;
  status) cmd_status ;;
  *) usage ;;
esac
