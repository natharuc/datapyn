# LESSONS - auto-maintained by scripts/lessons.py

> Machine-owned. Do NOT hand-edit. Changes are overwritten on the next `lessons.py` write.
> Canonical state lives in `.specs/lessons.json`. Edit lessons only via the script.
> promote_threshold=2 distinct features · window_days=45 · quarantine_threshold=2

## Confirmed (load these at Plan/Checks)

Corroborated across multiple features. Safe to apply as guidance.

_none_

## Candidates (under observation - do NOT load as guidance yet)

Seen once or not yet corroborated. Tracked, not trusted.

### L-001 - Assert missing and malformed version errors for every Linux packaging command mode at its shell boundary.
- signal: `gate_fail` · recurrence: 1 feature(s) · scope: `scripts/linux/package.sh` · harmful: 0
- features: linux-installers
- evidence: .specs/features/linux-installers/verification.md:70 (scripts/linux/package.sh)
- last seen: 2026-09-17T02:33:55Z

## Quarantined (failed when applied - ignore)

A confirmed lesson that recurred alongside failure. Kept for the maintainer to review.

_none_
