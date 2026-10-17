"""Discord Bot。`/dragon` とメッセージコンテキストメニュー「ドラゴン判定」で判定する。"""

import asyncio
import logging
import os
import sys
from io import BytesIO

import discord
import httpx
from discord import app_commands
from PIL import UnidentifiedImageError

from is_it_dragon.adapters.cache_memory import MemoryCache
from is_it_dragon.adapters.draw_pil import draw_box
from is_it_dragon.adapters.fetch_image import MAX_BYTES, FetchError, fetch_image, too_large
from is_it_dragon.adapters.jev_httpx import Jev, JevError
from is_it_dragon.adapters.normalize_pil import normalize
from is_it_dragon.core.types import Verdict
from is_it_dragon.judge import cached, judge, load_profile

SOURCE = "An image posted in a Discord message"
MAX_IMAGES = 4
RESULT_TEXT = {
    "yes": "{label}がいます",
    "maybe_yes": "たぶん{label}がいます",
    "maybe_no": "たぶん{label}はいません",
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
    """添付の画像と、埋め込みの画像（なければサムネイル）を集める。転送されたメッセージは転送元の中身も見る。"""
    items: list[ImageItem] = []
    for m in [message, *message.message_snapshots]:
        items += [a for a in m.attachments if (a.content_type or "").startswith("image/")]
        for embed in m.embeds:
            media = embed.image if embed.image.url else embed.thumbnail
            url = media.proxy_url or media.url
            if url and url not in items:
                items.append(url)
    return items


def item_url(item: ImageItem) -> str:
    return item.url if isinstance(item, discord.Attachment) else item


def is_spoiler(item: ImageItem) -> bool:
    return isinstance(item, discord.Attachment) and item.is_spoiler()


async def read_image(item: ImageItem, client: httpx.AsyncClient) -> bytes:
    # 添付の CDN URL は署名付きで失効するので、受け取ったその場でダウンロードする
    if isinstance(item, discord.Attachment):
        if not (item.content_type or "").startswith("image/"):
            raise FetchError(f"画像ではありません（{item.content_type or 'Content-Type なし'}）")
        if item.size > MAX_BYTES:
            raise too_large()
        return await item.read()
    return await fetch_image(item, client)


def format_probabilities(probabilities: dict[str, float], names: dict[str, str]) -> str:
    ranked = sorted(probabilities.items(), key=lambda kv: kv[1], reverse=True)
    return " ・ ".join(f"{names.get(k, k)} {p:.0%}" for k, p in ranked if p >= 0.005)


def result_title(v: Verdict, label: str) -> str:
    """unsure は p が 0.5 以上か未満かで言い方を分ける（判定の結果そのものは変えない）。"""
    key = v.result if v.result != "unsure" else "maybe_yes" if v.p >= 0.5 else "maybe_no"
    return RESULT_TEXT[key].format(label=label)


def verdict_embed(
    v: Verdict,
    profile: dict,
    url: str | None,
    *,
    box_image_url: str | None = None,
    link: str | None = None,
) -> discord.Embed:
    """url は元画像（スポイラーなら None）。box_image_url は枠を描いた画像。link はタイトルのリンク先。"""
    answers = v.response["answers"]
    label = profile["label"]
    embed = discord.Embed(
        title=result_title(v, label),
        url=link,
        description=f"{label}がいる確率 {v.p:.0%}",
        color=COLORS[v.result],
    )
    # no のときの choice は当てにならないので出さない
    if v.result != "no":
        for name, a in answers.items():
            if a["type"] == "choice":
                display = profile.get("display", {}).get(name, {})
                field = display.get("label", name)
                probabilities = format_probabilities(a["probabilities"], display.get("options", {}))
                value = f"{probabilities}\n{field}の確信度 {a['confidence']:.2f}"
                # choice は対象がいる前提で答えるので、unsure のときは前提を見出しに書く
                heading = f"{field}（{label}だとしたら）" if v.result == "unsure" else field
                embed.add_field(name=heading, value=value, inline=False)
    if v.box:
        b = v.box
        value = f"top {b.top:.2f} / left {b.left:.2f} / bottom {b.bottom:.2f} / right {b.right:.2f}"
        embed.add_field(name="位置", value=f"{value}\n位置の確信度 {answers['locate']['confidence']:.2f}", inline=False)
    footer = f"{v.response['model']} ・ {v.response['usage']['input_tokens']:,} tokens"
    embed.set_footer(text=footer + (" ・ キャッシュ" if v.response.get("cached") else ""))
    if box_image_url:
        embed.set_image(url=box_image_url)
    elif url:
        embed.set_thumbnail(url=url)
    return embed


def error_message(e: Exception) -> str:
    match e:
        case FetchError():
            return f"画像を取得できませんでした（{e}）"
        case UnidentifiedImageError():
            return "対応していない画像形式です"
        case JevError(status=400 | 413):
            return "判定 API が画像を受け付けませんでした"
        case JevError(status=401):
            return "判定 API のキーが無効です"
        case JevError(status=429 | 529):
            return "判定 API が混み合っています。少し待ってから試してください"
        case JevError():
            return f"判定 API がエラーを返しました（{e.status}）"
        case httpx.TimeoutException():
            return "判定 API の応答がタイムアウトしました"
        case _:
            return "判定中にエラーが発生しました"


def error_embed(message: str, url: str | None, link: str | None = None) -> discord.Embed:
    embed = discord.Embed(title="判定できませんでした", url=link, description=message, color=discord.Color.red())
    if url:
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

    async def judge_embed(
        self, item: ImageItem, index: int, link: str | None
    ) -> tuple[discord.Embed, discord.File | None]:
        """判定結果の Embed と、枠を描いた画像の添付ファイル（なければ None）を返す。"""
        # スポイラーの画像は、Embed に出すとぼかしなしで見えてしまうので出さない
        url = None if is_spoiler(item) else item_url(item)
        try:
            raw = await read_image(item, self.fetcher)
            v = await judge(raw, self.profile, normalize=normalize, send=self.send, source=SOURCE, locate=True)
        except Exception as e:
            log.warning("judge failed: %s", item_url(item), exc_info=e)
            return error_embed(error_message(e), url, link), None
        if not (v.box and url):
            return verdict_embed(v, self.profile, url, link=link), None
        jpg = await asyncio.to_thread(lambda: draw_box(normalize(raw), v.box))
        file = discord.File(BytesIO(jpg), filename=f"box{index}.jpg")
        embed = verdict_embed(v, self.profile, url, box_image_url=f"attachment://{file.filename}", link=link)
        return embed, file

    async def reply(self, interaction: discord.Interaction, items: list[ImageItem], link: str | None = None) -> None:
        """link を渡すと、各 Embed のタイトルをそのリンク（判定したメッセージ）にする。"""
        tasks = (self.judge_embed(item, i, link) for i, item in enumerate(items[:MAX_IMAGES]))
        results = await asyncio.gather(*tasks)
        content = f"画像が多いため、先頭の{MAX_IMAGES}枚だけ判定しました" if len(items) > MAX_IMAGES else None
        embeds = [embed for embed, _ in results]
        files = [file for _, file in results if file]
        await interaction.followup.send(content=content, embeds=embeds, files=files)


@app_commands.command(name="dragon", description="画像にドラゴンがいるか判定します")
@app_commands.describe(url="画像の URL", image="画像ファイル")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def dragon_command(
    interaction: discord.Interaction, url: str | None = None, image: discord.Attachment | None = None
) -> None:
    items: list[ImageItem] = [x for x in (image, url) if x]
    if not items:
        await interaction.response.send_message("`url` か `image` のどちらかを指定してください", ephemeral=True)
        return
    await interaction.response.defer(thinking=True)
    await interaction.client.reply(interaction, items)


@app_commands.context_menu(name="ドラゴン判定")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def dragon_context_menu(interaction: discord.Interaction, message: discord.Message) -> None:
    await interaction.response.defer(thinking=True)
    items = message_images(message)
    if not items:
        await interaction.followup.send("このメッセージには画像がありません")
        return
    await interaction.client.reply(interaction, items, link=message.jump_url)


def main() -> None:
    token = os.environ.get("DISCORD_TOKEN")
    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not token or not api_key:
        sys.exit("DISCORD_TOKEN と TYPESAFE_API_KEY を設定してください")
    Bot(api_key).run(token)
