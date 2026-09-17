# Project state

## Decisions

| ID | Decision | Rationale | Status | Date |
| --- | --- | --- | --- | --- |
| AD-001 | Release assets are published under versioned names only; `DataPyn-Setup.exe` is the single unversioned asset across Linux, Windows and macOS | user decision at linux-installers plan review: unversioned aliases duplicated every artifact; the Windows updater and setup cache rely on `DataPyn-Setup.exe` | active | 2026-09-16 |
| AD-002 | The Linux PyInstaller bundle never ships `libstdc++.so*` or `libgcc_s.so*`; the host provides the C++ runtime, floor Ubuntu/Debian 22.04 (`GLIBCXX_3.4.30`) | a bundled older libstdc++ breaks host Mesa drivers built against a newer one (1.60.1 AppImage abort); enforced by the `package.sh` bundle gate | active | 2026-09-16 |

## Handoff

**Feature**: linux-installers
**Where**: BUILD fix round 2 closed the verifier's C8/C9/C19 stale-alias failures, C14 upload-list exclusivity gap, C2/C3 wildcard coverage, and the required metadata, print-command, and macOS error-path proofs at `80db0c1a922e221dbd272651954d2b12296a6cc6`; focused proofs passed (18 passed) and the six-file packaging suite passed (84 passed, 4 skipped). C5, C6, C22 pending external actions.
**In progress**: none
**Next step**: Independent VERIFY over `ee07590..HEAD` with every check; re-evaluate C2/C3/C8/C9/C14/C19 and the supplemental wildcard/error-path proofs, and retain the external C5/C6/C22 status. Release role: push `fix/linux-app` and dispatch `release-linux.yml` dry-run (C5). User: Arch/Mesa 26 host smoke (C6). After first release: C22 download-URL proof.
**Blockers**: none for VERIFY of C1-C4 and C7-C21. Pending: C5 - Release-role push + `release-linux.yml` dry-run; C6 - user host run on Arch/Mesa 26.2.2 with the C5 AppImage; C22 - after the first release built from this change
**Uncommitted**: none
**Branch**: fix/linux-app
