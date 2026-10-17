import asyncio
import base64

from is_it_dragon.adapters.cache_memory import MemoryCache
from is_it_dragon.core.request import build_request, image_ref, request_key
from is_it_dragon.core.types import Box
from is_it_dragon.core.verdict import to_verdict
from is_it_dragon.judge import cached, judge, load_profile

PROFILE = load_profile("dragon")
IMG = b"\xff\xd8fake-jpeg"


BOX = {"top": 0.1, "bottom": 0.9, "left": 0.2, "right": 0.8}


def answers(p: float, kind: str = "western", *, locate: bool = False) -> dict:
    a = {
        "is_target": {"type": "noul", "noul": p},
        "kind": {"type": "choice", "choice": kind, "probabilities": {kind: 1.0}, "confidence": 1.0},
    }
    if locate:
        a["locate"] = {"type": "box", "box": BOX, "confidence": 0.9}
    return a


def test_build_request_references_image_in_state():
    body = build_request(PROFILE, IMG, source="test")
    ref = image_ref(IMG)
    assert body["model"] == "jev-1.14.0"
    assert body["state"] == {"source": "test", "image": ref}
    assert base64.b64decode(body["assets"][ref]["data_base64"]) == IMG
    assert body["questions"] == PROFILE["questions"]


def test_request_is_deterministic():
    a = build_request(PROFILE, IMG, source="test")
    b = build_request(PROFILE, IMG, source="test")
    assert request_key(a) == request_key(b)
    assert request_key(a) != request_key(build_request(PROFILE, IMG + b"x", source="test"))


def test_locate_adds_box_question():
    body = build_request(PROFILE, IMG, source="test", locate=True)
    assert body["questions"] == {
        **PROFILE["questions"],
        "locate": {"type": "box", "instructions": PROFILE["locate"]["instructions"]},
    }


def test_thresholds():
    assert to_verdict(PROFILE, answers(0.8)).result == "yes"
    assert to_verdict(PROFILE, answers(0.79)).result == "unsure"
    assert to_verdict(PROFILE, answers(0.21)).result == "unsure"
    assert to_verdict(PROFILE, answers(0.2)).result == "no"


def test_verdict_details_and_box():
    v = to_verdict(PROFILE, answers(0.9, "eastern", locate=True))
    assert v.details == {"kind": "eastern"}
    assert v.box == Box(top=0.1, left=0.2, bottom=0.9, right=0.8)


def test_box_ignored_unless_yes():
    assert to_verdict(PROFILE, answers(0.5, locate=True)).box is None
    assert to_verdict(PROFILE, answers(0.1, locate=True)).box is None


class FakeJev:
    def __init__(self, p: float):
        self.p = p
        self.bodies: list[dict] = []

    async def __call__(self, body: dict) -> dict:
        self.bodies.append(body)
        return {"answers": answers(self.p, locate="locate" in body["questions"])}


def run_judge(send, *, locate: bool):
    return asyncio.run(judge(IMG, PROFILE, normalize=lambda raw: raw, send=send, source="test", locate=locate))


def test_judge_locates_in_single_request():
    jev = FakeJev(0.95)
    assert run_judge(jev, locate=True).box is not None
    assert len(jev.bodies) == 1
    assert run_judge(FakeJev(0.95), locate=False).box is None


def test_cached_skips_second_call():
    jev = FakeJev(0.95)
    send = cached(jev, MemoryCache())
    run_judge(send, locate=False)
    run_judge(send, locate=False)
    assert len(jev.bodies) == 1


def test_memory_cache_evicts_oldest():
    cache = MemoryCache(max_items=2)
    cache.set("a", {})
    cache.set("b", {})
    cache.get("a")
    cache.set("c", {})
    assert cache.get("b") is None
    assert cache.get("a") is not None
