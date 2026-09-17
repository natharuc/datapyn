# Linux installers verification

**Verdict**: FAIL
**Profile**: standard
**Diff range**: `87e28b7..5082e8a` (feature HEAD before this report commit)
**Round**: 1 - full
**Verifier**: independent verifier (author != verifier)
**Checks proven**: 15/22; 2 behavior failures, 2 proof gaps, 3 not run

The approved profile is `standard`. No source in `plan.md` is marked as a binding UI design, so the `ui` binding-source comparison and user-facing flow walk do not apply. The plan, checks, feature diff, current scripts, workflows, documents, and named tests were read at `5082e8a`.

## Checks

All 18 named pytest selectors were found and ran individually at feature HEAD: 20 selected cases passed (the runtime-library selectors each have two parameter cases). The two existing tests named by `Test policy` also ran and passed. The table distinguishes a green named test from a claim that its assertions do not settle.

| Check | Claim | Proof run | Evidence | Result |
| --- | --- | --- | --- | --- |
| C1 | Linux bundle excludes both host C++ runtimes | PyInstaller build in clean scratch at `5082e8a` exit 0; `find` count assertion exit 0, count 0 | `scripts/datapyn.spec:194` filters both patterns in binaries and datas; scratch `dist/DataPyn` contained zero matching names | PASS |
| C2 | Full packaging rejects either runtime, exact stderr, no versioned output | `test_bundled_host_runtime_library_blocks_packaging`, both cases passed | `tests/test_linux_package_plan.py:128` asserts exit 1; `:131` exact stderr; `:134` output absence. The fixture creates an empty output directory; a pre-existing AppImage survives because `scripts/linux/package.sh:1018` rejects before cleanup at `:1022` | FAIL |
| C3 | AppImage-only rejects either runtime, exact stderr, no AppImage | `test_bundled_host_runtime_library_blocks_appimage`, both cases passed | `tests/test_linux_appimage.py:56` asserts exit 1; `:59` exact stderr; `:61` output absence. A pre-existing AppImage survives because `scripts/linux/package.sh:974` rejects before cleanup at `:978` | FAIL |
| C4 | Other shared libraries pass runtime gate | `test_host_runtime_gate_allows_other_libraries` passed | `tests/test_linux_appimage.py:89` asserts the later builder error; `:90` excludes the gate error | PASS |
| C5 | Ubuntu 22.04 FUSE3 CI smoke exits 0 | Not run: workflow has not been dispatched here; network unavailable | `.specs/features/linux-installers/checks.md:34` names the external job step; no job result exists in this verification | NOT RUN |
| C6 | Reporter's Arch/Mesa host launch lasts 30 seconds with no named errors | Not run: the user has not executed the host smoke | `.specs/features/linux-installers/checks.md:37` names the host command; no host result exists | NOT RUN |
| C7 | Release asset list is exactly seven ordered names | `test_release_asset_list_contains_versioned_metadata_set` passed | `tests/test_linux_release_manifest.py:90` asserts the complete ordered tuple | PASS |
| C8 | Full build writes and lists exactly seven names | `test_full_package_run_writes_versioned_names_only` passed | `tests/test_linux_package_plan.py:197` asserts exit 0; `:200` exact listing; `:202` exact output set | PASS |
| C9 | AppImage-only writes and lists versioned name only | `test_appimage_only_writes_versioned_name_only` passed | `tests/test_linux_appimage.py:130` asserts exit 0; `:133` exact listing; `:134` and `:135` assert present and absent names | PASS |
| C10 | Print-plan has exactly five versioned keys and values | `test_artifact_plan_has_only_versioned_names` passed | `tests/test_linux_package_plan.py:38` asserts the exact mapping; `:45` excludes `_stable` | PASS |
| C11 | AppImage metadata has exactly 12 retained keys and values | `test_appimage_metadata_declares_portable_x86_64_fuse3_contract` passed | `tests/test_linux_appimage.py:143` asserts the exact mapping; `:157` asserts 12; `:158` excludes the alias key | PASS |
| C12 | Versioned fixture validates without aliases | `test_manifest_and_checksums_describe_complete_fixture` passed | `tests/test_linux_release_manifest.py:129` calls the real `--validate-release`; `:130` asserts exit 0 | PASS |
| C13 | Schema 1, five exact entry shapes, five checksums | Same fixture test passed | `tests/test_linux_release_manifest.py:106` asserts schema 1; `:111` and `:114` assert count and keys; `:117` and `:122` assert checksum lines and filenames | PASS |
| C14 | Both workflow upload lists come only from printed assets | `test_workflows_share_versioned_assets_and_dry_run_never_publishes` passed | `tests/test_linux_release_manifest.py:292` to `:304` use substrings and occurrence counts, not each upload field. Adding `stray-linux.tar.gz` beside `${{ steps.release_assets.outputs.files }}` in the release upload left the test green | UNPROVEN |
| C15 | README Linux names match manifest and all install commands are versioned | Both documentation selectors passed | `tests/test_linux_documentation.py:77` asserts filename-set equality; `:115` and `:124` assert versioned install and launch lines | PASS |
| C16 | Windows upload list is exactly ZIP and unversioned setup | `test_windows_release_uploads_single_setup` passed | `tests/test_release_assets.py:190` asserts the parsed exact list; `:195` excludes creation of a versioned setup in job steps | PASS |
| C17 | Windows updater selects unversioned setup | `test_fetch_latest_release_picks_unversioned_setup` passed | `tests/test_windows_installer.py:85` asserts `setup_asset.name == "DataPyn-Setup.exe"` | PASS |
| C18 | Installer release section lists only the specified Linux names and setup | `test_installer_readme_lists_versioned_assets_only` passed | `tests/test_release_assets.py:205` to `:218` assert required names are present and five old aliases absent, but no exact set. Adding `datapyn-extra-{version}-linux.tar.xz` to the section left the test green | UNPROVEN |
| C19 | macOS packager writes only versioned DMG | `test_macos_dmg_package_writes_versioned_name_only` passed | `tests/test_release_assets.py:252` asserts exit 0; `:253` and `:254` assert versioned present and alias absent | PASS |
| C20 | macOS upload list has exactly one versioned DMG | `test_macos_release_uploads_versioned_dmg_only` passed | `tests/test_release_assets.py:265` asserts the parsed exact list | PASS |
| C21 | Both docs use only the versioned macOS DMG name | `test_docs_name_versioned_dmg_only` passed | `tests/test_release_assets.py:273` to `:276` assert both versioned names and absence of the alias | PASS |
| C22 | First post-change release returns ten 200s and seven 404s | Not run: the release does not yet exist and network is unavailable | `.specs/features/linux-installers/checks.md:109` defines the live URL proof; no URL response exists | NOT RUN |

## Coverage

Recomputed from the plan's `Landing` and `Surface`, current `package.sh` and `release_metadata.py`, release workflows, and document/test assertions. A green local test does not fill an external or mutation-surviving member.

| Set (size) | Recomputed from | Member -> proof | Unproven |
| --- | --- | --- | --- |
| Host runtime library patterns (2) | `scripts/datapyn.spec:194`; `scripts/linux/package.sh:529` | `libstdc++.so*` C1/C2/C3; `libgcc_s.so*` C1/C2/C3 | C2/C3 sample only `.so.6` and `.so.1`; other matching suffixes have no assertion |
| Packaging entry points (2) | `scripts/linux/package.sh:960` and `:1003` | full C2; AppImage-only C3 | stale output cleanup at both rejected entries fails |
| Runtime gate outcomes (2) | `scripts/linux/package.sh:523` | matching library C2/C3; unrelated libraries C4 | - |
| Host runtime smokes (2) | plan criteria 4 and 5 | Ubuntu floor C5; Arch/Mesa C6 | both not run |
| Removed Linux aliases (5) | plan `Landing` door 2; `scripts/linux/package.sh:163` | all five excluded by C8; AppImage alias also C9 | - |
| Linux upload names (7) | `scripts/linux/release_metadata.py:114`; plan door 2 | seven ordered values C7 | - |
| Alias-bearing package outputs (5) | `scripts/linux/package.sh:228`, `:400`, `:960`, `:988`, `:1047` | asset list C7; full build C8; AppImage C9; plan C10; metadata C11 | - |
| Linux metadata files (2) | `scripts/linux/release_metadata.py:24` | manifest and checksums C13 | - |
| Workflows consuming Linux assets (2) | `.github/workflows/release.yml:390`; `.github/workflows/release-linux.yml:167` | both cited by C14 | C14 does not prove either upload field is exclusively the printed list |
| Platform release lists (3) | plan `Landing` doors 2 and 3 | Linux C7/C8; Windows C16; macOS C19/C20 | - |
| Single unversioned exception (1) | plan door 2; `.github/workflows/release.yml:230` | `DataPyn-Setup.exe` C16/C17 | - |
| Documentation placements (5) | plan `Observable`; `README.md`; `installer/README.md` | README Linux C15, macOS C21; installer Windows/Linux C18, macOS C21 | installer Linux list is not checked for additional names (C18) |
| Download statuses (2 across 17 names) | plan `Surface` | ten `200` and seven `404` outcomes C22 | all 17 live responses not run |
| Metadata file validity branches (2) | `scripts/linux/release_metadata.py:160` and `:162` | missing file: `test_missing_artifact_blocks_metadata_generation` passed | empty file rejection has no named assertion |
| macOS packaging input branches (2) | `scripts/macos/package_dmg.sh:10` to `:14` | app present C19 | missing `dist/DataPyn.app` has no named assertion |
| Landing doors (3) | plan `Landing` | host runtime C1-C4; Linux/Windows naming C7/C16; macOS naming C19/C20 | floor and host outcomes C5/C6 remain open |

## Test policy rows

| Row | Files it classifies | Required proof | Expectation met |
| --- | --- | --- | --- |
| Decides, reached across a boundary | `scripts/linux/package.sh` runtime gate | both entry points and both pattern families, matching and unrelated inputs | no - C2/C3 fail on stale output and only canonical suffixes are sampled |
| Decides, reached across a boundary | `scripts/linux/release_metadata.py` artifact validation | accepted, missing, and empty file cases at its command boundary | no - accepted C12 and missing test ran; no empty-file assertion (`scripts/linux/release_metadata.py:162`) |
| Entry point that decides nothing | `scripts/linux/package.sh` main, print-plan, print-metadata | accepted and each rejected input/error path | no - C8-C11 cover accepted output, but no named proof for missing/invalid version on the print entries |
| Entry point that decides nothing | `scripts/macos/package_dmg.sh` | app present and missing-app error | no - C19 covers present only; missing-app branch at `scripts/macos/package_dmg.sh:11` is untested |
| Declarative upload lists | `.github/workflows/release.yml`; `.github/workflows/release-linux.yml` | parsed, exact lists for C14/C16/C20 | no - C14 uses global text counts and survives an extra Linux upload; C16/C20 are parsed exact lists |
| Instrumentation and pass-throughs | `release_asset_filenames` | covered by consumer C7 | yes - C7 asserts seven ordered names |

## Swept existing

`scripts/linux/package.sh:704` removes only the current versioned names when called; it is reached after the new refusal at `:974` and `:1018`, so the existing cleanup constraint does not hold on that error path. `scripts/macos/package_dmg.sh:17` still removes the current versioned DMG before writing. Authorization, concurrency, data lifecycle, and state transitions remain the `n/a` policies approved in `checks.md`. The missing-artifact analogue at `tests/test_linux_package_plan.py:81` ran and passed, but its output directory starts empty.

## Faults injected

All mutations were made in detached scratch worktree `/tmp/datapyn-verify-5082e8a` at `5082e8a`, one at a time. Each file was restored before the next mutation; `git status --porcelain` of the real worktree remained identical to its initial empty baseline.

| Mutation | Location | Covering proof result | Killed |
| --- | --- | --- | --- |
| Return success before runtime-library scan | `scripts/linux/package.sh:523` | C2's two parameter cases failed | yes |
| Add `DataPyn-x86_64.AppImage` to printed release assets | `scripts/linux/release_metadata.py:118` | C7 test failed | yes |
| Add `stray-linux.tar.gz` beside the Linux release upload expression | `.github/workflows/release.yml:394` | C14 test passed | no - survived |
| Add a sixth versioned Linux name to installer release section | `installer/README.md:40` | C18 test passed | no - survived |
| Make the macOS script write the stable DMG name | `scripts/macos/package_dmg.sh:16` | C19 test failed | yes |

## Ranked findings

1. **C2/C3, behavior:** a rejected bundle leaves an earlier `DataPyn-1.57.0-x86_64.AppImage` in the output directory. Both real commands exited 1 with the expected stderr while the stale file remained. Move cleanup onto the rejected path, or make the approved checks explicitly limit the output claim after resolving the contradiction with the plan.
2. **C14, proof:** the workflow test does not assert the actual Linux upload fields. A release upload with an extra filename passed it. Assert the parsed upload field equals the printed asset expression for each workflow.
3. **C18, proof:** the installer documentation test permits extra Linux release names. Compare the extracted release-section filename set with the approved seven Linux names and two Windows names.
4. **Coverage/policy:** the wildcard runtime-library promise is sampled only at the canonical suffixes; empty metadata artifacts, rejected print inputs, and the missing macOS app path lack the decision-table proofs required by `Test policy`.
5. **C5/C6/C22, pending external proof:** run the authorized CI FUSE3 smoke, the user's Arch/Mesa launch, and the 17 post-release URL checks when their inputs exist. None is a PASS now.

## Gate

`env -u QT_QPA_PLATFORMTHEME QT_QPA_PLATFORM=offscreen QTWEBENGINE_DISABLE_SANDBOX=1 QTWEBENGINE_CHROMIUM_FLAGS=--no-sandbox UV_CACHE_DIR=/tmp/datapyn-verifier-uv uv run --no-sync pytest -v <six named test files> -k <18 named selectors>`: 20 passed, 59 deselected, exit 0. Two additional test-policy evidence selectors passed. PyInstaller scratch build and `find` assertion exited 0. `git diff --check 87e28b7..5082e8a` exited 0.

`python3 ~/.claude/skills/tlc-spec-lean/scripts/validate_verification.py --root <worktree> linux-installers`: exit 1, one error: `verdict is FAIL - route the ranked gaps back as fixes, then re-verify`. This gate cannot exit 0 while the findings and external proofs remain open.

No lesson files were written: this verifier's assignment allows only the verification report, and findings are recorded above for the Maestro.
