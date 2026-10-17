import asyncio
import ipaddress
import socket

import httpx

MAX_BYTES = 20 * 1024 * 1024
MAX_REDIRECTS = 3


class FetchError(Exception):
    pass


async def fetch_image(url: str, client: httpx.AsyncClient) -> bytes:
    """http(s) の画像を取得する。内部アドレス宛てと画像以外の応答は拒否する。

    名前解決とリクエストの間に DNS が書き換わる攻撃（DNS rebinding）は防げない。
    """
    target = httpx.URL(url)
    for _ in range(MAX_REDIRECTS + 1):
        if target.scheme not in ("http", "https"):
            raise FetchError("http(s) の URL ではありません")
        await check_host(target.host, target.port or (443 if target.scheme == "https" else 80))
        try:
            async with client.stream("GET", target, follow_redirects=False) as r:
                if r.is_redirect:
                    target = target.join(r.headers["location"])
                    continue
                if r.is_error:
                    raise FetchError(f"HTTP {r.status_code}")
                ctype = r.headers.get("content-type", "").split(";")[0].strip()
                if not ctype.startswith("image/"):
                    raise FetchError(f"画像ではありません（{ctype or 'Content-Type なし'}）")
                if int(r.headers.get("content-length") or 0) > MAX_BYTES:
                    raise too_large()
                buf = bytearray()
                async for chunk in r.aiter_bytes():
                    buf += chunk
                    if len(buf) > MAX_BYTES:
                        raise too_large()
                return bytes(buf)
        except httpx.TimeoutException as e:
            raise FetchError("タイムアウトしました") from e
        except httpx.TransportError as e:
            raise FetchError("接続できませんでした") from e
    raise FetchError("リダイレクトが多すぎます")


def too_large() -> FetchError:
    return FetchError(f"{MAX_BYTES // 1024 // 1024}MiB を超えています")


async def check_host(host: str, port: int) -> None:
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise FetchError(f"ホスト名を解決できません（{host}）") from e
    for *_, sockaddr in infos:
        ip = ipaddress.ip_address(sockaddr[0])
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not ip.is_global:
            raise FetchError("内部ネットワークのアドレスには接続しません")
