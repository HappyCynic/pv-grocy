# Design

How Private Grocy MCP (`pv-grocy`) works and why. Decisions with more background are in
[`docs/adr/`](adr/); the security summary is in [`SECURITY.md`](../SECURITY.md).

## Goals

- Let an MCP client read a household's **Grocy**: stock, shopping lists, recipes, meal plan,
  chores, tasks, batteries, equipment and files.
- **Read-only by default**; everyday changes and irreversible ones are separate, opt-in
  access levels ([ADR-0002](adr/0002-opt-in-writes.md)).
- **No silent data errors**: a write is never applied twice and never lands on a record the
  caller did not name exactly ([ADR-0003](adr/0003-grocy-client-safety.md)).
- Run next to Grocy on a small always-on host, as a hardened container.

Out of scope: Grocy user management, Grocy's own settings, and anything the Grocy API does
not offer.

## Overview

```
MCP client ──HTTP /mcp (bearer)──▶ pv-grocy ──HTTP /api (GROCY-API-KEY)──▶ Grocy
```

One stateless process: the MCP server (official Python SDK, stateless Streamable HTTP with
JSON responses at `/mcp`) and one pooled HTTP client to Grocy. No local state: the only
in-memory state is the per-token write counter.

| Module | Role |
|---|---|
| `config` | YAML config (Grocy URL, tokens and their access levels), API key from the environment, the write switch |
| `auth` | Bearer token → caller (SHA-256, constant-time), pure ASGI middleware |
| `server` | Registers tools, per-token tool surface and instructions, audit log, `/healthz`, app lifespan |
| `tooling` | `ToolGroup` registry (each tool tagged with its access level), request services, paging and argument fields |
| `grocy` | Read-only Grocy client: GET only, never a print endpoint; retries reads |
| `grocy_write` | The only code that changes Grocy (POST, PUT, DELETE, print); loaded only with writes on |
| `resolve` | Id or exact name → one record; never guesses |
| `entities` | Which entities the generic tools may read, edit, delete or create as master data |
| `ratelimit` | Per-token hourly write limit (in memory) |
| `text` | Grocy's HTML descriptions → plain text (standard library, fetches nothing) |
| `tools/` | Read tools, one module per area |
| `writes/` | Write tools, one module per area; loaded only with writes on |

## Tools

77 tools: 32 read, 37 `write`, 8 `full`. The full list by level is in
[ADR-0002](adr/0002-opt-in-writes.md); each tool's description says what it does, its limits
and how to page.

Conventions shared by all tools:

- **Typed arguments, structured results.** Every argument has a JSON Schema (lists of items
  are real arrays of objects, not JSON in a string), every result is an object.
- **References.** Products, recipes, chores, batteries, equipment, locations, shopping lists
  and other master data are given by id (an integer) or exact name (a string, ignoring case
  and surrounding spaces). Anything else fails with up to five candidates. `search` and
  `stock_search` find names by part.
- **Paging.** Lists that can grow take `limit` (default 50 unless stated, at most 200) and
  `offset`, and return `next_offset` (`null` on the last page). Long text (descriptions,
  the iCal export) is capped or paged by characters, as each description says.
- **Untrusted content.** Every result carries `content_trust: "untrusted"` and provenance
  (`source: "grocy"`, `fetched_at`). Instructions tell the model that content may contain
  instructions it must not follow.
- **Time.** "Today" and "overdue" use Grocy's own local time (`/system/time`), not this
  server's, since the two can be in different time zones.
- **Undo.** Every stock change returns Grocy's `transaction_id`; `stock_undo` reverts one.
  Chore executions, battery charges and task completions have their own undo tools.
- **Batches.** Receipt intake and shopping reconcile are split into a preview (read: matches
  and proposed changes, never auto-picking a partial match) and an apply (write: ids only,
  each item counts against the write limit, stops at the first failure).

## Writes

Decided in [ADR-0002](adr/0002-opt-in-writes.md). Three things have to agree before Grocy
changes:

1. **Deployment switch** `PV_GROCY_WRITE=enabled`. Without it the write modules are never
   imported, and a token with `write` or `full` is a config error.
2. **Access level** of the calling token. Middleware lists each token only the tools its
   level allows and refuses the others exactly as the SDK refuses an unknown tool (the tool
   wrapper checks again). Each level has its own server instructions.
3. **Write limit**: `max_writes_per_hour` per token (default 60), checked before anything is
   sent; batch tools count each item.

Grocy behaviour the tools rely on, checked against Grocy 4.7.1:

- Stock bookings return their `stock_log` rows; their shared `transaction_id` undoes them all.
  Consumption is oldest-due-first and refused beyond the amount in stock.
- `recipe_consume` consumes each ingredient's amount, only what is in stock when there is
  less, and skips ingredients that are out of stock, in one database transaction.
  `recipe_consume_preview` shows exactly that.
- Meal-plan shopping uses Grocy's internal week recipe, named by SQLite
  `STRFTIME('%Y-%W')` (Monday-first weeks, week 00 before the year's first Monday, split at
  New Year), which counts stock once across the week. This is not the ISO week.
- `created_object_id` is a string; `GET /objects/<entity>/<id>` is 404 when missing, but
  `/stock/products/<id>` is 400.
- The print endpoints are GETs that print, so they belong to the write client.

## Grocy client

Decided in [ADR-0003](adr/0003-grocy-client-safety.md). Reads retry twice on connection
errors and 502/503/504. Writes retry only if the connection was never opened; after that, a
timeout, dropped connection or 5xx is reported as "may or may not have been applied" and
never repeated. Redirects are never followed. Grocy's own `error_message` reaches the caller
(capped); its stack traces do not.

## Health

`GET /healthz` is unauthenticated and returns `{"status": "ok"}` without contacting Grocy
(the container health check). `GET /healthz?deep=1` also reads Grocy's version and returns
503 if Grocy is unreachable, rejects the API key, or is older than 4.4.1.

## Logging

Diagnostics go to stderr; one JSON audit line per tool call goes to stdout: time, token
label, tool, whether it writes, arguments (numbers, booleans, dates and enum values as given;
free text and names by size only), outcome and latency. httpx request logging is turned down
to warnings, since URLs carry barcodes and file names.
