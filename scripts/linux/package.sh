#!/usr/bin/env bash
# Package the PyInstaller onedir payload as native Linux packages, an AppImage, and a tarball.
# Usage: scripts/linux/package.sh <version>
# Expects dist/DataPyn/ from: uv run pyinstaller scripts/datapyn.spec --clean
set -euo pipefail

ROOT="${DATAPYN_PACKAGE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
OUTPUT_DIR="${DATAPYN_PACKAGE_OUTPUT_DIR:-$ROOT}"
DIST_DIR="${DATAPYN_PACKAGE_DIST_DIR:-$ROOT/dist/DataPyn}"
STAGE_DIR="${DATAPYN_PACKAGE_STAGE_DIR:-$ROOT/pkg}"
APPDIR="${DATAPYN_PACKAGE_APPDIR:-$ROOT/pkg-appimage}"
APPIMAGE_TOOLCHAIN_FILE="${DATAPYN_APPIMAGE_TOOLCHAIN_FILE:-$ROOT/scripts/linux/appimage-toolchain.env}"
APPIMAGETOOL_PATH="${DATAPYN_APPIMAGE_TOOL:-${APPIMAGETOOL:-}}"
APPIMAGE_RUNTIME_PATH="${DATAPYN_APPIMAGE_RUNTIME:-${APPIMAGE_RUNTIME_FILE:-}}"

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

load_appimage_toolchain() {
  if [[ ! -f "$APPIMAGE_TOOLCHAIN_FILE" ]]; then
    echo "error: pinned AppImage toolchain input is missing: $APPIMAGE_TOOLCHAIN_FILE" >&2
    return 1
  fi

  # shellcheck disable=SC1090
  source "$APPIMAGE_TOOLCHAIN_FILE"

  local required_variable
  for required_variable in \
    APPIMAGETOOL_VERSION APPIMAGETOOL_URL APPIMAGETOOL_SHA256 \
    APPIMAGE_RUNTIME_VERSION APPIMAGE_RUNTIME_URL APPIMAGE_RUNTIME_SHA256 \
    APPIMAGE_ARCHITECTURE APPIMAGE_RUNTIME_KIND; do
    if [[ -z "${!required_variable:-}" ]]; then
      echo "error: pinned AppImage toolchain input is missing $required_variable" >&2
      return 1
    fi
  done
}

validate_checksum_value() {
  local label="$1"
  local checksum="$2"

  if [[ ! "$checksum" =~ ^[[:xdigit:]]{64}$ || "$checksum" != "${checksum,,}" ]]; then
    echo "error: $label must be a lowercase 64-character SHA-256 value" >&2
    return 1
  fi
}

validate_appimage_toolchain_input() {
  load_appimage_toolchain

  case "$APPIMAGETOOL_VERSION" in
    continuous|latest)
      echo "error: AppImage builder version must be immutable, not $APPIMAGETOOL_VERSION" >&2
      return 1
      ;;
  esac
  case "$APPIMAGE_RUNTIME_VERSION" in
    continuous|latest)
      echo "error: AppImage runtime version must be immutable, not $APPIMAGE_RUNTIME_VERSION" >&2
      return 1
      ;;
  esac

  if [[ "$APPIMAGE_ARCHITECTURE" != "x86_64" ]]; then
    echo "error: AppImage packaging supports x86_64 only: $APPIMAGE_ARCHITECTURE" >&2
    return 1
  fi
  if [[ "$APPIMAGE_RUNTIME_KIND" != "type2" ]]; then
    echo "error: AppImage runtime must be Type 2: $APPIMAGE_RUNTIME_KIND" >&2
    return 1
  fi

  local expected_tool_url
  local expected_runtime_url
  expected_tool_url="https://github.com/AppImage/appimagetool/releases/download/${APPIMAGETOOL_VERSION}/appimagetool-x86_64.AppImage"
  expected_runtime_url="https://github.com/AppImage/type2-runtime/releases/download/${APPIMAGE_RUNTIME_VERSION}/runtime-x86_64"
  if [[ "$APPIMAGETOOL_URL" != "$expected_tool_url" ]]; then
    echo "error: AppImage builder URL is not the pinned official x86_64 release URL" >&2
    return 1
  fi
  if [[ "$APPIMAGE_RUNTIME_URL" != "$expected_runtime_url" ]]; then
    echo "error: AppImage runtime URL is not the pinned official x86_64 release URL" >&2
    return 1
  fi

  validate_checksum_value APPIMAGETOOL_SHA256 "$APPIMAGETOOL_SHA256"
  validate_checksum_value APPIMAGE_RUNTIME_SHA256 "$APPIMAGE_RUNTIME_SHA256"
}

resolve_appimage_toolchain() {
  validate_appimage_toolchain_input

  if [[ -z "$APPIMAGETOOL_PATH" ]]; then
    APPIMAGETOOL_PATH="$(command -v appimagetool || true)"
  fi
  if [[ -z "$APPIMAGETOOL_PATH" || ! -f "$APPIMAGETOOL_PATH" ]]; then
    echo "error: pinned AppImage builder is unavailable; set DATAPYN_APPIMAGE_TOOL to the verified appimagetool binary." >&2
    return 1
  fi
  if [[ ! -x "$APPIMAGETOOL_PATH" ]]; then
    echo "error: pinned AppImage builder is not executable: $APPIMAGETOOL_PATH" >&2
    return 1
  fi

  if [[ -z "$APPIMAGE_RUNTIME_PATH" || ! -f "$APPIMAGE_RUNTIME_PATH" ]]; then
    echo "error: pinned Type 2 AppImage runtime is unavailable; set DATAPYN_APPIMAGE_RUNTIME to the verified runtime-x86_64 file." >&2
    return 1
  fi
  if [[ ! -x "$APPIMAGE_RUNTIME_PATH" ]]; then
    echo "error: pinned Type 2 AppImage runtime is not executable: $APPIMAGE_RUNTIME_PATH" >&2
    return 1
  fi

  verify_pinned_file "AppImage builder" "$APPIMAGETOOL_PATH" "$APPIMAGETOOL_SHA256"
  verify_pinned_file "Type 2 AppImage runtime" "$APPIMAGE_RUNTIME_PATH" "$APPIMAGE_RUNTIME_SHA256"
}

verify_pinned_file() {
  local label="$1"
  local path="$2"
  local expected="$3"
  local actual

  if ! command -v sha256sum >/dev/null 2>&1; then
    echo "error: required executable 'sha256sum' is missing; it blocks $label verification." >&2
    return 1
  fi
  actual="$(sha256sum -- "$path" | awk '{print $1}')"
  if [[ "$actual" != "$expected" ]]; then
    echo "error: $label checksum mismatch: $path" >&2
    echo "expected: $expected" >&2
    echo "actual: $actual" >&2
    return 1
  fi
}

check_appimage_toolchain() {
  resolve_appimage_toolchain
}

validate_fuse3_policy() {
  local policy_input="${1:-${DATAPYN_APPIMAGE_FUSE_POLICY:-}}"
  local policy_text="$policy_input"

  if [[ -n "$policy_input" && -f "$policy_input" ]]; then
    policy_text="$(<"$policy_input")"
  fi
  if grep -Eiq '(^|[^[:alnum:]_])(libfuse2(t64)?|fusermount)([^[:alnum:]_]|$)' <<<"$policy_text"; then
    echo "error: FUSE2-only AppImage policy is rejected; use fuse3/fusermount3 or extract-and-run." >&2
    return 1
  fi
}

validate_fuse3_environment() {
  validate_fuse3_policy "${DATAPYN_APPIMAGE_FUSE_POLICY:-}"

  if ! command -v fusermount3 >/dev/null 2>&1; then
    echo "error: required executable 'fusermount3' is missing; it blocks normal AppImage smoke validation." >&2
    return 1
  fi
  if command -v fusermount >/dev/null 2>&1; then
    echo "error: FUSE2-only 'fusermount' is present; AppImage validation requires fusermount3." >&2
    return 1
  fi

  if command -v dpkg-query >/dev/null 2>&1; then
    local package
    for package in libfuse2 libfuse2t64; do
      if dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q 'install ok installed'; then
        echo "error: FUSE2 package is installed and rejected for AppImage validation: $package" >&2
        return 1
      fi
    done
  fi
}

print_appimage_metadata() {
  local version="$1"

  validate_version "$version"
  set_artifact_names "$version"
  validate_appimage_toolchain_input
  printf 'appimage_format=appimage\n'
  printf 'appimage_distro_family=universal\n'
  printf 'appimage_architecture=x86_64\n'
  printf 'appimage_display_name=Universal Linux (AppImage, FUSE3)\n'
  printf 'appimage_filename=%s\n' "$APPIMAGE_VERSIONED"
  printf 'appimage_stable_alias=%s\n' "$APPIMAGE_STABLE"
  printf 'appimage_requires=fuse3\n'
  printf 'appimage_install_mode=portable\n'
  printf 'appimage_runtime=type2\n'
  printf 'appimage_runtime_version=%s\n' "$APPIMAGE_RUNTIME_VERSION"
  printf 'appimage_runtime_sha256=%s\n' "$APPIMAGE_RUNTIME_SHA256"
  printf 'appimage_builder_version=%s\n' "$APPIMAGETOOL_VERSION"
  printf 'appimage_builder_sha256=%s\n' "$APPIMAGETOOL_SHA256"
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

prepare_appimage_dir() {
  local appimage_payload="$STAGE_DIR/opt/datapyn"
  local appimage_desktop="$APPDIR/datapyn.desktop"

  if [[ ! -d "$appimage_payload" ]]; then
    echo "error: shared staged payload not found: $appimage_payload" >&2
    return 1
  fi
  if [[ ! -x "$appimage_payload/DataPyn" ]]; then
    echo "error: staged DataPyn executable is missing or not executable: $appimage_payload/DataPyn" >&2
    return 1
  fi
  if [[ "$APPDIR" == "/" || "$APPDIR" == "$ROOT" || -z "$APPDIR" ]]; then
    echo "error: refusing to use an unsafe AppDir path: $APPDIR" >&2
    return 1
  fi

  rm -rf -- "$APPDIR"
  mkdir -p \
    "$APPDIR/usr/bin" \
    "$APPDIR/usr/share/applications" \
    "$APPDIR/usr/share/mime/packages" \
    "$APPDIR/usr/share/icons/hicolor/scalable/apps"

  # Keep the PyInstaller onedir files together. The executable resolves its support files relative
  # to this directory, so the shared native payload is copied as one logical bundle.
  cp -a "$appimage_payload/." "$APPDIR/usr/bin/"
  install -m 755 "$ROOT/scripts/linux/datapyn-appimage-apprun.sh" "$APPDIR/AppRun"

  # AppImage requires a root desktop entry and icon. Translate the native absolute launcher paths
  # into AppDir-local names while retaining the existing metadata and MIME declaration.
  sed \
    -e 's#^Exec=.*#Exec=DataPyn %F#' \
    -e 's#^Icon=.*#Icon=datapyn_logo#' \
    "$ROOT/scripts/linux/datapyn.desktop" >"$appimage_desktop"
  install -m 644 "$appimage_desktop" "$APPDIR/usr/share/applications/datapyn.desktop"
  install -m 644 "$STAGE_DIR/usr/share/mime/packages/datapyn-workspace.xml" \
    "$APPDIR/usr/share/mime/packages/datapyn-workspace.xml"

  install -m 644 "$APPDIR/usr/bin/datapyn_logo.svg" "$APPDIR/datapyn_logo.svg"
  install -m 644 "$APPDIR/usr/bin/datapyn_logo.svg" \
    "$APPDIR/usr/share/icons/hicolor/scalable/apps/datapyn_logo.svg"
}

validate_appdir() {
  local required_path
  for required_path in \
    "$APPDIR/AppRun" \
    "$APPDIR/datapyn.desktop" \
    "$APPDIR/datapyn_logo.svg" \
    "$APPDIR/usr/bin/DataPyn" \
    "$APPDIR/usr/bin/datapyn-wrapper.sh" \
    "$APPDIR/usr/share/applications/datapyn.desktop" \
    "$APPDIR/usr/share/mime/packages/datapyn-workspace.xml"; do
    if [[ ! -e "$required_path" ]]; then
      echo "error: AppDir is missing required path: $required_path" >&2
      return 1
    fi
  done
  if [[ ! -x "$APPDIR/AppRun" || ! -x "$APPDIR/usr/bin/DataPyn" || ! -x "$APPDIR/usr/bin/datapyn-wrapper.sh" ]]; then
    echo "error: AppDir launch entrypoints must be executable" >&2
    return 1
  fi
  grep -Eq '^Exec=DataPyn %F$' "$APPDIR/datapyn.desktop" || {
    echo "error: AppImage desktop entry does not point at the AppRun payload" >&2
    return 1
  }
  grep -Eq '^Icon=datapyn_logo$' "$APPDIR/datapyn.desktop" || {
    echo "error: AppImage desktop entry does not point at the bundled icon" >&2
    return 1
  }
}

validate_appimage_artifact() {
  local artifact_path="$1"
  local file_description
  local offset

  if [[ ! -s "$artifact_path" || ! -x "$artifact_path" ]]; then
    echo "error: AppImage artifact is missing or not executable: $artifact_path" >&2
    return 1
  fi
  require_command file "AppImage type validation"
  file_description="$(file -b "$artifact_path")"
  if ! grep -Eiq 'ELF 64-bit.*executable' <<<"$file_description"; then
    echo "error: AppImage is not an x86_64 ELF executable: $artifact_path ($file_description)" >&2
    return 1
  fi
  offset="$("$artifact_path" --appimage-offset 2>/dev/null)" || {
    echo "error: AppImage does not expose a Type 2 runtime offset: $artifact_path" >&2
    return 1
  }
  if [[ ! "$offset" =~ ^[0-9]+$ ]]; then
    echo "error: AppImage runtime offset is invalid: $artifact_path ($offset)" >&2
    return 1
  fi
}

build_appimage() {
  local output_path="$OUTPUT_DIR/$APPIMAGE_VERSIONED"

  prepare_appimage_dir
  validate_appdir
  mkdir -p "$OUTPUT_DIR"

  local -a appimage_tool_args=(
    --no-appstream
    --runtime-file "$APPIMAGE_RUNTIME_PATH"
    "$APPDIR"
    "$output_path"
  )
  # appimagetool is itself an AppImage. Use its built-in fallback by default so packaging does not
  # require the build runner to mount the builder; the produced artifact is still smoke-tested on
  # the normal FUSE3 path when that controlled environment is available.
  if [[ "${DATAPYN_APPIMAGE_TOOL_EXTRACT_AND_RUN:-1}" == "1" ]]; then
    ARCH="$APPIMAGE_ARCHITECTURE" VERSION="$VERSION" \
      "$APPIMAGETOOL_PATH" --appimage-extract-and-run "${appimage_tool_args[@]}"
  else
    ARCH="$APPIMAGE_ARCHITECTURE" VERSION="$VERSION" \
      "$APPIMAGETOOL_PATH" "${appimage_tool_args[@]}"
  fi
  validate_appimage_artifact "$output_path"
}

smoke_appimage() {
  local artifact_path="$1"
  shift

  validate_fuse3_environment
  validate_appimage_artifact "$artifact_path"
  "$artifact_path" "$@"
}

smoke_appimage_extract_and_run() {
  local artifact_path="$1"
  shift

  validate_fuse3_policy "${DATAPYN_APPIMAGE_FUSE_POLICY:-}"
  validate_appimage_artifact "$artifact_path"
  "$artifact_path" --appimage-extract-and-run "$@"
}

cleanup_outputs() {
  local output
  for output in \
    "$DEB_VERSIONED" "$DEB_STABLE" \
    "$RPM_VERSIONED" "$RPM_STABLE" \
    "$PACMAN_VERSIONED" "$PACMAN_STABLE" \
    "$APPIMAGE_VERSIONED" "$APPIMAGE_STABLE" \
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
  if [[ "${1:-}" == "--print-appimage-metadata" ]]; then
    [[ -n "${2:-}" ]] || { echo "error: version required (e.g. 1.57.0)" >&2; return 1; }
    print_appimage_metadata "$2"
    return 0
  fi

  if [[ "${1:-}" == "--validate-appimage-toolchain" ]]; then
    check_appimage_toolchain
    echo "Validated pinned AppImage builder/runtime"
    return 0
  fi

  if [[ "${1:-}" == "--validate-fuse-policy" ]]; then
    [[ -n "${2:-}" ]] || { echo "error: FUSE policy input required" >&2; return 1; }
    validate_fuse3_policy "$2"
    echo "Validated FUSE3-only AppImage policy"
    return 0
  fi

  if [[ "${1:-}" == "--validate-fuse3-environment" ]]; then
    validate_fuse3_environment
    echo "Validated FUSE3/fusermount3 environment"
    return 0
  fi

  if [[ "${1:-}" == "--validate-appimage" ]]; then
    [[ -n "${2:-}" ]] || { echo "error: AppImage path required" >&2; return 1; }
    validate_appimage_artifact "$2"
    echo "Validated $2"
    return 0
  fi

  if [[ "${1:-}" == "--smoke-appimage" ]]; then
    [[ -n "${2:-}" ]] || { echo "error: AppImage path required" >&2; return 1; }
    local smoke_path="$2"
    shift 2
    smoke_appimage "$smoke_path" "$@"
    return 0
  fi

  if [[ "${1:-}" == "--smoke-appimage-extract-and-run" ]]; then
    [[ -n "${2:-}" ]] || { echo "error: AppImage path required" >&2; return 1; }
    local fallback_path="$2"
    shift 2
    smoke_appimage_extract_and_run "$fallback_path" "$@"
    return 0
  fi

  if [[ "${1:-}" == "--appimage-only" ]]; then
    local appimage_version="${2:-}"
    if [[ -z "$appimage_version" ]]; then
      echo "error: version required (e.g. 1.57.0)" >&2
      return 1
    fi
    validate_version "$appimage_version"
    set_artifact_names "$appimage_version"
    VERSION="$appimage_version"

    if [[ ! -d "$DIST_DIR" ]]; then
      echo "error: dist/DataPyn not found. Run PyInstaller first." >&2
      return 1
    fi

    trap cleanup_on_error EXIT
    mkdir -p "$OUTPUT_DIR"
    cleanup_outputs
    check_appimage_toolchain
    stage_payload
    build_appimage
    copy_stable_alias "$APPIMAGE_VERSIONED" "$APPIMAGE_STABLE"
    trap - EXIT
    echo "Created:"
    printf '%s\n' "$APPIMAGE_VERSIONED" "$APPIMAGE_STABLE"
    return 0
  fi

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
  check_appimage_toolchain
  stage_payload

  build_appimage

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
  copy_stable_alias "$APPIMAGE_VERSIONED" "$APPIMAGE_STABLE"
  copy_stable_alias "$TAR_VERSIONED" "$TAR_STABLE"

  trap - EXIT
  echo "Created:"
  printf '%s\n' \
    "$DEB_VERSIONED" "$RPM_VERSIONED" "$PACMAN_VERSIONED" "$APPIMAGE_VERSIONED" "$TAR_VERSIONED" \
    "$DEB_STABLE" "$RPM_STABLE" "$PACMAN_STABLE" "$APPIMAGE_STABLE" "$TAR_STABLE"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
