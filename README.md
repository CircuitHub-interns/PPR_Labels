# PPR Labels — all the commands

Mints permanent serials (PR01–PR99) for physical PPR units and prints their
12.5 × 25 mm portrait labels: 10×10 DataMatrix on top, human-readable code
below it, both reading upright (`--horizontal` on ppr_labels.py gives the
legacy 25 × 12.5 mm side-by-side layout). Labels land in `labels/`, the
ledger is `ppr_registry.json`.

**One rule:** the serial belongs to the physical unit, not the slot — the
label never encodes location. Where a unit currently sits is a separate,
changeable fact: record it with `attach` / `detach` (below). Grid's scan
(`head.current_ppr_id`) stays the machine-side source of truth.

Setup (once): `pip install ppf.datamatrix reportlab`

---

## Three scripts, three jobs

- **`main.py`** — mint a new serial + print its label, in one command (most common)
- **`ppr_labels.py`** — just print labels for serials that already exist (batch printing, no minting)
- **`ppr_tracker.py`** — everything else: attach/detach, retire, bulk fixes, reports

## Print labels (main.py)

```powershell
# Mint the NEXT free serial + print its label (most common command)
python main.py --print --by "JOA"

# Mint a SPECIFIC serial
python main.py --print PR07 --by "JOA"

# Add a note while minting
python main.py --print --by "JOA" --note "spare from bin 4"

# Reprint an existing label (same command — it knows PR07 already exists)
python main.py --print PR07

# Print to a different folder
python main.py --print --by "JOA" -o "C:\labels"
```

Serial typing is forgiving: `PR07`, `pr7`, and `7` all mean PR07.

## Check / manage the fleet (ppr_tracker.py)

```powershell
# Table of every unit — serial, who minted, reprints, status, location, who attached it
python ppr_tracker.py list

# Unit installed — record where it sits (gantry, or a specific head)
python ppr_tracker.py attach PR01 G1 --by "JOA"
python ppr_tracker.py attach PR01 G1H2 --by "JOA"
python ppr_tracker.py attach PR01 --location G1H2 --by "JOA"   # --location works too

# Already attached elsewhere? attach refuses — detach first
python ppr_tracker.py detach PR01

# Bulk-move location on already-attached units (leaves who/when alone)
python ppr_tracker.py relocate PR01 PR03-PR05 --to G2

# Bulk-fix who attached (and/or note) without touching location
python ppr_tracker.py credit PR01-PR05 --by "JOA"

# Unit came out — back in the drawer
python ppr_tracker.py detach PR01

# Unit died — retire it (with why; auto-detaches if attached)
python ppr_tracker.py retire PR02 --note "force sensor drift"

# Oops, undo a retire
python ppr_tracker.py unretire PR02

# Destroy bad labels entirely — registry entry AND labels/<CODE>.svg/.pdf
# are erased, the numbers become mintable again (irreversible!)
python ppr_tracker.py delete PR03 PR04

# Copy-paste summary for the supervisor
python ppr_tracker.py report

# Same, plus a markdown table file
python ppr_tracker.py report --md report.md
```

`PR03-PR05` (and any other code list) also accepts ranges without the `PR`
prefix, e.g. `3-5`.

## Batch printing (ppr_labels.py)

```powershell
# Several labels at once
python ppr_labels.py PR01 PR02 PR03

# SVG only / PDF only / custom folder
python ppr_labels.py PR04 --svg
python ppr_labels.py PR05 --pdf -o out

# Legacy 25 x 12.5 mm landscape layout
python ppr_labels.py PR01 --horizontal
```

---

## Life of one unit, start to finish

```powershell
python main.py --print --by "JOA"                     # 1. mint PR03 + print label
                                                        #    (then stick the label on the PPR)
python ppr_tracker.py attach PR03 G1H1 --by "JOA"      # 2. installed (also scan in Grid)
python main.py --print PR03                            # 3. label wore off? reprint
python ppr_tracker.py detach PR03                       # 4. pulled out for a while
python ppr_tracker.py retire PR03 --note "…"            # 5. unit dies (auto-detaches)
python ppr_tracker.py report                            # 6. tell the supervisor
```

## What the output looks like

```
> python main.py --print --by "JOA"
wrote labels\PR01.svg
wrote labels\PR01.pdf
PR01 minted by JOA

> python ppr_tracker.py attach PR01 G1H2 --by "JOA"
PR01 attached to G1H2 (by JOA)

> python ppr_tracker.py attach PR01 G2       # <- refused, already attached
error: PR01 is already attached to G1H2 (since 2026-07-14T09:41:03). Run 'detach PR01' first if it moved.

> python ppr_tracker.py list
SERIAL  MINTED            BY   REPRINTS  STATUS              LOCATION  ATTACHED BY  NOTE
PR01    2026-07-06 10:34  JOA  0         active              G1H2      JOA
PR02    2026-07-06 10:34  JOA  0         retired 2026-07-06                         force sensor drift

1 active of 2 minted.

> python main.py --print PR03 --gantry G1     # <- refused on purpose
error: serials are slot-independent, so minting never records a slot;
after the unit is installed, record it with:
python ppr_tracker.py attach PR07 G1H2
```

## Quick facts

| Thing | Value |
|---|---|
| Label | 12.5 × 25 mm portrait (default): DataMatrix (0.75 mm modules) on top, upright text below; `--horizontal` for legacy 25 × 12.5 mm |
| Retire vs delete | retire = real unit died, history kept; delete = bad label, entry + files erased, number reusable |
| Attach vs relocate/credit | attach = single unit, refuses if already attached elsewhere; relocate/credit = bulk fixes on units already attached |
| Serials | PR01–PR99 (10×10 symbol caps at PR + 2 digits) |
| Ledger | `ppr_registry.json` — `minted_at`/`retired_at` mirror `nozzle.validity` |
| Slots | G1×2, G2×4, G3×6 heads — record with `attach`/`detach`; Grid scan stays authoritative |
| Output | `labels/<SERIAL>.svg` + `.pdf` (PDF page = exact label size) |
