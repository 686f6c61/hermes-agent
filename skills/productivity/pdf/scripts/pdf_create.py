#!/usr/bin/env python3
"""Create a PDF from a JSON spec using reportlab platypus.

Spec format (UTF-8 JSON):
{
  "title": "Example Report",
  "author": "example-author",
  "page_size": "A4",            // or "letter" (default: A4)
  "page_numbers": true,          // default true
  "elements": [
    {"type": "heading", "text": "Section 1", "level": 1},
    {"type": "paragraph", "text": "Body text..."},
    {"type": "table", "rows": [["H1", "H2"], ["a", "b"]], "header": true},
    {"type": "image", "path": "chart.png", "width": 400},
    {"type": "pagebreak"}
  ]
}
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# A base-14 font has no glyphs past WinAnsi, so a PDF built with the sample
# stylesheet draws every ``ő``, ``ű``, Cyrillic or CJK character as a black box.
# Register a TrueType face that covers those code points instead, and keep
# Helvetica only as the fallback for hosts that ship no such font.
_UNICODE_FONT_PAIRS = (
    (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ),
    ("/usr/share/fonts/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/TTF/DejaVuSans.ttf", "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"),
    (
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ),
    (
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    ),
    # macOS ships this one; it is the only default face with wide coverage.
    (
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    ),
    ("/Library/Fonts/Arial Unicode.ttf", "/Library/Fonts/Arial Unicode.ttf"),
    ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
)
_UNICODE_FONT_NAME = "SkillUnicodeSans"


def _reconfigure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def _register_unicode_font() -> tuple[str, str] | None:
    """Register the first available wide-coverage TTF pair.

    Returns ``(regular, bold)`` font names, or ``None`` when the host has no
    such font and the caller should stay on the base-14 faces.
    """
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    for regular_path, bold_path in _UNICODE_FONT_PAIRS:
        if not (os.path.exists(regular_path) and os.path.exists(bold_path)):
            continue
        regular, bold = _UNICODE_FONT_NAME, _UNICODE_FONT_NAME + "-Bold"
        try:
            pdfmetrics.registerFont(TTFont(regular, regular_path))
            pdfmetrics.registerFont(TTFont(bold, bold_path))
        except Exception:
            continue
        return regular, bold
    return None


def _warn_on_unencodable_text(spec: dict, fonts: tuple[str, str] | None) -> None:
    """Name the characters a fallback run cannot draw, instead of hiding them."""
    if fonts is not None:
        return
    text = json.dumps(spec, ensure_ascii=False)
    lost = sorted({ch for ch in text if ord(ch) > 0xFF})
    if lost:
        print(
            "Warning: no Unicode TrueType font found; "
            f"{''.join(lost)!r} will render as empty boxes",
            file=sys.stderr,
        )


def build_pdf(spec: dict, out_path: str) -> int:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, letter
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import (
            Image,
            PageBreak,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError:
        print("Missing dependency: install with 'python3 -m pip install reportlab'", file=sys.stderr)
        return 2

    page_size = letter if str(spec.get("page_size", "A4")).lower() == "letter" else A4
    styles = getSampleStyleSheet()
    fonts = _register_unicode_font()
    body_font, bold_font = fonts if fonts else ("Helvetica", "Helvetica-Bold")
    if fonts:
        for style in styles.byName.values():
            # ListStyle has no fontName; only the paragraph styles carry one.
            font_name = getattr(style, "fontName", "")
            if font_name == "Helvetica-Bold":
                style.fontName = bold_font
            elif font_name == "Helvetica":
                style.fontName = body_font
    _warn_on_unencodable_text(spec, fonts)
    story = []
    for el in spec.get("elements", []):
        etype = el.get("type")
        if etype == "heading":
            level = min(max(int(el.get("level", 1)), 1), 3)
            story.append(Paragraph(el.get("text", ""), styles[f"Heading{level}"]))
        elif etype == "paragraph":
            story.append(Paragraph(el.get("text", ""), styles["BodyText"]))
            story.append(Spacer(1, 6))
        elif etype == "table":
            rows = el.get("rows", [])
            if not rows:
                continue
            table = Table(rows, repeatRows=1 if el.get("header", True) else 0)
            style = [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
            if fonts:
                # Plain-string cells are drawn with the table's own font, which
                # defaults to Helvetica.
                style.append(("FONTNAME", (0, 0), (-1, -1), body_font))
            if el.get("header", True):
                style += [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("FONTNAME", (0, 0), (-1, 0), bold_font),
                ]
            table.setStyle(TableStyle(style))
            story.append(table)
            story.append(Spacer(1, 10))
        elif etype == "image":
            kwargs = {}
            if el.get("width"):
                kwargs["width"] = float(el["width"])
            if el.get("height"):
                kwargs["height"] = float(el["height"])
            img = Image(el["path"], **kwargs)
            if "width" in kwargs and "height" not in kwargs:
                # keep aspect ratio
                ratio = img.imageHeight / img.imageWidth
                img.drawWidth = kwargs["width"]
                img.drawHeight = kwargs["width"] * ratio
            story.append(img)
            story.append(Spacer(1, 10))
        elif etype == "pagebreak":
            story.append(PageBreak())
        else:
            print(f"Warning: unknown element type {etype!r}, skipped", file=sys.stderr)

    def draw_page_number(canvas, doc):
        if spec.get("page_numbers", True):
            canvas.saveState()
            canvas.setFont(body_font, 9)
            canvas.drawCentredString(page_size[0] / 2.0, 0.5 * inch, f"Page {doc.page}")
            canvas.restoreState()

    doc = SimpleDocTemplate(
        out_path,
        pagesize=page_size,
        title=spec.get("title", ""),
        author=spec.get("author", ""),
    )
    doc.build(story, onFirstPage=draw_page_number, onLaterPages=draw_page_number)
    print(json.dumps({"output": out_path, "elements": len(spec.get("elements", []))}))
    return 0


def main() -> int:
    _reconfigure_stdio()
    parser = argparse.ArgumentParser(description="Create a PDF from a JSON spec (reportlab).")
    parser.add_argument("spec", help="Path to UTF-8 JSON spec file")
    parser.add_argument("-o", "--output", required=True, help="Output PDF path")
    args = parser.parse_args()
    with open(args.spec, encoding="utf-8") as fh:
        spec = json.load(fh)
    return build_pdf(spec, args.output)


if __name__ == "__main__":
    sys.exit(main())
