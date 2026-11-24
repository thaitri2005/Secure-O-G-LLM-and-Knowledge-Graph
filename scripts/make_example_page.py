"""Make the small example page image the frontend's example mode shows (frontend/public/example-pages).

    python scripts/make_example_page.py <ak3 end-of-well pdf>

Page 7 of the public (the page the example answer cites) AK-3 end-of-well report (CC BY 4.0), rendered with pypdfium2 at 100 dpi and reduced to a
64-colour palette so the committed file stays far under 200 KB. Real pages are served at 150 dpi (platform/render_pages.py).
"""
import sys
from pathlib import Path

import pypdfium2 as pdfium

OUT = Path(__file__).resolve().parents[1] / "frontend/public/example-pages/gdr882_ak3_eowr/p7.png"

document = pdfium.PdfDocument(sys.argv[1])
image = document[6].render(scale=100 / 72).to_pil().convert("L").quantize(colors=16)
OUT.parent.mkdir(parents=True, exist_ok=True)
image.save(OUT, format="PNG", optimize=True)
print(f"{OUT} {OUT.stat().st_size / 1000:.0f} KB {image.size}")
