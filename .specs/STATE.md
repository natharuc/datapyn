# Project state

## Decisions

| ID | Decision | Rationale | Status | Date |
| --- | --- | --- | --- | --- |
| AD-001 | Release assets are published under versioned names only; `DataPyn-Setup.exe` is the single unversioned asset across Linux, Windows and macOS | user decision at linux-installers plan review: unversioned aliases duplicated every artifact; the Windows updater and setup cache rely on `DataPyn-Setup.exe` | active | 2026-09-16 |
| AD-002 | The Linux PyInstaller bundle never ships `libstdc++.so*` or `libgcc_s.so*`; the host provides the C++ runtime, floor Ubuntu/Debian 22.04 (`GLIBCXX_3.4.30`) | a bundled older libstdc++ breaks host Mesa drivers built against a newer one (1.60.1 AppImage abort); enforced by the `package.sh` bundle gate | active | 2026-09-16 |

## Handoff

**Feature**: linux-installers
**Where**: BUILD complete for C1-C4 and C7-C21 at `71f7db894edb6f67fa910e063939c4c690f5c54a`. C5, C6, C22 pending external actions.
**In progress**: none
**Next step**: VERIFY over `ee07590..HEAD` with every check. Release role: push `fix/linux-app` and dispatch `release-linux.yml` dry-run (C5). User: Arch/Mesa 26 host smoke (C6). After first release: C22 download-URL proof.
**Blockers**: none for VERIFY of C1-C4 and C7-C21. Pending: C5 - Release-role push + `release-linux.yml` dry-run; C6 - user host run on Arch/Mesa 26.2.2 with the C5 AppImage; C22 - after the first release built from this change
**Uncommitted**: none
**Branch**: fix/linux-app
