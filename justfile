set windows-powershell
set dotenv-load

UV_SYNC_FLAGS := env("UV_SYNC_FLAGS", "--all-groups --all-extras")

# TODO: How might we make these repeated `run "--group [group] <command> [maybe args]" + flags` DRYer?

[group("tool")]
pytest *flags: (run "--group test pytest " + flags)

[group("tool")]
pyrefly *flags="check": (run "--group type pyrefly " + flags)

[group("tool")]
ruff *flags="check": (run "--group lint ruff " + flags)

[group("tool")]
bandit *flags: (run "--group security bandit -c pyproject.toml -r src " + flags)

[group("tool")]
vulture *flags: (run "--group security vulture --config pyproject.toml src tests " + flags)

[group("tool")]
prek *flags="run --all-files": (run "prek " + flags)

[group("venv")]
init: sync (prek "install --prepare-hooks")

[group("venv")]
run *flags: (uv "run " + flags)

[group("venv")]
sync *flags=UV_SYNC_FLAGS: (uv "sync " + flags)

uv *flags:
    uv {{ flags }}