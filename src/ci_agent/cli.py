"""Operator entry point. No live experiment behavior is implemented yet."""
import os
import sqlite3

import click
from dotenv import load_dotenv


@click.group()
def main():
    """CI improvement agent: setup and diagnostics."""


@main.command()
@click.option("--live", is_flag=True, help="Validate live settings without making network calls.")
def smoke(live):
    """Check local runtime; optionally validate live environment configuration."""
    if live:
        load_dotenv()
        required = ("GITHUB_TOKEN", "CRUSOE_API_KEY", "CRUSOE_BASE_URL", "CRUSOE_MODEL")
        missing = [name for name in required if not os.getenv(name, "").strip()]
        if missing:
            raise click.ClickException("Missing configuration: " + ", ".join(missing))
        click.echo("Live configuration present; network connectivity has not been tested.")
    with sqlite3.connect(":memory:") as connection:
        connection.execute("SELECT 1").fetchone()
    click.echo("Local smoke check passed. Agent workflows are not implemented yet.")
