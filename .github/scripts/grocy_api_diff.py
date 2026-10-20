# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""Markdown summary of what changed in Grocy's REST API between two releases, from the
OpenAPI spec Grocy ships (grocy.openapi.json at the release tag).

Usage: python -I grocy_api_diff.py OLD_VERSION NEW_VERSION > diff.md
Standard library only; the downloaded specs are data, never executed.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from typing import Any

SPEC_URL = "https://raw.githubusercontent.com/grocy/grocy/v{version}/grocy.openapi.json"
METHODS = ("get", "post", "put", "delete", "patch")
ENUMS = (
    "ExposedEntity",
    "ExposedEntityNoListing",
    "ExposedEntityNoEdit",
    "ExposedEntityNoDelete",
    "FileGroups",
    "StockTransactionType",
)


def fetch(version: str) -> dict[str, Any]:
    with urllib.request.urlopen(SPEC_URL.format(version=version), timeout=30) as resp:  # noqa: S310
        data: dict[str, Any] = json.load(resp)
    return data


def operations(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out = {}
    for path, ops in (spec.get("paths") or {}).items():
        for method in METHODS:
            if method in ops:
                out[f"{method.upper()} {path}"] = ops[method]
    return out


def _resolve(spec: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    ref = schema.get("$ref", "")
    if ref.startswith("#/components/schemas/"):
        return (spec.get("components", {}).get("schemas", {}) or {}).get(ref.rsplit("/", 1)[1], {})
    return schema


def fields(spec: dict[str, Any], op: dict[str, Any]) -> set[str]:
    """Query/path parameters and JSON request body properties of one operation."""
    names = set()
    for p in op.get("parameters") or []:
        p = _resolve(spec, p) if "$ref" in p else p
        if "$ref" in p:
            p = (spec.get("components", {}).get("parameters", {}) or {}).get(
                p["$ref"].rsplit("/", 1)[1], {}
            )
        if p.get("name"):
            names.add(f"param {p['name']}")
    body = (
        (op.get("requestBody") or {})
        .get("content", {})
        .get("application/json", {})
        .get("schema", {})
    )
    for prop in _resolve(spec, body).get("properties") or {}:
        names.add(f"body {prop}")
    return names


def enum(spec: dict[str, Any], name: str) -> set[str]:
    return set((spec.get("components", {}).get("schemas", {}).get(name) or {}).get("enum") or [])


def diff(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    a, b = operations(old), operations(new)
    for title, items in (
        ("Removed endpoints", sorted(a.keys() - b.keys())),
        ("Added endpoints", sorted(b.keys() - a.keys())),
    ):
        if items:
            lines += [f"**{title}**", "", *[f"- `{i}`" for i in items], ""]
    changed = []
    for key in sorted(a.keys() & b.keys()):
        fa, fb = fields(old, a[key]), fields(new, b[key])
        if fa != fb:
            parts = [f"-`{x}`" for x in sorted(fa - fb)] + [f"+`{x}`" for x in sorted(fb - fa)]
            changed.append(f"- `{key}`: {' '.join(parts)}")
    if changed:
        lines += ["**Changed parameters or request fields**", "", *changed, ""]
    for name in ENUMS:
        ea, eb = enum(old, name), enum(new, name)
        if ea != eb:
            parts = [f"-`{x}`" for x in sorted(ea - eb)] + [f"+`{x}`" for x in sorted(eb - ea)]
            lines.append(f"- `{name}`: {' '.join(parts)}")
    return lines or ["No differences in endpoints, parameters, request fields or entity lists."]


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    old_version, new_version = argv[1], argv[2]
    try:
        old, new = fetch(old_version), fetch(new_version)
    except (OSError, ValueError) as exc:
        print(f"Could not compare the OpenAPI specs ({type(exc).__name__}).")
        return 0
    print(f"Grocy API changes from {old_version} to {new_version} (from grocy.openapi.json):\n")
    print("\n".join(diff(old, new)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
