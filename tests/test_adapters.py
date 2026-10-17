import asyncio
from io import BytesIO

import pytest
from PIL import Image

from is_it_dragon.adapters.fetch_image import FetchError, check_host, fetch_image
from is_it_dragon.adapters.normalize_pil import MAX_SIDE, MIN_SIDE, normalize


def encode(img: Image.Image, fmt: str, **kwargs) -> bytes:
    out = BytesIO()
    img.save(out, fmt, **kwargs)
    return out.getvalue()


def decode(data: bytes) -> Image.Image:
    img = Image.open(BytesIO(data))
    img.load()
    return img


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        ((4032, 3024), (1568, 1176)),  # 縮小
        ((100, 50), (560, 280)),  # 拡大
        ((800, 600), (800, 600)),  # そのまま
        ((3000, 100), (1568, 280)),  # 極端な縦横比はパディング
        ((100, 3000), (280, 1568)),
    ],
)
def test_normalize_size(size, expected):
    out = decode(normalize(encode(Image.new("RGB", size, "red"), "PNG")))
    assert out.format == "JPEG"
    assert out.size == expected
    assert MIN_SIDE <= min(out.size) and max(out.size) <= MAX_SIDE


def test_normalize_is_baseline_jpeg():
    out = decode(normalize(encode(Image.new("RGB", (400, 400)), "JPEG", progressive=True)))
    assert not out.info.get("progressive")


def test_normalize_transparent_becomes_white():
    out = decode(normalize(encode(Image.new("RGBA", (400, 400), (0, 0, 0, 0)), "PNG")))
    assert out.getpixel((200, 200)) == (255, 255, 255)


def test_normalize_applies_exif_orientation():
    img = Image.new("RGB", (600, 300), "blue")
    exif = Image.Exif()
    exif[0x0112] = 6  # 90度回転して表示する
    out = decode(normalize(encode(img, "JPEG", exif=exif)))
    assert out.size == (300, 600)


def test_normalize_takes_first_frame():
    frames = [Image.new("RGB", (400, 400), c) for c in ("red", "blue")]
    gif = BytesIO()
    frames[0].save(gif, "GIF", save_all=True, append_images=frames[1:])
    r, _, b = decode(normalize(gif.getvalue())).getpixel((200, 200))
    assert r > 200 and b < 50


@pytest.mark.parametrize("host", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "::ffff:127.0.0.1"])
def test_check_host_blocks_internal(host):
    with pytest.raises(FetchError):
        asyncio.run(check_host(host, 80))


def test_check_host_allows_global():
    asyncio.run(check_host("1.1.1.1", 443))


def test_fetch_rejects_non_http():
    with pytest.raises(FetchError):
        asyncio.run(fetch_image("file:///etc/passwd", None))
