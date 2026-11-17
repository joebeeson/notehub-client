"""Literal, bounded presentation of untrusted Notehub records."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from rich.text import Text

# Escape sequences include CSI and OSC, including terminal clipboard controls.
_ESCAPES = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]|\x1b[@-_]")
_CONTROLS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
_SENSITIVE = frozenset({"authorization", "token", "access_token", "refresh_token", "password"})


def safe_string(value: object) -> str:
    """Remove terminal controls without interpreting Rich markup."""
    return _CONTROLS.sub("", _ESCAPES.sub("", str(value)))


def safe_text(value: object) -> Text:
    """Return literal terminal-safe text suitable for Rich or Textual."""
    return Text(safe_string(value))


def record_label(record: Mapping[str, Any]) -> str:
    """Choose a readable label without manufacturing a domain identifier."""
    for key in ("label", "name", "event", "uid", "file", "device"):
        if record.get(key) is not None:
            return safe_string(record[key])
    return "Record (identifier not reported)"


def sanitize_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Copy a record while removing environment values and credential fields.

    This is the common display/copy/export boundary. Original input is untouched.
    Payload body values remain available unless their field names identify secrets.
    """

    def visit(value: Any, key: str = "") -> Any:
        if key.casefold() in _SENSITIVE:
            return "[redacted]"
        if key.casefold() in {"environment", "environment_variables"}:
            if isinstance(value, Mapping):
                return {str(name): "[masked]" for name in value}
            return "[masked]"
        if isinstance(value, Mapping):
            return {str(name): visit(item, str(name)) for name, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [visit(item) for item in value]
        return deepcopy(value)

    return visit(record)


def json_text(value: object, limit: int | None = 65_536) -> tuple[Text, bool]:
    """Format parsed JSON, limiting the UTF-8 preview without changing source data."""
    formatted = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    encoded = formatted.encode("utf-8")
    truncated = limit is not None and len(encoded) > limit
    if truncated:
        formatted = (
            encoded[:limit].decode("utf-8", errors="ignore")
            + "\n… Preview limited. Expand to view more."
        )
    text = safe_text(formatted)
    # JSONHighlighter styles Text directly; it never interprets payload markup.
    from rich.highlighter import JSONHighlighter

    return JSONHighlighter()(text), truncated
