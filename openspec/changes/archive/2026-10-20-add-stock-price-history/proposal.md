# Proposal

## Why

Implements GitHub issue #2. Callers can see a product's last and average price
(`stock_product`) and the price on each stock entry still in stock (`stock_entries`), but
not what the product cost over time or where it was cheapest. Grocy already records a
price (and usually a store) for every purchase and serves it at
`GET /stock/products/{productId}/price-history`; pv-grocy does not expose it.

## What Changes

- New read tool `stock_price_history`. It takes `product` (an id or an exact name, like the
  other stock tools) and returns the product's past purchase prices, newest first: date,
  price per stock unit, and store name where Grocy has one.
- The result also carries a summary over the whole history (not just the current page): the
  lowest, highest and most recent price, each with its date and store.
- It pages with `limit` / `offset` / `next_offset` like the other list tools (default 50 per
  page, at most 200), and its description says so.
- **No write is added or changed.** The tool is at the `read` level; ADR-0002's read list
  grows from 31 to 32 tools. It sends one GET to Grocy (plus the usual reads that resolve the
  product and name the store and unit) and never touches `grocy_write` or `writes/`.
- The fake Grocy gains the endpoint, shaped like Grocy 4.7.1's response, and the live suite
  calls the new tool.
- Out of scope (per the issue): writes, currency conversion, price charts.

## Capabilities

### New Capabilities
- `stock-reads`: read tools about stock; starts with the price history of one product.

### Modified Capabilities
<!-- None: access levels, paging and result conventions already cover a new read tool. -->

## Impact

- Code: `src/pv_grocy/tools/stock.py` (new tool). No change to `grocy.py`,
  `grocy_write.py`, `writes/` or `entities.py`.
- Grocy API: `GET /stock/products/{productId}/price-history` (read-only).
- Tests: `tests/fakegrocy.py` (new route; purchases record their store), `tests/test_tools_read.py`,
  `tests/test_live.py`, `tests/snapshots/tools.json` (tool surface, updated on purpose).
- Docs: `docs/adr/0002-opt-in-writes.md` (read list, 31 -> 32), `docs/design.md` and
  `README.md` (tool counts and stock row), `CHANGELOG.md` (Unreleased entry).
