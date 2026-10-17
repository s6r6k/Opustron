"""Only chronicle/guard (and the Tavily client) may talk to the network.

Every model call must go through ``chronicle.guard.llm`` so PII is pseudonymised
and the call is logged. The OpenShell policy can't enforce this (it sees one
Python process), so CI does.
"""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCANNED = ["chronicle", "adapters", "eval", "deploy"]
ALLOWED = {
    "chronicle/guard": "the privacy router and LLM client",
    "chronicle/integrations/tavily.py": "web search with its own PII gate",
}
NETWORK_MODULES = {"openai", "requests", "httpx", "aiohttp", "urllib.request", "http.client"}
PROVIDER_MARKERS = ("tokenfactory.nebius.com", "api.tavily.com", "/chat/completions")
FIX = "Call models via `from chronicle.guard import llm` (see README: 'Calling a model')."


def find_violations(source: str) -> list[str]:
    tree = ast.parse(source)
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules = [node.module] + [f"{node.module}.{alias.name}" for alias in node.names]
        else:
            modules = []
        for module in modules:
            if module in NETWORK_MODULES or module.split(".")[0] in NETWORK_MODULES:
                found.append(f"line {node.lineno}: imports {module}")
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            for marker in PROVIDER_MARKERS:
                if marker in node.value:
                    found.append(f"line {node.lineno}: hard-codes {marker!r}")
    return found


def _is_allowed(rel: str) -> bool:
    return any(rel == allowed or rel.startswith(allowed + "/") for allowed in ALLOWED)


def test_no_network_calls_outside_guard():
    violations = []
    for top in SCANNED:
        for path in sorted((ROOT / top).rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            if not _is_allowed(rel):
                violations += [f"{rel} {v}" for v in find_violations(path.read_text(encoding="utf-8"))]
    assert not violations, "Direct network/model calls outside chronicle/guard:\n  " + "\n  ".join(violations) + f"\n{FIX}"


@pytest.mark.parametrize(
    "source",
    [
        "import openai",
        "from openai import OpenAI",
        "import urllib.request",
        "from urllib import request",
        "import requests",
        "import httpx as h",
        'BASE = "https://api.tokenfactory.nebius.com/v1"',
        'url = base + "/chat/completions"',
    ],
)
def test_checker_flags_direct_calls(source):
    assert find_violations(source)


@pytest.mark.parametrize(
    "source",
    [
        "from chronicle.guard import llm",
        "import urllib.parse",
        "from urllib.parse import quote",
        '"""Calls api.tokenfactory.nebius.com via the guard."""',
        'def f():\n    """POSTs to /chat/completions through llm."""\n    return 1',
        "# import openai",
    ],
)
def test_checker_allows_safe_code(source):
    assert find_violations(source) == []
