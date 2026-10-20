# ADR-0002: Read-only by default; writes by access level

- **Status:** Accepted
- **Date:** 2026-10-20

## Context

A Grocy API key can change everything in the household's Grocy, and MCP clients act on what
a language model decides, including on instructions hidden in data (a product name, a recipe
note, a barcode lookup). Private iCloud MCP answers this with a deployment switch per kind of
write plus per-token, per-action grants. Grocy's writes are lower-stakes and mostly
reversible (Grocy can undo stock bookings, chore executions, battery charges and task
completions), so per-action grants would be more configuration than protection. Some writes
cannot be undone, though, and a few things reach beyond what the household UI does.

## Decision

Two layers have to agree before anything changes:

1. **Deployment switch** `PV_GROCY_WRITE=enabled`. Without it, `grocy_write.py` and the
   `writes/` package are never imported, no write tool is registered, and a token with
   `write` or `full` access is a config error. Any value other than `enabled`, `disabled`
   or empty is a config error.
2. **Per-token access level**, `access: read | write | full` (default `read`). Each level
   includes the ones below it. A token is listed only the tools its level allows; others
   fail exactly like a tool that does not exist. Each level gets its own server instructions.

Every write call also counts against the token's hourly write limit (`max_writes_per_hour`,
default 60, sliding window, in memory); batch tools count each item. A call over the limit
fails before anything is sent.

### What each level allows

**read** (31 tools): every read tool. Nothing can change Grocy.
`stock_overview`, `stock_due`, `stock_product`, `stock_entries`, `stock_search`,
`stock_barcode_lookup`, `stock_journal`, `shopping_list_view`, `recipes_list`,
`recipe_details`, `recipe_fulfillment`, `recipe_consume_preview`, `meal_plan_list`,
`chores_list`, `chore_details`, `tasks_list`, `batteries_list`, `battery_details`,
`equipment_list`, `equipment_details`, `entity_list`, `entity_get`, `entity_describe`,
`search`, `calendar_summary`, `calendar_ical`, `file_download`, `workflow_match_products`,
`workflow_stock_intake_preview`, `workflow_shopping_reconcile_preview`, `system_info`.

**write** (37 more): everyday household changes, each reversible in Grocy or easily redone.
`stock_add`, `stock_consume`, `stock_open`, `stock_transfer`, `stock_inventory`,
`stock_undo`, `shopping_list_add`, `shopping_list_update`, `shopping_list_remove`,
`shopping_list_add_missing`, `recipe_consume`, `recipe_add_missing_to_shopping_list`,
`recipe_create`, `recipe_update`, `recipe_ingredient_add`, `recipe_ingredient_remove`,
`meal_plan_add`, `meal_plan_remove`, `meal_plan_add_missing_to_shopping_list`,
`chore_execute`, `chore_undo`, `chore_create`, `task_create`, `task_complete`, `task_undo`,
`battery_charge`, `battery_charge_undo`, `battery_create`, `battery_update`,
`equipment_create`, `equipment_update`, `catalog_create`, `catalog_update`,
`workflow_stock_intake_apply`, `workflow_shopping_reconcile_apply`, `print_label`,
`print_shopping_list`.

**full** (8 more): what cannot be undone, or reaches past the household UI.
`shopping_list_clear`, `task_delete`, `entity_create`, `entity_update`, `entity_delete`,
`file_upload`, `file_delete`, `calendar_sharing_link`.

The sharing link is a read, but it is a credential (anyone with it can read the calendar
without logging in), so it is `full` only and, like the other `full` tools, exists only when
the switch is on.

### Entities

The generic tools work only on the entities in `src/pv_grocy/entities.py`: Grocy 4.7's
exposed entities minus `api_keys`, `sessions` and `permission_hierarchy`, which no tool may
read or write. Users are never written. `catalog_create`/`catalog_update` (write level) are
limited to master data: products, product barcodes, product groups, locations, quantity
units and conversions, shopping lists, stores, task categories and meal plan sections.

## Consequences

- A read token's tool list and instructions are the same whether or not writes are on.
- Changing which level a tool belongs to, adding a write tool, or touching the entity lists
  needs this ADR updated first; `tests/test_repo_policy.py` checks the code against it.
- Nothing writes on its own: no startup, background or scheduled write exists.
