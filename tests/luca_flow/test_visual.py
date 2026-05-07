"""Per-page visual diff for the LUCA-flow site.

Serves `dist/` over a local http.server and uses Playwright (headless
chromium) to take a full-page screenshot of every page. Compares against
the PNG snapshot under `snapshots/screenshots/`. Fails on any pixel
that exceeds `PIXEL_TOLERANCE` per channel.

To regenerate baselines, run with `UPDATE_LUCA_SNAPSHOTS=1`.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from PIL import Image, ImageChops

SNAPSHOT_DIR = Path(__file__).parent / "snapshots" / "screenshots"
UPDATE = os.environ.get("UPDATE_LUCA_SNAPSHOTS") == "1"

VIEWPORT: dict[str, int] = {"width": 1280, "height": 800}
# Subpixel font rendering and JPEG decode are not bit-stable across machines.
# Allow a tiny per-channel delta. Tighten to 0 if you want strict.
PIXEL_TOLERANCE = 8
# Fraction of pixels allowed to exceed PIXEL_TOLERANCE. 0.5% catches real
# regressions while letting font hinting drift slide.
MAX_DIFF_FRACTION = 0.005

PAGES = [
    "index.html",
    "gallery.html",
    "science.html",
    "product.html",
    "mission.html",
    "about.html",
    "preorder.html",
    "CITATIONS.html",
]


def _diff_fraction(a: Image.Image, b: Image.Image) -> float:
    if a.size != b.size:
        return 1.0
    diff = ImageChops.difference(a.convert("RGB"), b.convert("RGB"))
    bbox_pixels = a.size[0] * a.size[1]
    over = 0
    for pixel in list(diff.getdata()):
        r, g, b_ = pixel
        if r > PIXEL_TOLERANCE or g > PIXEL_TOLERANCE or b_ > PIXEL_TOLERANCE:
            over += 1
    return over / bbox_pixels


@pytest.mark.luca_flow
@pytest.mark.parametrize("page", PAGES)
def test_page_visual_diff(luca_dist_url: str, page: str) -> None:
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    snap_path = SNAPSHOT_DIR / f"{page}.png"
    snap_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            viewport={"width": VIEWPORT["width"], "height": VIEWPORT["height"]},
            device_scale_factor=1,
        )
        pg = context.new_page()
        pg.goto(f"{luca_dist_url}/{page}", wait_until="networkidle")
        png_bytes = pg.screenshot(full_page=True, animations="disabled")
        browser.close()

    if UPDATE or not snap_path.exists():
        snap_path.write_bytes(png_bytes)
        return

    import io

    actual = Image.open(io.BytesIO(png_bytes))
    expected = Image.open(snap_path)
    frac = _diff_fraction(expected, actual)
    if frac > MAX_DIFF_FRACTION:
        # Drop the actual screenshot next to the snapshot for triage.
        (snap_path.parent / f"{page}.actual.png").write_bytes(png_bytes)
        pytest.fail(
            f"visual diff for {page}: {frac:.4%} pixels exceed tolerance "
            f"(threshold {MAX_DIFF_FRACTION:.2%}); see {page}.actual.png"
        )
