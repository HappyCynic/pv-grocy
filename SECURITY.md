# Security policy

## Reporting a vulnerability

Please report vulnerabilities **privately** through GitHub's private vulnerability reporting:
the repository's **Security** tab → **Report a vulnerability**. If you cannot use that,
email **security.admin@happycynic.com**. Do not open a public issue.

Include what you found, how to reproduce it, and the version or image digest. You should get
an acknowledgement within a week. Fixes are released as a new version, and the advisory is
published once users have had a chance to update.

Only the latest release is supported.

## Threat model in short

Private Grocy MCP gives an MCP client access to one household's Grocy: read access always,
and write access only where the operator turns it on. It assumes the server runs on hardware
the household controls, next to Grocy, and is reached over a private network or through an
authenticating proxy or tunnel.

**Read-only by default.** Unless `PV_GROCY_WRITE=enabled`, the write client and the write
tools are not even imported, and the read client can send only GET requests, never to a
print endpoint. With writes on, each token has an access level (`read`, `write`, `full`;
[ADR-0002](docs/adr/0002-opt-in-writes.md)) and an hourly write limit. These are
vulnerabilities: any change to Grocy without the switch and a token whose level allows the
tool; a tool listed to, or callable by, a token whose level does not allow it; any read or
write of `api_keys`, `sessions` or `permission_hierarchy`, or any write of users.

**No repeated or misdirected writes** ([ADR-0003](docs/adr/0003-grocy-client-safety.md)).
A write is never sent twice once it may have reached Grocy, and never applied to a record
the caller did not name exactly (or by id). A repeated write or a write to a record resolved
by partial name is a bug we treat as a vulnerability.

**Authentication.** Every request except `GET /healthz` needs `Authorization: Bearer <token>`.
Tokens are stored only as SHA-256 hashes and compared in constant time. The server speaks
plain HTTP: never expose its port to the internet; put a TLS proxy or tunnel with its own
authentication in front of it.

**Untrusted content.** Product and recipe names, notes, descriptions and barcode data can be
written by anyone with access to Grocy, or come from outside sources. Every result is
marked `content_trust: "untrusted"`, and tool descriptions and instructions tell the model
never to act on instructions found in it.

**Secrets and logs.** The Grocy API key comes from the environment and is sent only to the
configured Grocy (redirects are not followed). It, bearer tokens and the iCal sharing link
are never logged; free-text arguments appear in the audit log by size only.

**Out of scope:** the security of Grocy itself and its API key handling; someone with access
to the host or the container's environment; denial of service by an authenticated caller
(the write limit caps writes, not reads).
