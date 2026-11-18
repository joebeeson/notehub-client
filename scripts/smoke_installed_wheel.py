"""Serve the dashboard and run a bundled simulation from an installed wheel."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
from importlib.metadata import distribution
from pathlib import Path
from tempfile import TemporaryDirectory


async def _smoke(wheel_uri: str) -> None:
    # The isolated interpreter is already running. The runtime has no Node or PAT.
    os.environ["PATH"] = ""
    os.environ.pop("NOTEHUB_TOKEN", None)

    import httpx

    import notehub_client
    from notehub_client.runtimes.api import create_app

    package_init = Path(notehub_client.__file__).resolve()
    installed = distribution("notehub-client")
    origin = json.loads(installed.read_text("direct_url.json") or "{}")
    if (
        origin.get("url") != wheel_uri
        or package_init != installed.locate_file("notehub_client/__init__.py").resolve()
    ):
        raise RuntimeError("Smoke check must import the requested wheel distribution")
    static = package_init.parent / "runtimes" / "web" / "static"
    manifest = json.loads((static / "asset-manifest.json").read_bytes())
    entry = manifest["index.html"]["file"]
    asset_url = f"/dashboard/{entry}"

    app = create_app(dashboard=True)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as client,
    ):
        shell = (await client.get("/dashboard")).raise_for_status()
        if asset_url not in shell.text:
            raise RuntimeError("Dashboard shell does not reference the bundled entry point")
        asset = (await client.get(asset_url)).raise_for_status()
        if not asset.content or asset.content != (static / entry).read_bytes():
            raise RuntimeError("Dashboard did not serve the packaged entry point")

        (
            await client.post(
                "/api/session/bootstrap", headers={"X-Launch-Secret": app.state.bootstrap_secret}
            )
        ).raise_for_status()
        run = (
            await client.post("/api/simulation/start", json={"name": "sensor"})
        ).raise_for_status()
        project = run.json()["projects"][0]["uid"]
        devices = (await client.get(f"/api/projects/{project}/devices")).raise_for_status()
        if not devices.json()["devices"]:
            raise RuntimeError("Packaged sensor simulation did not expose its devices")


def main() -> None:
    """Run the smoke check against exactly one wheel in a disposable environment."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="directory containing exactly one wheel")
    options = parser.parse_args()
    wheels = list(options.directory.glob("*.whl"))
    if len(wheels) != 1:
        parser.error("directory must contain exactly one wheel")
    uv = shutil.which("uv")
    if uv is None:
        parser.error("uv is required to install the wheel")

    script = Path(__file__).resolve()
    wheel_uri = wheels[0].resolve().as_uri()
    requirement = f"notehub-client[web] @ {wheel_uri}"
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    with TemporaryDirectory(prefix="notehub-wheel-smoke-") as directory:
        subprocess.run(  # noqa: S603
            [
                uv,
                "run",
                "--isolated",
                "--no-project",
                "--python",
                python_version,
                "--with",
                requirement,
                "python",
                "-I",
                str(script),
                "--installed",
                wheel_uri,
            ],
            cwd=directory,
            check=True,
        )
    print(f"Verified installed dashboard and simulation: {wheels[0]}")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--installed":
        asyncio.run(_smoke(sys.argv[2]))
    else:
        main()
