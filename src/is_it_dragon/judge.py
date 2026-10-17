import asyncio
import json
from pathlib import Path

from is_it_dragon.core.request import build_request, request_key
from is_it_dragon.core.types import Cache, Normalizer, Transport, Verdict
from is_it_dragon.core.verdict import to_verdict

PROFILES_DIR = Path(__file__).resolve().parents[2] / "profiles"


def load_profile(name_or_path: str) -> dict:
    """`dragon` のような名前なら profiles/ から、それ以外はパスとして読む。"""
    path = Path(name_or_path)
    if path.suffix != ".json":
        path = PROFILES_DIR / f"{name_or_path}.json"
    return json.loads(path.read_text())


async def judge(
    raw: bytes,
    profile: dict,
    *,
    normalize: Normalizer,
    send: Transport,
    source: str,
    locate: bool = False,
) -> Verdict:
    img = await asyncio.to_thread(normalize, raw)
    resp = await send(build_request(profile, img, source=source, locate=locate and "locate" in profile))
    return to_verdict(profile, resp)


def cached(send: Transport, cache: Cache) -> Transport:
    """リクエスト本文のハッシュをキーに応答をキャッシュする。ヒットした応答には `"cached": True` を付ける。"""

    async def send_cached(body: dict) -> dict:
        key = request_key(body)
        if (hit := cache.get(key)) is not None:
            return {**hit, "cached": True}
        resp = await send(body)
        cache.set(key, resp)
        return resp

    return send_cached
