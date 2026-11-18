"""Verify runtime resources in built wheels without importing the checkout."""

from __future__ import annotations

import argparse
import json
from html.parser import HTMLParser
from pathlib import Path
from zipfile import ZipFile

STATIC = "notehub_client/runtimes/web/static/"
MANIFEST = STATIC + "asset-manifest.json"


class DashboardReferences(HTMLParser):
    """Collect local resource URLs referenced by the dashboard shell."""

    def __init__(self) -> None:
        super().__init__()
        self.paths: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Record local script and stylesheet references."""
        if tag not in {"script", "link"}:
            return
        for key, value in attrs:
            if key in {"src", "href"} and value and value.startswith("/dashboard/"):
                self.paths.add(STATIC + value.removeprefix("/dashboard/"))


def check_wheel(path: Path) -> None:
    """Reject wheels missing runtime resources or dashboard build files."""
    required = {
        "notehub_client/py.typed",
        "notehub_client/runtimes/tui/styles.tcss",
        STATIC + "index.html",
        STATIC + "favicon.svg",
        MANIFEST,
        *(
            f"notehub_client/simulate/scenarios/{name}.toml"
            for name in (
                "field_lab",
                "telemetry",
                "commands",
                "environment",
                "sensor",
            )
        ),
    }
    with ZipFile(path) as wheel:
        names = set(wheel.namelist())
        missing = required - names
        if missing:
            raise ValueError(f"{path.name}: missing resources: {', '.join(sorted(missing))}")
        references = DashboardReferences()
        references.feed(wheel.read(STATIC + "index.html").decode("utf-8"))
        if not any(name.endswith(".js") for name in references.paths):
            raise ValueError(f"{path.name}: dashboard shell has no local JavaScript entry point")
        missing = references.paths - names
        if missing:
            raise ValueError(
                f"{path.name}: missing shell dependencies: {', '.join(sorted(missing))}"
            )
        manifest = json.loads(wheel.read(MANIFEST))
        # All Vite manifest entries matter, including chunks loaded after navigation.
        build_files = {
            STATIC + filename
            for entry in manifest.values()
            for filename in (entry["file"], *entry.get("css", ()), *entry.get("assets", ()))
        }
        if missing := build_files - names:
            raise ValueError(
                f"{path.name}: missing dashboard build files: {', '.join(sorted(missing))}"
            )
    print(f"Verified runtime resources: {path}")


def main() -> None:
    """Check every wheel directly inside a build output directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    options = parser.parse_args()
    wheels = sorted(options.directory.glob("*.whl"))
    if not wheels:
        parser.error("directory contains no wheels")
    for wheel in wheels:
        check_wheel(wheel)


if __name__ == "__main__":
    main()
