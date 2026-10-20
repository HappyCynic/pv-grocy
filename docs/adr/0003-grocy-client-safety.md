# ADR-0003: Grocy client rules: no repeated writes, no guessed names

- **Status:** Accepted
- **Date:** 2026-10-20

## Context

Grocy's write endpoints are not idempotent (a repeated `POST .../add` books stock again), and
a language model often names things loosely ("milk", "the pasta"). Both turn into silent
data errors in a household inventory.

## Decision

**HTTP.** `grocy.py` (always loaded) sends only GET, and never to a print endpoint
(`.../printlabel`, `/print/...`: GETs that print). `grocy_write.py` (loaded only with writes
on) is the only code that sends POST, PUT or DELETE, or calls a print endpoint. One pooled
client; redirects are not followed, so the API key only goes to the configured Grocy.

**Retries.**
- Reads: retried twice (0.5 s, 1 s) on connection errors and 502/503/504.
- Writes: retried only when the request provably never left (connection refused, connect
  timeout, pool timeout). After that, a timeout, dropped connection or any 5xx is reported as
  "may or may not have been applied", with a hint for what to check, and never repeated.
- Batch applies run items in order and stop at the first failure, reporting what was applied,
  what failed and what was not tried. Every id in a batch is checked before the first write.

**Names.** A reference is an id (an integer that must exist) or an exact name (a string,
compared ignoring case and surrounding spaces). Anything else is an error that lists up to
five candidates. Grocy's internal meal-plan recipes never resolve. Batch applies take ids
only; their preview tools do the matching and never auto-pick a partial match.

**Errors.** Grocy's `error_message` is passed to the caller (capped, SQL prefixes trimmed),
never its `error_details` stack trace. An API key Grocy rejects is logged for the operator and
reported as an operator problem.

## Consequences

- Some calls take one more GET (to resolve a name or confirm a row exists) before writing.
- Callers learn to look names up (`search`, `stock_search`) instead of hoping.
- `tests/test_grocy_client.py` and `tests/test_repo_policy.py` enforce these rules.
