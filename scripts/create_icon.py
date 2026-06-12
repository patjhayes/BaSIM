#!/usr/bin/env python3
"""Create logo/logomark.ico from SVG (preferred) or PNG fallbacks.

Requires Pillow; for SVG conversion, also requires cairosvg.
Safe to run multiple times.
"""
from __future__ import annotations

import io
from pathlib import Path


def main() -> int:
    base = Path(__file__).resolve().parents[1]
    logo_dir = base / "logo"
    ico = logo_dir / "logomark.ico"
    svg_primary = logo_dir / "logomark_background.svg"
    svg_alt = logo_dir / "logomark.svg"
    png_candidates = [
        logo_dir / "transparent_logomark.png",
        logo_dir / "transparent_logomark_black.png",
        logo_dir / "transparent_logomark_white.png",
        logo_dir / "logomark.png",
        logo_dir / "logomark_black.png",
        logo_dir / "logomark_white.png",
    ]

    try:
        from PIL import Image
    except Exception:
        print("Pillow not installed; installing...")
        import subprocess, sys
        subprocess.check_call([sys.executable, "-m", "pip", "install", "Pillow"])
        from PIL import Image  # type: ignore

    img = None

    # Try SVG
    for svg in (svg_primary, svg_alt):
        if svg.exists():
            try:
                import cairosvg  # type: ignore
            except Exception:
                try:
                    import subprocess, sys
                    print("Installing cairosvg...")
                    subprocess.check_call([sys.executable, "-m", "pip", "install", "cairosvg"])
                    import cairosvg  # type: ignore
                except Exception:
                    cairosvg = None  # type: ignore
            if 'cairosvg' in globals():
                try:
                    png_bytes = cairosvg.svg2png(url=str(svg), output_height=256)
                    img = Image.open(io.BytesIO(png_bytes)).convert('RGBA')
                    break
                except Exception as e:  # fall back to PNGs
                    print(f"SVG conversion failed for {svg.name}: {e}")

    # Try PNG fallbacks
    if img is None:
        for p in png_candidates:
            if p.exists():
                try:
                    img = Image.open(p).convert('RGBA')
                    break
                except Exception:
                    continue

    if img is None:
        print("No logo source found; skipping icon generation.")
        return 0

    sizes = [(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)]
    ico.parent.mkdir(parents=True, exist_ok=True)
    img.save(ico, format='ICO', sizes=sizes)
    print(f"Wrote {ico}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
