#!/usr/bin/env python3
"""Count characters in Proscenium prompt strings and enforce the 1000 limit."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


LIMIT = 1000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Count each prompt exactly as Python/Blender sees the string."
    )
    parser.add_argument("prompts", nargs="*", help="One or more literal prompt strings")
    parser.add_argument(
        "--file",
        type=Path,
        help="UTF-8 text file containing one literal prompt per non-empty line",
    )
    return parser.parse_args()


def collect_prompts(args: argparse.Namespace) -> list[str]:
    prompts = list(args.prompts)
    if args.file:
        prompts.extend(
            line.strip("\r\n")
            for line in args.file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    if not prompts and not sys.stdin.isatty():
        value = sys.stdin.read().strip("\r\n")
        if value:
            prompts.append(value)
    return prompts


def main() -> int:
    args = parse_args()
    prompts = collect_prompts(args)
    if not prompts:
        print("No prompt supplied.", file=sys.stderr)
        return 2

    over_limit = False
    for index, prompt in enumerate(prompts, start=1):
        count = len(prompt)
        status = "OK" if count <= LIMIT else "OVER_LIMIT"
        print(f"{index}: {count}/{LIMIT} {status}")
        over_limit |= count > LIMIT
    return 1 if over_limit else 0


if __name__ == "__main__":
    raise SystemExit(main())
