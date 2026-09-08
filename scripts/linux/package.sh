#!/usr/bin/env bash
# Package the PyInstaller onedir payload as native Linux packages and a tarball.
# Usage: scripts/linux/package.sh <version>
# Expects dist/DataPyn/ from: uv run pyinstaller scripts/datapyn.spec --clean
set -euo pipefail

ROOT="${DATAPYN_PACKAGE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
OUTPUT_DIR="${DATAPYN_PACKAGE_OUTPUT_DIR:-$ROOT}"
DIST_DIR="${DATAPYN_PACKAGE_DIST_DIR:-$ROOT/dist/DataPyn}"
STAGE_DIR="${DATAPYN_PACKAGE_STAGE_DIR:-$ROOT/pkg}"

# The Debian dependency list is the source capability list. Every capability must have a
# family-specific mapping before its target package is built; an omitted mapping is an error.
readonly RUNTIME_CAPABILITIES=(
  opengl
  egl
  xkbcommon
  xkbcommon_x11
  dbus
  xcb_cursor
  xcb_icccm
  xcb_image
  xcb_keysyms
  xcb_randr
  xcb_render_util
  xcb_xinerama
  xcb_xfixes
  nss
  nspr
  gbm
  alsa
  drm
  xcomposite
  xdamage
  xrandr
  xss
  xtst
  atk
  atk_bridge
  cups
  pango
)

readonly OPTIONAL_CAPABILITIES=(
  libsecret
  unixodbc
)

declare -Ar DEBIAN_DEPENDENCY_MAP=(
  [opengl]="libgl1"
  [egl]="libegl1"
  [xkbcommon]="libxkbcommon0"
  [xkbcommon_x11]="libxkbcommon-x11-0"
  [dbus]="libdbus-1-3"
  [xcb_cursor]="libxcb-cursor0"
  [xcb_icccm]="libxcb-icccm4"
  [xcb_image]="libxcb-image0"
  [xcb_keysyms]="libxcb-keysyms1"
  [xcb_randr]="libxcb-randr0"
  [xcb_render_util]="libxcb-render-util0"
  [xcb_xinerama]="libxcb-xinerama0"
  [xcb_xfixes]="libxcb-xfixes0"
  [nss]="libnss3"
  [nspr]="libnspr4"
  [gbm]="libgbm1"
  [alsa]="libasound2"
  [drm]="libdrm2"
  [xcomposite]="libxcomposite1"
  [xdamage]="libxdamage1"
  [xrandr]="libxrandr2"
  [xss]="libxss1"
  [xtst]="libxtst6"
  [atk]="libatk1.0-0"
  [atk_bridge]="libatk-bridge2.0-0"
  [cups]="libcups2"
  [pango]="libpango-1.0-0"
  [libsecret]="libsecret-1-0"
  [unixodbc]="unixodbc"
)

declare -Ar RPM_DEPENDENCY_MAP=(
  [opengl]="mesa-libGL"
  [egl]="mesa-libEGL"
  [xkbcommon]="libxkbcommon"
  [xkbcommon_x11]="libxkbcommon-x11"
  [dbus]="dbus-libs"
  [xcb_cursor]="xcb-util-cursor"
  [xcb_icccm]="xcb-util-wm"
  [xcb_image]="xcb-util-image"
  [xcb_keysyms]="xcb-util-keysyms"
  [xcb_randr]="libxcb"
  [xcb_render_util]="xcb-util-renderutil"
  [xcb_xinerama]="libxcb"
  [xcb_xfixes]="libxcb"
  [nss]="nss"
  [nspr]="nspr"
  [gbm]="mesa-libgbm"
  [alsa]="alsa-lib"
  [drm]="libdrm"
  [xcomposite]="libXcomposite"
  [xdamage]="libXdamage"
  [xrandr]="libXrandr"
  [xss]="libXScrnSaver"
  [xtst]="libXtst"
  [atk]="atk"
  [atk_bridge]="at-spi2-atk"
  [cups]="cups-libs"
  [pango]="pango"
  [libsecret]="libsecret"
  [unixodbc]="unixODBC"
)

declare -Ar PACMAN_DEPENDENCY_MAP=(
  [opengl]="mesa"
  [egl]="mesa"
  [xkbcommon]="libxkbcommon"
  [xkbcommon_x11]="libxkbcommon-x11"
  [dbus]="dbus"
  [xcb_cursor]="xcb-util-cursor"
  [xcb_icccm]="xcb-util-wm"
  [xcb_image]="xcb-util-image"
  [xcb_keysyms]="xcb-util-keysyms"
  [xcb_randr]="libxcb"
  [xcb_render_util]="xcb-util-renderutil"
  [xcb_xinerama]="libxcb"
  [xcb_xfixes]="libxcb"
  [nss]="nss"
  [nspr]="nspr"
  [gbm]="mesa"
  [alsa]="alsa-lib"
  [drm]="libdrm"
  [xcomposite]="libxcomposite"
  [xdamage]="libxdamage"
  [xrandr]="libxrandr"
  [xss]="libxss"
  [xtst]="libxtst"
  [atk]="atk"
  [atk_bridge]="at-spi2-core"
  [cups]="libcups"
  [pango]="pango"
  [libsecret]="libsecret"
  [unixodbc]="unixodbc"
)

VERSION="${1:-}"
DEB_VERSIONED=""
DEB_STABLE=""
RPM_VERSIONED=""
RPM_STABLE=""
PACMAN_VERSIONED=""
PACMAN_STABLE=""
APPIMAGE_VERSIONED=""
APPIMAGE_STABLE=""
TAR_VERSIONED=""
TAR_STABLE=""
MAPPED_DEPENDENCIES=()
MAPPED_RECOMMENDS=()

set_artifact_names() {
  local version="$1"

  DEB_VERSIONED="datapyn_${version}_amd64.deb"
  DEB_STABLE="datapyn_amd64.deb"
  RPM_VERSIONED="datapyn-${version}-1.x86_64.rpm"
  RPM_STABLE="datapyn-x86_64.rpm"
  PACMAN_VERSIONED="datapyn-${version}-1-x86_64.pkg.tar.zst"
  PACMAN_STABLE="datapyn-x86_64.pkg.tar.zst"
  APPIMAGE_VERSIONED="DataPyn-${version}-x86_64.AppImage"
  APPIMAGE_STABLE="DataPyn-x86_64.AppImage"
  TAR_VERSIONED="DataPyn-${version}-linux-x86_64.tar.gz"
  TAR_STABLE="DataPyn-linux-x86_64.tar.gz"
}

print_plan() {
  local version="$1"

  set_artifact_names "$version"
  printf 'deb_versioned=%s\n' "$DEB_VERSIONED"
  printf 'deb_stable=%s\n' "$DEB_STABLE"
  printf 'rpm_versioned=%s\n' "$RPM_VERSIONED"
  printf 'rpm_stable=%s\n' "$RPM_STABLE"
  printf 'pacman_versioned=%s\n' "$PACMAN_VERSIONED"
  printf 'pacman_stable=%s\n' "$PACMAN_STABLE"
  printf 'appimage_versioned=%s\n' "$APPIMAGE_VERSIONED"
  printf 'appimage_stable=%s\n' "$APPIMAGE_STABLE"
  printf 'tar_versioned=%s\n' "$TAR_VERSIONED"
  printf 'tar_stable=%s\n' "$TAR_STABLE"
}

validate_version() {
  local version="$1"

  if [[ ! "$version" =~ ^[[:alnum:]][[:alnum:].+~:_-]*$ ]]; then
    echo "error: invalid release version: $version" >&2
    return 1
  fi
}

dependency_map_for_family() {
  case "$1" in
    deb) printf '%s\n' DEBIAN_DEPENDENCY_MAP ;;
    rpm) printf '%s\n' RPM_DEPENDENCY_MAP ;;
    pacman) printf '%s\n' PACMAN_DEPENDENCY_MAP ;;
    *)
      echo "error: unsupported package family: $1" >&2
      return 1
      ;;
  esac
}

map_dependency() {
  local family="$1"
  local capability="$2"
  local map_name
  local mapped

  map_name="$(dependency_map_for_family "$family")"
  # Bash namerefs keep the capability list as the single source of truth while keeping the
  # family maps readable above.
  declare -n dependency_map="$map_name"
  mapped="${dependency_map[$capability]-}"

  if [[ -z "$mapped" ]]; then
    echo "error: missing $family dependency mapping for capability: $capability" >&2
    return 1
  fi
  if [[ ! "$mapped" =~ ^[[:alnum:]][[:alnum:].+_-]*$ ]]; then
    echo "error: invalid $family dependency mapping for capability $capability: $mapped" >&2
    return 1
  fi
  # A few capability names are intentionally identical across distributions (for example
  # Arch's `unixodbc`). The explicit family map above is authoritative; only reject a shared
  # name when it is not one of those valid cross-family package names.
  if [[ "$family" != deb && "$capability" != unixodbc && "$mapped" == "${DEBIAN_DEPENDENCY_MAP[$capability]-}" ]]; then
    echo "error: $family dependency mapping for capability $capability still uses Debian name: $mapped" >&2
    return 1
  fi

  printf '%s\n' "$mapped"
}

collect_dependencies() {
  local family="$1"
  local capability
  local mapped
  declare -A seen=()

  MAPPED_DEPENDENCIES=()
  for capability in "${RUNTIME_CAPABILITIES[@]}"; do
    mapped="$(map_dependency "$family" "$capability")"
    if [[ -z "${seen[$mapped]-}" ]]; then
      MAPPED_DEPENDENCIES+=("$mapped")
      seen["$mapped"]=1
    fi
  done
}

collect_recommends() {
  local family="$1"
  local capability
  local mapped
  declare -A seen=()

  MAPPED_RECOMMENDS=()
  for capability in "${OPTIONAL_CAPABILITIES[@]}"; do
    mapped="$(map_dependency "$family" "$capability")"
    if [[ -z "${seen[$mapped]-}" ]]; then
      MAPPED_RECOMMENDS+=("$mapped")
      seen["$mapped"]=1
    fi
  done
}

print_dependencies() {
  local family="$1"
  local dependency

  collect_dependencies "$family"
  collect_recommends "$family"
  for dependency in "${MAPPED_DEPENDENCIES[@]}"; do
    printf 'depends=%s\n' "$dependency"
  done
  for dependency in "${MAPPED_RECOMMENDS[@]}"; do
    printf 'recommends=%s\n' "$dependency"
  done
}

require_command() {
  local command_name="$1"
  local target="$2"

  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "error: required executable '$command_name' is missing; it blocks $target packaging validation." >&2
    return 1
  fi
}

check_toolchain() {
  require_command fpm "native Linux packages"
  require_command dpkg-deb ".deb"
  require_command rpm ".rpm"
  require_command rpmbuild ".rpm"
  require_command pacman ".pkg.tar.zst"
  require_command zstd ".pkg.tar.zst"
  require_command tar "tar.gz"
}

stage_payload() {
  if [[ ! -d "$DIST_DIR" ]]; then
    echo "error: dist/DataPyn not found. Run PyInstaller first." >&2
    return 1
  fi

  rm -rf "$STAGE_DIR"
  mkdir -p \
    "$STAGE_DIR/opt/datapyn" \
    "$STAGE_DIR/usr/share/applications" \
    "$STAGE_DIR/usr/share/mime/packages"

  cp -a "$DIST_DIR/." "$STAGE_DIR/opt/datapyn/"
  cp "$ROOT/scripts/linux/datapyn.desktop" "$STAGE_DIR/usr/share/applications/"
  cp "$ROOT/scripts/linux/datapyn-workspace.xml" "$STAGE_DIR/usr/share/mime/packages/"
  install -m 755 "$ROOT/scripts/linux/datapyn-wrapper.sh" "$STAGE_DIR/opt/datapyn/datapyn-wrapper.sh"

  if [[ ! -f "$STAGE_DIR/opt/datapyn/datapyn_logo.svg" ]]; then
    cp "$ROOT/source/src/assets/datapyn_logo.svg" "$STAGE_DIR/opt/datapyn/datapyn_logo.svg"
  fi
}

cleanup_outputs() {
  local output
  for output in \
    "$DEB_VERSIONED" "$DEB_STABLE" \
    "$RPM_VERSIONED" "$RPM_STABLE" \
    "$PACMAN_VERSIONED" "$PACMAN_STABLE" \
    "$TAR_VERSIONED" "$TAR_STABLE"; do
    [[ -z "$output" ]] || rm -f "$OUTPUT_DIR/$output"
  done
}

cleanup_on_error() {
  local status=$?

  if [[ "$status" -ne 0 ]]; then
    cleanup_outputs
  fi
  exit "$status"
}

validate_contents() {
  local listing="$1"
  local package_name="$2"
  local required_path

  for required_path in \
    /opt/datapyn/DataPyn \
    /opt/datapyn/datapyn-wrapper.sh \
    /opt/datapyn/datapyn_logo.svg \
    /usr/share/applications/datapyn.desktop \
    /usr/share/mime/packages/datapyn-workspace.xml; do
    if ! grep -Fq "$required_path" <<<"$listing"; then
      echo "error: $package_name is missing required payload path: $required_path" >&2
      return 1
    fi
  done
}

validate_deb() {
  local package_path="$1"
  local metadata
  local listing
  local dependency

  metadata="$(dpkg-deb --field "$package_path" 2>/dev/null)"
  grep -Eq "^Version: ${VERSION//./\\.}($|[[:space:]])" <<<"$metadata" || {
    echo "error: .deb metadata version does not match $VERSION: $package_path" >&2
    return 1
  }
  grep -Eq '^Architecture: amd64$' <<<"$metadata" || {
    echo "error: .deb metadata architecture is not amd64: $package_path" >&2
    return 1
  }
  listing="$(dpkg-deb --contents "$package_path")"
  validate_contents "$listing" "$package_path"

  for dependency in "${MAPPED_DEPENDENCIES[@]}"; do
    grep -Fq "$dependency" <<<"$metadata" || {
      echo "error: .deb metadata is missing dependency $dependency: $package_path" >&2
      return 1
    }
  done
}

validate_rpm() {
  local package_path="$1"
  local metadata
  local listing
  local dependency

  metadata="$(rpm -qp --queryformat '%{VERSION}\t%{ARCH}\n' "$package_path")"
  grep -Eq "^${VERSION//./\\.}[[:space:]]+x86_64$" <<<"$metadata" || {
    echo "error: .rpm metadata version/architecture does not match $VERSION/x86_64: $package_path" >&2
    return 1
  }
  listing="$(rpm -qpl "$package_path")"
  validate_contents "$listing" "$package_path"

  metadata="$(rpm -qp --requires "$package_path")"
  for dependency in "${MAPPED_DEPENDENCIES[@]}"; do
    grep -Fq "$dependency" <<<"$metadata" || {
      echo "error: .rpm metadata is missing dependency $dependency: $package_path" >&2
      return 1
    }
  done
}

validate_pacman() {
  local package_path="$1"
  local metadata
  local listing
  local dependency

  metadata="$(pacman -Qip "$package_path")"
  grep -Eq "^Version[[:space:]]*:[[:space:]]*${VERSION//./\\.}(-1)?$" <<<"$metadata" || {
    echo "error: pacman metadata version does not match $VERSION: $package_path" >&2
    return 1
  }
  grep -Eq '^Architecture[[:space:]]*:[[:space:]]*x86_64$' <<<"$metadata" || {
    echo "error: pacman metadata architecture is not x86_64: $package_path" >&2
    return 1
  }
  listing="$(pacman -Qlp "$package_path")"
  validate_contents "$listing" "$package_path"

  for dependency in "${MAPPED_DEPENDENCIES[@]}"; do
    grep -Fq "$dependency" <<<"$metadata" || {
      echo "error: pacman metadata is missing dependency $dependency: $package_path" >&2
      return 1
    }
  done
}

validate_package() {
  local family="$1"
  local package_path="$2"

  case "$family" in
    deb) validate_deb "$package_path" || return 1 ;;
    rpm) validate_rpm "$package_path" || return 1 ;;
    pacman) validate_pacman "$package_path" || return 1 ;;
    *)
      echo "error: unsupported package family: $family" >&2
      return 1
      ;;
  esac
  echo "Validated $package_path"
}

build_fpm_package() {
  local family="$1"
  local target="$2"
  local architecture="$3"
  local output_path="$4"
  local dependency
  local -a fpm_args=(
    -s dir
    -t "$target"
    -n datapyn
    -v "$VERSION"
    --architecture "$architecture"
    --description "DataPyn - SQL + Python IDE for data analysis"
    --url "https://github.com/${GITHUB_REPOSITORY:-natharuc/datapyn}"
    --license MIT
    --after-install "$ROOT/scripts/linux/postinst.sh"
    --before-remove "$ROOT/scripts/linux/prerm.sh"
  )

  case "$family" in
    deb) fpm_args+=(--deb-use-file-permissions) ;;
    rpm) fpm_args+=(--rpm-use-file-permissions) ;;
    pacman) fpm_args+=(--pacman-use-file-permissions) ;;
  esac
  if [[ "$family" != deb ]]; then
    fpm_args+=(--iteration 1)
  fi

  collect_dependencies "$family"
  collect_recommends "$family"
  for dependency in "${MAPPED_DEPENDENCIES[@]}"; do
    fpm_args+=(--depends "$dependency")
  done
  for dependency in "${MAPPED_RECOMMENDS[@]}"; do
    case "$family" in
      deb) fpm_args+=(--deb-recommends "$dependency") ;;
      rpm) fpm_args+=(--rpm-tag "Recommends: $dependency") ;;
      pacman) fpm_args+=(--pacman-optional-depends "$dependency") ;;
    esac
  done
  if [[ "$family" == pacman ]]; then
    fpm_args+=(--pacman-compression zstd)
  fi

  fpm_args+=(
    -C "$STAGE_DIR"
    -p "$output_path"
    .
  )
  fpm "${fpm_args[@]}"
}

build_tarball() {
  tar -czf "$OUTPUT_DIR/$TAR_VERSIONED" -C "$(dirname "$DIST_DIR")" "$(basename "$DIST_DIR")"
}

copy_stable_alias() {
  local versioned="$1"
  local stable="$2"

  cp "$OUTPUT_DIR/$versioned" "$OUTPUT_DIR/$stable"
  cmp -s "$OUTPUT_DIR/$versioned" "$OUTPUT_DIR/$stable" || {
    echo "error: stable alias is not byte-identical to $versioned: $stable" >&2
    return 1
  }
}

main() {
  if [[ "${1:-}" == "--print-plan" ]]; then
    [[ -n "${2:-}" ]] || { echo "error: version required (e.g. 1.57.0)" >&2; return 1; }
    validate_version "$2"
    print_plan "$2"
    return 0
  fi

  if [[ "${1:-}" == "--print-dependencies" ]]; then
    case "${2:-}" in
      deb|rpm|pacman) print_dependencies "$2" ;;
      *) echo "error: package family required: deb, rpm, or pacman" >&2; return 1 ;;
    esac
    return 0
  fi

  local version="${1:-}"
  if [[ -z "$version" ]]; then
    echo "error: version required (e.g. 1.57.0)" >&2
    return 1
  fi
  validate_version "$version"
  set_artifact_names "$version"
  VERSION="$version"

  if [[ ! -d "$DIST_DIR" ]]; then
    echo "error: dist/DataPyn not found. Run PyInstaller first." >&2
    return 1
  fi

  trap cleanup_on_error EXIT
  mkdir -p "$OUTPUT_DIR"
  cleanup_outputs
  check_toolchain
  stage_payload

  build_fpm_package deb deb amd64 "$OUTPUT_DIR/$DEB_VERSIONED"
  collect_dependencies deb
  validate_package deb "$OUTPUT_DIR/$DEB_VERSIONED"

  build_fpm_package rpm rpm x86_64 "$OUTPUT_DIR/$RPM_VERSIONED"
  collect_dependencies rpm
  validate_package rpm "$OUTPUT_DIR/$RPM_VERSIONED"

  build_fpm_package pacman pacman x86_64 "$OUTPUT_DIR/$PACMAN_VERSIONED"
  collect_dependencies pacman
  validate_package pacman "$OUTPUT_DIR/$PACMAN_VERSIONED"

  build_tarball

  copy_stable_alias "$DEB_VERSIONED" "$DEB_STABLE"
  copy_stable_alias "$RPM_VERSIONED" "$RPM_STABLE"
  copy_stable_alias "$PACMAN_VERSIONED" "$PACMAN_STABLE"
  copy_stable_alias "$TAR_VERSIONED" "$TAR_STABLE"

  trap - EXIT
  echo "Created:"
  printf '%s\n' \
    "$DEB_VERSIONED" "$RPM_VERSIONED" "$PACMAN_VERSIONED" "$TAR_VERSIONED" \
    "$DEB_STABLE" "$RPM_STABLE" "$PACMAN_STABLE" "$TAR_STABLE"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
