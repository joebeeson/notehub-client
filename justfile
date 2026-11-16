set windows-powershell
set dotenv-load

UV_SYNC_FLAGS := env("UV_SYNC_FLAGS", "--all-groups --all-extras")

[group("tool")]
pytest *flags: (run "--group test pytest " + flags)

[group("tool")]
pyrefly *flags="check": (run "--group type pyrefly " + flags)

[group("tool")]
ruff *flags="check": (run "--group lint ruff " + flags)

[group("tool")]
prek *flags="run --all-files": (run "prek " + flags)

[group("venv")]
init: sync (prek "install --prepare-hooks")

[group("venv")]
run *flags:
    uv run {{ flags }}

[group("venv")]
sync *flags=UV_SYNC_FLAGS:
    uv sync {{ flags }}
