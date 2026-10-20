# write-safety Specification

## Purpose
Rules that keep writes to Grocy from being repeated, misdirected or unbounded: the retry
rule, name resolution, entity allowlists, the write limit and batch behaviour.

## Requirements

### Requirement: Writes are never repeated once sent
The server SHALL retry a write only when the connection to Grocy could not be opened. After
a write may have reached Grocy, a timeout, dropped connection or 5xx response SHALL fail the
call with a message that the change may or may not have been applied, and SHALL NOT repeat
the request.

#### Scenario: Timeout on a stock booking
- **WHEN** `stock_add` is sent and Grocy does not answer before the timeout
- **THEN** the call fails saying the change may or may not have been applied and to check
  `stock_journal`, and the request was sent exactly once

#### Scenario: Grocy unreachable
- **WHEN** the connection to Grocy cannot be opened for a write, three times
- **THEN** the call fails saying nothing was changed

### Requirement: Exact references
A reference to a Grocy record SHALL be either an integer id that exists or a string equal to
exactly one record's name ignoring case and surrounding spaces; anything else SHALL fail with
up to five candidates. Grocy's internal meal-plan recipes SHALL NOT resolve.

#### Scenario: Partial name
- **WHEN** a write names product `almond` and only `Almond milk` contains it
- **THEN** the call fails listing `'Almond milk' (id 2)` as a candidate and nothing is written

### Requirement: Entity allowlists
The generic entity tools SHALL accept only the entities listed in `src/pv_grocy/entities.py`,
and SHALL never read or write `api_keys`, `sessions` or `permission_hierarchy`.

#### Scenario: API keys
- **WHEN** `entity_list` is called with `entity: api_keys`
- **THEN** the call fails and no request reaches Grocy

### Requirement: Write limit
Each token SHALL have an hourly write limit (`max_writes_per_hour`, default 60) over a
sliding window held in memory. Every write call SHALL count once and a batch call SHALL count
each item; a call over the limit SHALL fail before anything is sent.

#### Scenario: Batch over the limit
- **WHEN** a token with a limit of 3 has made one write and calls a batch apply with 3 items
- **THEN** the call fails with the limit and a retry hint, and nothing is written

### Requirement: Batches stop at the first failure
Batch apply tools SHALL take only ids, SHALL check every id before the first write, SHALL
apply items in order, and on the first failure SHALL stop and report which items were
applied, which failed (and whether it may have been applied) and which were not tried.

#### Scenario: Second item times out
- **WHEN** `workflow_stock_intake_apply` gets three items and the second times out
- **THEN** the call reports one applied, the second may or may not have been applied, and the
  third not tried, and the third is never sent
