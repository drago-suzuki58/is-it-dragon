"""プロンプトと画像を試すための CLI。"""

import argparse
import asyncio
import json
import os
import sys
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image

from is_it_dragon.adapters.cache_disk import DiskCache
from is_it_dragon.adapters.draw_pil import draw_box
from is_it_dragon.adapters.fetch_image import fetch_image
from is_it_dragon.adapters.jev_httpx import Jev
from is_it_dragon.adapters.normalize_pil import normalize
from is_it_dragon.apps.discord_bot import SOURCE
from is_it_dragon.core.request import build_request
from is_it_dragon.core.types import Transport
from is_it_dragon.judge import PROFILES_DIR, cached, judge, load_profile

CACHE_DIR = PROFILES_DIR.parent / ".cache" / "lab"
DEFAULT_SOURCE = SOURCE  # Bot と同じ条件で試す
USD_PER_INPUT_TOKEN = 0.042 / 1_000_000
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


async def read_input(src: str) -> bytes:
    if src.startswith(("http://", "https://")):
        async with httpx.AsyncClient(timeout=10) as client:
            return await fetch_image(src, client)
    return Path(src).read_bytes()


def input_stem(src: str) -> str:
    return Path(httpx.URL(src).path if "://" in src else src).stem or "image"


def expand_inputs(inputs: list[str]) -> list[str]:
    """ディレクトリは、その直下の画像ファイルに展開する。"""
    sources = []
    for src in inputs:
        path = Path(src)
        if "://" not in src and path.is_dir():
            sources += sorted(str(f) for f in path.iterdir() if f.suffix.lower() in IMAGE_SUFFIXES)
        else:
            sources.append(src)
    return sources


def describe(e: Exception) -> str:
    return f"{type(e).__name__}: {e}"


async def try_one(
    i: int, src: str, profiles: list[tuple[str, dict]], send: Transport, args: argparse.Namespace
) -> tuple[list[str], bool]:
    """1つの入力を全プロファイルで判定し、出力する行と、すべて成功したかを返す。"""
    lines = [src]
    try:
        raw = await read_input(src)
    except Exception as e:  # noqa: BLE001  1つの入力の失敗で全体を止めない
        return [*lines, f"  error  {describe(e)}"], False
    ok = True
    for label, profile in profiles:
        try:
            # Bot と同じく位置（Box）も同じリクエストで聞く
            v = await judge(raw, profile, normalize=normalize, send=send, source=args.source, locate=True)
        except Exception as e:  # noqa: BLE001
            lines.append(f"  [{label}] error  {describe(e)}")
            ok = False
            continue
        details = "  ".join(f"{k}={c}" for k, c in v.details.items())
        lines.append(f"  [{label}] {v.result}  p={v.p:.3f}  {details}")
        if v.box:
            b = v.box
            lines.append(f"    box  top={b.top:.2f} left={b.left:.2f} bottom={b.bottom:.2f} right={b.right:.2f}")
            if args.box:
                out = args.box / f"{i:02d}-{input_stem(src)}.{Path(label).stem}.jpg"
                out.parent.mkdir(parents=True, exist_ok=True)
                img = await asyncio.to_thread(normalize, raw)
                out.write_bytes(await asyncio.to_thread(draw_box, img, b))
                lines.append(f"    -> {out}")
        resp = v.response
        tokens = resp["usage"]["input_tokens"]
        cost = tokens * USD_PER_INPUT_TOKEN
        lines.append(f"    {resp['model']}  {tokens} tokens (~${cost:.6f}){'  cached' if resp.get('cached') else ''}")
        lines.append(f"    answers {json.dumps(resp['answers'], ensure_ascii=False)}")
    return lines, ok


async def cmd_try(args: argparse.Namespace) -> None:
    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not api_key:
        sys.exit("TYPESAFE_API_KEY が設定されていません")
    profiles = [(p, load_profile(p)) for p in args.profile or ["dragon"]]
    sources = expand_inputs(args.inputs)
    sem = asyncio.Semaphore(args.jobs)

    async def run(i: int, src: str) -> tuple[list[str], bool]:
        async with sem:
            return await try_one(i, src, profiles, send, args)

    failed = 0
    async with Jev(api_key) as jev:
        send = jev if args.no_cache else cached(jev, DiskCache(CACHE_DIR))
        tasks = [asyncio.create_task(run(i, src)) for i, src in enumerate(sources)]
        # 並列に判定し、入力の順に出力する
        for task in tasks:
            lines, ok = await task
            print("\n".join(lines), flush=True)
            failed += not ok
    if failed:
        sys.exit(f"{failed} 件の入力で失敗しました")


async def cmd_request(args: argparse.Namespace) -> None:
    img = normalize(await read_input(args.input))
    body = build_request(load_profile(args.profile), img, source=args.source, locate=True)
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
    p.add_argument("inputs", nargs="+", help="画像ファイルかディレクトリのパス、または http(s) URL")
    p.add_argument("-p", "--profile", action="append", help="プロファイル名またはパス。複数指定で比較（既定: dragon）")
    p.add_argument("--box", type=Path, metavar="DIR", help="yes のとき、枠を描いた画像を DIR に保存する")
    p.add_argument("--no-cache", action="store_true", help="キャッシュを使わずに API を呼ぶ")
    p.add_argument("--source", default=DEFAULT_SOURCE, help="state.source に入れる文言")
    p.add_argument("-j", "--jobs", type=int, default=4, help="同時に判定する入力の数（既定: 4）")
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
