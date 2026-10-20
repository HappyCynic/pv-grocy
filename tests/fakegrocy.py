# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""An in-process fake of the Grocy 4.7 REST API, as an httpx transport.

It copies the behaviour pv-grocy depends on, observed against a real Grocy 4.7.1: status
codes (404 for a missing object, 400 for a missing product in /stock, 400 with
`error_message` for refusals, 401 for a wrong key), `created_object_id` as a string, the
`query[]` filter grammar, FIFO consumption, transaction ids and undo, and the computed
views (recipes_pos_resolved, fulfillment). When real Grocy behaves differently from this
fake, fix the fake as well as the server, and add a test.

Fault injection: `fail(method, path_prefix, mode)` makes the next matching request time out
(after it reached the server: `read_timeout`), fail before it was sent (`connect`), or
return 500/503. `requests` records every request.
"""

from __future__ import annotations

import base64
import copy
import itertools
import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs

import httpx

API_KEY = "test-grocy-key"
NOW = "2026-10-20 12:00:00"
TODAY = NOW[:10]

_ids = itertools.count(1000)


def _tx() -> str:
    return f"{next(_ids):013x}"


def seed() -> dict[str, list[dict[str, Any]]]:
    return {
        "quantity_units": [
            {"id": 1, "name": "Piece"},
            {"id": 2, "name": "Pack"},
            {"id": 3, "name": "Bottle"},
        ],
        "locations": [
            {"id": 1, "name": "Fridge", "is_freezer": 0, "active": 1},
            {"id": 2, "name": "Pantry", "is_freezer": 0, "active": 1},
            {"id": 3, "name": "Freezer", "is_freezer": 1, "active": 1},
        ],
        "shopping_locations": [{"id": 1, "name": "Corner shop"}],
        "product_groups": [{"id": 1, "name": "Dairy"}],
        "products": [
            {
                "id": 1,
                "name": "Milk",
                "active": 1,
                "location_id": 1,
                "qu_id_stock": 3,
                "qu_id_purchase": 3,
                "min_stock_amount": 2,
                "parent_product_id": None,
            },
            {
                "id": 2,
                "name": "Almond milk",
                "active": 1,
                "location_id": 1,
                "qu_id_stock": 3,
                "qu_id_purchase": 3,
                "min_stock_amount": 0,
                "parent_product_id": None,
            },
            {
                "id": 3,
                "name": "Eggs",
                "active": 1,
                "location_id": 1,
                "qu_id_stock": 1,
                "qu_id_purchase": 2,
                "min_stock_amount": 6,
                "parent_product_id": None,
            },
            {
                "id": 4,
                "name": "Flour",
                "active": 1,
                "location_id": 2,
                "qu_id_stock": 2,
                "qu_id_purchase": 2,
                "min_stock_amount": 0,
                "parent_product_id": None,
            },
            {
                "id": 5,
                "name": "Old cheese",
                "active": 0,
                "location_id": 1,
                "qu_id_stock": 1,
                "qu_id_purchase": 1,
                "min_stock_amount": 0,
                "parent_product_id": None,
            },
        ],
        "product_barcodes": [{"id": 1, "product_id": 1, "barcode": "4000000000001"}],
        "stock": [  # entries
            {
                "id": 1,
                "product_id": 1,
                "amount": 2,
                "best_before_date": "2026-10-22",
                "purchased_date": "2026-10-15",
                "location_id": 1,
                "open": 0,
                "price": 1.2,
                "stock_id": "s1",
                "note": None,
            },
            {
                "id": 2,
                "product_id": 3,
                "amount": 4,
                "best_before_date": "2026-11-01",
                "purchased_date": "2026-10-10",
                "location_id": 1,
                "open": 0,
                "price": 0.3,
                "stock_id": "s2",
                "note": None,
            },
            {
                "id": 3,
                "product_id": 4,
                "amount": 1,
                "best_before_date": "2027-06-01",
                "purchased_date": "2026-09-01",
                "location_id": 2,
                "open": 0,
                "price": 2.0,
                "stock_id": "s3",
                "note": None,
            },
        ],
        "stock_log": [],
        "shopping_lists": [{"id": 1, "name": "Shopping list"}, {"id": 2, "name": "Hardware"}],
        "shopping_list": [
            {
                "id": 1,
                "product_id": 1,
                "note": None,
                "amount": 2,
                "shopping_list_id": 1,
                "done": 0,
                "qu_id": 3,
            },
            {
                "id": 2,
                "product_id": None,
                "note": "Candles",
                "amount": 1,
                "shopping_list_id": 1,
                "done": 0,
                "qu_id": None,
            },
        ],
        "recipes": [
            {
                "id": 1,
                "name": "Pancakes",
                "description": "<p>Mix <b>well</b>.</p><script>x</script>",
                "base_servings": 1,
                "desired_servings": 1,
                "type": "normal",
            },
            {
                "id": 2,
                "name": "Omelette",
                "description": "",
                "base_servings": 1,
                "desired_servings": 1,
                "type": "normal",
            },
            {
                "id": -1,
                "name": "2026-42",
                "description": None,
                "base_servings": 1,
                "desired_servings": 1,
                "type": "mealplan-week",
            },
        ],
        "recipes_pos": [
            {
                "id": 1,
                "recipe_id": 1,
                "product_id": 1,
                "amount": 1,
                "qu_id": 3,
                "note": None,
                "ingredient_group": None,
                "only_check_single_unit_in_stock": 0,
            },
            {
                "id": 2,
                "recipe_id": 1,
                "product_id": 3,
                "amount": 2,
                "qu_id": 1,
                "note": None,
                "ingredient_group": None,
                "only_check_single_unit_in_stock": 0,
            },
            {
                "id": 3,
                "recipe_id": 1,
                "product_id": 4,
                "amount": 3,
                "qu_id": 2,
                "note": None,
                "ingredient_group": None,
                "only_check_single_unit_in_stock": 0,
            },
            {
                "id": 4,
                "recipe_id": 2,
                "product_id": 3,
                "amount": 3,
                "qu_id": 1,
                "note": None,
                "ingredient_group": None,
                "only_check_single_unit_in_stock": 0,
            },
            {
                "id": 5,
                "recipe_id": -1,
                "product_id": 4,
                "amount": 3,
                "qu_id": 2,
                "note": None,
                "ingredient_group": None,
                "only_check_single_unit_in_stock": 0,
            },
        ],
        "meal_plan_sections": [
            {"id": -1, "name": None},
            {"id": 1, "name": "Breakfast"},
            {"id": 2, "name": "Dinner"},
        ],
        "meal_plan": [
            {
                "id": 1,
                "day": "2026-10-21",
                "type": "recipe",
                "recipe_id": 1,
                "recipe_servings": 2,
                "note": None,
                "product_id": None,
                "product_amount": 0,
                "section_id": 1,
                "done": 0,
            },
        ],
        "chores": [
            {
                "id": 1,
                "name": "Water plants",
                "description": "<p>All of them</p>",
                "period_type": "weekly",
                "period_interval": 1,
                "active": 1,
            },
        ],
        "chores_log": [
            {
                "id": 1,
                "chore_id": 1,
                "tracked_time": "2026-10-10 09:00:00",
                "done_by_user_id": 1,
                "undone": 0,
                "skipped": 0,
            },
        ],
        "batteries": [
            {
                "id": 1,
                "name": "Remote",
                "description": None,
                "used_in": "TV",
                "charge_interval_days": 30,
                "active": 1,
            },
        ],
        "battery_charge_cycles": [
            {"id": 1, "battery_id": 1, "tracked_time": "2026-09-01 10:00:00", "undone": 0},
        ],
        "equipment": [
            {
                "id": 1,
                "name": "Dishwasher",
                "description": "<h1>Manual</h1><p>Rinse first</p>",
                "instruction_manual_file_name": "dishwasher.pdf",
            },
        ],
        "tasks": [
            {
                "id": 1,
                "name": "Fix shelf",
                "description": None,
                "due_date": "2026-10-19",
                "done": 0,
                "done_timestamp": None,
                "category_id": 1,
                "assigned_to_user_id": 1,
            },
            {
                "id": 2,
                "name": "Old task",
                "description": None,
                "due_date": None,
                "done": 1,
                "done_timestamp": "2026-10-01 10:00:00",
                "category_id": None,
                "assigned_to_user_id": None,
            },
        ],
        "task_categories": [{"id": 1, "name": "Home"}],
        "userfields": [],
        "api_keys": [{"id": 1, "api_key": "secret", "description": "x"}],
        "quantity_unit_conversions": [],
        "users": [
            {"id": 1, "username": "alex", "display_name": "Alex"},
            {"id": 2, "username": "sam", "display_name": "Sam"},
        ],
    }


VIEWS = {
    "recipes_pos_resolved",
    "stock_current_locations",
    "products_last_purchased",
    "products_average_price",
    "battery_charge_cycles",
    "chores_log",
    "stock_log",
}
EXPOSED = (
    (set(seed()) - {"users"})
    | VIEWS
    | {"sessions", "permission_hierarchy", "userentities", "userobjects", "recipes_nestings"}
)
FILTER = re.compile(r"(?P<field>[A-Za-z_][A-Za-z0-9_]+)(?P<op>!?((>=)|(<=)|=|~|<|>))(?P<value>.+)")


class Fault(Exception):
    pass


@dataclass
class FakeGrocy:
    db: dict[str, list[dict[str, Any]]] = field(default_factory=seed)
    files: dict[tuple[str, str], bytes] = field(
        default_factory=lambda: {("productpictures", "milk.jpg"): b"\xff\xd8jpeg"}
    )
    requests: list[tuple[str, str]] = field(default_factory=list)
    faults: list[tuple[str, str, str]] = field(default_factory=list)
    printed: list[str] = field(default_factory=list)
    label_printer: bool = True
    undo: dict[str, list[tuple[int, float, bool]]] = field(default_factory=dict)

    # ------------------------------------------------------------------ plumbing

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def fail(self, method: str, path_prefix: str, mode: str) -> None:
        self.faults.append((method, path_prefix, mode))

    def count(self, method: str, path_prefix: str) -> int:
        return sum(1 for m, p in self.requests if m == method and p.startswith(path_prefix))

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api")
        for n, (m, prefix, mode) in enumerate(self.faults):
            if m == request.method and path.startswith(prefix):
                del self.faults[n]
                if mode == "connect":
                    raise httpx.ConnectError("refused", request=request)
                self.requests.append((request.method, path))
                if mode == "read_timeout":
                    self.dispatch(request, path)  # it reached Grocy and was applied
                    raise httpx.ReadTimeout("timed out", request=request)
                return httpx.Response(int(mode), json={"error_message": "server error"})
        self.requests.append((request.method, path))
        if request.headers.get("GROCY-API-KEY") != API_KEY:
            return httpx.Response(401, json={"error_message": "Unauthorized"})
        return self.dispatch(request, path)

    def dispatch(self, request: httpx.Request, path: str) -> httpx.Response:
        params = parse_qs(request.url.query.decode(), keep_blank_values=True)
        body: Any = None
        if request.content and request.headers.get("content-type", "").startswith(
            "application/json"
        ):
            body = json.loads(request.content)
        try:
            result = self.route(request.method, path, params, body, request.content)
        except Fault as exc:
            return httpx.Response(
                400, json={"error_message": str(exc), "error_details": {"stack_trace": "#0 ..."}}
            )
        if isinstance(result, httpx.Response):
            return result
        if result is None:
            return httpx.Response(204)
        if isinstance(result, bytes):
            return httpx.Response(
                200, content=result, headers={"content-type": "application/octet-stream"}
            )
        if isinstance(result, str):
            return httpx.Response(200, text=result)
        return httpx.Response(200, json=result)

    # ------------------------------------------------------------------ tables

    def table(self, entity: str) -> list[dict[str, Any]]:
        if entity == "recipes_pos_resolved":
            return self.resolved()
        if entity == "stock_current_locations":
            return self.current_locations()
        if entity in ("products_last_purchased", "products_average_price"):
            return []
        return self.db.setdefault(entity, [])

    def get_row(self, entity: str, obj_id: int) -> dict[str, Any] | None:
        return next((r for r in self.table(entity) if r.get("id") == obj_id), None)

    def next_id(self, entity: str) -> int:
        return max([int(r["id"]) for r in self.db.get(entity, [])] + [0]) + 1

    def query(
        self, rows: list[dict[str, Any]], params: dict[str, list[str]]
    ) -> list[dict[str, Any]]:
        for q in params.get("query[]", []):
            m = FILTER.match(q)
            if not m:
                raise Fault("Invalid query")
            fld, op, val = m["field"], m["op"], m["value"]
            neg = op.startswith("!")
            op = op.lstrip("!")

            def test(row: dict[str, Any], fld: str = fld, op: str = op, val: str = val) -> bool:
                v = row.get(fld)
                s = "" if v is None else str(v)
                if op == "=":
                    return s == val or (val.lower() == "null" and v is None)
                if op == "~":
                    return val.casefold() in s.casefold()
                try:
                    a, b = float(s), float(val)
                except ValueError:
                    a, b = s, val  # type: ignore[assignment]
                return {"<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[op]

            rows = [r for r in rows if test(r) != neg]
        if "order" in params:
            fld, _, direction = params["order"][0].partition(":")
            rows = sorted(
                rows, key=lambda r: (r.get(fld) is None, r.get(fld)), reverse=direction == "desc"
            )
        offset = int(params.get("offset", ["0"])[0])
        if "limit" in params:
            rows = rows[offset : offset + int(params["limit"][0])]
        elif offset:
            rows = rows[offset:]
        return rows

    # ------------------------------------------------------------------ stock

    def product(self, pid: int) -> dict[str, Any]:
        p = self.get_row("products", pid)
        if p is None:
            raise Fault("Product does not exist or is inactive")
        return p

    def entries(self, pid: int, location_id: int | None = None) -> list[dict[str, Any]]:
        rows = [e for e in self.db["stock"] if e["product_id"] == pid and e["amount"] > 0]
        if location_id is not None:
            rows = [e for e in rows if e["location_id"] == location_id]
        return sorted(rows, key=lambda e: (e["best_before_date"], e["id"]))

    def amount(self, pid: int) -> float:
        return sum(e["amount"] for e in self.entries(pid))

    def stock_line(self, pid: int) -> dict[str, Any]:
        es = self.entries(pid)
        return {
            "product_id": pid,
            "amount": self.amount(pid),
            "amount_opened": sum(e["amount"] for e in es if e["open"]),
            "best_before_date": es[0]["best_before_date"] if es else None,
            "value": round(sum(e["amount"] * (e["price"] or 0) for e in es), 4),
            "product": self.product(pid),
        }

    def log(
        self, tx: str, pid: int, amount: float, kind: str, entry: dict[str, Any], **extra: Any
    ) -> dict[str, Any]:
        row = {
            "id": self.next_id("stock_log"),
            "product_id": pid,
            "amount": amount,
            "transaction_type": kind,
            "transaction_id": tx,
            "undone": 0,
            "spoiled": 0,
            "location_id": entry["location_id"],
            "stock_id": entry["stock_id"],
            "best_before_date": entry["best_before_date"],
            "recipe_id": None,
            "row_created_timestamp": NOW,
            **extra,
        }
        self.db["stock_log"].append(row)
        return row

    def add(
        self,
        pid: int,
        amount: float,
        body: dict[str, Any],
        tx: str | None = None,
        kind: str = "purchase",
    ) -> list[dict[str, Any]]:
        p = self.product(pid)
        tx = tx or _tx()
        e = {
            "id": self.next_id("stock"),
            "product_id": pid,
            "amount": amount,
            "best_before_date": body.get("best_before_date") or "2999-12-31",
            "purchased_date": TODAY,
            "location_id": body.get("location_id") or p["location_id"],
            "open": 0,
            "price": body.get("price"),
            "stock_id": _tx(),
            "note": None,
        }
        self.db["stock"].append(e)
        self.undo.setdefault(tx, []).append((e["id"], amount, True))
        return [self.log(tx, pid, amount, kind, e)]

    def take(
        self, pid: int, amount: float, location_id: int | None, tx: str, kind: str, **extra: Any
    ) -> list[dict[str, Any]]:
        self.product(pid)
        es = self.entries(pid, location_id)
        if amount > sum(e["amount"] for e in es) + 1e-9:
            raise Fault(
                "Amount to be consumed cannot be > current stock amount "
                "(if supplied, at the desired location)"
            )
        rows, left = [], amount
        for e in es:
            if left <= 0:
                break
            use = min(left, e["amount"])
            e["amount"] -= use
            left -= use
            self.undo.setdefault(tx, []).append((e["id"], -use, False))
            rows.append(self.log(tx, pid, -use, kind, e, **extra))
        return rows

    # ------------------------------------------------------------------ recipes

    def resolved(self) -> list[dict[str, Any]]:
        out = []
        for pos in self.db["recipes_pos"]:
            r = self.get_row("recipes", pos["recipe_id"]) or {}
            factor = (r.get("desired_servings") or 1) / (r.get("base_servings") or 1)
            need = pos["amount"] * factor
            have = self.amount(pos["product_id"])
            on_list = sum(
                i["amount"]
                for i in self.db["shopping_list"]
                if i["product_id"] == pos["product_id"]
            )
            out.append(
                {
                    "id": pos["id"],
                    "recipe_id": pos["recipe_id"],
                    "recipe_pos_id": pos["id"],
                    "product_id": pos["product_id"],
                    "recipe_amount": need,
                    "stock_amount": have,
                    "need_fulfilled": int(have >= need),
                    "missing_amount": max(0, need - have),
                    "amount_on_shopping_list": on_list,
                    "need_fulfilled_with_shopping_list": int(have + on_list >= need),
                    "qu_id": pos["qu_id"],
                    "note": pos["note"],
                    "ingredient_group": pos["ingredient_group"],
                    "is_nested_recipe_pos": 0,
                    "product_name": self.product(pos["product_id"])["name"],
                    "only_check_single_unit_in_stock": pos.get(
                        "only_check_single_unit_in_stock", 0
                    ),
                }
            )
        return out

    def fulfillment(self, rid: int) -> dict[str, Any]:
        lines = [p for p in self.resolved() if p["recipe_id"] == rid]
        return {
            "recipe_id": rid,
            "need_fulfilled": int(all(p["need_fulfilled"] for p in lines)),
            "need_fulfilled_with_shopping_list": int(
                all(p["need_fulfilled_with_shopping_list"] for p in lines)
            ),
            "missing_products_count": sum(1 for p in lines if not p["need_fulfilled"]),
            "costs": 1.0,
            "costs_per_serving": 1.0,
            "calories": 100,
            "prices_incomplete": 0,
        }

    def current_locations(self) -> list[dict[str, Any]]:
        agg: dict[tuple[int, int], float] = {}
        for e in self.db["stock"]:
            if e["amount"] > 0:
                agg[(e["product_id"], e["location_id"])] = (
                    agg.get((e["product_id"], e["location_id"]), 0) + e["amount"]
                )
        return [{"product_id": p, "location_id": loc, "amount": a} for (p, loc), a in agg.items()]

    def add_to_list(
        self, pid: int, amount: float, list_id: int = 1, note: str | None = None
    ) -> None:
        for i in self.db["shopping_list"]:
            if i["product_id"] == pid and i["shopping_list_id"] == list_id:
                i["amount"] += amount
                return
        self.db["shopping_list"].append(
            {
                "id": self.next_id("shopping_list"),
                "product_id": pid,
                "note": note,
                "amount": amount,
                "shopping_list_id": list_id,
                "done": 0,
                "qu_id": self.product(pid)["qu_id_stock"],
            }
        )

    # ------------------------------------------------------------------ routes

    def route(
        self, method: str, path: str, params: dict[str, list[str]], body: Any, raw: bytes
    ) -> Any:
        parts = [p for p in path.split("/") if p]
        body = body or {}
        # ---- generic objects
        if parts[0] == "objects":
            entity = parts[1]
            if entity not in EXPOSED or (
                entity in ("api_keys", "sessions") and len(parts) == 2 and method == "GET"
            ):
                raise Fault("Entity does not exist or is not exposed")
            if len(parts) == 2 and method == "GET":
                return self.query(copy.deepcopy(self.table(entity)), params)
            if len(parts) == 2 and method == "POST":
                cols = (
                    set().union(*(r.keys() for r in self.table(entity)))
                    if self.table(entity)
                    else set(body)
                )
                cols |= {
                    "description",
                    "name",
                    "note",
                    "amount",
                    "done",
                    "shopping_list_id",
                    "product_id",
                    "recipe_id",
                    "qu_id",
                    "ingredient_group",
                    "type",
                    "day",
                    "recipe_servings",
                    "section_id",
                    "period_type",
                    "period_interval",
                    "used_in",
                    "charge_interval_days",
                    "is_freezer",
                    "base_servings",
                    "desired_servings",
                    "due_date",
                    "category_id",
                    "assigned_to_user_id",
                }
                for k in body:
                    if k not in cols:
                        raise Fault(
                            f"SQLSTATE[HY000]: General error: 1 table {entity} "
                            f"has no column named {k}"
                        )
                existing = (
                    set().union(*(r.keys() for r in self.table(entity)))
                    if self.table(entity)
                    else set()
                )
                row = {
                    **dict.fromkeys(existing),
                    "id": self.next_id(entity),
                    **body,
                }  # NULL columns, as in SQLite
                self.db.setdefault(entity, []).append(row)
                return {"created_object_id": str(row["id"])}
            row = self.get_row(entity, int(parts[2]))
            if row is None:
                return httpx.Response(404, json={"error_message": "Object not found"})
            if method == "GET":
                return copy.deepcopy(row)
            if method == "PUT":
                row.update(body)
                return None
            if method == "DELETE":
                self.db[entity].remove(row)
                return None
        # ---- system
        if path == "/system/info":
            return {
                "grocy_version": {"Version": "4.7.1", "ReleaseDate": "2026-09-04"},
                "php_version": "8.5",
                "sqlite_version": "3.53",
                "os": "Linux secret-host",
                "client": "x",
            }
        if path == "/system/time":
            return {"timezone": "America/Chicago", "time_local": NOW}
        if path == "/users":
            return copy.deepcopy(self.db["users"])
        # ---- stock
        if path == "/stock":
            pids = sorted({e["product_id"] for e in self.db["stock"] if e["amount"] > 0})
            return [self.stock_line(p) for p in pids]
        if path == "/stock/volatile":
            days = int(params.get("due_soon_days", ["5"])[0])
            lines = [
                self.stock_line(p)
                for p in sorted({e["product_id"] for e in self.db["stock"] if e["amount"] > 0})
            ]
            soon = f"2026-10-{20 + days:02d}"
            missing = [
                {
                    "id": p["id"],
                    "name": p["name"],
                    "amount_missing": p["min_stock_amount"] - self.amount(p["id"]),
                    "is_partly_in_stock": int(self.amount(p["id"]) > 0),
                }
                for p in self.db["products"]
                if self.amount(p["id"]) < p["min_stock_amount"]
            ]
            return {
                "due_products": [
                    line for line in lines if TODAY <= line["best_before_date"] <= soon
                ],
                "overdue_products": [line for line in lines if line["best_before_date"] < TODAY],
                "expired_products": [],
                "missing_products": missing,
            }
        if parts[:2] == ["stock", "locations"] and parts[3] == "entries":
            return [
                e for e in self.db["stock"] if e["location_id"] == int(parts[2]) and e["amount"] > 0
            ]
        if parts[:3] == ["stock", "products", "by-barcode"]:
            b = next((b for b in self.db["product_barcodes"] if b["barcode"] == parts[3]), None)
            if b is None:
                raise Fault(f"No product with barcode {parts[3]} found")
            parts = ["stock", "products", str(b["product_id"])]
        if parts[:2] == ["stock", "products"] and len(parts) == 3 and method == "GET":
            pid = int(parts[2])
            p = self.product(pid)
            line = self.stock_line(pid)
            units = {u["id"]: u for u in self.db["quantity_units"]}
            return {
                "product": p,
                "product_barcodes": [
                    b for b in self.db["product_barcodes"] if b["product_id"] == pid
                ],
                "stock_amount": line["amount"],
                "stock_amount_opened": line["amount_opened"],
                "stock_amount_aggregated": line["amount"],
                "stock_value": line["value"],
                "quantity_unit_stock": units.get(p["qu_id_stock"]),
                "next_due_date": line["best_before_date"],
                "last_purchased": None,
                "last_used": None,
                "last_price": 1.2,
                "avg_price": 1.1,
            }
        if parts[:2] == ["stock", "products"] and len(parts) == 4:
            pid = int(parts[2])
            if parts[3] == "entries":
                return self.entries(pid)
            if parts[3] == "locations":
                names = {loc["id"]: loc["name"] for loc in self.db["locations"]}
                return [
                    {
                        "product_id": pid,
                        "location_id": r["location_id"],
                        "amount": r["amount"],
                        "location_name": names[r["location_id"]],
                    }
                    for r in self.current_locations()
                    if r["product_id"] == pid
                ]
            if parts[3] == "printlabel":
                return self.print_label(path)
            amount = float(body.get("amount", 1))
            tx = _tx()
            if parts[3] == "add":
                return self.add(pid, amount, body, tx)
            if parts[3] == "consume":
                return self.take(
                    pid,
                    amount,
                    body.get("location_id"),
                    tx,
                    "consume",
                    spoiled=int(bool(body.get("spoiled"))),
                )
            if parts[3] == "open":
                self.product(pid)
                es = [e for e in self.entries(pid) if not e["open"]]
                if not es:
                    raise Fault("No unopened stock")
                es[0]["open"] = 1
                return [self.log(tx, pid, amount, "product-opened", es[0])]
            if parts[3] == "transfer":
                rows = self.take(pid, amount, body["location_id_from"], tx, "transfer_from")
                rows += self.add(
                    pid, amount, {"location_id": body["location_id_to"]}, tx, "transfer_to"
                )
                return rows
            if parts[3] == "inventory":
                diff = float(body["new_amount"]) - self.amount(pid)
                if abs(diff) < 1e-9:
                    raise Fault("The new amount cannot equal the current stock amount")
                if diff > 0:
                    return self.add(pid, diff, body, tx, "inventory-correction")
                return self.take(pid, -diff, None, tx, "inventory-correction")
        if parts[:2] == ["stock", "transactions"]:
            tx = parts[2]
            rows = [
                r for r in self.db["stock_log"] if r["transaction_id"] == tx and not r["undone"]
            ]
            if len(parts) == 3:
                return rows
            if not rows:
                raise Fault("This transaction was not found or already undone")
            for entry_id, delta, _created in self.undo.pop(tx, []):
                e = self.get_row("stock", entry_id)
                if e is not None:
                    e["amount"] -= delta
            for r in rows:
                r["undone"] = 1
            return None
        if parts[:2] == ["stock", "entry"] and parts[-1] == "printlabel":
            return self.print_label(path)
        if parts[:2] == ["stock", "shoppinglist"]:
            list_id = int(body.get("list_id", 1))
            if parts[2] == "add-product":
                self.add_to_list(
                    int(body["product_id"]),
                    float(body.get("product_amount", 1)),
                    list_id,
                    body.get("note"),
                )
                return None
            if parts[2] == "add-missing-products":
                for p in self.db["products"]:
                    if self.amount(p["id"]) < p["min_stock_amount"]:
                        self.add_to_list(
                            p["id"], p["min_stock_amount"] - self.amount(p["id"]), list_id
                        )
                return None
            if parts[2] in ("add-overdue-products", "add-expired-products"):
                return None
            if parts[2] == "clear":
                self.db["shopping_list"] = [
                    i
                    for i in self.db["shopping_list"]
                    if i["shopping_list_id"] != list_id or (body.get("done_only") and not i["done"])
                ]
                return None
        # ---- recipes
        if path == "/recipes/fulfillment":
            return [self.fulfillment(r["id"]) for r in self.db["recipes"]]
        if parts[0] == "recipes" and len(parts) >= 3:
            rid = int(parts[1])
            if self.get_row("recipes", rid) is None:
                raise Fault("Recipe does not exist")
            if parts[2] == "fulfillment":
                return self.fulfillment(rid)
            if parts[2] == "consume":
                tx = _tx()
                for pos in [p for p in self.resolved() if p["recipe_id"] == rid]:
                    if pos["stock_amount"] > 0 and not pos["only_check_single_unit_in_stock"]:
                        self.take(
                            pos["product_id"],
                            min(pos["recipe_amount"], pos["stock_amount"]),
                            None,
                            tx,
                            "consume",
                            recipe_id=rid,
                        )
                return None
            if parts[2] == "add-not-fulfilled-products-to-shoppinglist":
                excluded = set(body.get("excludedProductIds") or [])
                for pos in [p for p in self.resolved() if p["recipe_id"] == rid]:
                    if (
                        not pos["need_fulfilled_with_shopping_list"]
                        and pos["product_id"] not in excluded
                    ):
                        self.add_to_list(
                            pos["product_id"],
                            pos["missing_amount"] - pos["amount_on_shopping_list"],
                        )
                return None
            if parts[2] == "printlabel":
                return self.print_label(path)
        # ---- chores
        if path == "/chores":
            return [
                {
                    "chore_id": c["id"],
                    "chore_name": c["name"],
                    "last_tracked_time": self.last_chore(c["id"]),
                    "next_estimated_execution_time": "2026-10-17 09:00:00",
                    "next_execution_assigned_user": {"id": 1, "display_name": "Alex"},
                }
                for c in self.db["chores"]
            ]
        if parts[0] == "chores" and len(parts) == 2:
            c = self.get_row("chores", int(parts[1]))
            if c is None:
                raise Fault("Chore does not exist")
            return {
                "chore": c,
                "last_tracked": self.last_chore(c["id"]),
                "tracked_count": 1,
                "next_estimated_execution_time": "2026-10-17 09:00:00",
                "last_done_by": {"display_name": "Alex"},
                "next_execution_assigned_user": {"display_name": "Alex"},
            }
        if parts[0] == "chores" and parts[-1] == "execute":
            row = {
                "id": self.next_id("chores_log"),
                "chore_id": int(parts[1]),
                "tracked_time": body.get("tracked_time") or NOW,
                "done_by_user_id": body.get("done_by", 1),
                "undone": 0,
                "skipped": int(bool(body.get("skipped"))),
            }
            self.db["chores_log"].append(row)
            return row
        if parts[:2] == ["chores", "executions"] and parts[-1] == "undo":
            row = self.get_row("chores_log", int(parts[2]))
            if row is None or row["undone"]:
                raise Fault("Execution does not exist or was already undone")
            row["undone"] = 1
            return None
        if parts[0] in ("chores", "batteries") and parts[-1] == "printlabel":
            return self.print_label(path)
        # ---- batteries
        if path == "/batteries":
            return [
                {
                    "battery_id": b["id"],
                    "battery": b,
                    "last_tracked_time": "2026-09-01 10:00:00",
                    "next_estimated_charge_time": "2026-10-01 10:00:00",
                }
                for b in self.db["batteries"]
            ]
        if parts[0] == "batteries" and len(parts) == 2:
            b = self.get_row("batteries", int(parts[1]))
            if b is None:
                raise Fault("Battery does not exist")
            return {
                "battery": b,
                "charge_cycles_count": 1,
                "last_charged": "2026-09-01 10:00:00",
                "next_estimated_charge_time": "2026-10-01 10:00:00",
            }
        if parts[0] == "batteries" and parts[-1] == "charge":
            row = {
                "id": self.next_id("battery_charge_cycles"),
                "battery_id": int(parts[1]),
                "tracked_time": body.get("tracked_time") or NOW,
                "undone": 0,
            }
            self.db["battery_charge_cycles"].append(row)
            return row
        if parts[:2] == ["batteries", "charge-cycles"]:
            row = self.get_row("battery_charge_cycles", int(parts[2]))
            if row is None or row["undone"]:
                raise Fault("Charge cycle does not exist or was already undone")
            row["undone"] = 1
            return None
        # ---- tasks
        if path == "/tasks":
            return [t for t in self.db["tasks"] if not t["done"]]
        if parts[0] == "tasks" and parts[-1] in ("complete", "undo"):
            t = self.get_row("tasks", int(parts[1]))
            if t is None:
                raise Fault("Task does not exist")
            t["done"] = int(parts[-1] == "complete")
            return None
        # ---- calendar, files, print
        if path == "/calendar/ical":
            return (
                "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
                + "BEGIN:VEVENT\r\nSUMMARY:x\r\nEND:VEVENT\r\n" * 2000
                + "END:VCALENDAR\r\n"
            )
        if path == "/calendar/ical/sharing-link":
            return {"url": "http://grocy/api/calendar/ical?secret=abc123"}
        if path == "/print/shoppinglist/thermal":
            self.printed.append(path)
            return {"result": "ok"}
        if parts[0] == "files":
            key = (parts[1], base64.b64decode(parts[2]).decode())
            if method == "GET":
                if key not in self.files:
                    return httpx.Response(404, json={"error_message": "File not found"})
                return self.files[key]
            if method == "PUT":
                if key in self.files:
                    raise Fault("File already exists")
                self.files[key] = raw
                return None
            if method == "DELETE":
                self.files.pop(key, None)
                return None
        return httpx.Response(404, json={"error_message": f"no route {method} {path}"})

    def print_label(self, path: str) -> dict[str, Any]:
        if not self.label_printer:
            raise Fault("Label printer webhook is not configured")
        self.printed.append(path)
        return {}

    def last_chore(self, cid: int) -> str | None:
        rows = [r for r in self.db["chores_log"] if r["chore_id"] == cid and not r["undone"]]
        return rows[-1]["tracked_time"] if rows else None
