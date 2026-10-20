# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""Checks the code against the rules in CLAUDE.md and ADR-0002/0003."""

from __future__ import annotations

import ast
import asyncio
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from pv_grocy.config import Access
from pv_grocy.server import Runtime, build_server
from pv_grocy.tooling import NO_UNDO, WRITE_NOTE
from pv_grocy.tools import GROUPS as READ_GROUPS
from pv_grocy.writes import GROUPS as WRITE_GROUPS

from .conftest import make_config

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "pv_grocy"
SNAPSHOT = ROOT / "tests" / "snapshots" / "tools.json"
HTTP_WRITE_METHODS = {"post", "put", "delete", "patch", "request", "send", "stream"}


def _http_calls(path: Path) -> set[str]:
    """Methods called on a `_http` attribute (the httpx client) in a module."""
    found = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "_http"
        ):
            found.add(node.func.attr)
    return found


def _runtime_nodes(tree: ast.AST) -> list[ast.AST]:
    """Every node except those under `if TYPE_CHECKING:` (never executed)."""
    skip: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and getattr(node.test, "id", None) == "TYPE_CHECKING":
            skip.update(id(n) for b in node.body for n in ast.walk(b))
    return [n for n in ast.walk(tree) if id(n) not in skip]


def _imports(path: Path) -> set[str]:
    names = set()
    for node in _runtime_nodes(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom):
            names.add(("." * node.level) + (node.module or ""))
            names.update(
                f"{'.' * node.level}{node.module or ''}.{a.name}".replace("..", ".")
                for a in node.names
            )
        elif isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
    return names


def test_read_client_sends_only_get() -> None:
    assert _http_calls(SRC / "grocy.py") == {"get"}


def test_only_the_write_client_sends_anything_else() -> None:
    for path in SRC.rglob("*.py"):
        calls = _http_calls(path)
        if path.name != "grocy_write.py":
            assert not (calls & HTTP_WRITE_METHODS), f"{path} sends {calls & HTTP_WRITE_METHODS}"
    assert _http_calls(SRC / "grocy_write.py") == {"request"}


def test_read_tools_never_reach_the_writer() -> None:
    for path in (SRC / "tools").glob("*.py"):
        text = path.read_text()
        assert not any("grocy_write" in i or "writes" in i for i in _imports(path)), path
        assert "writer(" not in text, path


def test_write_modules_are_imported_only_by_the_server() -> None:
    for path in SRC.rglob("*.py"):
        if path.parent.name == "writes" or path.name in ("server.py", "grocy_write.py"):
            continue
        imports = _imports(path)
        assert not any(
            "grocy_write" in i or i.startswith((".writes", "pv_grocy.writes")) for i in imports
        ), path
    server = (SRC / "server.py").read_text()
    # Both imports are inside functions, after the switch is checked.
    for line in (
        "from .grocy_write import GrocyWriter",
        "from .writes import GROUPS as WRITE_GROUPS",
    ):
        assert f"            {line}" in server or f"    {line}" in server
        assert not re.search(rf"^{re.escape(line)}", server, re.M)


def test_print_endpoints_are_only_called_by_the_write_client() -> None:
    for path in SRC.rglob("*.py"):
        if "printlabel" in path.read_text() or "/print/" in path.read_text():
            assert path.name in ("grocy.py", "printing.py"), path


def test_levels_match_adr_0002() -> None:
    adr = (ROOT / "docs" / "adr" / "0002-opt-in-writes.md").read_text()
    sections = {
        Access.READ: adr.split("**read**")[1].split("**write**")[0],
        Access.WRITE: adr.split("**write**")[1].split("**full**")[0],
        Access.FULL: adr.split("**full**")[1].split("###")[0],
    }
    words = {"read", "write", "full"}
    documented = {
        lvl: set(re.findall(r"`([a-z_]+)`", text)) - words for lvl, text in sections.items()
    }
    actual: dict[Access, set[str]] = {lvl: set() for lvl in Access}
    for group in READ_GROUPS + WRITE_GROUPS:
        for d in group.defs:
            actual[d.access].add(d.name)
    for lvl in Access:
        assert actual[lvl] == documented[lvl], (lvl, actual[lvl] ^ documented[lvl])
    assert f"**read** ({len(actual[Access.READ])} tools)" in adr
    assert f"**write** ({len(actual[Access.WRITE])} more)" in adr
    assert f"**full** ({len(actual[Access.FULL])} more)" in adr


def test_read_modules_hold_only_read_tools_and_write_modules_only_writes() -> None:
    for group in READ_GROUPS:
        assert all(d.access == Access.READ and d.write_cost is None for d in group.defs)
    for group in WRITE_GROUPS:
        for d in group.defs:
            # The one read in writes/ is the iCal sharing link: full access, never counted.
            assert d.write_cost is not None or (
                d.name == "calendar_sharing_link" and d.access == Access.FULL
            )


def test_write_descriptions_carry_the_untrusted_note_and_undo_warnings() -> None:
    for group in WRITE_GROUPS:
        for d in group.defs:
            if d.write_cost is None or d.name.startswith("print_"):
                continue
            assert WRITE_NOTE in d.description, d.name
            if d.access == Access.FULL and d.annotations.destructive_hint:
                assert NO_UNDO in d.description, d.name


def test_annotations_agree_with_levels() -> None:
    for group in READ_GROUPS:
        for d in group.defs:
            assert d.annotations.read_only_hint and not d.annotations.destructive_hint, d.name
    for group in WRITE_GROUPS:
        for d in group.defs:
            if d.write_cost is not None:
                assert d.annotations.read_only_hint is False, d.name


def test_paged_tools_say_how_to_page() -> None:
    mcp = build_server(Runtime(make_config()))
    for tool in asyncio.run(mcp.list_tools()):
        if "offset" in tool.input_schema.get("properties", {}):
            assert "next_offset" in (tool.description or ""), tool.name


def test_tool_surface_matches_the_snapshot() -> None:
    mcp = build_server(Runtime(make_config()))
    levels = {d.name: d.access.label for g in READ_GROUPS + WRITE_GROUPS for d in g.defs}
    surface = {
        t.name: {
            "access": levels[t.name],
            "annotations": t.annotations.model_dump(exclude_none=True) if t.annotations else None,
            "description": t.description,
            "input_schema": t.input_schema,
        }
        for t in sorted(asyncio.run(mcp.list_tools()), key=lambda t: t.name)
    }
    text = json.dumps(surface, indent=2, sort_keys=True) + "\n"
    if os.environ.get("PV_GROCY_UPDATE_SNAPSHOT") == "1":
        SNAPSHOT.parent.mkdir(exist_ok=True)
        SNAPSHOT.write_text(text)
    assert SNAPSHOT.exists() and SNAPSHOT.read_text() == text, (
        "tool surface changed; review, then "
        "PV_GROCY_UPDATE_SNAPSHOT=1 uv run pytest tests/test_repo_policy.py"
    )


def _tracked_files() -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except OSError, subprocess.CalledProcessError:
        pytest.skip("not a git checkout")
    return [ROOT / f for f in out.splitlines() if (ROOT / f).is_file()]


def test_spdx_header_on_python_files() -> None:
    for path in [*SRC.rglob("*.py"), *(ROOT / "tests").glob("*.py")]:
        if path.name == "__init__.py" and not path.read_text().strip():
            continue
        assert "SPDX-License-Identifier: Apache-2.0" in path.read_text()[:300], path


def test_nothing_deployment_specific_is_committed() -> None:
    private_ip = re.compile(
        r"\b(10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+)\b"
    )
    for path in _tracked_files():
        if path.suffix in (".png", ".jpg", ".lock") or "snapshots" in path.parts:
            continue
        text = path.read_text(errors="ignore")
        assert not private_ip.search(text), f"{path}: private IP address"
        # Host names (a deployment's); the project's own email addresses are fine.
        assert not re.search(r"[a-z0-9-]+\.happycynic\.com", text), f"{path}: host name"


def test_claude_md_keeps_the_rules_and_checks() -> None:
    text = (ROOT / "CLAUDE.md").read_text()
    for needle in (
        "sends only GET",
        "grocy_write.py",
        "PV_GROCY_WRITE=enabled",
        "ADR-0002",
        "ADR-0003",
        "api_keys",
        "uv run pytest",
        "uv run mypy",
        "ruff format --check",
        "@fission-ai/openspec@1.13.2",
        "agent:propose",
        "agent:implement",
    ):
        assert needle in text, needle


def test_openspec_config_has_context_and_spdx() -> None:
    text = (ROOT / "openspec" / "config.yaml").read_text()
    assert text.startswith("# SPDX-FileCopyrightText") and "context: |" in text and "rules:" in text


def test_every_tool_runs_in_the_live_suite() -> None:
    """The Grocy compatibility job (.github/workflows/grocy-compat.yml) runs the live suite
    against each new Grocy release; a tool it never calls would break unnoticed."""
    text = (ROOT / "tests" / "test_live.py").read_text()
    called = set(re.findall(r'"([a-z_]+)"', text))
    names = {d.name for g in READ_GROUPS + WRITE_GROUPS for d in g.defs}
    assert names <= called, sorted(names - called)


def test_tested_grocy_version_is_used_everywhere() -> None:
    """tests/grocy-version.txt is the Grocy release the suite last passed against; the
    compatibility job compares new releases with it."""
    version = (ROOT / "tests" / "grocy-version.txt").read_text().strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+", version)
    assert (
        f"lscr.io/linuxserver/grocy:{version}@"
        in (ROOT / ".devcontainer" / "compose.yaml").read_text()
    )
    assert f"Tested with Grocy {version}" in (ROOT / "README.md").read_text()
    assert f"lscr.io/linuxserver/grocy:{version}" in (ROOT / "CONTRIBUTING.md").read_text()
