from types import SimpleNamespace

from PIL import UnidentifiedImageError

from is_it_dragon.adapters.fetch_image import FetchError
from is_it_dragon.adapters.jev_httpx import JevError
from is_it_dragon.apps.discord_bot import error_message, message_images, verdict_embed
from is_it_dragon.core.types import Verdict
from is_it_dragon.judge import load_profile

PROFILE = load_profile("dragon")


def media(url=None, proxy_url=None):
    return SimpleNamespace(url=url, proxy_url=proxy_url)


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
    )
    assert message_images(message) == [png, "https://proxy/big.jpg", "https://proxy/t.jpg"]


def test_verdict_embed_shows_details_only_on_yes():
    yes = verdict_embed(Verdict("dragon", "yes", 0.97, {"kind": "western"}), PROFILE, "https://x/a.png")
    assert yes.title == "ドラゴンがいます"
    assert yes.description == "確率 97%"
    assert [(f.name, f.value) for f in yes.fields] == [("kind", "western")]
    assert yes.thumbnail.url == "https://x/a.png"

    no = verdict_embed(Verdict("dragon", "no", 0.05, {"kind": "wyvern"}), PROFILE, "https://x/a.png")
    assert no.title == "ドラゴンはいません"
    assert no.fields == []


def test_error_message():
    assert "too large" in error_message(FetchError("too large"))
    assert error_message(UnidentifiedImageError()) == "対応していない画像形式です"
    assert "429" in error_message(JevError(429, ""))
    assert error_message(RuntimeError()) == "判定中にエラーが発生しました"
