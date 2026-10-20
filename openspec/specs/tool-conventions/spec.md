# tool-conventions Specification

## Purpose
Rules every MCP tool follows: typed arguments and structured results, paging, untrusted
content and provenance, audit logging with redaction, and how errors reach the caller.

## Requirements

### Requirement: Structured results with provenance
Every tool result SHALL be a JSON object carrying `content_trust: "untrusted"` and
`provenance` with `source: "grocy"` and `fetched_at`.

#### Scenario: Any read
- **WHEN** a caller calls `system_info`
- **THEN** the result has `content_trust` `untrusted` and `provenance.source` `grocy`, and
  does not include Grocy's host operating system string

### Requirement: Paging stated in descriptions
A tool that pages SHALL take `limit` and `offset`, return `next_offset` (null on the last
page), and say so in its description.

#### Scenario: Last page
- **WHEN** `stock_overview` is called with an `offset` past which fewer than `limit`
  products remain
- **THEN** `next_offset` is null

### Requirement: Audit line per call
The server SHALL write one JSON audit line per tool call with time, token label, tool,
whether it writes, arguments, outcome and latency. Numbers, booleans, dates and enumerated
values SHALL be logged as given; other strings by length only; lists and objects by size.

#### Scenario: Note in a write
- **WHEN** `shopping_list_add` is called with a 20-character note
- **THEN** the audit line records `note` as `<20 chars>` and not its text

### Requirement: Safe error messages
Errors SHALL reach the caller as tool errors whose text names no secret: Grocy's
`error_message` (capped at 300 characters, SQL prefixes trimmed) but never its
`error_details`; an API key Grocy rejects SHALL be reported as an operator problem.

#### Scenario: Refusal from Grocy
- **WHEN** Grocy refuses a consume larger than the stock
- **THEN** the tool error carries Grocy's message prefixed `Grocy:` and no stack trace
