# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/). GitHub Releases link the container image for
each version.

## [Unreleased]

### Added

- First version: an MCP server over a household's Grocy (tested with Grocy 4.7.1), serving
  stateless Streamable HTTP at `/mcp` with SHA-256-hashed bearer tokens.
- 31 read tools: stock (overview, due, product, entries, search, barcode, journal), shopping
  lists, recipes (details, fulfillment, consume preview), meal plan, chores, tasks,
  batteries, equipment, generic entities and search, calendar summary and iCal, file
  download, workflow previews (receipt intake, shopping reconcile), system info.
- Opt-in writes ([ADR-0002](docs/adr/0002-opt-in-writes.md)), off by default: deployment
  switch `PV_GROCY_WRITE=enabled` and per-token `access: read | write | full`, with an
  hourly write limit per token (default 60; batch items count each). 37 `write` tools for
  everyday changes (every stock change returns a `transaction_id` for `stock_undo`) and 8
  `full` tools for what cannot be undone.
- Safe Grocy client ([ADR-0003](docs/adr/0003-grocy-client-safety.md)): writes are never
  repeated once sent; names resolve exactly or not at all.
- `GET /healthz` (and `?deep=1`, which checks Grocy's version), a JSON audit line per tool
  call on stdout, and a hardened container image (non-root, read-only root filesystem).
