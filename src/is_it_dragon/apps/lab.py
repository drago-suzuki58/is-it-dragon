"""プロンプトと画像を試すための CLI。"""

import argparse
import asyncio
import json
import os
import sys
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

from is_it_dragon.adapters.cache_disk import DiskCache
from is_it_dragon.adapters.fetch_image import fetch_image
from is_it_dragon.adapters.jev_httpx import Jev
from is_it_dragon.adapters.normalize_pil import normalize
from is_it_dragon.apps.discord_bot import SOURCE
from is_it_dragon.core.request import build_request, request_key
from is_it_dragon.core.types import Box, Transport
from is_it_dragon.judge import PROFILES_DIR, judge, load_profile

CACHE_DIR = PROFILES_DIR.parent / ".cache" / "lab"
DEFAULT_SOURCE = SOURCE  # Bot と同じ条件で試す
USD_PER_INPUT_TOKEN = 0.042 / 1_000_000


async def read_input(src: str) -> bytes:
    if src.startswith(("http://", "https://")):
        async with httpx.AsyncClient(timeout=10) as client:
            return await fetch_image(src, client)
    return Path(src).read_bytes()


def input_stem(src: str) -> str:
    return Path(httpx.URL(src).path if "://" in src else src).stem or "image"


def traced(send: Transport, cache: DiskCache | None, log: list) -> Transport:
    """キャッシュを挟み、応答とキャッシュヒットの有無を log に残す。"""

    async def send_traced(body: dict) -> dict:
        key = request_key(body)
        hit = cache.get(key) if cache else None
        resp = hit if hit is not None else await send(body)
        if cache and hit is None:
            cache.set(key, resp)
        log.append((resp, hit is not None))
        return resp

    return send_traced


def draw_box(img: bytes, box: Box, out: Path) -> None:
    im = Image.open(BytesIO(img))
    w, h = im.size
    rect = (box.left * w, box.top * h, box.right * w, box.bottom * h)
    ImageDraw.Draw(im).rectangle(rect, outline="red", width=max(2, w // 200))
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out, "JPEG", quality=90)


async def cmd_try(args: argparse.Namespace) -> None:
    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not api_key:
        sys.exit("TYPESAFE_API_KEY が設定されていません")
    profiles = [(p, load_profile(p)) for p in args.profile or ["dragon"]]
    cache = None if args.no_cache else DiskCache(CACHE_DIR)
    async with Jev(api_key) as jev:
        for i, src in enumerate(args.inputs):
            print(src)
            raw = await read_input(src)
            for label, profile in profiles:
                log: list = []
                v = await judge(
                    raw,
                    profile,
                    normalize=normalize,
                    send=traced(jev, cache, log),
                    source=args.source,
                    locate=args.box is not None,
                )
                details = "  ".join(f"{k}={c}" for k, c in v.details.items())
                print(f"  [{label}] {v.result}  p={v.p:.3f}  {details}")
                if v.box:
                    b = v.box
                    out = args.box / f"{i:02d}-{input_stem(src)}.{Path(label).stem}.jpg"
                    draw_box(normalize(raw), b, out)
                    print(
                        f"    box  top={b.top:.2f} left={b.left:.2f} bottom={b.bottom:.2f} right={b.right:.2f}  -> {out}"
                    )
                for resp, hit in log:
                    tokens = resp["usage"]["input_tokens"]
                    cost = tokens * USD_PER_INPUT_TOKEN
                    print(f"    {resp['model']}  {tokens} tokens (~${cost:.6f}){'  cached' if hit else ''}")
                    print(f"    answers {json.dumps(resp['answers'], ensure_ascii=False)}")


async def cmd_request(args: argparse.Namespace) -> None:
    img = normalize(await read_input(args.input))
    body = build_request(load_profile(args.profile), img, source=args.source)
    for asset in body["assets"].values():
        asset["data_base64"] = f"<{len(img)} bytes>"
    print(json.dumps(body, ensure_ascii=False, indent=2))


async def cmd_normalize(args: argparse.Namespace) -> None:
    raw = await read_input(args.input)
    img = normalize(raw)
    args.output.write_bytes(img)
    with Image.open(BytesIO(raw)) as before, Image.open(BytesIO(img)) as after:
        print(f"{before.format} {before.size[0]}x{before.size[1]} {len(raw)} bytes")
        print(f"-> JPEG {after.size[0]}x{after.size[1]} {len(img)} bytes  {args.output}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="lab", description=__doc__)
    sub = parser.add_subparsers(required=True)

    p = sub.add_parser("try", help="画像を判定し、生の応答とトークン数を表示する")
    p.add_argument("inputs", nargs="+", help="画像ファイルのパスまたは http(s) URL")
    p.add_argument("-p", "--profile", action="append", help="プロファイル名またはパス。複数指定で比較（既定: dragon）")
    p.add_argument(
        "--box", type=Path, metavar="DIR", help="位置（Box）も聞き、yes のとき枠を描いた画像を DIR に保存する"
    )
    p.add_argument("--no-cache", action="store_true", help="キャッシュを使わずに API を呼ぶ")
    p.add_argument("--source", default=DEFAULT_SOURCE, help="state.source に入れる文言")
    p.set_defaults(func=cmd_try)

    p = sub.add_parser("request", help="送信するリクエスト本文を表示する（API は呼ばない）")
    p.add_argument("input")
    p.add_argument("-p", "--profile", default="dragon")
    p.add_argument("--source", default=DEFAULT_SOURCE)
    p.set_defaults(func=cmd_request)

    p = sub.add_parser("normalize", help="正規化後の画像を書き出す")
    p.add_argument("input")
    p.add_argument("-o", "--output", type=Path, required=True)
    p.set_defaults(func=cmd_normalize)

    args = parser.parse_args()
    asyncio.run(args.func(args))
