import base64
import hashlib
import json

MODEL = "jev-1.14.0"


def image_ref(img: bytes) -> str:
    # 画像から決まる参照キー。UUIDだと同じ入力でもリクエストが変わり、キャッシュが効かない
    return "img-" + hashlib.sha256(img).hexdigest()[:16]


def build_request(profile: dict, img: bytes, *, source: str, locate: bool = False) -> dict:
    questions = dict(profile["questions"])
    if locate:
        # 料金は画像の入力トークンが大半なので、Box は別リクエストにせず同じリクエストで聞く
        questions["locate"] = {"type": "box", "instructions": profile["locate"]["instructions"]}
    ref = image_ref(img)
    return {
        "model": MODEL,
        "state": {"source": source, "image": ref},
        "assets": {
            ref: {
                "type": "image",
                "format": "jpg",
                "data_base64": base64.b64encode(img).decode("ascii"),
            }
        },
        "questions": questions,
    }


def request_key(body: dict) -> str:
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
