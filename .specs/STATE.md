# Project state

## Decisions

| ID | Decision | Rationale | Status | Date |
| --- | --- | --- | --- | --- |
| AD-001 | Release assets are published under versioned names only; `DataPyn-Setup.exe` is the single unversioned asset across Linux, Windows and macOS | user decision at linux-installers plan review: unversioned aliases duplicated every artifact; the Windows updater and setup cache rely on `DataPyn-Setup.exe` | active | 2026-09-16 |
| AD-002 | The Linux PyInstaller bundle never ships `libstdc++.so*` or `libgcc_s.so*`; the host provides the C++ runtime, floor Ubuntu/Debian 22.04 (`GLIBCXX_3.4.30`) | a bundled older libstdc++ breaks host Mesa drivers built against a newer one (1.60.1 AppImage abort); enforced by the `package.sh` bundle gate | active | 2026-09-16 |

## Handoff

**Feature**: linux-installers
**Where**: PLAN approved; CHECKS approved by the user as written (C1-C22, profile `standard`, Test policy kept in `checks.md` only); no code yet
**In progress**: none
**Next step**: BUILD - one builder, S1 to S4 in order, per `.specs/features/linux-installers/checks.md` `## Handoff`; closes C1-C4 and C7-C21
**Blockers**: none for BUILD. Pending external actions: C5 - the user authorized push of `fix/linux-app` and a `release-linux.yml` dry-run dispatch, done by the Release role after the build; C6 - the user's host run on Arch/Mesa 26.2.2 with the C5 AppImage; C22 - after the first release built from this change
**Uncommitted**: none
**Branch**: fix/linux-app
