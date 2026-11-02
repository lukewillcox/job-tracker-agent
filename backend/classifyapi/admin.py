"""jt-admin: manage invite codes and see each friend's spend (beer tab).

Run by the host against the live codes table (uses the host's AWS credentials).

    jt-admin add <username>        create a user, print their one-time code
    jt-admin disable <username>    revoke a user's code
    jt-admin users                 table of usage + the beer tab, with a total

Env:
    CODES_TABLE   DynamoDB codes table (default JobTrackerCodes-dev)
    AWS_PROFILE / AWS_REGION as usual
Pricing overrides: CLASSIFY_INPUT_USD_PER_MTOK, CLASSIFY_OUTPUT_USD_PER_MTOK,
USD_TO_GBP, PINT_GBP (see billing.py).
"""

from __future__ import annotations

import argparse
import os
import sys

import boto3

from classifyapi.billing import beers, cost_gbp
from classifyapi.codes import new_code, normalise_username
from classifyapi.store import CodeStore


def _store() -> CodeStore:
    table_name = os.environ.get("CODES_TABLE", "JobTrackerCodes-dev")
    region = os.environ.get("AWS_REGION", "eu-north-1")
    table = boto3.resource("dynamodb", region_name=region).Table(table_name)
    return CodeStore(table)


def cmd_add(args: argparse.Namespace) -> int:
    store = _store()
    username = normalise_username(args.username)
    if store.get_code(username) is not None:
        print(f"user '{username}' already exists (use 'disable' then a new name)", file=sys.stderr)
        return 1
    code, raw = new_code(
        args.username,
        daily_request_cap=args.request_cap,
        daily_token_cap=args.token_cap,
    )
    store.put_code(code)
    print(f"\nCreated user '{username}'.")
    print("Give them this one-time invite code (it is not stored and can't be shown again):\n")
    print(f"    {raw}\n")
    print(f"They run:  jobtracker setup --username {username}")
    print(f"caps/day: {code.daily_request_cap} emails, {code.daily_token_cap:,} tokens")
    return 0


def cmd_disable(args: argparse.Namespace) -> int:
    store = _store()
    username = normalise_username(args.username)
    if store.revoke_code(username):
        print(f"disabled '{username}'.")
        return 0
    print(f"nothing to do: '{username}' not found or already disabled", file=sys.stderr)
    return 1


def cmd_users(_args: argparse.Namespace) -> int:
    store = _store()
    codes = sorted(store.list_codes(), key=lambda c: c.code_id)
    rows = []
    tot_req = tot_in = tot_out = 0
    for c in codes:
        usage = store.list_usage(c.code_id)
        req = sum(u.requests for u in usage)
        tin = sum(u.input_tokens for u in usage)
        tout = sum(u.output_tokens for u in usage)
        last = max((u.day for u in usage), default="-")
        tot_req += req
        tot_in += tin
        tot_out += tout
        gbp = cost_gbp(tin, tout)
        status = "on" if c.active else "off"
        rows.append((c.code_id, status, last, req, f"£{gbp:.2f}", f"{beers(gbp)}"))

    _print_table(
        ["user", "status", "last day", "emails", "tab (£)", "tab (pints)"],
        rows,
    )
    total_gbp = cost_gbp(tot_in, tot_out)
    print("-" * 64)
    print(
        f"{'TOTAL':20} {'':6} {'':10} {tot_req:>7}  £{total_gbp:>7.2f}  "
        f"{beers(total_gbp)} pints"
    )
    return 0


def _print_table(headers: list[str], rows: list[tuple]) -> None:
    widths = [max(len(str(h)), *(len(str(r[i])) for r in rows)) if rows else len(str(h))
              for i, h in enumerate(headers)]
    line = "  ".join(str(h).ljust(widths[i]) for i, h in enumerate(headers))
    print(line)
    print("  ".join("-" * widths[i] for i in range(len(headers))))
    for r in rows:
        print("  ".join(str(c).ljust(widths[i]) for i, c in enumerate(r)))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jt-admin", description="Manage Job Tracker invite codes")
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("add", help="create a user and print their invite code")
    a.add_argument("username")
    a.add_argument("--request-cap", type=int, default=5_000,
                   help="daily email backstop (hidden; friends don't see it)")
    a.add_argument("--token-cap", type=int, default=20_000_000,
                   help="daily token backstop (host emailed at 50%%)")
    a.set_defaults(func=cmd_add)

    d = sub.add_parser("disable", help="revoke a user's code")
    d.add_argument("username")
    d.set_defaults(func=cmd_disable)

    u = sub.add_parser("users", help="usage + beer tab per user")
    u.set_defaults(func=cmd_users)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    func = args.func
    result: int = func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
