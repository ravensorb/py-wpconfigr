"""
Command-line interface.

Exit codes are part of the interface: ``0`` success, ``1`` the key is not
defined, ``2`` the operation failed. A key defined as ``false``, ``0`` or ``''``
is present -- it prints its value and exits ``0``, which is what distinguishes
it from an absent key (ADR-0010).
"""

from __future__ import annotations

import argparse
import sys
from logging import basicConfig

from l3io.wp.config.adapters.config_file import WpConfigFile
from l3io.wp.config.domain.errors import WpConfigError
from l3io.wp.config.domain.values import ConfigValue, MissingType

__all__ = ["build_parser", "run"]

EXIT_OK = 0
EXIT_NOT_DEFINED = 1
EXIT_FAILED = 2


def build_parser() -> argparse.ArgumentParser:
    """The argument parser, exposed so tests can derive their scope from it."""
    parser = argparse.ArgumentParser(
        prog="l3io-wp-config",
        description=(
            "Read and write properties in a wp-config.php file. Include --value, "
            "--set-true or --set-false to write; omit them to read."
        ),
    )
    parser.add_argument("--filename", help="wp-config.php filename", required=True)
    parser.add_argument("--key", help="Property key", required=True)
    parser.add_argument("--value", help="New property value", required=False)
    parser.add_argument("--log-level", default="CRITICAL", help="Log level")

    write = parser.add_mutually_exclusive_group()
    write.add_argument("--set-true", action="store_true", help="Set boolean true")
    write.add_argument("--set-false", action="store_true", help="Set boolean false")
    return parser


def _format(value: ConfigValue) -> str:
    """Render for a shell: booleans as PHP spells them, strings unquoted."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def run(argv: list[str] | None = None) -> int:
    """Run the CLI and return its exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.value is not None and (args.set_true or args.set_false):
        parser.error("Cannot combine --value with --set-true or --set-false.")

    basicConfig(level=str(args.log_level).upper())

    new_value: ConfigValue | None = None
    if args.set_true:
        new_value = True
    elif args.set_false:
        new_value = False
    elif args.value is not None:
        new_value = args.value

    try:
        config = WpConfigFile(filename=args.filename)
        if new_value is not None:
            config.set(key=args.key, value=new_value)
            return EXIT_OK

        value = config.get(key=args.key)
        if isinstance(value, MissingType):
            print(f"{args.key} is not defined in {args.filename}", file=sys.stderr)
            return EXIT_NOT_DEFINED
        print(_format(value))
        return EXIT_OK
    except WpConfigError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_FAILED


def main() -> None:  # pragma: no cover - thin console-script shim
    sys.exit(run())
