"""見出し画像(note)と投稿画像(Instagram)を Pillow で生成する。"""
from __future__ import annotations

import hashlib
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .core import PUBLIC_DIR

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
]

PALETTES = [  # (背景, アクセント, 文字)
    ((250, 246, 238), (232, 93, 63), (34, 34, 34)),
    ((236, 244, 250), (36, 99, 235), (24, 32, 48)),
    ((240, 247, 241), (22, 128, 82), (24, 40, 32)),
    ((252, 241, 246), (190, 50, 110), (40, 24, 32)),
]


def _font(size: int) -> ImageFont.FreeTypeFont:
    for p in FONT_CANDIDATES:
        if Path(p).exists():
            return ImageFont.truetype(p, size, index=0)  # ttc の0番目が日本語(JP)
    return ImageFont.load_default()


def _palette(seed: str):
    return PALETTES[int(hashlib.md5(seed.encode()).hexdigest(), 16) % len(PALETTES)]


def _wrap(draw, text: str, font, max_w: int) -> list[str]:
    lines, cur = [], ""
    for ch in text:
        if draw.textlength(cur + ch, font=font) > max_w:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines


def eyecatch(title: str, label: str, slug: str) -> Path:
    """note の見出し画像 1280x670。"""
    bg, accent, fg = _palette(title)
    W, H = 1280, 670
    im = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 24, H], fill=accent)
    f_label, f_title = _font(34), _font(64)
    tl = _wrap(d, title, f_title, W - 180)[:4]
    y = (H - len(tl) * 92) // 2 + 20
    d.text((90, y - 70), label, font=f_label, fill=accent)
    for line in tl:
        d.text((90, y), line, font=f_title, fill=fg)
        y += 92
    out = PUBLIC_DIR / "images" / f"{slug}-eyecatch.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out)
    return out


def insta_cards(title: str, points: list[str], cta: str, slug: str) -> list[Path]:
    """Instagram 用の縦長カード(1080x1350)。1枚目=表紙、2枚目以降=要点、最後=誘導。"""
    bg, accent, fg = _palette(title)
    W, H = 1080, 1350
    pages: list[tuple[str, str]] = [("cover", title)] + [("point", p) for p in points[:5]] + [("cta", cta)]
    outs = []
    for i, (kind, text) in enumerate(pages, 1):
        im = Image.new("RGB", (W, H), bg)
        d = ImageDraw.Draw(im)
        d.rectangle([0, 0, W, 18], fill=accent)
        if kind == "cover":
            f = _font(84)
            y = 360
            for line in _wrap(d, text, f, W - 160)[:5]:
                d.text((80, y), line, font=f, fill=fg)
                y += 118
            d.text((80, H - 160), "保存して後で読み返してください →", font=_font(40), fill=accent)
        elif kind == "point":
            f = _font(58)
            pl = _wrap(d, text, f, W - 160)[:9]
            y = (H - len(pl) * 88) // 2
            d.text((80, y - 110), f"POINT {i - 1}", font=_font(52), fill=accent)
            for line in pl:
                d.text((80, y), line, font=f, fill=fg)
                y += 88
        else:
            f = _font(60)
            y = 460
            for line in _wrap(d, text, f, W - 160)[:6]:
                d.text((80, y), line, font=f, fill=fg)
                y += 92
        d.text((W - 160, H - 90), f"{i}/{len(pages)}", font=_font(36), fill=fg)
        out = PUBLIC_DIR / "images" / f"{slug}-ig-{i}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        im.save(out)
        outs.append(out)
    return outs
