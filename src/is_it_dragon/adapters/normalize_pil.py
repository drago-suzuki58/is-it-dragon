from io import BytesIO

from PIL import Image, ImageOps

MIN_SIDE = 280
MAX_SIDE = 1568


def normalize(raw: bytes) -> bytes:
    """任意の画像を Jev の制約内に収めた baseline JPEG にする。"""
    with Image.open(BytesIO(raw)) as im:
        im.seek(0)  # GIF / WebP / APNG は先頭フレーム
        img = ImageOps.exif_transpose(im)
        img = _fit(_flatten(img))
    out = BytesIO()
    img.save(out, "JPEG", quality=90)
    return out.getvalue()


def _flatten(img: Image.Image) -> Image.Image:
    if img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info:
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, "white")
        bg.paste(rgba, mask=rgba.getchannel("A"))
        return bg
    return img.convert("RGB")


def _fit(img: Image.Image) -> Image.Image:
    w, h = img.size
    down = MAX_SIDE / max(w, h)
    up = MIN_SIDE / min(w, h)
    # 縦横比が MAX/MIN を超えると両方は満たせないので、長辺に合わせて短辺をパディングする
    scale = down if up > down else max(up, min(1.0, down))
    size = (_clamp(w * scale), _clamp(h * scale))
    if size != (w, h):
        img = img.resize(size, Image.Resampling.LANCZOS)
    if min(size) < MIN_SIDE:
        canvas = Image.new("RGB", (max(size[0], MIN_SIDE), max(size[1], MIN_SIDE)), "white")
        canvas.paste(img, ((canvas.width - size[0]) // 2, (canvas.height - size[1]) // 2))
        img = canvas
    return img


def _clamp(v: float) -> int:
    return max(1, min(MAX_SIDE, round(v)))
