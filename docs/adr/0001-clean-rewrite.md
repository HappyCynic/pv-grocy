# ADR-0001: A clean rewrite, not a wrapper around grocy-mcp

- **Status:** Accepted
- **Date:** 2026-10-20

## Context

The first plan was to wrap the community package [`grocy-mcp`](https://github.com/moustafattia/grocy-mcp)
(MIT, PyPI `grocy-mcp` 0.2.0): add bearer auth in front of its streamable HTTP app and ship it
in a hardened container. Reading its source (0.2.0, released 2026-04-01, three releases in
two days, no releases since) turned up problems a wrapper cannot fix:

- **Writes can be applied twice.** Its HTTP client retries every request, POSTs included, on
  any transport error (read timeouts too) and on 502/503/504. A slow Grocy can book the same
  purchase or consumption twice.
- **Writes can land on the wrong record.** Names resolve by substring: if exactly one product
  contains "milk", a stock change for "milk" goes to it ("Almond milk"). An all-digit string is
  taken as an id without checking it exists.
- **No access control.** Every tool, including generic create/update/delete on any Grocy
  entity, file upload and delete, and the iCal sharing link (a credential), is available to
  any caller. The generic entity tools pass any entity name through, including `api_keys`.
- **Unbounded dependency.** It requires `fastmcp>=3.2.0` with no upper bound; a fresh install
  resolves fastmcp 4.x, a major version it was never released against.
- **Tool interface.** Structured arguments are JSON inside strings (`data: str`,
  `items: str`), so clients get no schema; results are formatted text; nothing is paged.
- Some calls do not match Grocy 4.7 (for example, equipment has no `battery_id` column).

## Decision

Write `pv-grocy` from scratch on the official MCP Python SDK, with the same architecture and
conventions as Private iCloud MCP (`pv-icloud`): stateless Streamable HTTP with JSON
responses at `/mcp`, SHA-256-hashed bearer tokens, read-only by default with opt-in writes
(ADR-0002), a write path confined to one module with a strict retry rule (ADR-0003), an
audit log, in-process fakes for tests, and a hardened container image.

`grocy-mcp`'s tool list is used as a checklist for coverage: every capability it offers has
an equivalent here, verified against Grocy's own OpenAPI specification and a real Grocy
4.7.1. No code is copied from it.

## Consequences

- We own the whole surface and its tests; Grocy API changes are ours to track (the live test
  suite, `pytest -m live`, runs against a real Grocy).
- Tools are typed (JSON Schema for every argument), return structured results, and page.
- Some upstream tools are merged where they were one capability with several names (for
  example `shopping_list_update` covers set-amount, set-note and tick-off; `print_label`
  covers the five label targets).
