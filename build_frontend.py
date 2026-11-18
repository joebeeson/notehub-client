"""Build the browser application while producing Python wheels."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

if TYPE_CHECKING:
    from collections.abc import Iterable


def _digest(root: Path, paths: Iterable[Path]) -> str:
    """Fingerprint names and file contents, independent of mtime and iteration order."""
    checksum = hashlib.sha256()
    for path in sorted(paths):
        checksum.update(path.relative_to(root).as_posix().encode("utf-8"))
        checksum.update(b"\0")
        with path.open("rb") as stream:
            checksum.update(hashlib.file_digest(stream, "sha256").digest())
    return checksum.hexdigest()


def _input_digest(root: Path, frontend: Path) -> str:
    inputs = [
        Path(__file__).resolve(),
        *(
            frontend / name
            for name in (
                "index.html",
                "package.json",
                "package-lock.json",
                "tsconfig.json",
                "vite.config.ts",
            )
        ),
    ]
    for name in ("src", "public"):
        inputs.extend(path for path in (frontend / name).rglob("*") if path.is_file())
    return _digest(root, inputs)


def _bundle_digest(static: Path) -> str | None:
    if not all(
        (static / name).is_file() for name in ("index.html", "favicon.svg", "asset-manifest.json")
    ):
        return None
    return _digest(static, (path for path in static.rglob("*") if path.is_file()))


def _read_stamp(stamp: Path) -> list[str]:
    try:
        return stamp.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, UnicodeDecodeError):
        return []


class CustomBuildHook(BuildHookInterface):
    """Generate UI SDK assets for wheels; source archives retain frontend sources."""

    def initialize(self, version: str, build_data: dict[str, object]) -> None:
        """Install locked JS dependencies and bundle the dashboard."""
        if self.target_name != "wheel":
            return
        root = Path(self.root).resolve()
        frontend = root / "frontend"
        static = root / "src" / "notehub_client" / "runtimes" / "web" / "static"
        stamp = frontend / "node_modules" / ".notehub-editable-bundle"
        inputs = None
        if version == "editable":
            inputs = _input_digest(root, frontend)
            previous = _read_stamp(stamp)
            if (
                len(previous) == 2
                and previous[0] == inputs
                and previous[1] == _bundle_digest(static)
            ):
                return
            stamp.unlink(missing_ok=True)

        npm = "npm.cmd" if os.name == "nt" else "npm"
        try:
            subprocess.run([npm, "ci", "--no-audit", "--no-fund"], cwd=frontend, check=True)  # noqa: S603
            subprocess.run([npm, "run", "build"], cwd=frontend, check=True)  # noqa: S603
        except FileNotFoundError as error:
            raise RuntimeError("Building notehub-client requires Node and npm") from error
        if inputs is not None and inputs == _input_digest(root, frontend):
            if (bundle := _bundle_digest(static)) is not None:
                stamp.write_text(f"{inputs}\n{bundle}\n", encoding="utf-8")
