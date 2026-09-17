# Linux installers verification

**Verdict**: FAIL
**Profile**: standard
**Diff range**: 87e28b7..1392301 (feature HEAD before this report commit)
**Round**: 4 - scoped after 92ec965 and 1392301; all C1-C22 reconsidered and all local proofs rerun
**Verifier**: independent fresh verifier (author != verifier)
**Checks proven**: 21/22; 0 failed local proofs, C22 not run

The plan, all 22 approved checks, the prior FAIL at 1dbc5fb, the 87e28b7..1392301 diff, code, workflows, docs, and test assertions were reviewed independently at 1392301. The missing/invalid version boundary proofs and fourth Landing door count identified in the prior FAIL are now present. No binding UI design is identified; the ui-only source comparison and human interaction walk do not apply to this standard packaging feature. Each named local pytest test appeared in the 88 passed, 4 skipped run. None of the four skipped integration tests is a named proof for C1-C4 or C7-C21. C5 and C6 rely on the explicitly sourced external evidence below.

## Checks

P = the single HEAD invocation of the six test files recorded in Gate. Names below appeared individually as PASSED in its verbose output, including all parameter cases. C1 used a separate fresh PyInstaller build. C5 and C6 are user-supplied external results, not commands rerun by this verifier.

| Check | Claim | Proof run | Evidence | Result |
| --- | --- | --- | --- | --- |
| C1 | Linux bundle excludes both runtime families | `uv run --no-sync pyinstaller scripts/datapyn.spec --clean --noconfirm --distpath <temp>/dist --workpath <temp>/build`, exit 0; `find` runtime-family count 0 | `scripts/datapyn.spec:194` filters both patterns; `scripts/datapyn.spec:196-197` filters binaries and datas; the fresh bundle count was 0 | PASS |
| C2 | Full packaging rejects both runtime families, exact stderr, removes seven versioned outputs | P: test_bundled_host_runtime_library_blocks_packaging, four cases passed | `tests/test_linux_package_plan.py:124-126` names canonical and wildcard suffix cases; `tests/test_linux_package_plan.py:151-157` asserts exit 1, exact path message, and seven absent files | PASS |
| C3 | AppImage-only rejects both runtime families, exact stderr, removes stale versioned AppImage | P: test_bundled_host_runtime_library_blocks_appimage, four cases passed | tests/test_linux_appimage.py:36 names four cases; :63-68 asserts exit 1, exact path message, and absence | PASS |
| C4 | Other shared libraries pass the runtime gate | P: test_host_runtime_gate_allows_other_libraries passed | `tests/test_linux_appimage.py:92-93` seeds libssl and libz; `tests/test_linux_appimage.py:112-114` asserts the later tool error and absence of gate error | PASS |
| C5 | Ubuntu 22.04 FUSE3 CI smoke succeeds | External: user-supplied GitHub Actions `release-linux.yml` dry-run 35175712912 at HEAD `1392301f40a2cc1e483dbda6207a40b9c7839ee8`; FUSE3 and host extract-and-run steps both reported success | Source: user's verification request naming run 35175712912 and both successful steps; `.github/workflows/release-linux.yml:146-156` defines them. The user reports its artifact set had exactly five versioned files plus `DataPyn-linux-artifacts.json` and `SHA256SUMS`, with no alias. CI logs were not independently fetched. | PASS |
| C6 | User's Arch/Mesa AppImage stays alive at 30 seconds and has neither named log error | External: user ran `timeout 30 ./DataPyn-1.60.1-x86_64.AppImage > c6.log 2>&1; echo exit=$?; grep -cE "GLIBCXX_3.4.32' not found|GLOzone not found" c6.log` in `~/Downloads/datapyn-c5` | Source: user's captured host command/output in this conversation: `exit=124`, grep count `0`, on Arch/Omarchy Mesa 26.2.2 AMD. The user identifies this as the C5 AppImage, SHA256 `3fcab47417ece7fc4757fe9ef53a27d4a760715bac8a7bb27939ff51a5f165a6` matching `SHA256SUMS`. The host and log are not accessible to this verifier; `.specs/features/linux-installers/checks.md:37-38` defines the exact proof. | PASS |
| C7 | Linux release list has seven exact ordered names | P: test_release_asset_list_contains_versioned_metadata_set passed | tests/test_linux_release_manifest.py:23-38 defines seven values; :92 asserts exact tuple equality | PASS |
| C8 | Full successful packaging leaves and lists exactly seven versioned names, even after stale aliases | P: test_full_package_run_writes_versioned_names_only passed | `tests/test_linux_package_plan.py:181-182` seeds all five aliases; `tests/test_linux_package_plan.py:223-230` asserts exit 0, exact Created tuple and output set | PASS |
| C9 | AppImage-only successful packaging leaves only the versioned AppImage name | P: test_appimage_only_writes_versioned_name_only passed | `tests/test_linux_appimage.py:125` seeds stale alias; `tests/test_linux_appimage.py:156-161` asserts exit 0, exact Created tuple, versioned file, absent alias | PASS |
| C10 | Print-plan has exactly five versioned keys and values | P: test_artifact_plan_has_only_versioned_names passed | tests/test_linux_package_plan.py:38-45 asserts the exact mapping and excludes stable keys | PASS |
| C11 | AppImage metadata has twelve exact values and no alias key | P: test_appimage_metadata_declares_portable_x86_64_fuse3_contract passed | `tests/test_linux_appimage.py:169-184` asserts exact mapping, count 12 and absent alias key | PASS |
| C12 | Five versioned fixtures without aliases validate | P: test_manifest_and_checksums_describe_complete_fixture passed | tests/test_linux_release_manifest.py:71-75 seeds only five versioned files; :131-132 asserts validation exit 0 | PASS |
| C13 | Manifest schema, five exact nine-key entries, and five checksum lines | P: same fixture test passed | tests/test_linux_release_manifest.py:108 asserts schema 1; :113-116 asserts five entries and keys; :119-128 asserts five filenames and digests | PASS |
| C14 | Both Linux workflow uploads derive exclusively from the printed seven-name list and contain no alias literal | P: test_workflows_share_versioned_assets_and_dry_run_never_publishes passed | tests/test_linux_release_manifest.py:304-317 pins each entire generator recipe; :319-332 pins upload fields and excludes five literals | PASS |
| C15 | README Linux names match the manifest and all listed install commands use versioned names | P: test_documented_linux_filenames_exist_in_generated_manifest and test_readme_install_commands_use_versioned_names passed | tests/test_linux_documentation.py:77 asserts exact name set; :111-115 and :117-124 assert command and launch lines | PASS |
| C16 | Windows upload list is exactly ZIP plus unversioned setup and creates no versioned setup | P: test_windows_release_uploads_single_setup passed | tests/test_release_assets.py:195-200 asserts parsed list equality and excludes versioned setup in all job steps | PASS |
| C17 | Windows updater chooses unversioned setup asset | P: test_fetch_latest_release_picks_unversioned_setup passed | tests/test_windows_installer.py:54-68 supplies the two assets; :81-85 asserts selected setup name | PASS |
| C18 | Installer release section names exact Windows and Linux sets | P: test_installer_readme_lists_versioned_assets_only passed | tests/test_release_assets.py:210-216 parses the section and asserts both exact sets | PASS |
| C19 | macOS successful packaging removes stale alias and writes versioned DMG | P: test_macos_dmg_package_writes_versioned_name_only passed | tests/test_release_assets.py:232 seeds stale alias; :251-253 asserts exit 0, versioned DMG and absent alias | PASS |
| C20 | macOS upload list is exactly one versioned DMG | P: test_macos_release_uploads_versioned_dmg_only passed | tests/test_release_assets.py:287-289 asserts exact parsed list | PASS |
| C21 | Both docs name versioned DMG and omit alias | P: test_docs_name_versioned_dmg_only passed | tests/test_release_assets.py:295-298 asserts both versioned spellings and both alias absences | PASS |
| C22 | First post-change release returns ten 200s and seven 404s | NOT RUN: the first release built from this change does not yet exist | No tag or 17 responses; `.specs/features/linux-installers/checks.md:109-110` defines the live proof | NOT RUN |

## Coverage

Recomputed at 1392301 from plan.md Landing, Surface and criteria, current code and workflows, and the assertions above. The approved Coverage join now names all four Landing doors at `checks.md:129`. The later plan decision at `plan.md:76` overrides the earlier stale-alias assumption for successful builds. Rows unaffected by the fix were checked against the prior review at 1dbc5fb and their proofs rerun at HEAD; the full/AppImage argument and Landing rows were recomputed from the fix diff.

| Set (size) | Recomputed from | Member -> proof | Unproven |
| --- | --- | --- | --- |
| Host runtime filename families (2) | plan.md:90-92; scripts/linux/package.sh:530-544 | libstdc++.so* and libgcc_s.so*: C1, C2, C3, each canonical and alternate suffix | - |
| Runtime gate entry points and outcomes (2 each) | scripts/linux/package.sh:968-984, :1011-1028 | full C2; AppImage C3; reject C2/C3; unrelated libraries C4 | - |
| Host runtime floors (2) | plan.md:93-94 | Ubuntu 22.04 C5, external CI result; Arch/Mesa C6, captured user-run command/output | - |
| Removed Linux aliases (5) | plan.md:103-104; scripts/linux/package.sh:19-25 | all five seeded and absent C8; AppImage alias also C9 | - |
| Linux release names (7) and output modes (5) | plan.md:102-108; scripts/linux/release_metadata.py:114-121 | seven ordered C7; full C8; AppImage C9; plan C10; metadata C11 | - |
| Metadata entry keys (9), entries (5), checksum lines (5) | plan.md:108; scripts/linux/release_metadata.py:65-107 | all three exact sets C13; validation C12 | - |
| Linux workflow consumers (2) | .github/workflows/release.yml:372-394; .github/workflows/release-linux.yml:158-171 | complete generator and upload paths in both C14 | - |
| Platform release upload lists (3) | plan.md:202-203; current workflows | Linux C7/C14; Windows C16; macOS C20 | - |
| Documentation placements (5) | plan.md:161-164 | README Linux C15/macOS C21; installer Windows/Linux C18/macOS C21 | - |
| Metadata validation branches (2) | scripts/linux/release_metadata.py:158-164 | missing and empty artifact: test_missing_artifact_blocks_metadata_generation[False/True], both passed | - |
| Print entry modes (3 times accepted/missing/invalid) | scripts/linux/package.sh:216-258, :996-1000; checks.md:145 | accepted C7/C10/C11; missing and invalid: test_print_commands_reject_missing_and_invalid_versions, all three cases passed | - |
| Full and AppImage argument modes (2 times accepted/missing/invalid) | scripts/linux/package.sh:968-975, :1011-1017; checks.md:145 | accepted C8/C9; missing/invalid `test_full_package_rejects_missing_and_invalid_versions` and `test_appimage_only_rejects_missing_and_invalid_versions`, all four cases passed; missing bundle and tool failures also tested | - |
| macOS app input branches (2) | scripts/macos/package_dmg.sh:10-17 | present C19; missing test_macos_dmg_package_rejects_missing_app passed | - |
| Release URL outcomes (10 published, 7 removed) | plan.md:193-195 | 200 and 404 sets C22 | all 17 live responses not run |
| Landing doors (4) | plan.md:201-204 | host runtime C1-C6; public naming C7/C16; macOS naming C19/C20; stale alias cleanup C8/C9/C19 | - |

## Test policy rows

Re-judged at 1392301. The two packaging entry modes failed this row at 1dbc5fb; the four new parameter cases now assert both rejected inputs at the script boundary.

| Row | Files it classifies | Required proof | Expectation met |
| --- | --- | --- | --- |
| Decides, reached across a boundary | Linux runtime gate | both entry points, both wildcard families, accepted unrelated libraries at the script boundary | yes: C2-C4, including four suffix cases per rejecting entry |
| Decides, reached across a boundary | release_metadata.py artifact validation | accepted, missing and empty artifacts | yes: C12 and both test_missing_artifact_blocks_metadata_generation cases |
| Entry point that decides nothing | package.sh print-release-assets, print-plan, print-appimage-metadata | accepted, missing and invalid version at the command boundary | yes: C7/C10/C11 and test_print_commands_reject_missing_and_invalid_versions |
| Entry point that decides nothing | package.sh full and --appimage-only modes | accepted, each rejected input and error path at the command boundary | yes: C8/C9 accepted; `tests/test_linux_package_plan.py:97-111` and `tests/test_linux_appimage.py:71-85` assert missing and invalid versions; missing bundle, runtime gate and tool failures passed |
| Entry point that decides nothing | macOS package_dmg.sh | present app and missing-app error at script boundary | yes: C19 and test_macos_dmg_package_rejects_missing_app |
| Declarative upload lists | both Linux workflows, Windows and macOS release jobs | exact parsed lists and exclusive Linux generator recipe | yes: C14, C16, C20 |
| Instrumentation, pass-throughs | release_asset_filenames | consumer proof | yes: C7 |

## Swept existing

The full and AppImage branches call cleanup_outputs before refusing a runtime file (scripts/linux/package.sh:983-984, :1027-1028), and cleanup_outputs removes the seven versioned outputs and five known aliases (:711-723). The macOS script removes the known alias before writing (:17). The missing-bundle analogue at tests/test_linux_package_plan.py:81-94 passed. Authorization, concurrency, data lifecycle and state transitions remain the approved n/a policies at checks.md:166-170. No user-facing interaction walk applies.

## Faults injected

Baseline real-tree `git status --porcelain` was empty. Five behavior faults were applied one at a time in detached scratch worktree `/tmp/datapyn-verify-scratch-Wydxle/tree` at 1392301, with each tracked file restored before the next. The scratch worktree was removed; real-tree porcelain matched its empty baseline. These are this verifier's injections.

| Mutation | Location | Narrow covering proof result | Killed |
| --- | --- | --- | --- |
| Bypass the full-mode missing-version guard | scripts/linux/package.sh:1013 | `test_full_package_rejects_missing_and_invalid_versions[missing-version]` failed exact stderr (1 failed, 1 passed) | yes |
| Miss recursive libgcc_s.so* names | scripts/linux/package.sh:537 | C2 libgcc_s.so.1 and .fixture cases failed on exact stderr (2 failed, 2 passed) | yes |
| Omit all known alias names from cleanup_outputs | scripts/linux/package.sh:720 | C8 failed exact output-set assertion with five extra aliases | yes |
| Insert an extra name inside Linux release_assets generator | .github/workflows/release.yml:377 | C14 failed exact generator-recipe assertion | yes |
| Stop deleting stale macOS alias | scripts/macos/package_dmg.sh:17 | C19 failed absent-alias assertion | yes |

## Ranked findings

1. C22 remains NOT RUN because there is no first release built from this change. On that release, capture all ten redirected 200 responses and seven 404 responses. No local assertion or dry-run artifact substitutes for the live release boundary.

## Gate

At 1392301, the HEAD six-file pytest run: 88 passed, 4 skipped, exit 0; every named local test appeared as PASSED. The fresh `--clean --noconfirm` PyInstaller build to a temp dist/work directory: exit 0, runtime-family file count 0. `git diff --check 87e28b7..1392301`: exit 0. Five mutant proofs failed as intended. C5 uses the user-supplied CI run; C6 uses the user's captured host command/output, on a host this verifier cannot reach. C22 alone remains unproven. `validate_verification.py --root <worktree> linux-installers`: exit 1, reporting `verdict is FAIL`; the completion gate cannot pass while C22 is not run.
