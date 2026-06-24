from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _scalar(value: str) -> Any:
    v = value.strip().strip('"').strip("'")
    if v.lower() in {"true", "false"}:
        return v.lower() == "true"
    if v.lower() in {"null", "none"}:
        return None
    try:
        if "." in v:
            return float(v)
        return int(v)
    except ValueError:
        return v


def load_simple_yaml(path: str) -> dict[str, Any]:
    """Tiny YAML subset parser for this project's config.example.yaml shape.

    Supports nested maps by indentation and scalar/list values. This avoids adding a PyYAML
    dependency for the first MVP. Complex YAML should use JSON-compatible shapes only.
    """
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    last_key_at_indent: dict[int, str] = {}
    for raw in Path(path).read_text().splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        cur = stack[-1][1]
        if line.startswith("- "):
            key = last_key_at_indent.get(stack[-1][0])
            if key is None:
                continue
            cur.setdefault(key, []).append(_scalar(line[2:]))
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        if val == "":
            child: dict[str, Any] = {}
            cur[key] = child
            stack.append((indent, child))
            last_key_at_indent[indent] = key
        else:
            if val == "[]":
                cur[key] = []
            else:
                cur[key] = _scalar(val)
            last_key_at_indent[stack[-1][0]] = key
    return root


def deep_get(config: dict[str, Any], path: str, default: Any = None) -> Any:
    cur: Any = config
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur
