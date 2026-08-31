"""
Roll Call — twin check label ZPL generator.

Generates the label defined as:

    Order Number - Film Type
    Twin Check Number
    Barcode

Resolution-independent: all layout is computed in millimetres and converted to
dots at the target printer's DPI, so the same template works on a 203dpi office
printer and a 300dpi production printer.

Intended to be imported by the RollCall FastAPI backend:

    from twincheck_label import build_label
    zpl = build_label(order="48213", film_type="C41-135", twin_check=4821,
                      store="BON", cycle=7)

Standalone use for bench testing:

    python twincheck_label.py --preview
    python twincheck_label.py --host 192.168.1.50
    python twincheck_label.py --dpi 300 --height 15 --barcode datamatrix
"""

from __future__ import annotations

import argparse
import socket
from dataclasses import dataclass


# --------------------------------------------------------------------------
# Layout
# --------------------------------------------------------------------------
# Proportions of total label height. Tuned so the twin check number stays the
# dominant element at any label height — it is the one field that must survive
# chemistry and be readable at a glance.

MARGIN_FRAC = 0.05          # top/bottom margin
LINE1_FRAC = 0.15           # "order - film type"
TWINCHECK_FRAC = 0.38       # the number itself
BARCODE_FRAC = 0.28         # barcode height
SIDE_MARGIN_MM = 1.0        # left/right quiet zone


@dataclass
class LabelSpec:
    """Physical label and printer parameters."""

    dpi: int = 203
    width_mm: float = 23.0
    height_mm: float = 15.0

    @property
    def dots_per_mm(self) -> float:
        return self.dpi / 25.4

    def mm(self, value_mm: float) -> int:
        """Convert millimetres to whole dots."""
        return int(round(value_mm * self.dots_per_mm))

    @property
    def width_dots(self) -> int:
        return self.mm(self.width_mm)

    @property
    def height_dots(self) -> int:
        return self.mm(self.height_mm)


def _code128(spec: LabelSpec, y: int, height: int, data: str) -> str:
    """
    Code 128 barcode, centred, no human-readable interpretation line
    (the number is already printed larger above it).

    Module width is chosen so the symbol fits the label width with quiet zones.
    Code 128 subset C encodes 4 digits in 57 modules total.
    """
    usable = spec.width_dots - 2 * spec.mm(SIDE_MARGIN_MM)
    modules = 57 if len(data) <= 4 else 11 * (len(data) + 3) + 2
    module_w = max(1, min(4, usable // modules))
    bar_w = modules * module_w
    x = (spec.width_dots - bar_w) // 2
    return (
        f"^BY{module_w},3,{height}"
        f"^FO{x},{y}^BCN,{height},N,N,N^FD{data}^FS"
    )


TARGET_DM_MODULE_MM = 0.35   # below ~0.3mm handheld scanners get unreliable


def _dm_geometry(spec: LabelSpec, data: str) -> tuple[int, int]:
    """
    Return (module_dots, symbol_width_dots) for an ECC200 Data Matrix.

    Module size is driven by a target *physical* width, not by available dots,
    so a 300dpi printer produces the same scannable module as a 203dpi one.
    Symbol side is estimated from ECC200 capacity: 16x16 holds 12 alphanumeric
    characters, 20x20 holds 22.
    """
    module = max(3, int(round(TARGET_DM_MODULE_MM * spec.dots_per_mm)))
    modules = 16 if len(data) <= 12 else 20
    return module, module * modules


def _datamatrix(spec: LabelSpec, x: int, y: int, data: str) -> str:
    """Data Matrix (ECC200) placed at an explicit origin."""
    module, _ = _dm_geometry(spec, data)
    return f"^FO{x},{y}^BXN,{module},200^FD{data}^FS"


def build_label(
    order: str,
    film_type: str,
    twin_check: int | str,
    store: str = "BON",
    cycle: int = 1,
    roll_index: int | None = None,
    roll_total: int | None = None,
    spec: LabelSpec | None = None,
    barcode: str = "code128",
    copies: int = 2,
    digits: int = 4,
) -> str:
    """
    Build the ZPL for one twin check.

    copies=2 prints the matched pair from a 1-across roll — one for the
    negative, one for the paperwork. On 2-across media set copies=1.

    barcode:
        "code128"    encodes the bare twin check number. Fits comfortably,
                     but is ambiguous once the 4-digit sequence rotates.
        "datamatrix" encodes STORE-CYCLE-NUMBER, which stays unique forever.
                     Recommended once you have scanners in the lab.
    """
    spec = spec or LabelSpec()
    tc = str(twin_check).zfill(digits)

    # Line 1: order number, film type, and optionally "roll n/m"
    line1 = f"{order} \xb7 {film_type}"
    if roll_index and roll_total:
        line1 += f" \xb7 {roll_index}/{roll_total}"

    barcode_data = tc if barcode == "code128" else f"{store}-{cycle:02d}-{tc}"

    margin = spec.mm(spec.height_mm * MARGIN_FRAC)
    side = spec.mm(SIDE_MARGIN_MM)
    h_line1 = spec.mm(spec.height_mm * LINE1_FRAC)
    gap = spec.mm(0.3)

    y_line1 = margin
    y_body = y_line1 + h_line1 + gap
    body_h = spec.height_dots - y_body - margin

    # Line 1 must never truncate. Rescan orders carry a suffix ("48213-B") which
    # pushes the string past the label width at the nominal font size, so shrink
    # to fit rather than let ^FB clip it. Floor at 1.4mm cap height — below that
    # it stops being readable and the fix is a wider label, not a smaller font.
    usable = spec.width_dots - 2 * spec.mm(0.5)
    min_h = spec.mm(1.4)
    while h_line1 > min_h and len(line1) * int(h_line1 * 0.55) > usable:
        h_line1 -= 1
    if len(line1) * int(h_line1 * 0.55) > usable:
        raise ValueError(
            f"Line 1 ({line1!r}, {len(line1)} chars) cannot fit "
            f"{spec.width_mm}mm even at minimum font size. Shorten the order "
            f"number or service code, or use wider stock."
        )

    fields = [
        # Line 1 — centred across full width
        f"^FO0,{y_line1}^A0N,{h_line1},{int(h_line1 * 0.55)}"
        f"^FB{spec.width_dots},1,0,C,0^FD{line1}^FS",
    ]

    if barcode == "datamatrix":
        # Square symbol, so sit it beside the number rather than below it.
        # This is the only layout that fits a compound key on narrow stock.
        _, dm_w = _dm_geometry(spec, barcode_data)
        if dm_w > body_h:
            raise ValueError(
                f"Data Matrix needs {dm_w / spec.dots_per_mm:.1f}mm square but "
                f"only {body_h / spec.dots_per_mm:.1f}mm of body height is "
                f"available. Use taller stock or switch to code128."
            )
        dm_x = spec.width_dots - side - dm_w
        num_w = dm_x - side - gap
        h_tc = min(body_h, int(num_w / (4 * 0.6)))
        fields += [
            f"^FO{side},{y_body + (body_h - h_tc) // 2}"
            f"^A0N,{h_tc},{int(h_tc * 0.6)}"
            f"^FB{num_w},1,0,C,0^FD{tc}^FS",
            _datamatrix(spec, dm_x, y_body + (body_h - dm_w) // 2, barcode_data),
        ]
    else:
        # Stacked: number above, 1D barcode below.
        h_tc = spec.mm(spec.height_mm * TWINCHECK_FRAC)
        h_bar = spec.mm(spec.height_mm * BARCODE_FRAC)
        y_bar = y_body + h_tc + gap
        if y_bar + h_bar > spec.height_dots - margin:
            raise ValueError(
                f"Layout overflows label: needs "
                f"{(y_bar + h_bar + margin) / spec.dots_per_mm:.1f}mm "
                f"but label is {spec.height_mm}mm. Use taller stock."
            )
        fields += [
            f"^FO0,{y_body}^A0N,{h_tc},{int(h_tc * 0.6)}"
            f"^FB{spec.width_dots},1,0,C,0^FD{tc}^FS",
            _code128(spec, y_bar, h_bar, barcode_data),
        ]

    return "".join(
        ["^XA", "^CI28", f"^PW{spec.width_dots}", f"^LL{spec.height_dots}",
         "^LH0,0", "^MNY"]
        + fields
        + [f"^PQ{copies}", "^XZ"]
    )


def build_job(rolls: list[dict], **kwargs) -> str:
    """
    Build one ZPL stream for a whole booking-in job.

    `rolls` is one dict per DEV SKU unit, e.g.:
        [{"order": "48213", "film_type": "C41-135", "twin_check": 4821}, ...]

    Numbers must already have been allocated atomically by RollCall — this
    function only renders. Never allocate here.
    """
    total = len(rolls)
    return "".join(
        build_label(roll_index=i, roll_total=total, **roll, **kwargs)
        for i, roll in enumerate(rolls, start=1)
    )


def send_to_printer(zpl: str, host: str, port: int = 9100, timeout: float = 5.0) -> None:
    """Send raw ZPL to a networked printer over TCP 9100."""
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.sendall(zpl.encode("utf-8"))


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(description="Generate / send a twin check label")
    p.add_argument("--dpi", type=int, default=203, choices=[203, 300])
    p.add_argument("--width", type=float, default=23.0, help="label width, mm")
    p.add_argument("--height", type=float, default=15.0, help="label height, mm")
    p.add_argument("--order", default="48213")
    p.add_argument("--film-type", default="C41-135")
    p.add_argument("--twin-check", default="4821")
    p.add_argument("--store", default="BON")
    p.add_argument("--cycle", type=int, default=7)
    p.add_argument("--barcode", default="code128", choices=["code128", "datamatrix"])
    p.add_argument("--copies", type=int, default=2)
    p.add_argument("--host", help="printer IP — omit to just print ZPL to stdout")
    p.add_argument("--port", type=int, default=9100)
    p.add_argument("--preview", action="store_true", help="show layout in mm")
    args = p.parse_args()

    spec = LabelSpec(dpi=args.dpi, width_mm=args.width, height_mm=args.height)

    if args.preview:
        print(f"Label      {spec.width_mm} x {spec.height_mm} mm "
              f"@ {spec.dpi}dpi = {spec.width_dots} x {spec.height_dots} dots")
        for name, frac in [
            ("margin", MARGIN_FRAC),
            ("line 1", LINE1_FRAC),
            ("twin check", TWINCHECK_FRAC),
            ("barcode", BARCODE_FRAC),
        ]:
            mm = spec.height_mm * frac
            print(f"  {name:<12} {mm:5.2f} mm  ({spec.mm(mm)} dots)")
        print()

    zpl = build_label(
        order=args.order,
        film_type=args.film_type,
        twin_check=args.twin_check,
        store=args.store,
        cycle=args.cycle,
        spec=spec,
        barcode=args.barcode,
        copies=args.copies,
    )

    if args.host:
        send_to_printer(zpl, args.host, args.port)
        print(f"Sent to {args.host}:{args.port}")
    else:
        print(zpl)


if __name__ == "__main__":
    main()
