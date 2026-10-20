# Private Grocy MCP (`pv-grocy`)

An [MCP](https://modelcontextprotocol.io) server for a household's
[Grocy](https://grocy.info): stock, shopping lists, recipes, meal plan, chores, tasks,
batteries and equipment. Ask an assistant what is expiring, what you can cook tonight, or
what to buy; with writes switched on, have it book a receipt into stock, tick off the
shopping list or plan the week's meals.

- **Read-only by default.** Writes need a deployment switch and a token with `write` or
  `full` access; irreversible operations are `full` only ([ADR-0002](docs/adr/0002-opt-in-writes.md)).
- **No silent data errors.** A write is never sent twice, and never lands on a record you
  did not name exactly ([ADR-0003](docs/adr/0003-grocy-client-safety.md)). Every stock change
  returns a `transaction_id` that `stock_undo` reverts.
- **Typed tools.** 76 tools with JSON Schema arguments, structured results and paging.
- **Hardened container.** Non-root, read-only root filesystem, no local state.

Tested with Grocy 4.7.1; needs Grocy 4.4.1 or later. Not affiliated with the Grocy project.

## What it does

| Area | Read tools | Write tools (`write` level unless marked *full*) |
|---|---|---|
| Stock | `stock_overview`, `stock_due`, `stock_product`, `stock_entries`, `stock_search`, `stock_barcode_lookup`, `stock_journal` | `stock_add`, `stock_consume`, `stock_open`, `stock_transfer`, `stock_inventory`, `stock_undo` |
| Shopping | `shopping_list_view` | `shopping_list_add`, `shopping_list_update`, `shopping_list_remove`, `shopping_list_add_missing`, `shopping_list_clear` (*full*) |
| Recipes | `recipes_list`, `recipe_details`, `recipe_fulfillment`, `recipe_consume_preview` | `recipe_consume`, `recipe_add_missing_to_shopping_list`, `recipe_create`, `recipe_update`, `recipe_ingredient_add`, `recipe_ingredient_remove` |
| Meal plan | `meal_plan_list` | `meal_plan_add`, `meal_plan_remove`, `meal_plan_add_missing_to_shopping_list` |
| Chores | `chores_list`, `chore_details` | `chore_execute`, `chore_undo`, `chore_create` |
| Tasks | `tasks_list` | `task_create`, `task_complete`, `task_undo`, `task_delete` (*full*) |
| Batteries | `batteries_list`, `battery_details` | `battery_charge`, `battery_charge_undo`, `battery_create`, `battery_update` |
| Equipment | `equipment_list`, `equipment_details` | `equipment_create`, `equipment_update` |
| Master data | `entity_list`, `entity_get`, `entity_describe`, `search` | `catalog_create`, `catalog_update`; `entity_create`, `entity_update`, `entity_delete` (*full*) |
| Workflows | `workflow_match_products`, `workflow_stock_intake_preview`, `workflow_shopping_reconcile_preview` | `workflow_stock_intake_apply`, `workflow_shopping_reconcile_apply` |
| Calendar | `calendar_summary`, `calendar_ical` | `calendar_sharing_link` (*full*; a credential) |
| Files, printing | `file_download` | `file_upload`, `file_delete` (*full*); `print_label`, `print_shopping_list` |
| System | `system_info` | |

**Names.** Tools take an id or an exact name ("Milk", "milk", " MILK " all work). A name that
matches nothing or several things fails with up to five candidates; use `search` or
`stock_search` to find the right one. Nothing is ever resolved by partial match.

**Batch changes** come in two halves: a preview that matches and proposes (and never guesses),
then an apply that takes only ids. For example, for a receipt: `workflow_stock_intake_preview`
→ confirm with the user → `workflow_stock_intake_apply` with the preview's `apply_items`.

## Security model

- Plain HTTP with bearer tokens: run it on a private network next to Grocy, and put a TLS
  proxy or tunnel with its own authentication in front of it for anything remote. Never
  publish the port to the internet.
- Tokens are stored as SHA-256 hashes; one token per client, each with its own access level
  and write limit, so each can be revoked alone.
- Give pv-grocy its own Grocy API key (Grocy → Manage API keys), so it can be revoked
  independently. The key has full access to Grocy; pv-grocy is what limits it.
- Grocy data is untrusted: results are marked `content_trust: "untrusted"`, and the model is
  told never to follow instructions found in them.

Details: [SECURITY.md](SECURITY.md).

## Quick start (Docker Compose)

```sh
cp compose.example.yml compose.yml
cp config/pv-grocy.example.yaml config/pv-grocy.yaml
docker run --rm ghcr.io/happycynic/pv-grocy:latest hash-token   # put the sha256 in pv-grocy.yaml
echo "PV_GROCY_API_KEY=<a dedicated Grocy API key>" > pv-grocy.env && chmod 600 pv-grocy.env
docker compose up -d
curl -s http://127.0.0.1:8772/healthz?deep=1    # {"status":"ok","grocy_version":"4.7.1"}
```

Point MCP clients at `http://<host>:8772/mcp` with `Authorization: Bearer <token>`.

## Configuration

`config/pv-grocy.yaml` (see the [example](config/pv-grocy.example.yaml)): Grocy's URL and
the tokens with their access levels. Environment:

| Variable | Default | |
|---|---|---|
| `PV_GROCY_API_KEY` | (required) | Grocy API key |
| `PV_GROCY_WRITE` | off | `enabled` allows tokens with `write` or `full` access |
| `PV_GROCY_CONFIG` | `config/pv-grocy.yaml` (image: `/config/pv-grocy.yaml`) | Config file |
| `PV_GROCY_HOST` | `127.0.0.1` (image: `0.0.0.0`) | Bind address |
| `PV_GROCY_PORT` | `8772` | Port |
| `PV_GROCY_LOG_LEVEL` | `INFO` | |
| `PV_GROCY_FORWARDED_ALLOW_IPS` | unset | Proxies whose `X-Forwarded-*` headers are trusted; never `*` |

Each tool call writes one JSON audit line to stdout (tool, token label, outcome, latency;
free-text arguments by size only).

## Development

```sh
uv python install 3.14 && uv sync --frozen --all-groups
uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy
```

The tests use an in-process fake of the Grocy API; `pytest -m live` runs against a real one.
See [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/design.md](docs/design.md).

## License

[Apache License 2.0](LICENSE). Copyright 2026 Happy Cynic Software LLC.
