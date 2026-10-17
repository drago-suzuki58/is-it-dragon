from types import SimpleNamespace

from PIL import UnidentifiedImageError

from is_it_dragon.adapters.fetch_image import FetchError
from is_it_dragon.adapters.jev_httpx import JevError
from is_it_dragon.apps.discord_bot import error_message, format_probabilities, message_images, verdict_embed
from is_it_dragon.core.verdict import to_verdict
from is_it_dragon.judge import load_profile

PROFILE = load_profile("dragon")


def media(url=None, proxy_url=None):
    return SimpleNamespace(url=url, proxy_url=proxy_url)


def response(p: float, *, cached: bool = False) -> dict:
    resp = {
        "model": "jev-1.14.0",
        "answers": {
            "is_target": {"type": "noul", "noul": p},
            "kind": {
                "type": "choice",
                "choice": "western",
                "probabilities": {"western": 0.49, "wyvern": 0.2, "eastern": 0.0, "anthro": 0.31, "none": 0.0},
                "confidence": 0.36,
            },
            "locate": {
                "type": "box",
                "box": {"top": 0.02, "bottom": 0.98, "left": 0.1, "right": 0.9},
                "confidence": 0.75,
            },
        },
        "usage": {"input_tokens": 4657, "output_tokens": 90},
    }
    return {**resp, "cached": True} if cached else resp


def test_message_images_collects_attachments_and_embeds():
    png = SimpleNamespace(content_type="image/png", url="https://cdn/a.png")
    txt = SimpleNamespace(content_type="text/plain", url="https://cdn/a.txt")
    message = SimpleNamespace(
        attachments=[png, txt],
        embeds=[
            # 画像があればサムネイルより優先し、プロキシの URL を使う
            SimpleNamespace(
                image=media("https://x/big.jpg", "https://proxy/big.jpg"), thumbnail=media("https://x/s.jpg")
            ),
            SimpleNamespace(image=media(), thumbnail=media("https://x/t.jpg", "https://proxy/t.jpg")),
            SimpleNamespace(image=media(), thumbnail=media("https://x/t.jpg", "https://proxy/t.jpg")),
            SimpleNamespace(image=media(), thumbnail=media()),
        ],
        message_snapshots=[],
    )
    assert message_images(message) == [png, "https://proxy/big.jpg", "https://proxy/t.jpg"]


def test_message_images_reads_forwarded_message():
    png = SimpleNamespace(content_type="image/png", url="https://cdn/fwd.png")
    snapshot = SimpleNamespace(
        attachments=[png],
        embeds=[SimpleNamespace(image=media("https://x/e.jpg"), thumbnail=media())],
    )
    message = SimpleNamespace(attachments=[], embeds=[], message_snapshots=[snapshot])
    assert message_images(message) == [png, "https://x/e.jpg"]


def test_format_probabilities_ranks_and_drops_zero():
    assert format_probabilities({"a": 0.2, "b": 0.0, "c": 0.8}) == "c 80% ・ a 20%"


def test_verdict_embed_yes_shows_details_and_box_image():
    v = to_verdict(PROFILE, response(0.97))
    embed = verdict_embed(v, PROFILE, "https://x/a.png", box_image_url="https://cdn/box.jpg")
    assert embed.title == "ドラゴンがいます"
    assert embed.description == "確率 97%"
    fields = {f.name: f.value for f in embed.fields}
    assert fields["kind"] == "western 49% ・ anthro 31% ・ wyvern 20%\n信頼度 0.36"
    assert fields["位置"] == "top 0.02 / left 0.10 / bottom 0.98 / right 0.90\n信頼度 0.75"
    assert embed.footer.text == "jev-1.14.0 ・ 4,657 tokens"
    assert embed.image.url == "https://cdn/box.jpg"
    assert embed.thumbnail.url is None


def test_verdict_embed_no_hides_details():
    embed = verdict_embed(to_verdict(PROFILE, response(0.05, cached=True)), PROFILE, "https://x/a.png")
    assert embed.title == "ドラゴンはいません"
    assert embed.fields == []
    assert embed.footer.text == "jev-1.14.0 ・ 4,657 tokens ・ キャッシュ"
    assert embed.thumbnail.url == "https://x/a.png"


def test_verdict_embed_without_url_has_no_image():
    embed = verdict_embed(to_verdict(PROFILE, response(0.5)), PROFILE, None)
    assert embed.title == "ドラゴンかどうか判断がつきません"
    assert "kind" in {f.name for f in embed.fields}
    assert embed.thumbnail.url is None and embed.image.url is None


def test_error_message():
    assert "too large" in error_message(FetchError("too large"))
    assert error_message(UnidentifiedImageError()) == "対応していない画像形式です"
    assert "429" in error_message(JevError(429, ""))
    assert error_message(RuntimeError()) == "判定中にエラーが発生しました"
