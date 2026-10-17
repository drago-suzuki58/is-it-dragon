from io import BytesIO

from PIL import Image, ImageDraw

from is_it_dragon.core.types import Box


def draw_box(img: bytes, box: Box) -> bytes:
    """画像に Box の枠を描いた JPEG を返す。Box は送信した（正規化後の）画像に対する比率。"""
    with Image.open(BytesIO(img)) as im:
        im = im.convert("RGB")
    w, h = im.size
    rect = (box.left * w, box.top * h, box.right * w, box.bottom * h)
    ImageDraw.Draw(im).rectangle(rect, outline="red", width=max(2, w // 200))
    out = BytesIO()
    im.save(out, "JPEG", quality=90)
    return out.getvalue()
