"""PPR label generator — Circuit Hub PR series.

Produces print-ready labels (SVG and/or PDF, one label per page). The default
is a portrait 12.5 x 25 mm label with the DataMatrix stacked above the code;
BOTH read upright — the text is never rotated. --horizontal keeps the legacy
25 x 12.5 mm side-by-side layout:

   default (portrait)          --horizontal (legacy)
  +------------+              +--------------------------+
  | [10x10 DM] |              | [10x10 DataMatrix]  PR01 |
  |    PR01    |              +--------------------------+
  +------------+

Layout spec (shared):
  - Data Matrix ..... 10x10 ECC 200, always square
  - Human-readable .. bold condensed, stretched to fill its region exactly
                      at any code length; always horizontal
  - Capacity ........ 10x10 holds 3 data codewords: PR + 1-2 digits
                      (PR1 through PR99; ASCII mode packs digit pairs)
  - Portrait ........ symbol fills the width minus two modules of quiet
                      zone per side: 14 modules across 12.5 mm ->
                      0.8929 mm module, 8.929 mm symbol; upright text below
  - Landscape ....... 0.75 mm module -> 7.5 mm symbol, left-anchored,
                      1.0 mm quiet zone, text filling the remaining width

Usage:
  python ppr_labels.py PR01                  # -> labels/PR01.svg + labels/PR01.pdf
  python ppr_labels.py PR01 PR02 PR03        # one file pair per code
  python ppr_labels.py PR01 --svg            # SVG only
  python ppr_labels.py PR01 --pdf -o out     # PDF only, custom output dir
  python ppr_labels.py PR01 --horizontal     # legacy landscape 25 x 12.5 mm

The printed code IS the unit's permanent, slot-independent serial (mirroring
uniplex.nozzle ids). Every print is logged to ppr_registry.json; use
ppr_tracker.py for list / retire / report, and main.py to mint-and-print.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ppf.datamatrix import DataMatrix

from ppr_tracker import canon, register_print

# ---------------------------------------------------------------- geometry (mm)
LABEL_W = 25.0
LABEL_H = 12.5

MODULE = 0.75          # DataMatrix module size
N = 10                 # 10x10 symbol
SYM = MODULE * N       # 7.5 mm symbol edge

DM_X = 1.0                     # left quiet zone
DM_Y = (LABEL_H - SYM) / 2     # 2.5 mm top/bottom

TXT_X0 = DM_X + SYM + 1.5      # text region: 10.0 mm ...
TXT_X1 = LABEL_W - 1.0         # ... to 24.0 mm
TXT_FONT_MM = 5.6              # nominal font size before horizontal fit
CAP_RATIO = 0.72               # Helvetica-Bold cap height, em fraction

# Portrait (default): 12.5 x 25 mm, DataMatrix stacked above upright text.
# Symbol fills the width minus two modules of quiet zone per side:
# 14 modules across the 12.5 mm label -> 0.8929 mm module, 8.929 mm symbol.
V_QUIET = 2                   # quiet-zone modules per side
V_W, V_H = LABEL_H, LABEL_W
V_MODULE = V_W / (N + 2 * V_QUIET)
V_SYM = V_MODULE * N
V_DM_X = V_QUIET * V_MODULE
V_GAP = 3.0                   # symbol -> text
V_CAP = CAP_RATIO * TXT_FONT_MM
V_DM_Y = (V_H - (V_SYM + V_GAP + V_CAP)) / 2   # center the stack vertically
V_TXT_CY = V_DM_Y + V_SYM + V_GAP + V_CAP / 2  # text center line
V_TXT_X0 = 1.0
V_TXT_X1 = V_W - 1.0

MM_TO_PT = 72 / 25.4


def encode(code: str) -> list[list[int]]:
    """Return the 10x10 module grid (1 = dark) for a validated PR code."""
    code = canon(code)  # raises ValueError on anything outside PR01-PR99
    matrix = DataMatrix(code).matrix
    if len(matrix) != N or len(matrix[0]) != N:
        raise ValueError(
            f"{code!r} encoded to {len(matrix)}x{len(matrix[0])}, expected {N}x{N}"
        )
    return matrix


# ------------------------------------------------------------------------- SVG
def _geometry(
    vertical: bool,
) -> tuple[float, float, float, float, float, float, float, float]:
    """(page_w, page_h, module, dm_x, dm_y, txt_x0, txt_x1, txt_cy) for a layout."""
    if vertical:
        return V_W, V_H, V_MODULE, V_DM_X, V_DM_Y, V_TXT_X0, V_TXT_X1, V_TXT_CY
    return LABEL_W, LABEL_H, MODULE, DM_X, DM_Y, TXT_X0, TXT_X1, LABEL_H / 2


def label_svg(code: str, vertical: bool = True) -> str:
    """Full label as an SVG document in real millimeter units.

    Default is the portrait 12.5 x 25 mm page: DataMatrix stacked above the
    upright human-readable code (text is horizontal in both layouts).
    vertical=False gives the legacy 25 x 12.5 mm landscape label.
    """
    matrix = encode(code)
    page_w, page_h, module, dm_x, dm_y, tx0, tx1, tcy = _geometry(vertical)
    modules = "".join(
        f'<rect x="{dm_x + c * module:.4f}" y="{dm_y + r * module:.4f}" '
        f'width="{module:.4f}" height="{module:.4f}"/>'
        for r in range(N)
        for c in range(N)
        if matrix[r][c]
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{page_w}mm" height="{page_h}mm" '
        f'viewBox="0 0 {page_w} {page_h}">'
        f'<rect width="{page_w}" height="{page_h}" fill="#fff"/>'
        f'<g fill="#000">{modules}</g>'
        f'<text x="{(tx0 + tx1) / 2}" y="{tcy}" '
        f'textLength="{tx1 - tx0:.2f}" lengthAdjust="spacingAndGlyphs" '
        f'text-anchor="middle" dominant-baseline="central" '
        f"font-family=\"Bahnschrift, 'Arial Narrow', sans-serif\" font-weight=\"700\" "
        f'font-size="{TXT_FONT_MM}" fill="#000">{code}</text>'
        f"</svg>"
    )


# ------------------------------------------------------------------------- PDF
def label_pdf(code: str, path: Path, vertical: bool = True) -> None:
    """Write a single-page PDF whose page is exactly the label.

    Default is the portrait 12.5 x 25 mm page: DataMatrix stacked above the
    upright human-readable code (text is horizontal in both layouts).
    vertical=False gives the legacy 25 x 12.5 mm landscape label.
    """
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.pdfgen import canvas

    matrix = encode(code)
    page_w, page_h, module, dm_x, dm_y, tx0, tx1, tcy = _geometry(vertical)
    c = canvas.Canvas(str(path), pagesize=(page_w * MM_TO_PT, page_h * MM_TO_PT))
    c.setTitle(f"PPR label {code}")

    def rect_mm(x: float, y_top: float, w: float, h: float) -> None:
        # PDF origin is bottom-left; our spec measures y from the top edge.
        c.rect(
            x * MM_TO_PT,
            (page_h - y_top - h) * MM_TO_PT,
            w * MM_TO_PT,
            h * MM_TO_PT,
            stroke=0,
            fill=1,
        )

    c.setFillColorRGB(1, 1, 1)
    rect_mm(0, 0, page_w, page_h)

    c.setFillColorRGB(0, 0, 0)
    for r in range(N):
        for col in range(N):
            if matrix[r][col]:
                rect_mm(dm_x + col * module, dm_y + r * module, module, module)

    # Human-readable: Helvetica-Bold horizontally scaled to fill the text
    # region exactly, mirroring the SVG textLength behaviour.
    font, size_pt = "Helvetica-Bold", TXT_FONT_MM * MM_TO_PT
    natural_pt = stringWidth(code, font, size_pt)
    target_pt = (tx1 - tx0) * MM_TO_PT
    text = c.beginText()
    text.setFont(font, size_pt)
    text.setHorizScale(100 * target_pt / natural_pt)
    # Vertically center on cap height (CAP_RATIO em for Helvetica).
    baseline_pt = (page_h - tcy) * MM_TO_PT - (CAP_RATIO * size_pt) / 2
    text.setTextOrigin(tx0 * MM_TO_PT, baseline_pt)
    text.textOut(code)
    c.drawText(text)

    c.showPage()
    c.save()


# ------------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate 25 x 12.5 mm PPR labels (PR series)."
    )
    parser.add_argument("codes", nargs="+", metavar="CODE", help="e.g. PR01 PR02")
    parser.add_argument("--svg", action="store_true", help="write SVG only")
    parser.add_argument("--pdf", action="store_true", help="write PDF only")
    parser.add_argument(
        "--horizontal",
        action="store_true",
        help="legacy landscape 25 x 12.5 mm label (default is portrait 12.5 x 25 mm)",
    )
    parser.add_argument(
        "-o", "--out", default="labels", help="output directory (default: labels)"
    )
    args = parser.parse_args(argv)

    want_svg = args.svg or not args.pdf
    want_pdf = args.pdf or not args.svg

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    for code in args.codes:
        try:
            code = canon(code)
            if want_svg:
                svg_path = out / f"{code}.svg"
                svg_path.write_text(
                    label_svg(code, vertical=not args.horizontal), encoding="utf-8"
                )
                print(f"wrote {svg_path}")
            if want_pdf:
                pdf_path = out / f"{code}.pdf"
                label_pdf(code, pdf_path, vertical=not args.horizontal)
                print(f"wrote {pdf_path}")
            register_print(code)
        except ValueError as err:
            print(f"error: {err}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
