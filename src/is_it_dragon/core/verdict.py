from is_it_dragon.core.types import Box, Verdict


def to_verdict(profile: dict, answers: dict) -> Verdict:
    p = answers[profile["main"]]["noul"]
    th = profile["thresholds"]
    result = "yes" if p >= th["yes"] else "no" if p <= th["no"] else "unsure"
    details = {k: a["choice"] for k, a in answers.items() if a["type"] == "choice"}
    # Box は対象がなくても必ず返るので、yes のときだけ採用する
    box = None
    if result == "yes" and "locate" in answers:
        b = answers["locate"]["box"]
        box = Box(top=b["top"], left=b["left"], bottom=b["bottom"], right=b["right"])
    return Verdict(profile["id"], result, p, details, box)
