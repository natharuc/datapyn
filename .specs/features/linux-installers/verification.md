# Linux installers verification

**Verdict**: FAIL
**Profile**: standard
**Diff range**: 87e28b7..7f14b02 (feature HEAD before this report commit)
**Round**: 2 - full, as explicitly requested; no check verdict carried forward
**Verifier**: independent verifier (author != verifier)
**Checks proven**: 15/22; 3 failing, 1 unproven, 3 not run

The plan, checks, prior FAIL report, feature diff, current code, workflows, documentation and named tests were read independently at 7f14b02. No binding UI design is identified in the plan. The ui binding-source comparison and interactive flow walk do not apply to this standard infrastructure feature.

## Checks

The 18 named pytest selectors for C2-C4 and C7-C21, including parameter cases, ran together at feature HEAD: 20 passed. Two existing policy-evidence tests also ran: 22 passed, 57 deselected overall. C1 was built separately. A green named test is distinguished below from a claim that its assertion does not settle.

| Check | Claim | Proof run | Evidence | Result |
| --- | --- | --- | --- | --- |
| C1 | Linux PyInstaller bundle contains neither runtime family | PyInstaller --clean in detached scratch, exit 0; find count 0 | scripts/datapyn.spec:194 filters both filename patterns from binaries and datas; dist/DataPyn had zero matching names | PASS |
| C2 | Full packaging rejects both runtimes, exact stderr, removes seven versioned outputs | test_bundled_host_runtime_library_blocks_packaging, both cases passed | tests/test_linux_package_plan.py:131 asserts exit 1, :134 exact stderr, :137 absence after stale outputs were seeded at :118 | PASS |
| C3 | AppImage-only rejects both runtimes, exact stderr, removes stale AppImage | test_bundled_host_runtime_library_blocks_appimage, both cases passed | tests/test_linux_appimage.py:60 asserts exit 1, :63 exact stderr, :65 absence after stale AppImage at :45 | PASS |
| C4 | Other shared libraries pass the runtime gate | test_host_runtime_gate_allows_other_libraries passed | tests/test_linux_appimage.py:92 asserts the later tool error; :94 excludes the runtime gate error | PASS |
| C5 | Ubuntu 22.04 FUSE3 CI smoke succeeds | **Not run**: no workflow job result; network unavailable here | .specs/features/linux-installers/checks.md:34 names the external workflow step | NOT RUN |
| C6 | User's Arch/Mesa host AppImage runs for 30 seconds without named errors | **Not run**: user host result has not been supplied | .specs/features/linux-installers/checks.md:37 names the host command and output checks | NOT RUN |
| C7 | Printed Linux release list is seven ordered names | test_release_asset_list_contains_versioned_metadata_set passed | tests/test_linux_release_manifest.py:92 asserts the exact ordered tuple defined at :23-:38 | PASS |
| C8 | Full build output contains exactly seven names and no aliases | test_full_package_run_writes_versioned_names_only passed; independent stale-alias rerun exited 0 but left five aliases, 12 files total | tests/test_linux_package_plan.py:203 and :205 assert exact listing and set only from an initially empty output directory; scripts/linux/package.sh:704 removes only versioned names | FAIL |
| C9 | AppImage-only output contains the versioned name and no alias | test_appimage_only_writes_versioned_name_only passed; independent stale-alias rerun exited 0 and left DataPyn-x86_64.AppImage | tests/test_linux_appimage.py:137-:139 assert the clean fixture; scripts/linux/package.sh:975 invokes cleanup that does not remove aliases | FAIL |
| C10 | Print-plan contains exactly five versioned keys and values | test_artifact_plan_has_only_versioned_names passed | tests/test_linux_package_plan.py:38 asserts the exact mapping; :45 excludes _stable | PASS |
| C11 | AppImage metadata retains 12 exact values and no alias key | test_appimage_metadata_declares_portable_x86_64_fuse3_contract passed | tests/test_linux_appimage.py:147 asserts the exact mapping; :161 count 12; :162 excludes alias | PASS |
| C12 | Five versioned fixtures validate without an alias | test_manifest_and_checksums_describe_complete_fixture passed | tests/test_linux_release_manifest.py:131 invokes --validate-release; :132 asserts exit 0 | PASS |
| C13 | Schema 1, five exact entry shapes and five checksum lines | Same fixture test passed | tests/test_linux_release_manifest.py:108 asserts schema, :113-:116 count and keys, :119-:128 checksum filenames and hashes | PASS |
| C14 | Both workflow upload lists derive only from printed assets | test_workflows_share_versioned_assets_and_dry_run_never_publishes passed; extra upload-field fault was killed | tests/test_linux_release_manifest.py:301-:303 only find substrings in the release_assets step; :305-:314 pin upload fields to its output. An added echo inside that step can enter the output without breaking these assertions | UNPROVEN |
| C15 | README Linux filename set and each install command use versioned names | Both documentation selectors passed | tests/test_linux_documentation.py:77 asserts set equality; :115 and :124 assert versioned install and launch lines | PASS |
| C16 | Windows upload list is exactly ZIP and unversioned setup | test_windows_release_uploads_single_setup passed | tests/test_release_assets.py:195 asserts the parsed exact list; :200 excludes creation of a versioned setup in job steps | PASS |
| C17 | Windows updater selects unversioned setup | test_fetch_latest_release_picks_unversioned_setup passed | tests/test_windows_installer.py:85 asserts release.setup_asset.name == "DataPyn-Setup.exe" | PASS |
| C18 | Installer release section has exact Windows and Linux names | test_installer_readme_lists_versioned_assets_only passed; extra-name fault was killed | tests/test_release_assets.py:212 and :213 compare the extracted section's backticked names with exact sets | PASS |
| C19 | macOS script leaves versioned DMG and no alias | test_macos_dmg_package_writes_versioned_name_only passed; independent rerun seeded with a stale alias exited 0 and retained it | tests/test_release_assets.py:250-:252 assert the clean fixture; scripts/macos/package_dmg.sh:17 removes only the versioned DMG | FAIL |
| C20 | macOS upload list has exactly one versioned DMG | test_macos_release_uploads_versioned_dmg_only passed | tests/test_release_assets.py:263 asserts the parsed exact list | PASS |
| C21 | Both docs name the versioned DMG and omit alias | test_docs_name_versioned_dmg_only passed | tests/test_release_assets.py:271-:274 assert both versioned names and exclude the alias | PASS |
| C22 | First post-change release returns ten 200s and seven 404s | **Not run**: no post-change release or network access here | .specs/features/linux-installers/checks.md:109 defines the live URL proof; no responses exist | NOT RUN |

## Coverage

Recomputed from the plan's Landing, Surface and criteria, the current code and the named assertions. .specs/features/linux-installers/plan.md:75 explicitly allows stale local aliases, while criteria 7, 8 and 18 state unconditional absence; those rows remain open pending a single agreed interpretation.

| Set (size) | Recomputed from | Member -> proof | Unproven |
| --- | --- | --- | --- |
| Runtime name families (2) | plan.md:89-:91; scripts/linux/package.sh:529-:530 | libstdc++.so* C1-C3; libgcc_s.so* C1-C3 | C2/C3 exercise only .so.6 and .so.1; other suffixes have no asserted case |
| Runtime gate entry points (2) | scripts/linux/package.sh:960, :1003 | full C2; AppImage-only C3 | - |
| Runtime gate outcomes (2) | scripts/linux/package.sh:523 | reject C2/C3; unrelated library C4 | - |
| Runtime hosts (2) | plan.md:92-:93 | Ubuntu floor C5; Arch/Mesa C6 | both not run |
| Removed Linux aliases (5) | plan.md:201; scripts/linux/package.sh:704 | all five absent from C7 upload list; clean output C8; AppImage C9 | all five can remain locally on rerun, conflicting with C8/C9's unconditional absence |
| Linux release assets (7) | scripts/linux/release_metadata.py:114 | all seven in order C7 | - |
| Package output forms (5) | scripts/linux/package.sh:215, :226, :392, :960, :1003 | asset list C7; full C8; AppImage C9; plan C10; metadata C11 | stale-alias cases of C8/C9 |
| Metadata files (2) | scripts/linux/release_metadata.py:117-:120 | manifest and checksum C13 | - |
| Linux workflow consumers (2) | .github/workflows/release.yml:372-:394; .github/workflows/release-linux.yml:158-:171 | both upload fields C14 | step-body exclusivity not asserted by C14 |
| Platform uploads (3) | plan.md:201-:202 | Linux C7/C14; Windows C16; macOS C20 | Linux step-body exclusivity C14 |
| Documentation placements (5) | plan.md:160-:164 | README Linux C15/macOS C21; installer Windows/Linux C18/macOS C21 | - |
| Release URL outcomes (17 names) | plan.md:194 | ten 200s and seven 404s C22 | all 17 live responses not run |
| Metadata validation branches (2) | scripts/linux/release_metadata.py:160-:163 | missing file: test_missing_artifact_blocks_metadata_generation passed | empty file has no named assertion |
| macOS input branches (2) | scripts/macos/package_dmg.sh:10-:14 | app present C19 | missing app has no named assertion; stale alias outcome fails C19 |
| Landing doors (3) | plan.md:200-:202 | host runtime C1-C4; naming C7/C16; macOS C19/C20 | C5/C6, local alias absence and C14 remain open |

## Test policy rows

| Row | Files it classifies | Required proof | Expectation met |
| --- | --- | --- | --- |
| Decides, reached across a boundary | scripts/linux/package.sh runtime gate | both entries, both wildcard families and unrelated input | no - C2/C3 use only canonical suffixes; wildcard coverage is not asserted |
| Decides, reached across a boundary | scripts/linux/release_metadata.py artifact validation | accepted, missing and empty files at the command boundary | no - C12 and missing-file test passed; empty-file rejection has no named assertion (scripts/linux/release_metadata.py:162) |
| Entry point that decides nothing | scripts/linux/package.sh main, print-plan, print-metadata | accepted and rejected inputs/error paths | no - C8-C11 cover accepted paths; missing/invalid version for print entry points is not asserted |
| Entry point that decides nothing | scripts/macos/package_dmg.sh | app present and missing-app error | no - C19 covers present only; missing-app path at scripts/macos/package_dmg.sh:11 is untested |
| Declarative upload lists | both Linux workflows, Windows and macOS release jobs | exact parsed lists and exclusive Linux asset-list derivation | no - C16/C20 are exact; C14 does not constrain extra lines inside the generating step |
| Instrumentation, pass-throughs | release_asset_filenames | consumer proof | yes - C7 pins seven ordered names |

## Swept existing

scripts/linux/package.sh:704 now runs before runtime refusal at :976 and :1020, so C2/C3 remove stale versioned outputs as required. It deliberately does not remove legacy aliases, matching the approved stale-output assumption at plan.md:75. scripts/macos/package_dmg.sh:17 still rewrites only the versioned DMG. Authorization, concurrency, data lifecycle and state transitions remain the approved n/a policies in checks.md:165-:170. The missing-bundle analogue at tests/test_linux_package_plan.py:81 ran and passed.

## Faults injected

All five faults were applied one at a time in detached scratch worktree /tmp/datapyn-verify-7f14b02-round2 at 7f14b02, never in the real tree. Each tracked file was restored before the next fault; the scratch worktree was removed and the real tree's porcelain matched its initial empty baseline. Initial scratch pytest attempts without the headless Qt environment were inconclusive; the rows below are the repeated runs with that environment set.

| Mutation | Location | Covering proof result | Killed |
| --- | --- | --- | --- |
| Disable Linux PyInstaller filter | scripts/datapyn.spec:191 | rebuilt bundle contained both _internal/libstdc++.so.6 and _internal/libgcc_s.so.1; C1 zero-count assertion failed | yes |
| Move full-build cleanup after runtime refusal | scripts/linux/package.sh:1018 | C2: 2 failed | yes |
| Move AppImage-only cleanup after runtime refusal | scripts/linux/package.sh:974 | C3: 2 failed | yes |
| Add stray-linux.tar.gz to Linux release upload field | .github/workflows/release.yml:394 | C14: 1 failed | yes |
| Add sixth Linux filename to installer release section | installer/README.md:38 | C18: 1 failed | yes |

## Ranked findings

1. **C8/C9/C19, plan-check conflict and counterexamples:** plan.md:75 approves ignoring stale local aliases, yet plan.md:102-:103, :127 and the checks demand none remain. Direct successful reruns left all five Linux aliases or the macOS alias. Resolve whether the approved stale-output exception limits those criteria; align the checks and proof fixtures with that decision, or make packaging remove aliases.
2. **C14, proof gap:** tests/test_linux_release_manifest.py:301-:303 assert substrings in the asset-list step. They do not exclude an extra echo between the printed-list command and the heredoc terminator, so the plan's “only from --print-release-assets” promise is not proven. Assert the complete step recipe or its produced list.
3. **C2/C3, wildcard coverage:** tests/test_linux_package_plan.py:107 and tests/test_linux_appimage.py:34 only seed the canonical .so.6/.so.1 suffixes. The approved libstdc++.so* / libgcc_s.so* promise has no proof for other suffixes.
4. **Test policy gaps:** scripts/linux/release_metadata.py:162 empty-artifact rejection, invalid/missing versions on print entry points, and scripts/macos/package_dmg.sh:11 missing-app rejection lack the asserted branch proofs required by checks.md:141-:155.
5. **C5/C6/C22, external proofs pending:** run the authorized CI smoke, the user's Arch/Mesa smoke, and the 17 URL requests after the corresponding artifact or release exists. None is a PASS here.

## Gate

env -u QT_QPA_PLATFORMTHEME QT_QPA_PLATFORM=offscreen QTWEBENGINE_DISABLE_SANDBOX=1 QTWEBENGINE_CHROMIUM_FLAGS=--no-sandbox UV_CACHE_DIR=/tmp/datapyn-verifier-uv uv run --no-sync pytest -vv <six test files> -k <18 named selectors plus two policy selectors>: 22 passed, 57 deselected, exit 0. The separate PyInstaller build and zero-count assertion exited 0. git diff --check 87e28b7..7f14b02 exited 0.

python3 ~/.claude/skills/tlc-spec-lean/scripts/validate_verification.py --root <worktree> linux-installers: exit 1 because this honest FAIL verdict cannot pass the completion gate; no PASS is claimed.
