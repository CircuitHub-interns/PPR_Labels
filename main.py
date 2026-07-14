"""One-shot PPR minting — create a serial and print its label together.

There is no upstream PPR serial to look up: this tool MINTS the identity,
exactly like uniplex.nozzle ids are human-assigned at labeling time. The
printed code is the unit's permanent, slot-independent serial.

Usage:
  python main.py --print                    # mint next free serial, print it
  python main.py --print PR07               # mint (or reprint) a specific serial
  python main.py --print --by Jonathan --note "spare from bin 4"

Deliberately out of scope: recording which gantry/head slot a unit sits in.
That binding is a Grid-side scan event (head.current_ppr_id, like nozzle
scanSlot) — a PPR in a drawer is still PR07. Use ppr_tracker.py for
list / retire / report.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ppr_labels import label_pdf, label_svg
from ppr_tracker import canon, next_code, register_print


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Mint a PPR serial and print its label in one command."
    )
    parser.add_argument("--print", dest="code", nargs="?", const="", default=None,
                        metavar="CODE",
                        help="serial to mint/reprint (e.g. PR07); "
                             "omit the value to mint the next free one")
    parser.add_argument("--by", help="who minted it")
    parser.add_argument("--note", help="anything else worth recording")
    parser.add_argument("-o", "--out", default="labels",
                        help="output directory (default: labels)")
    # Slot binding is not this tool's job — fail loudly with the reason.
    parser.add_argument("--assign", "--gantry", "--head", dest="slot",
                        help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.slot:
        parser.error(
            "serials are slot-independent, so minting never records a slot; "
            "after the unit is installed, record it with: "
            "python ppr_tracker.py attach PR07 G1H2"
        )
    if args.code is None:
        parser.error("--print is required (with or without a CODE)")

    try:
        code = canon(args.code) if args.code else next_code()
    except ValueError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    try:
        svg_path = out / f"{code}.svg"
        svg_path.write_text(label_svg(code), encoding="utf-8")
        print(f"wrote {svg_path}")
        pdf_path = out / f"{code}.pdf"
        label_pdf(code, pdf_path)
        print(f"wrote {pdf_path}")
    except ValueError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1

    minted = register_print(code, by=args.by, note=args.note)
    print(f"{code} {'minted' if minted else 'reprinted'}"
          + (f" by {args.by}" if minted and args.by else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
