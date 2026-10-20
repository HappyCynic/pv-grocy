# access-and-auth Specification

## Purpose
How callers authenticate, what each access level may see and call, the deployment write
switch, and the unauthenticated health endpoint.

## Requirements

### Requirement: Bearer token authentication
The server SHALL require `Authorization: Bearer <token>` on every HTTP request except
`GET /healthz`, SHALL compare the SHA-256 hash of the presented token in constant time with
every configured hash, and SHALL answer a missing, malformed or unknown token with 401,
`WWW-Authenticate: Bearer realm="pv-grocy"` and `{"error": "unauthorized"}`.

#### Scenario: Unknown token
- **WHEN** a request to `/mcp` carries a bearer token whose hash is not configured
- **THEN** the server answers 401 and nothing is sent to Grocy

#### Scenario: Health without a token
- **WHEN** `GET /healthz` is requested without a token
- **THEN** the server answers 200 `{"status": "ok"}` without contacting Grocy

### Requirement: Deep health
`GET /healthz?deep=1` SHALL read Grocy's version and SHALL answer 503 when Grocy is
unreachable (`grocy_unreachable`), rejects the API key (`grocy_api_key_rejected`) or is older
than 4.4.1 (`grocy_version_unsupported`), and 200 with `grocy_version` otherwise.

#### Scenario: Grocy down
- **WHEN** Grocy cannot be reached and `GET /healthz?deep=1` is requested
- **THEN** the server answers 503 with `"error": "grocy_unreachable"`

### Requirement: Read-only unless switched on
Unless `PV_GROCY_WRITE` is `enabled`, the server SHALL NOT import `grocy_write` or the
`writes` package, SHALL register only read tools, and SHALL refuse to start when a token has
`write` or `full` access. Any value of `PV_GROCY_WRITE` other than `enabled`, `disabled` or
empty SHALL be a config error.

#### Scenario: Write token without the switch
- **WHEN** a token has `access: write` and `PV_GROCY_WRITE` is unset
- **THEN** the server exits with a config error naming `PV_GROCY_WRITE`

### Requirement: Access levels
Each token SHALL have exactly one access level, `read` (default), `write` or `full`, each
including the ones below it, and each tool SHALL have the level docs/adr/0002-opt-in-writes.md
lists. The server SHALL list each token only the tools its level allows, SHALL refuse a call
to any other tool exactly as it refuses a tool that does not exist (without contacting
Grocy), and SHALL give each level its own server instructions.

#### Scenario: Read token calls a write tool
- **WHEN** a `read` token calls `stock_add`
- **THEN** the result is the same error as for an unknown tool, naming `stock_add`, and no
  request reaches Grocy

#### Scenario: Write token lists tools
- **WHEN** a `write` token lists tools
- **THEN** the list includes `stock_add` and excludes `task_delete`, `entity_delete`,
  `shopping_list_clear`, `file_upload`, `file_delete`, `entity_create`, `entity_update` and
  `calendar_sharing_link`
