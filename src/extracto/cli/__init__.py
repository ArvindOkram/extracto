"""Command-line interface. Commands stay thin and only call services."""

from __future__ import annotations

import logging
from typing import Annotated

import typer

from extracto import __version__
from extracto.adapters.storage.backup import backup_sqlite, prune_backups
from extracto.adapters.storage.migrate import upgrade_to_head
from extracto.bootstrap import build_notifier, build_run_service
from extracto.config import ConfigError, load_config
from extracto.domain.models import Notification
from extracto.interfaces import NotificationError, Notifier
from extracto.logging import configure_logging
from extracto.services.notification_service import (
    connectivity_check,
    deliver,
    run_failed,
    run_summary,
)
from extracto.settings import Settings

log = logging.getLogger(__name__)

app = typer.Typer(
    name="extracto",
    help="Crawl configured websites, detect changes, and report them.",
    no_args_is_help=True,
    add_completion=False,
)


def _not_implemented(command: str) -> None:
    typer.echo(f"{command}: not implemented", err=True)
    raise typer.Exit(code=1)


def _version(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    log_level: Annotated[str, typer.Option(help="Log level.")] = "INFO",
    log_format: Annotated[str, typer.Option(help="Log format: kv or json.")] = "kv",
    version: Annotated[
        bool, typer.Option("--version", callback=_version, is_eager=True, help="Show version.")
    ] = False,
) -> None:
    configure_logging(log_level, log_format)


@app.command("init-db")
def init_db() -> None:
    """Create or upgrade the database schema (safe to run repeatedly)."""
    settings = Settings()
    upgrade_to_head(settings.resolved_database_url)
    typer.echo("database ready")


@app.command()
def backup(
    keep: Annotated[int, typer.Option(help="Number of backups to keep.")] = 30,
) -> None:
    """Write a compressed, consistent copy of the SQLite database to DATA_DIR/backups."""
    settings = Settings()
    try:
        path = backup_sqlite(settings.resolved_database_url, settings.backup_dir)
    except FileNotFoundError:
        typer.echo("no database found; run `extracto init-db` first", err=True)
        raise typer.Exit(code=1) from None
    prune_backups(settings.backup_dir, keep)
    typer.echo(f"backup written: {path}")


@app.command()
def run(
    site: Annotated[str | None, typer.Option(help="Crawl only this site.")] = None,
    dry_run: Annotated[bool, typer.Option(help="Crawl and print, no DB writes.")] = False,
) -> None:
    """Crawl all configured sites (or one)."""
    settings = Settings()
    try:
        config = load_config(settings.sites_config)
        sites = [config.site(site)] if site else config.sites
    except ConfigError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None

    notifier = None if dry_run else _notifier_or_warn(settings)
    try:
        outcome = build_run_service(settings, dry_run=dry_run).run(sites, dry_run=dry_run)
    except Exception as exc:
        _notify(notifier, run_failed(exc))
        raise

    for result in outcome.results:
        if dry_run:
            typer.echo(f"[dry run] {result.site}")
            for page in result.pages:
                title = f'"{page.title}"' if page.title else "-"
                short = " SHORT" if page.short_text else ""
                typer.echo(
                    f"  {page.status_code or '---'} {page.outcome:<14} {page.url}  {title}"
                    f" ({page.chars} chars){short}"
                )
        typer.echo(
            f"{result.site}: {result.pages_crawled} pages, {result.new_snapshots} new snapshots, "
            f"{result.errors} errors, {result.skipped_robots} skipped by robots.txt "
            f"({result.duration_s:.1f}s)"
        )
    if outcome.run_id is not None:
        typer.echo(f"run {outcome.run_id} completed")
    _notify(notifier, run_summary(outcome))


@app.command("notify-test")
def notify_test() -> None:
    """Send a test message to the configured Discord webhook."""
    try:
        notifier = build_notifier(Settings())
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None
    if notifier is None:
        typer.echo("DISCORD_WEBHOOK_URL is not set (see .env.example)", err=True)
        raise typer.Exit(code=1)
    try:
        notifier.send(connectivity_check())
    except NotificationError as exc:
        typer.echo(f"notification failed: {exc}", err=True)
        raise typer.Exit(code=1) from None
    finally:
        notifier.close()
    typer.echo("test notification sent")


def _notifier_or_warn(settings: Settings) -> Notifier | None:
    try:
        return build_notifier(settings)
    except ValueError as exc:
        typer.echo(f"notifications disabled: {exc}", err=True)
        return None


def _notify(notifier: Notifier | None, notification: Notification) -> None:
    """Deliver a notification; a delivery failure never fails the run."""
    error = deliver(notifier, notification)
    if error:
        typer.echo(f"notification failed: {error}", err=True)


LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


@app.command()
def serve(
    host: Annotated[
        str, typer.Option(help="Interface to bind. Keep local unless you set a key.")
    ] = "127.0.0.1",
    port: Annotated[int, typer.Option(envvar="PORT", help="Port to listen on.")] = 8000,
) -> None:
    """Run the HTTP API (interactive docs at /docs). Needs: pip install -e ".[api]"."""
    try:
        import uvicorn

        from extracto.api.app import create_app
    except ImportError:
        typer.echo('the API needs extra packages: pip install -e ".[api]"', err=True)
        raise typer.Exit(code=1) from None

    settings = Settings()
    if host not in LOCAL_HOSTS and settings.api_key is None:
        typer.echo(
            f"refusing to listen on {host} without EXTRACTO_API_KEY set; anyone on the network "
            "could make this machine fetch URLs. Set it in .env or use --host 127.0.0.1.",
            err=True,
        )
        raise typer.Exit(code=1)
    typer.echo(f"Extracto API on http://{host}:{port}  (try it: http://{host}:{port}/docs)")
    uvicorn.run(create_app(settings), host=host, port=port, log_config=None)


@app.command()
def report(
    run_id: Annotated[int | None, typer.Option(help="Run to report on (default: latest).")] = None,
    send: Annotated[bool, typer.Option(help="Deliver via email/Slack.")] = False,
) -> None:
    """Build (and optionally send) the report for a run."""
    _not_implemented("report")


@app.command()
def health() -> None:
    """Show the last run's health per site."""
    _not_implemented("health")
