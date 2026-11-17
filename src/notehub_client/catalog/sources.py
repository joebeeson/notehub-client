"""Optional fsspec loading of explicitly selected catalog sources."""

from __future__ import annotations

import posixpath
from typing import Any

from ..errors import NotehubDependencyError
from .loading import loads
from .models import Catalog, CatalogError


def load_sources(*sources: str, storage_options: dict[str, Any] | None = None) -> Catalog:
    """Layer TOML files, directories, or globs in source order and sorted file order.

    Directory sources select immediate ``*.toml`` children. Each source may use
    a different protocol; document paths are relative to their TOML artifact.
    """
    try:
        from fsspec.core import url_to_fs
    except ImportError as error:
        raise NotehubDependencyError("remote catalogs", "fsspec", "fsspec") from error
    catalog = Catalog()
    try:
        for source in sources:
            fs, path = url_to_fs(source, **(storage_options or {}))
            if fs.isdir(path):
                paths = sorted(fs.glob(posixpath.join(path, "*.toml")))
            elif any(char in path for char in "*?["):
                paths = sorted(fs.glob(path))
            else:
                paths = [path]
            if not paths:
                raise CatalogError("load", "catalog source matched no artifacts")
            for name in paths:

                def read_document(relative: str) -> str:
                    if "://" in relative:
                        raise ValueError("companion references must be relative paths")
                    with fs.open(
                        posixpath.join(posixpath.dirname(name), relative), "rt", encoding="utf-8"
                    ) as stream:
                        return stream.read()

                with fs.open(name, "rt", encoding="utf-8") as stream:
                    layer = loads(stream.read(), read_document=read_document)
                catalog = catalog.overlay(layer)
        return catalog
    except (CatalogError, NotehubDependencyError):
        raise
    except Exception as error:
        raise CatalogError("load", "cannot read catalog source") from error
