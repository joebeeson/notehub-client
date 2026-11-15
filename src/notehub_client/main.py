"""Runnable entry point for ``python -m notehub_client.main`` and console script."""

from .cli import cli


def main() -> None:
    """Invoke the Click command group."""
    cli()


if __name__ == "__main__":
    main()
