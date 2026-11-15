"""Command-line entry point scaffold; commands will be designed after the API settles."""

import click


@click.group()
@click.version_option(package_name="notehub-client")
def cli() -> None:
    """Work with Blues Notehub from the command line."""


if __name__ == "__main__":
    cli()
