"""Private validation and value-location helpers for composed inputs."""

__all__ = ["mapping_path", "require_identifier"]


def require_identifier(value: object, name: str) -> str:
    """Return a nonempty path identifier or raise ``ValueError``."""
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must resolve to a nonempty string")
    return value


def mapping_path(path: str, key: str) -> str:
    """Append one mapping key to a diagnostic JSON-style value path."""
    escaped = key.replace("\\", "\\\\").replace('"', '\\"')
    return f'{path}["{escaped}"]'
