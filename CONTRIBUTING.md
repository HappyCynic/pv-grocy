# Contributing to Private Grocy MCP

Thanks for helping. Bug reports, fixes and focused features are welcome; for anything larger
than a small fix, open an issue first so we can agree on the approach.

**Security issues:** do not open a public issue. Report them privately through GitHub's
private vulnerability reporting (the repository's **Security** tab); see
[SECURITY.md](SECURITY.md).

Everyone taking part is expected to follow the [code of conduct](CODE_OF_CONDUCT.md).

The design is described in [docs/design.md](docs/design.md), with decisions in
[docs/adr/](docs/adr/).

## Development setup

You need Python 3.14 and [uv](https://docs.astral.sh/uv/), or just Docker and an editor that
supports dev containers (VS Code, or the `devcontainer` CLI).

### Dev container (recommended)

Open the repository in the dev container. It comes with uv, the pinned OpenSpec CLI, the
GitHub CLI, Claude Code, and a **demo Grocy** next to it (`http://grocy:80`: sample data, no
API key, reset whenever the container is recreated), so the server and the live tests work
without touching a real Grocy. On first start it creates three gitignored files from their
templates:

| File | Purpose |
|---|---|
| `.devcontainer/devcontainer.env` | Grocy API key and `PV_GROCY_WRITE`, only for runs against a real Grocy |
| `.devcontainer/compose.local.yaml` | Your own additions to the container: extra mounts, a host SSH agent |
| `config/pv-grocy.yaml` | Local server config (its `grocy.url` already points at the demo Grocy) |

SSH and git work through the agent your editor forwards. To use the host's own agent
instead (for example a 1Password agent with OrbStack or Docker Desktop on macOS), uncomment
the example in `compose.local.yaml` and rebuild the container; `post-create.sh` then points
ssh and git commit signing at it.

To try the server against the demo Grocy: put a hash from `uv run pv-grocy hash-token` in
`config/pv-grocy.yaml`, then `PV_GROCY_HOST=0.0.0.0 uv run pv-grocy` (port 8772 is
forwarded). Set `PV_GROCY_WRITE=enabled` and a token's `access` to try writes.

### Without the dev container

```sh
uv python install 3.14 && uv sync --frozen --all-groups
```

## Checks

CI runs these on every pull request; run them before you push:

```sh
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

The tests need no Grocy and no network: `tests/fakegrocy.py` is an in-process fake of the
Grocy 4.7 API that copies the behaviour the server depends on (status codes, the `query[]`
filter grammar, FIFO consumption, transaction undo, the computed recipe views). When you find
Grocy behaving differently from the fake, fix the fake as well as the server, and add a test.

`tests/snapshots/tools.json` pins every tool's name, access level, annotations and argument
schema. A change to the tool surface fails that test until you regenerate it on purpose:

```sh
PV_GROCY_UPDATE_SNAPSHOT=1 uv run pytest tests/test_repo_policy.py
```

### Live runs (optional)

`tests/test_live.py` runs read and write scenarios against a real Grocy. Use a throwaway
instance, never your household's: Grocy's demo mode needs no API key and comes with sample
data. In the dev container `PV_GROCY_TEST_URL` already points at its demo Grocy, so
`uv run pytest -m live` is all it takes; elsewhere:

```sh
docker run -d --rm --name grocy-demo -p 127.0.0.1:9283:80 -e GROCY_MODE=demo \
  lscr.io/linuxserver/grocy:4.7.1
curl -s http://127.0.0.1:9283/ >/dev/null   # first request creates the database
PV_GROCY_TEST_URL=http://127.0.0.1:9283 uv run pytest -m live
```

### New Grocy releases

`tests/grocy-version.txt` is the Grocy release the suite last passed against.
`.github/workflows/grocy-compat.yml` checks every Monday for a newer Grocy release; once
linuxserver has published its image, it runs the live suite (which calls every tool; a
policy test keeps it that way) against that release in demo mode, and compares Grocy's
OpenAPI spec with the tested version's (`.github/scripts/grocy_api_diff.py`).

- **Failure:** it opens an issue labeled `grocy-compat` with the failing tests and the API
  changes (or comments on the open one for that version). Fix the server and the fake, then
  bump the version as below.
- **Pass:** the run summary says so. To record it, set `tests/grocy-version.txt` to the new
  version and update the pins `tests/test_repo_policy.py` checks (the dev container's demo
  Grocy, the README and this file), in one pull request.

Run it by hand from the Actions tab, optionally with a version to test.

## Ground rules for changes

- **Read-only by default.** `grocy.py` sends only GET (never to a print endpoint); the tools
  under `tools/` only read. Every change to Grocy goes through `grocy_write.py`, from a tool
  under `writes/`, both loaded only with `PV_GROCY_WRITE=enabled`
  ([ADR-0002](docs/adr/0002-opt-in-writes.md)). A new write tool, or a change to a tool's
  access level, needs ADR-0002 updated first.
- **No repeated or guessed writes** ([ADR-0003](docs/adr/0003-grocy-client-safety.md)). Never
  retry a write that may have reached Grocy; never resolve a name by partial match for a
  write.
- **Content is untrusted.** Grocy data can contain prompt-injection attempts. Return it as
  data with `content_trust: "untrusted"`; never let it change server behaviour.
- **Nothing private in logs.** Audit lines record tool, token label, outcome and timing;
  free-text arguments are redacted to their length. Never log the API key, tokens or the
  iCal sharing link.
- **Tool descriptions state their limits.** If a tool caps results, its description says what
  the cap is and how to page (`limit` / `offset` / `next_offset`).
- **Dependencies** must have permissive licences compatible with Apache-2.0 (MIT, BSD,
  Apache, PSF, MPL-2.0 unmodified). No GPL/LGPL.
- New source files start with the SPDX header:

  ```python
  # SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
  # SPDX-License-Identifier: Apache-2.0
  ```

## Pull requests

- Keep each pull request to one change, with tests.
- Add a line to the `Unreleased` section of [`CHANGELOG.md`](CHANGELOG.md) for anything a
  user would notice.
- Commits to `main` must be signed (SSH or GPG signing both work).
- By contributing you agree that your contribution is licensed under the
  [Apache License 2.0](LICENSE), as described in its section 5.
