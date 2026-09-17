# Linux installers: host C++ runtime and versioned-only release assets

Sources:

- conversation (Maestro brief, 2026-09-16) - defect 1 evidence: the 1.60.1 AppImage ships
  `usr/bin/_internal/libstdc++.so.6` with max `GLIBCXX_3.4.30` (built on `ubuntu-22.04`); the host
  Mesa radeonsi / libSPIRV-Tools needs `GLIBCXX_3.4.32`, so the dlopen fails ->
  `EGL not available`, `Failed to create Vulkan instance`,
  `Initialization of all EGL display types failed`, `GLOzone not found` -> Qt abort (SIGABRT on
  thread `Chrome_InProcGp`). Host: Arch/Omarchy, Mesa 26.2.2, AMD GPU, host libstdc++ up to
  `GLIBCXX_3.4.36`.
- conversation - defect 2 **user decision, settled**: publish only versioned names; remove the
  Linux stable aliases and the duplicate `DataPyn-Setup-<version>.exe`; keep the unversioned
  `DataPyn-Setup.exe`.
- `scripts/datapyn.spec`, `scripts/linux/package.sh`, `scripts/linux/release_metadata.py`,
  `.github/workflows/release.yml`, `.github/workflows/release-linux.yml`,
  `source/src/services/windows_installer.py`, `README.md`, `installer/README.md`,
  `tests/test_linux_{appimage,package_plan,release_manifest,documentation}.py` - read at `87e28b7`.
- conversation (user plan review, 2026-09-16) - plan approved with changes: the user updates
  `datapyn.page` after this ships; the macOS `DataPyn-macos-arm64.dmg` alias is removed too, so
  only versioned names are published on every platform with `DataPyn-Setup.exe` as the single
  unversioned exception; the user runs criterion 5 on the Arch/Mesa 26 host before release.
- `scripts/macos/package_dmg.sh` - read at `87e28b7`.
- `uv.lock` - `pyqt6-qt6 6.11.1` and `pyqt6-webengine-qt6` wheels are `manylinux_2_34_x86_64`;
  `pyinstaller 6.20.0`.

## Problem

On a current distribution the 1.60.1 AppImage aborts before its first window. The PyInstaller
bundle carries the build runner's `libstdc++.so.6` (Ubuntu 22.04, max `GLIBCXX_3.4.30`), and
because the bundle's library directory is searched first, every library loaded into the process -
including the host's own Mesa GPU driver - is bound to that older C++ runtime. A driver built
against `GLIBCXX_3.4.32` then fails to load, Chromium's GPU thread finds no EGL/Vulkan backend and
Qt aborts. Anyone on a rolling or recent distro with a new Mesa (the reporter: Arch, Mesa 26.2.2,
AMD) cannot start DataPyn at all. The same `dist/DataPyn` is the payload of the `.deb`, `.rpm`,
`.pkg.tar.zst` and `.tar.gz`, so the Arch package - installed on exactly the distro that reported
it - carries the same file.

Every GitHub Release also carries each Linux artifact twice (a versioned file and a byte-identical
unversioned alias) , the Windows setup twice (`DataPyn-Setup-<version>.exe` is a `Copy-Item` of
`DataPyn-Setup.exe`) and the macOS DMG twice (`DataPyn-macos-arm64.dmg` is a `cp` of
`DataPyn-<version>-macos-arm64.dmg`). A user picking a download sees two files that differ only by name, the
release doubles its upload size for Linux, and which setup asset the Windows updater picks depends
on the order the API returns them. The source gives no download or support figures.

When this ships, the AppImage and the native packages start on a host whose C++ runtime is newer
than the build runner's, and a release lists one file per Linux format, one Windows setup and one macOS DMG - every
name versioned except `DataPyn-Setup.exe`.

## Out of scope

| Excluded | Why |
| --- | --- |
| Deleting alias assets already uploaded to past releases (1.60.1 and earlier) | an outward change to published releases; needs its own go-ahead and is a Release-role action |
| A bundle-wide ELF scan that fails on any `GLIBCXX_*` above the floor | no evidence any bundled binary exceeds `GLIBCXX_3.4.30` (the Qt wheels are `manylinux_2_34`, whose toolchain links against GCC 11's `3.4.29`); a floor-enforcement gate is a new capability |
| A CI smoke on a newer-than-floor container (e.g. `archlinux`) reproducing the Mesa dlopen | CI runners have no AMD GPU; whether a container hits the same driver path offscreen is unverified, so it cannot be a deterministic proof; candidate follow-up |
| Excluding other host-provided libraries (`libz`, `libEGL`, `libGL`, `libX11`, ...) from the bundle | no evidence they break; the reported abort names only the C++ runtime |
| Changing `SETUP_ASSET_PATTERN` in `windows_installer.py` | it already accepts `DataPyn-Setup.exe`; still accepting the versioned name keeps older releases parseable |
| Updating `datapyn.page/downloads.html` | not in this repository; the user updates the site after this ships |
| Raising or lowering the supported distro floor | the floor stays "Ubuntu/Debian 22.04+" as the README states; this change must not move it |

## Assumptions

| Assumption | Chosen default | Rationale | Confirmed? |
| --- | --- | --- | --- |
| Where the C++ runtime fix lives | the shared bundle: `scripts/datapyn.spec` drops `libstdc++.so.6` and `libgcc_s.so.1` from the Linux collected binaries, and `package.sh` refuses a `dist/DataPyn` that still carries them | all five Linux artifacts are built from the same `dist/DataPyn`; an AppRun-only fix leaves the `.pkg.tar.zst` on Arch broken with the identical file || y |
| Whether `libgcc_s.so.1` goes with `libstdc++.so.6` | both are dropped | a host libstdc++ from a newer GCC needs the matching host `libgcc_s` symbol versions; an old bundled `libgcc_s` beside a new host libstdc++ reproduces the same class of failure || y |
| What dropping them implies for the floor | the floor is unchanged at Ubuntu/Debian 22.04 | every host at the floor ships `libstdc++6` providing `GLIBCXX_3.4.30`, the same runtime the bundle carried; the build runner is `ubuntu-22.04` and the Qt wheels need at most `3.4.29`; hosts below 22.04 already fail today on the runner-built Python (glibc 2.35) || y |
| That the bundled libstdc++ is the only cause of the abort | yes | Maestro-confirmed evidence; the go-live host smoke (criterion 5) is what refutes it if another bundled library also blocks the driver || y |
| How the regression is proven | three layers: a deterministic `package.sh` gate plus unit test on the bundle contents (criteria 1-3), the existing FUSE3 `ubuntu:22.04` container smoke proving the app still starts with the host runtime at the floor (criterion 4), and a manual launch on the reporter's host before release (criterion 5) | the real failure needs the reporter's GPU driver, which no CI runner has; the structural gate prevents the root cause from returning || y |
| Error message wording of the new bundle gate | `error: dist/DataPyn must not bundle host runtime library: <relative path>` | matches the existing `error: ...` stderr style of `package.sh`; reversible || y |
| Whether the unversioned `DataPyn-Setup.exe` must stay | keep it, drop only `DataPyn-Setup-<version>.exe` | user decision; `_download_setup_helper` downloads whichever asset matches `SETUP_ASSET_PATTERN` and caches it as `DataPyn-Setup.exe`, and the versioned file is a byte copy, so no behaviour is lost | y |
| `release-linux.yml` edits | none expected beyond what the shared asset list changes | it already builds its upload list only from `package.sh --print-release-assets` and names no alias literally || y |
| Manifest `DataPyn-linux-artifacts.json` and `SHA256SUMS` | stay at `schema_version` 1 with the same fields and five versioned entries | they already contain no `stable_alias` field and no alias checksum line; only the internal `expected_artifacts` definitions, the asset list and the alias byte-compare carry aliases || y |
| A local rerun leaving stale alias files from an older build in the output directory | ignored - not deleted, not uploaded | uploads come from the printed asset list, so a stale file never reaches a release || y |
| Links to unversioned names on `datapyn.page` (open question 1) | the site probably links them; the build proceeds, and the user updates the site after this ships and before relying on the first release built from it | user answer at plan review | y |
| macOS `DataPyn-macos-arm64.dmg` alias (open question 2) | removed: `package_dmg.sh` stops copying it, the macOS upload lists only `DataPyn-<version>-macos-arm64.dmg`, docs follow | user answer at plan review - "only versioned names" holds on every platform, `DataPyn-Setup.exe` the single unversioned exception | y |
| Who runs criterion 5 (open question 3) | the user, on the Arch/Omarchy Mesa 26.2.2 AMD host, before the release | user answer at plan review | y |

**Open questions:** none - all resolved or logged above. Go-live still depends on two user actions
recorded in `Assumptions`: the host smoke (criterion 5) and the `datapyn.page` update.

## Criteria

### S1: The Linux bundle uses the host C++ runtime (P1)

**Acceptance Criteria**

1. WHERE `scripts/datapyn.spec` is built on Linux, the build SHALL produce a `dist/DataPyn` tree containing no file named `libstdc++.so.6` or `libgcc_s.so.1` (nor any `libstdc++.so*` / `libgcc_s.so*`).
2. IF `dist/DataPyn` contains a file matching `libstdc++.so*` or `libgcc_s.so*` THEN `scripts/linux/package.sh <version>` SHALL exit non-zero, print `error: dist/DataPyn must not bundle host runtime library: <path relative to dist/DataPyn>` to stderr, and leave none of the five versioned artifacts, `DataPyn-linux-artifacts.json` or `SHA256SUMS` in the output directory.
3. IF `dist/DataPyn` contains a file matching `libstdc++.so*` or `libgcc_s.so*` THEN `scripts/linux/package.sh --appimage-only <version>` SHALL exit non-zero with the same stderr line and leave no `DataPyn-<version>-x86_64.AppImage` in the output directory.
4. WHEN the release workflows run `scripts/linux/run_fuse3_smoke_container.sh <version>` against the AppImage built from a `dist/DataPyn` without the two libraries THEN the script SHALL exit 0 in the `ubuntu:22.04` container (the supported floor, host `GLIBCXX_3.4.30`).
5. WHEN `DataPyn-<version>-x86_64.AppImage` built by this branch is launched on the reporter's host (Arch/Omarchy, Mesa 26.2.2, AMD GPU) with `timeout 30 ./DataPyn-<version>-x86_64.AppImage` THEN the command SHALL exit `124` (still running at 30 s) and its output SHALL contain neither `GLIBCXX_3.4.32' not found` nor `GLOzone not found`.

**Independent test:** copy a fixture `dist/DataPyn` with a dummy `_internal/libstdc++.so.6` and run `package.sh --appimage-only 1.57.0` - it fails naming the file; remove it and the gate passes.

### S2: Linux releases publish only versioned names (P1)

**Acceptance Criteria**

6. WHEN `scripts/linux/package.sh --print-release-assets <version>` runs THEN it SHALL print exactly these 7 lines in order: `datapyn_<version>_amd64.deb`, `datapyn-<version>-1.x86_64.rpm`, `datapyn-<version>-1-x86_64.pkg.tar.zst`, `DataPyn-<version>-x86_64.AppImage`, `DataPyn-<version>-linux-x86_64.tar.gz`, `DataPyn-linux-artifacts.json`, `SHA256SUMS`.
7. WHEN `scripts/linux/package.sh <version>` completes with exit 0 THEN the output directory SHALL contain none of `datapyn_amd64.deb`, `datapyn-x86_64.rpm`, `datapyn-x86_64.pkg.tar.zst`, `DataPyn-x86_64.AppImage`, `DataPyn-linux-x86_64.tar.gz`, and its `Created:` listing SHALL name exactly the five versioned files plus the two metadata files.
8. WHEN `scripts/linux/package.sh --appimage-only <version>` completes with exit 0 THEN the output directory SHALL contain `DataPyn-<version>-x86_64.AppImage` and SHALL NOT contain `DataPyn-x86_64.AppImage`.
9. WHEN `scripts/linux/package.sh --print-plan <version>` runs THEN it SHALL print exactly the five keys `deb_versioned`, `rpm_versioned`, `pacman_versioned`, `appimage_versioned`, `tar_versioned` and no key ending in `_stable`.
10. WHEN `scripts/linux/package.sh --print-appimage-metadata <version>` runs THEN its output SHALL contain no `appimage_stable_alias` key and SHALL keep every other key and value it prints today.
11. WHEN the five versioned artifacts, `DataPyn-linux-artifacts.json` and `SHA256SUMS` are present and consistent and no unversioned alias exists THEN `scripts/linux/package.sh --validate-release <version> <tag>` SHALL exit 0.
12. The system SHALL generate `DataPyn-linux-artifacts.json` with `schema_version` `1`, exactly 5 entries whose keys are exactly `id`, `format`, `distro_family`, `display_name`, `filename`, `download_url`, `sha256`, `requires`, `install_mode`, and `SHA256SUMS` with exactly 5 lines, one per versioned filename.
13. The system SHALL keep `.github/workflows/release.yml` (`build-linux-release`) and `.github/workflows/release-linux.yml` free of any unversioned Linux filename literal, each taking its upload or workflow-artifact list only from `bash scripts/linux/package.sh --print-release-assets`.
14. The `README.md` installation section SHALL name each Linux artifact only by its versioned filename with the `VERSION` placeholder, with every install command (`apt install`, `dnf install`, `zypper install`, `pacman -U`, `chmod +x`, the AppImage launch, `--appimage-extract-and-run`, `tar -xzf`) using that versioned name, and the set of Linux filenames it documents SHALL equal the five manifest filenames.

**Independent test:** `bash scripts/linux/package.sh --print-release-assets 1.57.0 | wc -l` prints `7` and none of the lines lacks `1.57.0` except the two metadata files.

### S3: Windows releases publish one setup executable (P2)

**Acceptance Criteria**

15. WHEN `build-windows-release` in `.github/workflows/release.yml` publishes THEN its `files` list SHALL be exactly `DataPyn-<version>-windows.zip` and `DataPyn-Setup.exe`, and no step in the job SHALL create `DataPyn-Setup-<version>.exe`.
16. WHEN `fetch_latest_release` parses a release whose assets are `DataPyn-<version>-windows.zip` and `DataPyn-Setup.exe` THEN the returned `setup_asset.name` SHALL be `DataPyn-Setup.exe`.
17. The `installer/README.md` "Release artifacts" section SHALL list `DataPyn-Setup.exe` and not `DataPyn-Setup-{version}.exe`, and SHALL list the Linux artifacts only by their five versioned names plus `DataPyn-linux-artifacts.json` and `SHA256SUMS`.

**Independent test:** `grep -n 'DataPyn-Setup-' .github/workflows/release.yml installer/README.md` prints nothing.

### S4: macOS releases publish one versioned DMG (P2)

**Acceptance Criteria**

18. WHEN `scripts/macos/package_dmg.sh <version>` completes with exit 0 THEN the repository root SHALL contain `DataPyn-<version>-macos-arm64.dmg` and SHALL NOT contain `DataPyn-macos-arm64.dmg`.
19. WHEN `build-macos-release` in `.github/workflows/release.yml` publishes THEN its `files` list SHALL be exactly `DataPyn-<version>-macos-arm64.dmg`.
20. The `README.md` installation table and the `installer/README.md` "Release artifacts" section SHALL name the macOS installer only as a versioned `DataPyn-VERSION-macos-arm64.dmg` / `DataPyn-{version}-macos-arm64.dmg`, and neither file SHALL contain `DataPyn-macos-arm64.dmg`.

**Independent test:** `grep -rn 'DataPyn-macos-arm64.dmg' README.md installer/README.md scripts/macos .github/workflows/release.yml` prints nothing.

## Traceability

| ID | Slice | Criteria | Status |
| --- | --- | --- | --- |
| LINUX-01 | S1 | 1, 2, 3, 4, 5 | In checks |
| LINUX-02 | S2 | 6, 7, 8, 9, 10, 11, 12, 13, 14 | In checks |
| WIN-01 | S3 | 15, 16, 17 | In checks |
| MAC-01 | S4 | 18, 19, 20 | In checks |

## Observable

| Surface | Decision | Landing |
| --- | --- | --- |
| command `package.sh <version>` | output format and verbosity | AC 7 |
| command `package.sh <version>` | flags and defaults | existing - no flag added; `DATAPYN_PACKAGE_*` overrides unchanged |
| command `package.sh <version>` | exit codes | AC 2 |
| command `package.sh <version>` | what it prints when it fails halfway | AC 2 |
| command `package.sh --appimage-only <version>` | output format and exit codes | AC 3, AC 8 |
| command `package.sh --appimage-only <version>` | what it prints when it fails halfway | existing - `cleanup_on_error` trap removes partial outputs; AC 3 |
| command `package.sh --print-release-assets` | output format | AC 6 |
| command `package.sh --print-plan` | output format | AC 9 |
| command `package.sh --print-appimage-metadata` | output format | AC 10 |
| command `package.sh --validate-release` | exit codes and error output | AC 11; existing - named `error:` lines for missing or mismatched versioned files |
| collection GitHub Release assets | naming | AC 6, AC 15, AC 19 |
| collection GitHub Release assets | what happens to duplicates | AC 7, AC 15, AC 18 |
| collection GitHub Release assets | grouping and ordering | existing - one release per tag, Windows/Linux/macOS jobs upload independently |
| collection GitHub Release assets | the exception that does not fit | existing - `DataPyn-Setup.exe` stays the single unversioned file, by user decision (AC 15) |
| document `README.md` Instalacao | structure | AC 14 |
| document `README.md` Instalacao | tone and depth | existing - Portuguese table plus shell snippets, unchanged |
| document `README.md` Instalacao | what the reader does next | AC 14 |
| document `installer/README.md` | structure and what the reader does next | AC 17, AC 20 |
| command `scripts/macos/package_dmg.sh <version>` | output format and exit codes | AC 18; existing - `ls -lh` of the produced file, `exit 1` when `dist/DataPyn.app` is missing |
| desktop launch of the app | error state on an unsupported host | AC 5; n/a for a new message - the app has no pre-Qt error screen and none is added |

## Flow

Reuses the existing gates instead of adding a second pipeline: the bundle check runs inside the
`stage_payload` path that every `package.sh` build already crosses, the alias removal shrinks the
one asset list both workflows already read, and the floor is proven by the FUSE3 smoke container
that already runs `ubuntu:22.04`.

1. `uv run pyinstaller scripts/datapyn.spec` -> `scripts/datapyn.spec` (exists) - on Linux, drops `libstdc++.so.6` and `libgcc_s.so.1` from the collected binaries (door 1); writes `dist/DataPyn`
2. `dist/DataPyn` -> `scripts/linux/package.sh` (exists) - refuses a bundle still carrying either library, stages `pkg/`, builds AppImage, `.deb`, `.rpm`, `.pkg.tar.zst`, `.tar.gz` under versioned names only (door 2)
3. `scripts/linux/release_metadata.py` (exists) - validates the five versioned files, writes `DataPyn-linux-artifacts.json` and `SHA256SUMS`, prints the 7-line asset list
4. `.github/workflows/release.yml` (exists) job `build-linux-release`, and `.github/workflows/release-linux.yml` (exists) - run the FUSE3 container smoke and extract-and-run smoke, then upload/collect exactly the printed list
5. `.github/workflows/release.yml` (exists) job `build-windows-release` - builds `DataPyn-Setup.exe` and uploads it with the Windows ZIP, no versioned copy (door 2)
6. `dist/DataPyn.app` -> `.github/workflows/release.yml` (exists) job `build-macos-release` runs `scripts/macos/package_dmg.sh` (exists) - writes and uploads `DataPyn-<version>-macos-arm64.dmg` only (door 3)
7. out: the GitHub Release; `source/src/services/windows_installer.py` `fetch_latest_release` (exists) reads `DataPyn-Setup.exe` on the next update

## Relations

None - no stored-data shape change. `DataPyn-linux-artifacts.json` keeps schema 1 with its current fields.

## Surface

The `package.sh` flags are consumed only by this repository's workflows and tests; their outputs
and exit codes are walked in `Observable` (AC 2, 3, 6-11). What is consumed outside is the release
download URL.

| Route | In | Out | Status |
| --- | --- | --- | --- |
| `GET https://github.com/natharuc/datapyn/releases/download/<tag>/<filename>` | a Linux versioned filename (5), `DataPyn-linux-artifacts.json`, `SHA256SUMS`, `DataPyn-<version>-windows.zip`, `DataPyn-Setup.exe`, `DataPyn-<version>-macos-arm64.dmg` | the asset bytes | `200` for every listed name on a release built after this change; `404` for `datapyn_amd64.deb`, `datapyn-x86_64.rpm`, `datapyn-x86_64.pkg.tar.zst`, `DataPyn-x86_64.AppImage`, `DataPyn-linux-x86_64.tar.gz`, `DataPyn-Setup-<version>.exe`, `DataPyn-macos-arm64.dmg` on those releases |

## Landing

| One-way door | Literal shape | Alternative rejected |
| --- | --- | --- |
| 1. The Linux bundle stops carrying the C++ runtime; the host provides it | Linux-only filter in `scripts/datapyn.spec` dropping `libstdc++.so.6` and `libgcc_s.so.1` from the collected binaries, plus a `package.sh` gate failing on `libstdc++.so*` / `libgcc_s.so*` anywhere under `dist/DataPyn`; floor stays Ubuntu/Debian 22.04 (`GLIBCXX_3.4.30`) | (a) fix only `datapyn-appimage-apprun.sh` (e.g. `LD_PRELOAD` of the host libstdc++ or a "use whichever is newer" switch) - leaves `.pkg.tar.zst`, `.deb`, `.rpm` and `.tar.gz` shipping the same file, and has to locate the host library per distro; (b) build on a newer runner - raises the floor above the 22.04 the README promises and still breaks the next time Mesa moves ahead |
| 2. Public release asset names become versioned-only (external consumers of `releases/latest/download/<alias>` break) | Linux: `datapyn_<v>_amd64.deb`, `datapyn-<v>-1.x86_64.rpm`, `datapyn-<v>-1-x86_64.pkg.tar.zst`, `DataPyn-<v>-x86_64.AppImage`, `DataPyn-<v>-linux-x86_64.tar.gz`, `DataPyn-linux-artifacts.json`, `SHA256SUMS`; Windows: `DataPyn-<v>-windows.zip`, `DataPyn-Setup.exe` | keeping the unversioned aliases - rejected by the user: every format is published twice under names that differ only by version; keeping `DataPyn-Setup-<v>.exe` instead of `DataPyn-Setup.exe` - the installed app's setup cache and docs use the unversioned name |
| 3. macOS release asset name becomes versioned-only (added at plan review) | `DataPyn-<v>-macos-arm64.dmg` is the only DMG `package_dmg.sh` writes and `build-macos-release` uploads; `DataPyn-Setup.exe` remains the single unversioned asset across all platforms | keeping `DataPyn-macos-arm64.dmg` - rejected by the user at plan review: it is the same duplicate the Linux and Windows rows remove, and leaving it breaks "only versioned names" on one platform |

- Nothing else in this change is hard to reverse

## Impact

| Front | What changes |
| --- | --- |
| domain | existing term: "stable alias" (`stable_alias`, `*_STABLE`, `copy_stable_alias`, `appimage_stable_alias`, `stable_aliases()`) is removed - branched on today by `validate_artifact_set` in `release_metadata.py`, `cleanup_outputs` / `print_plan` / `print_appimage_metadata` / `main` in `package.sh`, and asserted by `tests/test_linux_package_plan.py`, `tests/test_linux_release_manifest.py` (`ALIASES`, `test_stable_aliases_must_be_byte_identical`), `tests/test_linux_appimage.py` (metadata dict, fixture alias compare) and `tests/test_linux_documentation.py` (`generated_manifest`, `manifest_filenames`, the alias branches of `DOCUMENTED_FILENAME`) |
| domain | existing term: "pinned setup" `DataPyn-Setup-{version}.exe` is removed from `installer/README.md`; nothing in `source/` or `installer/` references it (only the tolerant `SETUP_ASSET_PATTERN`) |
| domain | existing term: `DMG_STABLE` in `scripts/macos/package_dmg.sh` is removed - nothing else branches on it; no test covers the script today |
| build output | `dist/DataPyn/_internal` loses `libstdc++.so.6` and `libgcc_s.so.1` on Linux; macOS and Windows collected binaries are unchanged |
| external consumers | links to `releases/latest/download/<unversioned Linux name>` or `DataPyn-macos-arm64.dmg` (README snippets today, probably `datapyn.page`, which the user updates after this ships) 404 from the first release after merge; already-published releases keep their aliases |
| stored data | nothing to migrate - no persisted data; the manifest schema is unchanged |
