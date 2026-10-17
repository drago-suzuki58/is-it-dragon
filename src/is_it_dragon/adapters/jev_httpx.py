import asyncio

import httpx

URL = "https://api.typesafe.ai/v1/systemone"
RETRY_STATUS = {429, 529}


class JevError(Exception):
    def __init__(self, status: int, body: str):
        super().__init__(f"Jev API {status}: {body}")
        self.status = status
        self.body = body


class Jev:
    """Transport の httpx 実装。429 / 529 は指数バックオフで再試行する。"""

    def __init__(self, api_key: str, *, timeout: float = 60, max_retries: int = 3):
        self._client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {api_key}",
                "TypeSafe-Danger-Zone-Images": "true",
            },
            timeout=timeout,
        )
        self._max_retries = max_retries

    async def __call__(self, body: dict) -> dict:
        for attempt in range(self._max_retries + 1):
            r = await self._client.post(URL, json=body)
            if r.status_code in RETRY_STATUS and attempt < self._max_retries:
                await asyncio.sleep(2**attempt)
                continue
            if r.is_error:
                raise JevError(r.status_code, r.text)
            return r.json()
        raise AssertionError("unreachable")

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.aclose()
