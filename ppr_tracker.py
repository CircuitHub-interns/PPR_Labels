"""PPR unit ledger — Circuit Hub PR series.

Owns ppr_registry.json, the local record of every physical PPR unit this
tool has minted a serial for. Modeled on uniplex.nozzle (shipped June 2026):

  - The printed code IS the identity: human-assigned, slot-independent,
    travels with the physical unit forever (like nozzle.id). It does NOT
    encode gantry/head — a PPR in a drawer is still PR07.
  - minted_at mirrors the lower bound of nozzle.validity (the "birth date");
    retired_at mirrors closing the range when the unit dies.
  - attach/detach record where a unit CURRENTLY sits (G1..G3, optionally a
    head H1..Hn). The serial never changes when the unit moves — location is
    a mutable field on the entry, not part of the identity. Grid's scan
    event (head.current_ppr_id) remains the authoritative machine-side
    binding; this is the local mirror of it.

Registry entry shape (one per PR code):
  {
    "minted_at":    "2026-07-06T14:02:11",   # birth date (validity lower bound)
    "minted_by":    "Jonathan" | null,
    "reprints":     0,                        # times re-printed after minting
    "retired_at":   null | "2027-01-15T09:00:00",  # unit dead (range closed)
    "location":     null | "G1" | "G1H2",     # where it sits right now
    "attached_at":  null | "2026-07-13T09:00:00",  # when it got there
    "attached_by":  "Jonathan" | null,        # who attached it
    "note":         "replacement unit" | null
  }

Usage:
  python ppr_tracker.py list
  python ppr_tracker.py attach PR01 G1 --by Jonathan   # unit installed on gantry 1
  python ppr_tracker.py attach PR01 G1H2               # ... specifically head 2
  python ppr_tracker.py detach PR01                    # back in the drawer
  python ppr_tracker.py relocate PR01 PR03-PR05 --to G2   # mass location fix
  python ppr_tracker.py credit PR01-PR05 --by Jonathan    # fix who, forgot at attach time
  python ppr_tracker.py retire PR03 --note "force sensor drift"
  python ppr_tracker.py unretire PR03                  # undo a mistake
  python ppr_tracker.py delete PR03 PR04               # erase bad labels entirely
  python ppr_tracker.py report                         # copy-paste summary
  python ppr_tracker.py report --md report.md          # also write a markdown table

retire vs delete: retire closes a real unit's validity range and keeps its
history; delete is for labels that should never have existed ("bad PPR
labels") — it erases the registry entry AND the generated label files, and
the number becomes mintable again.

attach refuses if the serial is already attached somewhere else (mirrors
lens_tracker's assign) — run detach first if it moved. relocate/credit are
the bulk escape hatches for already-attached units: relocate mass-fixes just
the location (leaving who/when alone), credit mass-fixes attached_by/note
(leaving location alone) for when --by got skipped at attach time.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

REGISTRY_PATH = Path(__file__).parent / "ppr_registry.json"

# Accepts "PR07", "pr7", or bare "7" -> canonical "PR07".
_CODE_RE = re.compile(r"^(?:PR)?(\d{1,2})$", re.IGNORECASE)

# Locations: gantry G1-G3, optionally a specific head. Head counts per gantry.
_LOC_RE = re.compile(r"^G([1-3])(?:H(\d{1,2}))?$", re.IGNORECASE)
HEADS = {1: 2, 2: 4, 3: 6}


def canon(code: str) -> str:
    """Normalize a PR code to canonical PRnn form, or raise ValueError."""
    m = _CODE_RE.match(code.strip())
    if not m or int(m.group(1)) == 0:
        raise ValueError(
            f"{code!r} is not a valid PR code (PR01-PR99; 10x10 DataMatrix "
            f"holds 3 codewords = PR + 2 digits)"
        )
    return f"PR{int(m.group(1)):02d}"


def canon_location(loc: str) -> str:
    """Normalize a location to G<n> or G<n>H<m>, or raise ValueError."""
    m = _LOC_RE.match(loc.strip())
    if not m:
        raise ValueError(
            f"{loc!r} is not a valid location (G1, G2, G3, or a head like G1H2)"
        )
    g = int(m.group(1))
    if m.group(2) is None:
        return f"G{g}"
    h = int(m.group(2))
    if not 1 <= h <= HEADS[g]:
        raise ValueError(f"G{g} has heads H1-H{HEADS[g]}, got H{h}")
    return f"G{g}H{h}"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def load_registry() -> dict:
    if REGISTRY_PATH.exists():
        return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    return {}


def save_registry(reg: dict) -> None:
    REGISTRY_PATH.write_text(
        json.dumps(reg, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def next_code(reg: dict | None = None) -> str:
    """Lowest unused PR number — the mint-next behaviour."""
    if reg is None:
        reg = load_registry()
    for n in range(1, 100):
        if f"PR{n:02d}" not in reg:
            return f"PR{n:02d}"
    raise ValueError("all 99 PR codes are minted; time for a bigger symbol")


def register_print(code: str, by: str | None = None, note: str | None = None) -> bool:
    """Log a print. Returns True if this minted a new unit, False on reprint."""
    reg = load_registry()
    if code in reg:
        reg[code]["reprints"] = reg[code].get("reprints", 0) + 1
        save_registry(reg)
        return False
    reg[code] = {
        "minted_at": _now(),
        "minted_by": by,
        "reprints": 0,
        "retired_at": None,
        "location": None,
        "attached_at": None,
        "attached_by": None,
        "note": note,
    }
    save_registry(reg)
    return True


# ---------------------------------------------------------------- commands
def cmd_attach(args: argparse.Namespace) -> int:
    reg = load_registry()
    code = canon(args.code)
    if args.location is None:
        print(
            "error: location required — pass it positionally "
            "(attach PR01 G3) or with --location (attach PR01 --location G3).",
            file=sys.stderr,
        )
        return 1
    loc = canon_location(args.location)
    if code not in reg:
        print(f"error: {code} was never minted.", file=sys.stderr)
        return 1
    if reg[code].get("retired_at"):
        print(f"error: {code} is retired — unretire it first if it's back in "
              f"service.", file=sys.stderr)
        return 1
    if reg[code].get("location"):
        print(
            f"error: {code} is already attached to {reg[code]['location']}"
            + (f" (since {reg[code]['attached_at']})" if reg[code].get("attached_at") else "")
            + f". Run 'detach {code}' first if it moved.",
            file=sys.stderr,
        )
        return 1
    # A specific head holds one unit; a bare gantry can hold several.
    if "H" in loc:
        occupant = next(
            (c for c, e in reg.items()
             if c != code and e.get("location") == loc and not e["retired_at"]),
            None,
        )
        if occupant:
            print(f"error: {loc} already holds {occupant} — detach it first "
                  f"(python ppr_tracker.py detach {occupant}).", file=sys.stderr)
            return 1
    reg[code]["location"] = loc
    reg[code]["attached_at"] = _now()
    reg[code]["attached_by"] = args.by
    save_registry(reg)
    line = f"{code} attached to {loc}"
    if args.by:
        line += f" (by {args.by})"
    print(line)
    return 0


def cmd_detach(args: argparse.Namespace) -> int:
    reg = load_registry()
    code = canon(args.code)
    if code not in reg or not reg[code].get("location"):
        print(f"error: {code} is not attached anywhere.", file=sys.stderr)
        return 1
    was = reg[code]["location"]
    reg[code]["location"] = None
    reg[code]["attached_at"] = None
    reg[code]["attached_by"] = None
    save_registry(reg)
    print(f"{code} detached from {was} (back in the drawer)")
    return 0


_RANGE_RE = re.compile(r"^(?:PR)?(\d{1,2})-(?:PR)?(\d{1,2})$", re.IGNORECASE)


def _expand_codes(tokens: list[str]) -> list[str]:
    """Expand serials and ranges: ['PR01', 'PR03-PR05'] -> PR01, PR03, PR04, PR05."""
    codes = []
    for tok in tokens:
        m = _RANGE_RE.match(tok.strip())
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            if lo == 0 or hi == 0:
                raise ValueError(f"range {tok!r} includes PR00, which doesn't exist")
            if lo > hi:
                raise ValueError(f"range {tok!r} runs backwards")
            codes += [f"PR{n:02d}" for n in range(lo, hi + 1)]
        else:
            codes.append(canon(tok))
    return codes


def _validate_attached_codes(reg: dict, codes: list[str]) -> tuple[list[str], list[str]]:
    """Split codes into (missing, not_attached) — empty of both means every
    code is a valid, currently-attached entry."""
    missing = [c for c in codes if c not in reg]
    not_attached = [c for c in codes if c in reg and not reg[c].get("location")]
    return missing, not_attached


def _report_attached_code_errors(missing: list[str], not_attached: list[str]) -> None:
    if missing:
        print(f"error: never minted: {', '.join(missing)}", file=sys.stderr)
    if not_attached:
        print(
            f"error: not currently attached (use 'attach' instead): "
            f"{', '.join(not_attached)}",
            file=sys.stderr,
        )
    print("no changes made.", file=sys.stderr)


def cmd_relocate(args: argparse.Namespace) -> int:
    reg = load_registry()
    codes = _expand_codes(args.codes)
    to = canon_location(args.to)

    missing, not_attached = _validate_attached_codes(reg, codes)
    if missing or not_attached:
        _report_attached_code_errors(missing, not_attached)
        return 1

    if "H" in to:
        if len(codes) > 1:
            print(f"error: {to} is a single head — relocate one unit at a "
                  f"time.", file=sys.stderr)
            return 1
        occupant = next(
            (c for c, e in reg.items()
             if c not in codes and e.get("location") == to and not e["retired_at"]),
            None,
        )
        if occupant:
            print(f"error: {to} already holds {occupant} — detach it first.",
                  file=sys.stderr)
            return 1

    for code in codes:
        old = reg[code]["location"]
        reg[code]["location"] = to
        print(f"{code}: {old} -> {to}")
    save_registry(reg)
    print(f"\n{len(codes)} unit(s) relocated.")
    return 0


def cmd_credit(args: argparse.Namespace) -> int:
    """Fix attached_by/note on already-attached units without touching location."""
    if args.by is None and args.note is None:
        print("error: pass --by and/or --note — nothing to update.", file=sys.stderr)
        return 1

    reg = load_registry()
    codes = _expand_codes(args.codes)

    missing, not_attached = _validate_attached_codes(reg, codes)
    if missing or not_attached:
        _report_attached_code_errors(missing, not_attached)
        return 1

    for code in codes:
        changes = []
        if args.by is not None:
            old_by = reg[code].get("attached_by") or "-"
            reg[code]["attached_by"] = args.by
            changes.append(f"attached by: {old_by} -> {args.by}")
        if args.note is not None:
            old_note = reg[code]["note"] or "-"
            reg[code]["note"] = args.note
            changes.append(f"note: {old_note!r} -> {args.note!r}")
        print(f"{code}: " + ", ".join(changes))
    save_registry(reg)
    print(f"\n{len(codes)} unit(s) updated.")
    return 0


def cmd_retire(args: argparse.Namespace) -> int:
    reg = load_registry()
    code = canon(args.code)
    if code not in reg:
        print(f"error: {code} was never minted.", file=sys.stderr)
        return 1
    if reg[code]["retired_at"]:
        print(f"error: {code} is already retired ({reg[code]['retired_at']}).",
              file=sys.stderr)
        return 1
    reg[code]["retired_at"] = _now()
    if args.note:
        reg[code]["note"] = args.note
    was = reg[code].get("location")
    if was:
        reg[code]["location"] = None
        reg[code]["attached_at"] = None
        reg[code]["attached_by"] = None
    save_registry(reg)
    print(f"{code} retired (validity range closed)"
          + (f" and detached from {was}" if was else ""))
    return 0


def cmd_unretire(args: argparse.Namespace) -> int:
    reg = load_registry()
    code = canon(args.code)
    if code not in reg or not reg[code]["retired_at"]:
        print(f"error: {code} is not retired.", file=sys.stderr)
        return 1
    reg[code]["retired_at"] = None
    save_registry(reg)
    print(f"{code} back in service")
    return 0


def cmd_delete(args: argparse.Namespace) -> int:
    reg = load_registry()
    codes = [canon(c) for c in args.codes]
    missing = [c for c in codes if c not in reg]
    if missing:
        # All-or-nothing: a typo in one code shouldn't half-delete the batch.
        print(f"error: never minted, nothing deleted: {', '.join(missing)}",
              file=sys.stderr)
        return 1
    for code in codes:
        del reg[code]
        removed = []
        for ext in ("svg", "pdf"):
            f = Path(args.labels) / f"{code}.{ext}"
            if f.exists():
                f.unlink()
                removed.append(f.name)
        files = f", removed {' + '.join(removed)}" if removed else ""
        print(f"{code} deleted — number is mintable again{files}")
    save_registry(reg)
    return 0


def _rows(reg: dict) -> list[tuple[str, str, str, str, str, str, str, str]]:
    rows = []
    for code in sorted(reg):
        e = reg[code]
        rows.append((
            code,
            (e["minted_at"] or "")[:16].replace("T", " "),
            e["minted_by"] or "",
            str(e.get("reprints", 0)),
            "retired " + e["retired_at"][:10] if e["retired_at"] else "active",
            e.get("location") or "",
            e.get("attached_by") or "",
            e["note"] or "",
        ))
    return rows


def cmd_list(args: argparse.Namespace) -> int:
    reg = load_registry()
    if not reg:
        print("Registry is empty — mint some labels first (main.py --print).")
        return 0
    header = ("SERIAL", "MINTED", "BY", "REPRINTS", "STATUS", "LOCATION",
              "ATTACHED BY", "NOTE")
    rows = _rows(reg)
    widths = [max(len(r[i]) for r in [header, *rows]) for i in range(len(header))]
    for r in [header, *rows]:
        print("  ".join(cell.ljust(w) for cell, w in zip(r, widths)).rstrip())
    active = sum(1 for e in reg.values() if not e["retired_at"])
    print(f"\n{active} active of {len(reg)} minted.")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    reg = load_registry()
    if not reg:
        print("Registry is empty — nothing to report.")
        return 0

    active = sorted(c for c, e in reg.items() if not e["retired_at"])
    retired = sorted(c for c, e in reg.items() if e["retired_at"])
    today = datetime.now().strftime("%b %d, %Y")

    lines = [f"PPR fleet update - {today}", ""]
    lines.append(f"Active units ({len(active)} of {len(reg)} minted):")
    for code in active:
        e = reg[code]
        detail = f"  {code}"
        if e.get("location"):
            detail += f" @ {e['location']}"
            if e.get("attached_by"):
                detail += f" (attached by {e['attached_by']})"
        detail += f" (minted {e['minted_at'][:10]}"
        if e["minted_by"]:
            detail += f", {e['minted_by']}"
        detail += ")"
        if e["note"]:
            detail += f" - {e['note']}"
        lines.append(detail)
    if retired:
        lines.append("")
        lines.append(f"Retired ({len(retired)}):")
        for code in retired:
            e = reg[code]
            detail = f"  {code} ({e['minted_at'][:10]} -> {e['retired_at'][:10]})"
            if e["note"]:
                detail += f" - {e['note']}"
            lines.append(detail)
    print("\n".join(lines))

    if args.md:
        md = [f"# PPR fleet update - {today}", ""]
        md.append("| Serial | Minted | By | Reprints | Status | Location | "
                   "Attached By | Note |")
        md.append("|---|---|---|---|---|---|---|---|")
        for r in _rows(reg):
            md.append("| " + " | ".join(cell or " " for cell in r) + " |")
        md.append("")
        md.append(f"**{len(active)} active** of {len(reg)} minted.")
        Path(args.md).write_text("\n".join(md) + "\n", encoding="utf-8")
        print(f"\nwrote {args.md}")
    return 0


# --------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ledger of physical PPR units (mirrors the uniplex.nozzle "
                    "pattern: human-assigned id + validity birth/retire dates). "
                    "attach/detach record the unit's current gantry/head; the "
                    "serial itself never encodes location."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("attach", help="record where a unit sits: G1..G3 or a "
                                      "head like G1H2")
    p.add_argument("code", help="serial, e.g. PR01")
    p.add_argument("location", nargs="?", default=None,
                   help="G1, G2, G3, or a specific head like G1H2 "
                        "(or pass --location instead)")
    p.add_argument("--location", dest="location", metavar="LOCATION",
                   help="alternative to the positional LOCATION")
    p.add_argument("--by", help="who attached it")
    p.set_defaults(func=cmd_attach)

    p = sub.add_parser("detach", help="unit came out of the machine "
                                      "(back in the drawer)")
    p.add_argument("code")
    p.set_defaults(func=cmd_detach)

    p = sub.add_parser("relocate", help="change location on already-attached "
                                        "units, leaving who/when alone")
    p.add_argument("codes", nargs="+", metavar="CODE",
                   help="serials and/or ranges, e.g. PR01 PR03-PR05")
    p.add_argument("--to", required=True, metavar="LOCATION",
                   help="new location, e.g. G2 or G2H1")
    p.set_defaults(func=cmd_relocate)

    p = sub.add_parser(
        "credit",
        help="fix who attached (and/or the note on) already-attached units, "
             "without touching location",
    )
    p.add_argument("codes", nargs="+", metavar="CODE",
                   help="serials and/or ranges, e.g. PR01-PR05")
    p.add_argument("--by", help="who actually attached these")
    p.add_argument("--note", help="anything else worth recording")
    p.set_defaults(func=cmd_credit)

    p = sub.add_parser("retire", help="close a unit's validity range (unit dead)")
    p.add_argument("code", help="serial, e.g. PR03")
    p.add_argument("--note", help="why it was retired")
    p.set_defaults(func=cmd_retire)

    p = sub.add_parser("unretire", help="reopen a retired unit (undo a mistake)")
    p.add_argument("code")
    p.set_defaults(func=cmd_unretire)

    p = sub.add_parser(
        "delete",
        help="erase bad labels entirely: registry entry + label files "
             "(irreversible; use retire for real units that died)",
    )
    p.add_argument("codes", nargs="+", metavar="CODE",
                   help="serial(s) to destroy, e.g. PR03 PR04")
    p.add_argument("--labels", default="labels", metavar="DIR",
                   help="directory holding <CODE>.svg/.pdf (default: labels)")
    p.set_defaults(func=cmd_delete)

    p = sub.add_parser("list", help="status table of every minted unit")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("report", help="print a supervisor-ready summary")
    p.add_argument("--md", metavar="FILE", help="also write a markdown table")
    p.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ValueError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
