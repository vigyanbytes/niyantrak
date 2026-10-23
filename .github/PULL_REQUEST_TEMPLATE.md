## What and why
<!-- One topic per PR. Link the issue: Fixes #123 -->

## How it was tested
- [ ] A test in `tests/unit/` fails without this change and passes with it
- [ ] `python3 -m pytest tests/unit -q` is green
- [ ] `python3 tools/leak-scan.py` says clean

## Checklist
- [ ] No real personal data, secrets or private host names in code, tests or commit messages
- [ ] Core package still standard-library only (new dependencies only in an optional extra)
- [ ] Values are never logged or stored (placeholders / counts / hashes only)
- [ ] `CHANGELOG.md` updated under *Unreleased* if users will notice
- [ ] Commits signed off (`git commit -s`) — see CONTRIBUTING.md
