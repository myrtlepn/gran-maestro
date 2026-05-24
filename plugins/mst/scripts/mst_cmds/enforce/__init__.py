from __future__ import annotations

from scripts.mst_cmds.enforce.verify import cmd_enforce_verify

__all__ = ["register"]


def register(subparsers):
    enforce = subparsers.add_parser("enforce")
    enforce_sub = enforce.add_subparsers(dest="subcommand")

    verify = enforce_sub.add_parser("verify")
    verify.add_argument("--strict", action="store_true")
    verify.add_argument("--tree")
    verify.add_argument("--json", action="store_true")
