"""HTML template -> 1080x1350 JPEG, via headless Chromium.

Instagram accepts JPEG only, so we screenshot straight to JPEG. The explicit
`clip` is deliberate: some Chromium builds add a 1px artefact when you rely on
the viewport alone.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..config import BRAND_HANDLE, BRAND_NAME
from ..models import Post
from .background import Background, fetch_background

log = logging.getLogger(__name__)

WIDTH, HEIGHT = 1080, 1350
TEMPLATE_DIR = Path(__file__).parent

# How far the layout may shrink before the copy is simply too long.
MIN_SCALE = 0.62

# Measure the content at its natural height, then step --s down until it fits.
# The copy length changes every run, so the card has to absorb it rather than
# assume a fixed amount of text.
FIT_SCRIPT = """
() => {
  const root = document.documentElement;
  const body = document.body;
  const target = %d;
  body.style.height = 'auto';          // measure natural height
  let scale = 1.0;
  while (scale > %f && body.scrollHeight > target) {
    scale -= 0.02;
    root.style.setProperty('--s', scale.toFixed(2));
  }
  body.style.height = target + 'px';   // restore the fixed canvas
  return scale;
}
""" % (HEIGHT, MIN_SCALE)

_env = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    autoescape=select_autoescape(["html", "j2"]),
)


def build_html(post: Post, background: Background, run_date: date) -> str:
    template = _env.get_template("template.html.j2")
    # Split here rather than in the template: a Jinja `selectattr` would hide the
    # one fact worth seeing from a caller, which is that the card renders two
    # different shapes depending on the day.
    return template.render(
        post=post,
        leads=[s for s in post.stories if s.is_lead],
        briefs=[s for s in post.stories if not s.is_lead],
        bg=background,
        date_label=run_date.strftime("%d %b %Y").upper(),
        brand=BRAND_NAME,
        handle=BRAND_HANDLE,
    )


def render_card(post: Post, out_dir: Path, run_date: date | None = None) -> Path:
    """Render the card and return the JPEG path. Also writes the HTML for debugging."""
    from playwright.sync_api import sync_playwright

    run_date = run_date or date.today()
    # Must be absolute: page.goto() needs a file:// URI.
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    background = fetch_background(post.image_query, seed=run_date.isoformat())
    html = build_html(post, background, run_date)

    html_path = out_dir / "card.html"
    html_path.write_text(html)
    jpeg_path = out_dir / "card.jpg"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=["--font-render-hinting=none"])
        try:
            page = browser.new_page(
                viewport={"width": WIDTH, "height": HEIGHT},
                device_scale_factor=1,
            )
            page.goto(html_path.as_uri())
            # Webfonts must be in before measuring or the fit is computed against
            # fallback metrics and the real text overflows.
            page.wait_for_load_state("networkidle")
            page.evaluate("document.fonts.ready")
            scale = page.evaluate(FIT_SCRIPT)
            if scale < 1.0:
                log.info("content shrunk to %.0f%% to fit the canvas", scale * 100)
            if scale <= MIN_SCALE:
                log.warning(
                    "copy is too long for the card even at minimum scale - "
                    "shorten the story detail lines"
                )
            page.screenshot(
                path=str(jpeg_path),
                type="jpeg",
                quality=90,
                clip={"x": 0, "y": 0, "width": WIDTH, "height": HEIGHT},
            )
        finally:
            browser.close()

    size_kb = jpeg_path.stat().st_size // 1024
    log.info("rendered %s (%d KB)", jpeg_path, size_kb)
    return jpeg_path
