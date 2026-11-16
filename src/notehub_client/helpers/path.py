"""Safe encoding for Notehub path segments."""

from __future__ import annotations

from urllib.parse import quote

__all__ = ["encode_path_segments"]


def encode_path_segments(*segments: str) -> str:
    """Encode path segments and join them with ``/``.

    Colons remain unescaped for Notehub identifiers. Slashes and other reserved
    characters inside a segment are percent-encoded. Empty and dot segments
    are rejected to prevent ambiguous paths.
    """
    if any(not segment or segment in {".", ".."} for segment in segments):
        raise ValueError("Path segments must be nonempty and cannot be dot segments")
    return "/".join(quote(segment, safe=":") for segment in segments)
