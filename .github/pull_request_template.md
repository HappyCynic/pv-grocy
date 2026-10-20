## What and why

<!-- One change per pull request. Link the issue if there is one. -->

## Checklist

- [ ] Tests added or updated; `uv run pytest`, `uv run ruff check .`, `uv run mypy` pass
- [ ] Read path still read-only: `grocy.py` sends only GET (no print endpoint), `tools/` only
      reads; every change to Grocy goes through `grocy_write.py` from a tool in `writes/`
      at the access level ADR-0002 lists
- [ ] No retry after a write may have reached Grocy; no partial-name resolution for writes
      (ADR-0003)
- [ ] Nothing private is logged (API key, tokens, iCal sharing link, free-text arguments)
- [ ] Tool descriptions state any new limits and how to page
- [ ] `tests/snapshots/tools.json` regenerated only for an intended change to the tool surface
- [ ] `CHANGELOG.md` updated (`Unreleased`) if users will notice the change
- [ ] New files carry the SPDX header
