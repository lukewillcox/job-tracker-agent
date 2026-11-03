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

    # 4. optional search profile (powers the weekly Prospects agent)
    console.print(
        "\n[bold]Prospects[/] (optional): a short profile lets me find new roles for you."
    )
    if click.confirm("  Set up your search profile now?", default=True):
        _edit_profile_interactive()
    else:
        console.print("  [dim]Skipped. Run `jobtracker profile` anytime.[/]")

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
@click.option("--edit", "open_editor", is_flag=True, help="open the profile file in your editor")
def profile(open_editor: bool) -> None:
    """Show or edit your search profile (used to find new roles)."""

    from jobtracker_cli.profile import PROFILE_PATH, Profile

    if open_editor:
        if not PROFILE_PATH.exists():
            Profile().save()  # seed defaults so there's something to edit
        click.edit(filename=str(PROFILE_PATH))
        # validate what they saved; warn but don't crash on a bad edit
        try:
            Profile.load()
        except Exception as exc:  # noqa: BLE001
            console.print(f"[yellow]Profile has an error, please fix:[/] {exc}")
        return

    p = Profile.load()
    if p is None:
        console.print("[yellow]No profile yet.[/] Run `jobtracker profile --edit` or re-run setup.")
        return

    table = Table(title="Search profile")
    table.add_column("")
    table.add_column("")
    table.add_row("programme", p.programme)
    table.add_row("start year", str(p.start_year))
    table.add_row("degrees", ", ".join(p.degrees) or "[dim]-[/]")
    table.add_row("skills", ", ".join(p.skills) or "[dim]-[/]")
    table.add_row("target roles", ", ".join(p.target_roles) or "[dim]-[/]")
    table.add_row("locations", ", ".join(p.locations) or "[dim]-[/]")
    table.add_row("exclude", ", ".join(p.exclude) or "[dim]-[/]")
    console.print(table)
    console.print("[dim]Edit with `jobtracker profile --edit`.[/]")


@cli.command()
@click.option("--quiet", is_flag=True, help="minimal output (used by the scheduler)")
@click.option("--no-fetch", is_flag=True, help="don't fetch pages, use snippets only")
def prospects(quiet: bool, no_fetch: bool) -> None:
    """Find new graduate roles that fit your profile and add them to the tracker."""

    _do_prospects(quiet=quiet, allow_fetch=not no_fetch)


def _do_prospects(quiet: bool, allow_fetch: bool = True) -> None:
    from jobtracker_cli.classify_client import ClassifyApiError
    from jobtracker_cli.profile import Profile
    from jobtracker_cli.prospects import run_prospects
    from jobtracker_cli.prospects_client import ProspectsClient
    from jobtracker_cli.scanner import write_excel

    c = cfg.Config.load()
    code = cfg.get_invite_code()
    if not c.username or not code:
        console.print("[red]Not set up.[/] Run: jobtracker setup --username <you>")
        raise SystemExit(1)

    p = Profile.load()
    if p is None or p.is_empty():
        # Requirement 1.4: skip with a one-line hint, don't error
        if not quiet:
            console.print(
                "[yellow]No search profile yet.[/] Run `jobtracker profile --edit` to "
                "find new roles."
            )
        return

    store = LocalStore()
    # read back any Status edits the user made in the existing workbook first,
    # so "Not for me" sticks and is never re-added (Requirement 6.3/6.4)
    xlsx_path = cfg.CONFIG_DIR / "Job_Applications_Tracker.xlsx"
    if xlsx_path.exists():
        from jobtracker_cli.prospects import apply_status_edits_from_excel

        apply_status_edits_from_excel(store, xlsx_path.read_bytes())

    client = ProspectsClient(c.api_url, code)
    try:
        summary = run_prospects(client, p, store, allow_fetch=allow_fetch)
    except ClassifyApiError as exc:
        if exc.status == 403:
            console.print("[red]Your invite code was rejected or disabled.[/] Ask Luke.")
        elif exc.status == 429:
            console.print("[yellow]Monthly search limit reached.[/] Try again next month.")
        else:
            console.print(f"[red]Prospects API error:[/] {exc.message}")
        raise SystemExit(1) from exc

    c.tokens_in_total += summary.tokens_in
    c.tokens_out_total += summary.tokens_out
    c.last_prospects_at = dt.datetime.now(dt.UTC).isoformat()
    c.save()

    out = cfg.CONFIG_DIR / "Job_Applications_Tracker.xlsx"
    out.write_bytes(write_excel(store))

    if not quiet:
        if summary.capped:
            console.print("[yellow]Monthly search cap reached.[/] No new searches this run.")
        console.print(
            f"[green]Prospects done.[/] searched {summary.searched}, "
            f"{summary.added} new, {summary.skipped_existing} already applied, "
            f"{summary.expired} expired."
        )
        console.print(f"  [dim]queries used this month: {summary.queries_used}[/]")
        console.print(f"  tracker: {out}")


@cli.command()
def status() -> None:
    """Show your tracker summary and your beer tab (from the classify API)."""

    from jobtracker_cli.classify_client import ClassifyClient

    c = cfg.Config.load()
    store = LocalStore()
    apps = store.applications()

    # The tab comes from the server (source of truth; survives reinstalls and
    # matches `jt-admin users`). Fall back gracefully if offline.
    tab_str = "tab unavailable (offline?)"
    emails_str = "-"
    code = cfg.get_invite_code()
    if c.api_url and code:
        try:
            tab = ClassifyClient(c.api_url, code).me()
            tab_str = f"£{tab.tab_gbp:.2f}  ({tab.tab_pints} pints)"
            emails_str = str(tab.emails_classified)
        except Exception:
            pass  # keep the "unavailable" fallback

    table = Table(title="Job Tracker")
    table.add_column("")
    table.add_column("", justify="right")
    table.add_row("username", c.username or "-")
    table.add_row("applications", str(len(apps)))
    table.add_row("emails classified", emails_str)
    table.add_row("scans run", str(c.scan_count))
    table.add_row("last scan", _fmt(c.last_scan_at))
    table.add_row("your tab", tab_str)
    console.print(table)
    console.print("[dim]The tab is Luke's Bedrock cost for your scans. Buy accordingly.[/]")


@cli.command()
def uninstall() -> None:
    """Remove the schedule and local data (Keychain secrets included)."""

    from jobtracker_cli.schedule import remove_schedule

    if click.confirm("Remove schedule, profile, local tracker data and Keychain secrets?"):
        remove_schedule()
        cfg.clear_secrets()
        # removes config.json, data.json, profile.json and the Excel in one go
        if cfg.CONFIG_DIR.exists():
            import shutil

            shutil.rmtree(cfg.CONFIG_DIR, ignore_errors=True)
        console.print("[green]Uninstalled.[/]")
        console.print("[dim]Run `uv tool uninstall jobtracker-cli` to remove the command.[/]")


def _edit_profile_interactive() -> None:
    """Ask the profile questions (each skippable by pressing Enter)."""

    from jobtracker_cli.profile import Profile, profile_from_prompts, profile_to_prompts

    existing = Profile.load() or Profile()
    cur = profile_to_prompts(existing)
    console.print("  [dim]Press Enter to keep the shown default; commas separate lists.[/]")

    answers = dict(cur)
    answers["programme"] = click.prompt(
        "  Programme type", type=click.Choice(["Graduate", "Internship", "Both"]),
        default=cur["programme"], show_choices=True,
    )
    answers["start_year"] = click.prompt("  Start year", default=cur["start_year"])
    answers["degrees"] = click.prompt("  Degree(s)", default=cur["degrees"])
    answers["skills"] = click.prompt("  Skills", default=cur["skills"])
    answers["target_roles"] = click.prompt("  Target roles", default=cur["target_roles"])
    answers["locations"] = click.prompt("  Locations", default=cur["locations"] or "London")
    answers["exclude"] = click.prompt("  Exclude (roles/words)", default=cur["exclude"])

    profile_from_prompts(answers).save()
    console.print("  [green]\u2713[/] profile saved")


def _fmt(iso: str | None) -> str:
    if not iso:
        return "never"
    try:
        return dt.datetime.fromisoformat(iso).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return iso
