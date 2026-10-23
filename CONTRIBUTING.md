# Contributing

Thank you for helping. Niyantrak is **alpha**: small, focused pull requests with tests are the easiest to accept.

## Before you start
- **Security issues:** do not open a public issue — see [SECURITY.md](SECURITY.md).
- **Bigger changes:** open an issue first so we can agree the approach before you write code.
- **Never paste real personal data** (Aadhaar, PAN, card numbers, phone numbers of real people) into issues, tests or
  commits. Use the checksum-valid test values already in `tests/`.
- Be kind: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Set up
```bash
git clone <your fork> niyantrak && cd niyantrak
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"            # add ,telemetry to run the 5W store tests
python3 -m pytest tests/unit -q    # must stay green
python3 tools/leak-scan.py         # must say clean
```

## Rules for changes
1. **Test first.** Add or change a test in `tests/unit/` that fails without your change.
2. **Standard library only** for the core package. New dependencies go in an optional extra in `pyproject.toml`,
   and the code must work (or degrade clearly) without them.
3. **Never log or store values.** Identifiers become placeholders and per-type counts; commands become hashes.
4. **No secrets or private infrastructure** in code, tests, fixtures or commit messages — `tools/leak-scan.py`
   is run in CI, and `--history` before every release. Use RFC 5737 / 1918 example addresses only under `tests/`.
5. Keep the panel usable by people who never open a terminal: plain words, no jargon in UI text.
6. Update `CHANGELOG.md` under *Unreleased* for anything a user would notice.

## Sign-off (DCO)
Add `Signed-off-by: Your Name <you@example.org>` to each commit message — `git commit -s` does it — certifying the
[Developer Certificate of Origin 1.1](https://developercertificate.org/). There is no CLA; if that ever changes, it
will be announced in this file before it applies to new contributions.

What this means: you keep the copyright in your contribution and license it under Apache-2.0, like the rest of this
repository. Apache-2.0 lets anyone — VigyanBytes included — use, change and redistribute it, also inside commercial
products, so contributed code may appear in the commercial Pro / Enterprise editions as well as here.

## Pull requests
- One topic per PR; describe *why*, not only *what*.
- CI must be green (unit tests, coverage run, leak scan, lab policy checks).
- By contributing you agree your contribution is licensed under Apache-2.0 (see `LICENSE`, section 5).
