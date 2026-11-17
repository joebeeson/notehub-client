"""Build the browser application while producing Python distributions."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    """Bundle UI SDK assets into the wheel and source distribution."""

    def initialize(self, version: str, build_data: dict[str, object]) -> None:
        """Install locked JS dependencies and bundle the dashboard."""
        frontend = Path(self.root) / "frontend"
        npm = "npm.cmd" if os.name == "nt" else "npm"
        try:
            subprocess.run([npm, "ci", "--no-audit", "--no-fund"], cwd=frontend, check=True)  # noqa: S603
            subprocess.run([npm, "run", "build"], cwd=frontend, check=True)  # noqa: S603
        except FileNotFoundError as error:
            raise RuntimeError("Building notehub-client requires Node and npm") from error
