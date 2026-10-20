# Design

## Context

Stock read tools live in `src/pv_grocy/tools/stock.py` and use the read-only client
(`grocy()`), `resolve` / `resolve_id` for product references, `names()` for id -> name
maps, and `paged()` for `limit` / `offset` / `next_offset`. Grocy 4.7.1 serves
`GET /stock/products/{productId}/price-history` as a JSON array, newest purchase first, of
objects with `date` (purchase date), `price` (per stock unit) and `shopping_location` (the
store record, or null when the purchase had none). It is derived from purchase bookings, so
an undone purchase drops out of it.

## Goals / Non-Goals

**Goals:**
- One read tool, `stock_price_history`, at the `read` level.
- Summary (lowest, highest, latest) computed over the full history, so it does not change
  with paging.
- Fake Grocy matches Grocy 4.7.1's response shape.

**Non-Goals:**
- Writes, currency conversion, price charts, per-store aggregation, prices in units other
  than the stock unit.

## Decisions

- **Modules touched:** only `src/pv_grocy/tools/stock.py` in `src/pv_grocy/`. It already
  imports nothing from `grocy_write` or `writes`, and the repo policy test keeps it that way.
- **Grocy endpoints:** `GET /stock/products/{id}/price-history`; the product is resolved
  first through the existing `resolve("product", ...)` (`GET /objects/products/{id}`, or the
  products list for a name), and the stock unit name comes from `names("quantity_units")`.
  The store name is taken from the embedded `shopping_location.name`, so no extra read of
  `shopping_locations` is needed.
- **Result shape:**
  `{product: {id, name}, unit, prices: [{date, price, store}], total, next_offset,
  lowest, highest, latest}`, where `lowest` / `highest` / `latest` are `{date, price,
  store}` or null when there is no history. `store` is null when Grocy has none.
- **Order:** keep Grocy's order (newest first) but sort defensively by `date` descending,
  stable, so the fake and Grocy cannot disagree on order.
- **Ties:** when several purchases share the lowest or highest price, the most recent one is
  reported (the first in newest-first order). This answers "where was it cheapest lately".
- **Missing prices:** rows whose `price` is null are listed but ignored by the summary.
- **Limits and paging:** `limit` defaults to `LIMIT_DEFAULT` (50), at most `LIMIT_MAX` (200),
  `offset` from 0; the whole history is fetched once (Grocy does not page this endpoint) and
  paged in memory with `paged()`. The description states the default, the cap and
  `PAGING_NOTE`.
- **Fake Grocy:** `tests/fakegrocy.py` serves the route from purchase rows of `stock_log`
  that are not undone and have a price (newest first), with `shopping_location` embedded
  from `shopping_locations`. Purchases record `price` and `shopping_location_id` from the
  request body on the log row. A few seeded purchase log rows (different dates, prices and
  one without a store) give the tests a history; an unknown product answers 400 like other
  product routes.

Alternatives considered: reading `stock_log` through the generic objects endpoint and
computing history ourselves (duplicates Grocy logic and misses its unit handling); adding
the summary as a separate tool (more surface for no gain).

## Risks / Trade-offs

- [The response shape is taken from Grocy 4.7.1's API; a Grocy that names fields
  differently would give empty values] -> the live suite calls the tool against a real
  Grocy, and the fake is fixed if they disagree.
- [Seeding purchase rows into the fake's `stock_log` changes what `stock_journal` returns]
  -> existing journal tests that count rows are adjusted in the same task, or the seed uses
  a product those tests do not count.
- [Very long histories are fetched in full for each page] -> acceptable for a household;
  Grocy offers no server-side paging here.
