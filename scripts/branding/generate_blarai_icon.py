"""
BlAIr brand-mark generator (#655 brand polish).
================================================
Renders the BlAIr app icon procedurally with Pillow (no SVG toolchain needed),
so the mark is reproducible and version-controlled rather than a binary blob with
no provenance.

THE WORDMARK: the product is "BlarAI" in writing, but the LOGO is "BlAIr" — a
tongue-in-cheek nod that the name is really just the operator's name, Blair, with
the AI winking out of the middle. So the mark renders "Bl" + "AI" (emphasised) +
"r", with the AI as the visual anchor (a bright amber accent / badge) so it is
both the joke AND the thing that reads at small sizes.

THE PALETTE: warm, low-blue, on purpose. A deep espresso field, a warm amber
glow, the "Bl/r" in warm cream and the "AI" in bright amber/gold — brown reads as
grounded/trustworthy, amber as warm intelligence. No blue light.

Produces, for each emphasis treatment:
  * branding/blair_<variant>.png   — 512px preview
  * branding/blair_<variant>.ico   — multi-res icon (16..256)
and a contact sheet `branding/blair_contact_sheet.png`.

Run:  .venv\\Scripts\\python.exe scripts\\branding\\generate_blarai_icon.py
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

S = 1024
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "branding")
os.makedirs(OUT, exist_ok=True)
ICO_SIZES = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)]

# ── warm palette (no blue) ─────────────────────────────────────────────────
BG_TOP = (26, 17, 10)        # espresso
BG_BOT = (48, 30, 16)        # warm brown
CREAM = (238, 219, 189)      # Bl / r
AMBER = (245, 168, 38)       # AI
AMBER_HI = (255, 198, 96)    # AI highlight
COPPER = (201, 124, 58)
GLOW = (240, 150, 40)        # warm glow
BORDER = (205, 134, 72, 110)
DARK_ON_AMBER = (30, 19, 9)  # text on an amber badge


def _font(px: int) -> ImageFont.FreeTypeFont:
    for name in ("segoeuib.ttf", "seguibl.ttf", "arialbd.ttf", "Arial.ttf"):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default()


def vgrad(size, top, bot):
    h = 512
    g = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / (h - 1)
        g.putpixel((0, y), tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)))
    return g.resize(size)


def rounded_mask(size, radius):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], radius=radius, fill=255)
    return m


def radial_glow(size, color, frac=0.55, strength=160, cy_frac=0.5):
    g = Image.new("L", size, 0)
    cx, cy = size[0] // 2, int(size[1] * cy_frac)
    r = int(min(size) * frac)
    ImageDraw.Draw(g).ellipse([cx - r, cy - r, cx + r, cy + r], fill=strength)
    g = g.filter(ImageFilter.GaussianBlur(r // 2))
    out = Image.new("RGBA", size, color + (0,))
    out.putalpha(g)
    return out


def base_tile():
    size = (S, S)
    tile = vgrad(size, BG_TOP, BG_BOT).convert("RGBA")
    tile.alpha_composite(radial_glow(size, GLOW, frac=0.5, strength=95, cy_frac=0.52))
    # faint warm top sheen
    sheen = Image.new("L", size, 0)
    ImageDraw.Draw(sheen).ellipse([-S * 0.3, -S * 0.7, S * 1.3, S * 0.4], fill=26)
    sheen = sheen.filter(ImageFilter.GaussianBlur(S // 8))
    warm = Image.new("RGBA", size, (255, 224, 180, 0))
    warm.putalpha(sheen)
    tile.alpha_composite(warm)
    return tile


def _seg_x(font, segments):
    """Cumulative left-x for each segment so kerning stays consistent."""
    d = ImageDraw.Draw(Image.new("L", (4, 4)))
    full = "".join(segments)
    total = d.textlength(full, font=font)
    x = (S - total) / 2
    xs, cum = [], ""
    for seg in segments:
        xs.append(x + d.textlength(cum, font=font))
        cum += seg
    return xs, total


def _fit_font(text, max_w, start=520):
    f = _font(start)
    w = ImageDraw.Draw(Image.new("L", (4, 4))).textlength(text, font=f)
    return _font(max(10, int(start * max_w / w)))


def glow_layer(mask, color, blur, alpha):
    g = mask.filter(ImageFilter.GaussianBlur(blur)).point(lambda p: min(255, int(p * alpha / 255)))
    out = Image.new("RGBA", mask.size, color + (0,))
    out.putalpha(g)
    return out


def _draw_seg(layer, x, ycenter, font, text, fill):
    ImageDraw.Draw(layer).text((x, ycenter), text, font=font, fill=fill, anchor="lm")


def finalize(img, name, radius_frac=0.225):
    mask = rounded_mask((S, S), int(S * radius_frac))
    out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    ImageDraw.Draw(out).rounded_rectangle(
        [6, 6, S - 7, S - 7], radius=int(S * radius_frac) - 4, outline=BORDER, width=6
    )
    png = out.resize((512, 512), Image.LANCZOS)
    png.save(os.path.join(OUT, f"blair_{name}.png"))
    out.save(os.path.join(OUT, f"blair_{name}.ico"), format="ICO", sizes=ICO_SIZES)
    return png


def _amber_text_mask(font, xs, yc):
    """Mask of just the 'AI' segment (for glow)."""
    m = Image.new("L", (S, S), 0)
    ImageDraw.Draw(m).text((xs[1], yc), "AI", font=font, fill=255, anchor="lm")
    return m


# ── Variant 1: BADGE — AI sits in a bright amber pill ──────────────────────
def variant_badge():
    img = base_tile()
    font = _fit_font("BlAIr", 0.80 * S)
    xs, _ = _seg_x(font, ["Bl", "AI", "r"])
    yc = int(S * 0.5)
    d = ImageDraw.Draw(img)
    ai_w = d.textlength("AI", font=font)
    asc, desc = font.getmetrics()
    pad_x, pad_y = int(ai_w * 0.16), int(asc * 0.12)
    box = [xs[1] - pad_x, yc - asc // 2 - pad_y, xs[1] + ai_w + pad_x, yc + asc // 2 + pad_y]
    badge = Image.new("L", (S, S), 0)
    ImageDraw.Draw(badge).rounded_rectangle(box, radius=int(asc * 0.22), fill=255)
    img.alpha_composite(glow_layer(badge, GLOW, S // 26, 150))
    fillgrad = vgrad((S, S), AMBER_HI, AMBER).convert("RGBA")
    img.paste(fillgrad, (0, 0), badge)
    _draw_seg(img, xs[0], yc, font, "Bl", CREAM)
    _draw_seg(img, xs[2], yc, font, "r", CREAM)
    _draw_seg(img, xs[1], yc, font, "AI", DARK_ON_AMBER)
    return finalize(img, "badge")


# ── Variant 2: GLOW — AI in bright amber with a warm halo, no pill ─────────
def variant_glow():
    img = base_tile()
    font = _fit_font("BlAIr", 0.82 * S)
    xs, _ = _seg_x(font, ["Bl", "AI", "r"])
    yc = int(S * 0.5)
    img.alpha_composite(glow_layer(_amber_text_mask(font, xs, yc), AMBER, S // 16, 245))
    _draw_seg(img, xs[0], yc, font, "Bl", CREAM)
    _draw_seg(img, xs[2], yc, font, "r", CREAM)
    aigrad = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    aigrad.paste(vgrad((S, S), AMBER_HI, AMBER).convert("RGBA"), (0, 0), _amber_text_mask(font, xs, yc))
    img.alpha_composite(aigrad)
    return finalize(img, "glow")


def _fit_mixed(target_w, ratio_big, base=120):
    """Pick (small_font, big_font) so 'Bl'(small)+'AI'(big)+'r'(small) ~ target_w.

    The 'AI' renders ``ratio_big`` x taller than 'Bl'/'r' (the dominant wink); at
    the small size B (cap) and l (ascender) read at the SAME height, both shorter
    than the big 'AI' (the operator's brief)."""
    d = ImageDraw.Draw(Image.new("L", (4, 4)))
    sf, bf = _font(base), _font(int(base * ratio_big))
    w = d.textlength("Bl", font=sf) + d.textlength("AI", font=bf) + d.textlength("r", font=sf)
    f = max(12, int(base * target_w / w))
    return _font(f), _font(int(f * ratio_big))


def _seg_mask(text, font, x, ybase):
    m = Image.new("L", (S, S), 0)
    ImageDraw.Draw(m).text((x, ybase), text, font=font, fill=255, anchor="ls")  # left-baseline
    return m


# ── Variant 3: GOLD — copper->gold word, AI ENLARGED + baseline-aligned ────
# The operator brief: AI is the tallest element; B and the lowercase l sit at the
# SAME (shorter) height; r is lowercase. Mixed font sizes on a shared baseline.
def variant_gold():
    img = base_tile()
    sf, bf = _fit_mixed(0.80 * S, ratio_big=1.42)
    d = ImageDraw.Draw(Image.new("L", (4, 4)))
    w_bl = d.textlength("Bl", font=sf)
    w_ai = d.textlength("AI", font=bf)
    w_r = d.textlength("r", font=sf)
    total = w_bl + w_ai + w_r
    x0 = (S - total) / 2
    x_bl, x_ai, x_r = x0, x0 + w_bl, x0 + w_bl + w_ai
    ybase = int(S / 2 + bf.getmetrics()[0] * 0.42)  # center the tall AI block

    m_bl = _seg_mask("Bl", sf, x_bl, ybase)
    m_r = _seg_mask("r", sf, x_r, ybase)
    m_ai = _seg_mask("AI", bf, x_ai, ybase)
    whole = Image.new("L", (S, S), 0)
    for m in (m_bl, m_r, m_ai):
        whole.paste(m, (0, 0), m)
    img.alpha_composite(glow_layer(whole, GLOW, S // 22, 110))

    grad_cc = vgrad((S, S), CREAM, COPPER).convert("RGBA")
    img.paste(grad_cc, (0, 0), m_bl)
    img.paste(grad_cc, (0, 0), m_r)
    img.alpha_composite(glow_layer(m_ai, AMBER, S // 16, 150))
    img.paste(vgrad((S, S), AMBER_HI, AMBER).convert("RGBA"), (0, 0), m_ai)

    uy = ybase + int(S * 0.018)
    ImageDraw.Draw(img).rounded_rectangle(
        [x_ai, uy, x_ai + w_ai, uy + int(S * 0.020)], radius=int(S * 0.010), fill=AMBER
    )
    return finalize(img, "gold")


def main():
    previews = [variant_badge(), variant_glow(), variant_gold()]
    names = ["Badge", "Glow", "Gold"]
    pad, label_h = 40, 56
    sheet = Image.new("RGBA", (512 * 3 + pad * 4, 512 + pad * 2 + label_h), (24, 18, 12, 255))
    d = ImageDraw.Draw(sheet)
    f = _font(34)
    for i, (p, n) in enumerate(zip(previews, names)):
        x = pad + i * (512 + pad)
        sheet.alpha_composite(p, (x, pad))
        b = d.textbbox((0, 0), n, font=f)
        d.text((x + (512 - (b[2] - b[0])) // 2, pad + 512 + 8), n, font=f, fill=(238, 219, 189, 255))
    sheet.convert("RGB").save(os.path.join(OUT, "blair_contact_sheet.png"))
    print("Wrote", OUT)


if __name__ == "__main__":
    main()
