"""`jobtracker` CLI: setup, scan, status, uninstall.

Everything runs locally except classification, which calls the host's shared API
using the invite code stored in the macOS Keychain.
"""

from __future__ import annotations

import datetime as dt

import click
from rich.console import Console
from rich.table import Table

from jobtracker_cli import config as cfg
from jobtracker_cli.localstore import LocalStore

console = Console()

# The host's shared classify API base URL. Baked in so friends don't have to
# know it; overridable at setup with --api-url.
DEFAULT_API_URL = "https://2f7gbt4jei.execute-api.eu-north-1.amazonaws.com"


@click.group()
@click.version_option()
def cli() -> None:
    """Job Tracker — keep an always-up-to-date tracker of your applications."""


@cli.command()
@click.option("--username", required=True, help="the username Luke gave you")
@click.option("--email", default="", help="your email (optional label)")
@click.option("--api-url", default=DEFAULT_API_URL, help="classify API (advanced)")
@click.option("--schedule", type=click.Choice(["daily", "every_2_days", "weekly", "off"]),
              default="every_2_days")
def setup(username: str, email: str, api_url: str, schedule: str) -> None:
    """Sign in to Microsoft, save your invite code, and schedule scans."""

    from jobtracker_cli.ms_auth import device_code_sign_in
    from jobtracker_cli.schedule import install_schedule, is_macos

    c = cfg.Config.load()
    c.username = username.strip()
    c.email = email
    c.api_url = api_url
    c.schedule = schedule

    # 1. invite code -> Keychain
    code = click.prompt("Paste your invite code", hide_input=True).strip()
    cfg.set_invite_code(code)
    console.print("  [green]\u2713[/] invite code saved to the macOS Keychain")

    # 2. Microsoft device-code sign-in
    console.print("\n[bold]Sign in to Microsoft[/] (read-only mail access):")
    refresh = device_code_sign_in(prompt=lambda m: console.print(f"  [cyan]{m}[/]"))
    cfg.set_refresh_token(refresh)
    console.print("  [green]\u2713[/] signed in; token saved to the Keychain")

    c.save()

    # 3. schedule
    if schedule != "off" and install_schedule(schedule):
        console.print(f"  [green]\u2713[/] auto-scan scheduled ({schedule.replace('_', ' ')})")
    elif schedule != "off" and not is_macos():
        console.print("  [yellow]![/] auto-scan is macOS-only; run `jobtracker scan` yourself")

    console.print("\n[bold green]Setup complete.[/] Running your first scan...\n")
    _do_scan(quiet=False)


@cli.command()
@click.option("--quiet", is_flag=True, help="minimal output (used by the scheduler)")
def scan(quiet: bool) -> None:
    """Scan your mailbox now and update the tracker."""

    _do_scan(quiet=quiet)


def _do_scan(quiet: bool) -> None:
    from jobtracker_cli.classify_client import ClassifyApiError
    from jobtracker_cli.scanner import run_scan, write_excel

    c = cfg.Config.load()
    code = cfg.get_invite_code()
    if not c.username or not code:
        console.print("[red]Not set up.[/] Run: jobtracker setup --username <you>")
        raise SystemExit(1)

    store = LocalStore()
    try:
        summary = run_scan(c, code, store)
    except ClassifyApiError as exc:
        if exc.status == 403:
            console.print("[red]Your invite code was rejected or disabled.[/] Ask Luke.")
        elif exc.status == 429:
            console.print("[yellow]Daily limit reached.[/] Try again tomorrow.")
        else:
            console.print(f"[red]Classify API error:[/] {exc.message}")
        raise SystemExit(1) from exc

    # persist usage for the local beer tab
    c.scan_count += 1
    c.tokens_in_total += summary.tokens_in
    c.tokens_out_total += summary.tokens_out
    c.save()

    # write the Excel locally (OneDrive upload is a later enhancement)
    out = cfg.CONFIG_DIR / "Job_Applications_Tracker.xlsx"
    out.write_bytes(write_excel(store))

    if not quiet:
        console.print(
            f"[green]Scan done.[/] read {summary.read}, classified {summary.classified}, "
            f"{summary.new_apps} new, {summary.status_changes} updated."
        )
        if summary.capped:
            console.print(f"  [yellow]{summary.capped} left for next time (daily cap).[/]")
        console.print(f"  tracker: {out}")


@cli.command()
def status() -> None:
    """Show your tracker summary and your beer tab."""

    from jobtracker_cli.billing import beers, cost_gbp

    c = cfg.Config.load()
    store = LocalStore()
    apps = store.applications()
    gbp = cost_gbp(c.tokens_in_total, c.tokens_out_total)

    table = Table(title="Job Tracker")
    table.add_column("")
    table.add_column("", justify="right")
    table.add_row("username", c.username or "-")
    table.add_row("applications", str(len(apps)))
    table.add_row("scans run", str(c.scan_count))
    table.add_row("last scan", _fmt(c.last_scan_at))
    table.add_row("your tab", f"£{gbp:.2f}  ({beers(gbp)} pints)")
    console.print(table)
    console.print("[dim]The tab is Luke's Bedrock cost for your scans. Buy accordingly.[/]")


@cli.command()
def uninstall() -> None:
    """Remove the schedule and local data (Keychain secrets included)."""

    from jobtracker_cli.schedule import remove_schedule

    if click.confirm("Remove schedule, local tracker data and Keychain secrets?"):
        remove_schedule()
        cfg.clear_secrets()
        if cfg.CONFIG_DIR.exists():
            import shutil

            shutil.rmtree(cfg.CONFIG_DIR, ignore_errors=True)
        console.print("[green]Uninstalled.[/]")
        console.print("[dim]Run `uv tool uninstall jobtracker-cli` to remove the command.[/]")


def _fmt(iso: str | None) -> str:
    if not iso:
        return "never"
    try:
        return dt.datetime.fromisoformat(iso).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return iso
