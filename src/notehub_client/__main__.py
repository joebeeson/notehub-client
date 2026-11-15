"""Module entry point for ``python -m notehub_client``."""

from .cli import cli


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
