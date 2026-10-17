"""Discord Bot。`/dragon` とメッセージコンテキストメニュー「ドラゴン判定」で判定する。"""

import asyncio
import logging
import os
import sys

import discord
import httpx
from discord import app_commands
from PIL import UnidentifiedImageError

from is_it_dragon.adapters.cache_memory import MemoryCache
from is_it_dragon.adapters.fetch_image import MAX_BYTES, FetchError, fetch_image
from is_it_dragon.adapters.jev_httpx import Jev, JevError
from is_it_dragon.adapters.normalize_pil import normalize
from is_it_dragon.core.types import Verdict
from is_it_dragon.judge import cached, judge, load_profile

SOURCE = "An image posted in a Discord message"
MAX_IMAGES = 4
RESULT_TEXT = {
    "yes": "{label}がいます",
    "unsure": "{label}かどうか判断がつきません",
    "no": "{label}はいません",
}
COLORS = {
    "yes": discord.Color.green(),
    "unsure": discord.Color.gold(),
    "no": discord.Color.light_grey(),
}

log = logging.getLogger(__name__)

# 添付ファイル、または画像の URL
ImageItem = discord.Attachment | str


def message_images(message) -> list[ImageItem]:
    """添付の画像と、埋め込みの画像（なければサムネイル）を集める。"""
    items: list[ImageItem] = [a for a in message.attachments if (a.content_type or "").startswith("image/")]
    for embed in message.embeds:
        media = embed.image if embed.image.url else embed.thumbnail
        url = media.proxy_url or media.url
        if url and url not in items:
            items.append(url)
    return items


def item_url(item: ImageItem) -> str:
    return item.url if isinstance(item, discord.Attachment) else item


async def read_image(item: ImageItem, client: httpx.AsyncClient) -> bytes:
    # 添付の CDN URL は署名付きで失効するので、受け取ったその場でダウンロードする
    if isinstance(item, discord.Attachment):
        if item.size > MAX_BYTES:
            raise FetchError("too large")
        return await item.read()
    return await fetch_image(item, client)


def verdict_embed(v: Verdict, profile: dict, url: str) -> discord.Embed:
    embed = discord.Embed(
        title=RESULT_TEXT[v.result].format(label=profile["label"]),
        description=f"確率 {v.p:.0%}",
        color=COLORS[v.result],
    )
    # yes でないときの choice は当てにならないので出さない
    if v.result == "yes":
        for name, choice in v.details.items():
            embed.add_field(name=name, value=choice)
    embed.set_thumbnail(url=url)
    return embed


def error_message(e: Exception) -> str:
    match e:
        case FetchError():
            return f"画像を取得できませんでした（{e}）"
        case UnidentifiedImageError():
            return "対応していない画像形式です"
        case JevError():
            return f"判定 API がエラーを返しました（{e.status}）"
        case _:
            return "判定中にエラーが発生しました"


def error_embed(message: str, url: str) -> discord.Embed:
    embed = discord.Embed(title="判定できませんでした", description=message, color=discord.Color.red())
    embed.set_thumbnail(url=url)
    return embed


class Bot(discord.Client):
    def __init__(self, api_key: str):
        # インタラクションだけを扱うので Gateway Intents は不要
        super().__init__(intents=discord.Intents.none())
        self.tree = app_commands.CommandTree(self)
        self.profile = load_profile("dragon")
        self._api_key = api_key

    async def setup_hook(self) -> None:
        self.jev = Jev(self._api_key)
        self.fetcher = httpx.AsyncClient(timeout=10)
        self.send = cached(self.jev, MemoryCache())
        self.tree.add_command(dragon_command)
        self.tree.add_command(dragon_context_menu)
        await self.tree.sync()

    async def close(self) -> None:
        await self.jev.aclose()
        await self.fetcher.aclose()
        await super().close()

    async def judge_embed(self, item: ImageItem) -> discord.Embed:
        url = item_url(item)
        try:
            raw = await read_image(item, self.fetcher)
            v = await judge(raw, self.profile, normalize=normalize, send=self.send, source=SOURCE)
        except Exception as e:
            log.warning("judge failed: %s", url, exc_info=e)
            return error_embed(error_message(e), url)
        return verdict_embed(v, self.profile, url)

    async def reply(self, interaction: discord.Interaction, items: list[ImageItem]) -> None:
        embeds = await asyncio.gather(*(self.judge_embed(item) for item in items[:MAX_IMAGES]))
        content = f"画像が多いため、先頭の{MAX_IMAGES}枚だけ判定しました" if len(items) > MAX_IMAGES else None
        await interaction.followup.send(content=content, embeds=list(embeds))


@app_commands.command(name="dragon", description="画像にドラゴンがいるか判定します")
@app_commands.describe(url="画像の URL")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def dragon_command(interaction: discord.Interaction, url: str) -> None:
    await interaction.response.defer(thinking=True)
    await interaction.client.reply(interaction, [url])


@app_commands.context_menu(name="ドラゴン判定")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def dragon_context_menu(interaction: discord.Interaction, message: discord.Message) -> None:
    await interaction.response.defer(thinking=True)
    items = message_images(message)
    if not items:
        await interaction.followup.send("このメッセージには画像がありません")
        return
    await interaction.client.reply(interaction, items)


def main() -> None:
    token = os.environ.get("DISCORD_TOKEN")
    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not token or not api_key:
        sys.exit("DISCORD_TOKEN と TYPESAFE_API_KEY を設定してください")
    Bot(api_key).run(token)
