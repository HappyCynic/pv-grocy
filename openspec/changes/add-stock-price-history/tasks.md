# Tasks

## 1. Fake Grocy price history

- [x] 1.1 Write tests in `tests/test_tools_read.py` that call
  `GET /stock/products/{id}/price-history` on the fake (through the read client) and assert
  Grocy 4.7.1's shape: an array, newest first, of `{date, price, shopping_location}` with the
  store record or null, undone purchases and purchases without a price left out (as in Grocy
  4.7.1), 400 for an unknown product
- [x] 1.2 In `tests/fakegrocy.py`, record `price` and `shopping_location_id` from the request
  body on purchase log rows, seed a few purchase log rows (different dates and prices, one
  without a store), and serve the route from non-undone priced purchases; adjust any existing
  journal test whose row counts change, and verify the 1.1 tests and the full suite pass

## 2. `stock_price_history` tool

- [x] 2.1 Write tests in `tests/test_tools_read.py` for every scenario in
  `specs/stock-reads/spec.md`: history by exact name and by id, store null, partial name
  fails without requesting the history, summary on a later page, ties report the most recent,
  never bought, and paging (`total`, `next_offset`)
- [x] 2.2 Implement `stock_price_history` in `src/pv_grocy/tools/stock.py` as a read tool
  whose description states the default page size, the cap and `PAGING_NOTE`; verify the 2.1
  tests pass and `tests/test_repo_policy.py` still finds no write path in `tools/`
- [x] 2.3 Add `stock_price_history` to the read list in `docs/adr/0002-opt-in-writes.md`
  (31 -> 32 tools), update the tool counts in `docs/design.md` and `README.md` (77 tools, 32
  read) and the README stock row, and verify the ADR policy test passes
- [x] 2.4 Update `tests/snapshots/tools.json` on purpose with
  `PV_GROCY_UPDATE_SNAPSHOT=1 uv run pytest tests/test_repo_policy.py`, check the diff adds
  only `stock_price_history`, and verify the snapshot test passes without the variable
- [x] 2.5 Add `stock_price_history` to `test_every_read_tool_works` in `tests/test_live.py`
  and verify it is collected (it runs only against a live Grocy)
- [x] 2.6 Add an `Unreleased` entry to `CHANGELOG.md` for the new tool and update the read
  tool count there

## 3. Checks

- [x] 3.1 Run `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .` and
  `uv run mypy`, and `openspec validate --all --strict`; all pass
