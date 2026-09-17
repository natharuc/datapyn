# Linux installers: host C++ runtime and versioned-only release assets - checks

Profile: standard
Plan: `.specs/features/linux-installers/plan.md`

## Intent

22 checks in 4 slices · 3 one-way doors · 0 open. 3 checks (C5, C6, C22) are proven outside the
builder's sandbox - see `Handoff`.

## Checks

Test names below are the selectors the builder creates or renames; each test asserts the claim
beside it, written from this file, never from the implementation.

### S1 - The Linux bundle uses the host C++ runtime · 5 files · 66 KB · ~17k

**C1** - A Linux PyInstaller build of `scripts/datapyn.spec` yields a `dist/DataPyn` with 0 files named `libstdc++.so*` and 0 named `libgcc_s.so*` (LINUX-01, AC 1)
Proof: `uv run pyinstaller scripts/datapyn.spec --clean && test "$(find dist/DataPyn \( -name 'libstdc++.so*' -o -name 'libgcc_s.so*' \) | wc -l)" -eq 0`
Closed.

**C2** - `package.sh 1.57.0` over a fixture `dist/DataPyn` holding `_internal/libstdc++.so.6` (and, second case, `_internal/libgcc_s.so.1`) exits `1`, stderr is exactly `error: dist/DataPyn must not bundle host runtime library: _internal/<name>`, and the output directory holds none of the 5 versioned artifacts, `DataPyn-linux-artifacts.json` or `SHA256SUMS` (LINUX-01, AC 2)
Proof: `uv run pytest tests/test_linux_package_plan.py -k "bundled_host_runtime_library_blocks_packaging"`
Closed.

**C3** - `package.sh --appimage-only 1.57.0` over the same two fixtures exits `1` with the same exact stderr line and leaves no `DataPyn-1.57.0-x86_64.AppImage` in the output directory (LINUX-01, AC 3)
Proof: `uv run pytest tests/test_linux_appimage.py -k "bundled_host_runtime_library_blocks_appimage"`
Closed.

**C4** - A fixture `dist/DataPyn` holding `_internal/libssl.so.3` and `_internal/libz.so.1` passes the runtime-library gate: `package.sh --appimage-only 1.57.0` with `DATAPYN_APPIMAGE_TOOL` pointing at a missing file fails on `pinned AppImage builder is unavailable` and its stderr does not contain `must not bundle host runtime library` (LINUX-01, AC 2)
Proof: `uv run pytest tests/test_linux_appimage.py -k "host_runtime_gate_allows_other_libraries"`
Closed.

**C5** - The AppImage built from this branch passes the FUSE3 smoke in the `ubuntu:22.04` container: `scripts/linux/run_fuse3_smoke_container.sh <version>` exits `0` (LINUX-01, AC 4)
Proof: `gh workflow run release-linux.yml --ref fix/linux-app -f dry_run=true` then the job step `Verify | Run AppImage FUSE3 smoke tests` (`bash scripts/linux/run_fuse3_smoke_container.sh "$DATAPYN_APPIMAGE_VERSION"`) concludes `success`

**C6** - On the Arch/Omarchy host (Mesa 26.2.2, AMD GPU) the AppImage from the C5 run is still alive at 30 s (`timeout` exits `124`) and its output contains neither `GLIBCXX_3.4.32' not found` nor `GLOzone not found` (LINUX-01, AC 5)
Proof: `timeout 30 ./DataPyn-<version>-x86_64.AppImage >smoke.log 2>&1; test $? -eq 124 && ! grep -Eq "GLIBCXX_3\.4\.32' not found|GLOzone not found" smoke.log`

### S2 - Linux releases publish only versioned names · 7 files · 67 KB · ~17k

**C7** - `package.sh --print-release-assets 1.57.0` prints exactly 7 lines, in order: `datapyn_1.57.0_amd64.deb`, `datapyn-1.57.0-1.x86_64.rpm`, `datapyn-1.57.0-1-x86_64.pkg.tar.zst`, `DataPyn-1.57.0-x86_64.AppImage`, `DataPyn-1.57.0-linux-x86_64.tar.gz`, `DataPyn-linux-artifacts.json`, `SHA256SUMS` (LINUX-02, AC 6)
Proof: `uv run pytest tests/test_linux_release_manifest.py -k "release_asset_list_contains_versioned_metadata_set"`
Closed.

**C8** - A full `package.sh 1.57.0` run, with only the external packagers stubbed (`check_toolchain`, `check_appimage_toolchain`, `build_appimage`, `build_fpm_package`, `validate_package` write or accept a fixture file), exits `0`, leaves exactly the 7 C7 filenames in the output directory - none of `datapyn_amd64.deb`, `datapyn-x86_64.rpm`, `datapyn-x86_64.pkg.tar.zst`, `DataPyn-x86_64.AppImage`, `DataPyn-linux-x86_64.tar.gz` - and prints a `Created:` listing of exactly those 7 names (LINUX-02, AC 7)
Proof: `uv run pytest tests/test_linux_package_plan.py -k "full_package_run_writes_versioned_names_only"`
Closed.

**C9** - `package.sh --appimage-only 1.57.0` with the builder stubbed exits `0`, leaves `DataPyn-1.57.0-x86_64.AppImage` and no `DataPyn-x86_64.AppImage`, and its `Created:` listing is exactly `DataPyn-1.57.0-x86_64.AppImage` (LINUX-02, AC 8)
Proof: `uv run pytest tests/test_linux_appimage.py -k "appimage_only_writes_versioned_name_only"`
Closed.

**C10** - `package.sh --print-plan 1.57.0` prints exactly the 5 keys `deb_versioned`, `rpm_versioned`, `pacman_versioned`, `appimage_versioned`, `tar_versioned` with their versioned values, and no key ending in `_stable` (LINUX-02, AC 9)
Proof: `uv run pytest tests/test_linux_package_plan.py -k "artifact_plan_has_only_versioned_names"`
Closed.

**C11** - `package.sh --print-appimage-metadata 1.57.0` prints exactly 12 keys - the 13 it prints today without `appimage_stable_alias` - each with today's value (LINUX-02, AC 10)
Proof: `uv run pytest tests/test_linux_appimage.py -k "appimage_metadata_declares_portable_x86_64_fuse3_contract"`
Closed.

**C12** - With the 5 versioned fixture files and generated metadata present and no unversioned alias in the directory, `package.sh --validate-release 1.57.0 v1.57.0` exits `0` (LINUX-02, AC 11)
Proof: `uv run pytest tests/test_linux_release_manifest.py -k "manifest_and_checksums_describe_complete_fixture"`
Closed.

**C13** - The generated `DataPyn-linux-artifacts.json` has `schema_version` `1` and exactly 5 artifacts, each with exactly the 9 keys `id`, `format`, `distro_family`, `display_name`, `filename`, `download_url`, `sha256`, `requires`, `install_mode`; `SHA256SUMS` has exactly 5 lines, one per versioned filename (LINUX-02, AC 12)
Proof: `uv run pytest tests/test_linux_release_manifest.py -k "manifest_and_checksums_describe_complete_fixture"`
Closed.

**C14** - `.github/workflows/release.yml` and `.github/workflows/release-linux.yml` each contain `bash scripts/linux/package.sh --print-release-assets` feeding `steps.release_assets.outputs.files`, and neither contains any of the 5 unversioned Linux filenames (LINUX-02, AC 13)
Proof: `uv run pytest tests/test_linux_release_manifest.py -k "workflows_share_versioned_assets_and_dry_run_never_publishes"`
Closed.

**C15** - The Linux filenames documented in `README.md` (with `VERSION` substituted) equal the 5 manifest filenames, and every `apt install`, `dnf install`, `zypper install`, `pacman -U`, `chmod +x`, AppImage launch, `--appimage-extract-and-run` and `tar -xzf` line in its installation section names a versioned filename (LINUX-02, AC 14)
Proof: `uv run pytest tests/test_linux_documentation.py -k "documented_linux_filenames_exist_in_generated_manifest"`
Proof: `uv run pytest tests/test_linux_documentation.py -k "readme_install_commands_use_versioned_names"`
Closed.

### S3 - Windows releases publish one setup executable · 3 files · 70 KB · ~18k

**C16** - In `.github/workflows/release.yml` (parsed as YAML), job `build-windows-release`'s `softprops/action-gh-release` `files` list is exactly `DataPyn-${{ needs.release.outputs.version }}-windows.zip` and `DataPyn-Setup.exe`, and no step of that job contains `DataPyn-Setup-` (WIN-01, AC 15)
Proof: `uv run pytest tests/test_release_assets.py -k "windows_release_uploads_single_setup"`
Closed.

**C17** - `fetch_latest_release`, with `urlopen` patched to return assets `DataPyn-1.61.0-windows.zip` and `DataPyn-Setup.exe`, returns `setup_asset.name == "DataPyn-Setup.exe"` (WIN-01, AC 16)
Proof: `uv run pytest tests/test_windows_installer.py -k "fetch_latest_release_picks_unversioned_setup"`
Closed.

**C18** - `installer/README.md` "Release artifacts" names `DataPyn-Setup.exe`, contains no `DataPyn-Setup-{version}.exe`, and names the Linux artifacts only as the 5 versioned names plus `DataPyn-linux-artifacts.json` and `SHA256SUMS` (WIN-01, AC 17)
Proof: `uv run pytest tests/test_release_assets.py -k "installer_readme_lists_versioned_assets_only"`
Closed.

### S4 - macOS releases publish one versioned DMG · 4 files · 30 KB · ~8k

**C19** - `package_dmg.sh 1.57.0`, run from a copy of the script in a temporary tree with `dist/DataPyn.app` and a stub `hdiutil` that writes its last argument, exits `0` and leaves `DataPyn-1.57.0-macos-arm64.dmg` and no `DataPyn-macos-arm64.dmg` in that tree's root (MAC-01, AC 18)
Proof: `uv run pytest tests/test_release_assets.py -k "macos_dmg_package_writes_versioned_name_only"`
Closed.

**C20** - In `.github/workflows/release.yml` (parsed as YAML), job `build-macos-release`'s `softprops/action-gh-release` `files` list is exactly `DataPyn-${{ needs.release.outputs.version }}-macos-arm64.dmg` (MAC-01, AC 19)
Proof: `uv run pytest tests/test_release_assets.py -k "macos_release_uploads_versioned_dmg_only"`
Closed.

**C21** - `README.md` names `DataPyn-VERSION-macos-arm64.dmg`, `installer/README.md` names `DataPyn-{version}-macos-arm64.dmg`, and neither file contains `DataPyn-macos-arm64.dmg` (MAC-01, AC 20)
Proof: `uv run pytest tests/test_release_assets.py -k "docs_name_versioned_dmg_only"`
Closed.

### Post-release - the download URL signature (plan `Surface`)

**C22** - On the first release `<tag>` built from this change, `GET https://github.com/natharuc/datapyn/releases/download/<tag>/<name>` answers `200` (after redirects) for each of the 10 published names and `404` for each of the 7 removed names (LINUX-02, WIN-01, MAC-01 - plan `Surface`)
Proof: `for n in <10 published names>; do test "$(curl -sL -o /dev/null -w '%{http_code}' https://github.com/natharuc/datapyn/releases/download/<tag>/$n)" = 200 || exit 1; done; for n in datapyn_amd64.deb datapyn-x86_64.rpm datapyn-x86_64.pkg.tar.zst DataPyn-x86_64.AppImage DataPyn-linux-x86_64.tar.gz DataPyn-Setup-<version>.exe DataPyn-macos-arm64.dmg; do test "$(curl -sL -o /dev/null -w '%{http_code}' https://github.com/natharuc/datapyn/releases/download/<tag>/$n)" = 404 || exit 1; done`

## Coverage

| Set (size) | Member -> proof | Unproven |
| --- | --- | --- |
| host runtime libraries excluded (2) | `libstdc++.so*` C1 C2 C3 · `libgcc_s.so*` C1 C2 C3 | - |
| bundle gate entry points (2 places) | `package.sh <version>` C2 · `package.sh --appimage-only <version>` C3 | - |
| bundle gate outcomes (2) | offending library rejected C2 · other shared library accepted C4 | - |
| hosts proving the runtime move (2) | `ubuntu:22.04` floor C5 · Arch Mesa 26.2.2 C6 | - |
| removed Linux aliases (5) | `datapyn_amd64.deb` C8 · `datapyn-x86_64.rpm` C8 · `datapyn-x86_64.pkg.tar.zst` C8 · `DataPyn-x86_64.AppImage` C8 C9 · `DataPyn-linux-x86_64.tar.gz` C8 | - |
| Linux release asset list (7) | C7, table-driven over all 7 | - |
| `package.sh` outputs that carried aliases (5) | `--print-release-assets` C7 · full build `Created:` C8 · `--appimage-only` C9 · `--print-plan` C10 · `--print-appimage-metadata` C11 | - |
| Linux metadata files (2) | `DataPyn-linux-artifacts.json` C13 · `SHA256SUMS` C13 | - |
| workflows reading the Linux asset list (2 places) | `release.yml` `build-linux-release` C14 · `release-linux.yml` C14 | - |
| platforms publishing versioned-only (3) | Linux C7 C8 · Windows C16 · macOS C19 C20 | - |
| unversioned exception (1) | `DataPyn-Setup.exe` C16 C17 | - |
| documentation places (5) | `README.md` Linux C15 · `README.md` macOS C21 · `installer/README.md` Windows C18 · `installer/README.md` Linux C18 · `installer/README.md` macOS C21 | - |
| `GET /releases/download/<tag>/<name>` statuses (2) | `200` C22 · `404` C22 | - |
| Landing doors (3) | door 1 runtime from host C1 C2 C3 · door 2 Linux/Windows names C7 C16 · door 3 macOS name C19 C20 | - |

- Claims naming a status code, route or response shape: C22 - its proof crosses the real GitHub download boundary
- Claims naming an exit code or exact stderr: C2, C3, C4, C5, C6, C8, C9, C12, C19 - each proof runs the real script entry point, not a sourced helper
- No other check claims more than the single case its proof exercises

## Test policy

`AGENTS.md` and `tests/README.md` say how to run tests and which modules CI ignores; neither says
which level proves shell packaging logic or how much of a set a proof must assert, so these rows
are the bar this build runs under.

| Code | Required proofs | Coverage expectation |
| --- | --- | --- |
| Decides, reached across a boundary | one at the boundary **and** one at its own layer | the contract at the boundary; one asserted case per row of the decision table at its own layer |
| Decides, not reached across a boundary | one at its own layer | one asserted case per row of the decision table |
| Entry point that decides nothing | one at the boundary | accepted input, each rejected input, each error path |
| Instrumentation, pass-throughs | none of its own | covered by its consumer's proof |

Evidence:

- `scripts/linux/package.sh` runtime-library gate (new): 2 patterns x found/not found, 1 branch point, reachable only through the 2 entry points -> decides; its own layer and the boundary coincide, so C2/C3 (each pattern) and C4 (accept) are the proofs
- `scripts/linux/release_metadata.py` `validate_artifact_set`: loops over 5 artifacts, 2 branch points (missing, empty) once the alias compare goes -> decides; already proven by `test_missing_artifact_blocks_metadata_generation`, plus C12
- `scripts/linux/release_metadata.py` `release_asset_filenames`: no conditional -> instrumentation, covered by C7
- `scripts/linux/package.sh` `main`, `print_plan`, `print_appimage_metadata`: sequence and print, no new conditional -> entry points deciding nothing; C8, C9, C10, C11 at the boundary
- `scripts/macos/package_dmg.sh`: 1 branch point (missing `dist/DataPyn.app`, unchanged) -> entry point; C19 at the boundary
- `.github/workflows/release.yml`, `release-linux.yml`: declarative upload lists -> C14, C16, C20 assert the parsed lists
- closest analogue in the repo: `tests/test_linux_package_plan.py::test_missing_bundle_fails_with_existing_message_and_no_outputs` - the same "refuse the bundle, exact stderr, no outputs" shape, proven at the `package.sh` boundary

Cost: 9 new or renamed tests across 5 test files (one new: `tests/test_release_assets.py`). Without
these rows, the gate's second pattern and the macOS script have no proof at all.

## Swept

- validation: C2, C3, C4
- failure modes: C2, C3
- idempotency: existing - `cleanup_outputs` runs at the start of every `package.sh` build and `package_dmg.sh` runs `rm -f` before writing, so a rerun rewrites the same versioned names
- authorization: n/a - no caller identity is involved; the release jobs' `contents: write` permission is unchanged
- concurrency: n/a - each packaging run writes into its own runner workspace, and the three release jobs upload disjoint names to one release; this change adds no shared name
- data lifecycle: n/a - nothing is persisted; aliases already uploaded to past releases stay, per plan `Out of scope`
- dependency failure: C5, C6
- state transitions: n/a - no entity with states is touched
- observability: C2, C8

## Handoff

Intended split, with the arithmetic, written before any code:

- S1 = 66 KB / 4 = ~17k; S2 adds 67 KB of new reading = ~34k; S3 adds ~70 KB (`windows_installer.py` read around `fetch_latest_release` only, `tests/test_windows_installer.py`, `installer/README.md`) = ~52k; S4 adds `package_dmg.sh` and re-reads `release.yml`/docs = ~60k total, under the 150k budget -> one builder, S1 to S4 in order
- A builder cannot close C5, C6 or C22 alone: C5 needs the user's go-ahead to push `fix/linux-app` and dispatch `release-linux.yml` (a Release-role action); C6 is run by the user on the Arch/Mesa 26 host with the C5 artifact; C22 runs after the first release built from this change. The builder closes C1-C4 and C7-C21 and reports these three as pending those actions
- C1 builds locally with PyInstaller on the Arch host; the check asserts only the file set, which does not depend on the host's glibc
- **Approved:** 2026-09-16 by the user, checks C1-C22 as written, profile `standard`; `Test policy` stays in this file only (not written to repo guidelines). C5 push of `fix/linux-app` and the `release-linux.yml` dry-run dispatch are authorized, to be run by the Release role after the build; C6 is the user's host run; C22 runs after the first release
- **Next phase:** BUILD
