#!/usr/bin/env bash
# Run pacman metadata queries in an Arch container from an Ubuntu packaging runner.
set -euo pipefail

ROOT="${DATAPYN_PACKAGE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
IMAGE="${DATAPYN_PACMAN_CONTAINER_IMAGE:-archlinux:base}"

if [[ "$#" -eq 0 ]]; then
  echo "error: pacman arguments are required" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "error: docker is required for the Arch pacman validation container." >&2
  exit 1
fi

container_args=()
for argument in "$@"; do
  case "$argument" in
    "$ROOT"/*)
      container_args+=("/workspace/${argument#"$ROOT"/}")
      ;;
    /*)
      echo "error: absolute pacman query paths must be inside the package root: $argument" >&2
      exit 1
      ;;
    *)
      container_args+=("$argument")
      ;;
  esac
done

exec docker run --rm --pull=always \
  --volume "$ROOT:/workspace:ro" \
  "$IMAGE" \
  pacman "${container_args[@]}"
