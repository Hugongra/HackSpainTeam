"""
Banco de casos VISTOS EN DIRECTO en los que AngryRobot se equivocó (lab/judge_cases.json). Así es como
"aprende" el auditor: no reentrena ningún modelo (el juez es un LLM ajeno con un prompt nuestro), guarda
el caso exacto que falló y lo vuelve a comprobar contra el JUEZ REAL cada vez que alguien toca el prompt.
Junto a los fallos van dos controles: la corrección no puede tapar un autoinforme real ni una tarifa
por debajo del mínimo.

Hace falta clave y pedirlo a propósito (llama a un modelo de pago y tarda unos segundos por caso):

    ANGRYROBOT_JUDGE_LIVE=1 python -m pytest -q tests/test_judge_live_cases.py

Sin ANGRYROBOT_JUDGE_LIVE=1 o sin clave (OPENROUTER_API_KEY / HF_TOKEN / ANTHROPIC_API_KEY) se salta:
el resto de la suite es determinista y no depende del juez.

Cuando una ronda en vivo vuelva a fallar: copia la acción, la conversación y las tools hermanas a
lab/judge_cases.json con el `max_score` (o `min_score`) que debería dar, arregla auditor.py hasta que
pase, y deja el commit del arreglo en `fix`.
"""
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

KEYS = ("TYPESAFE_API_KEY", "OPENROUTER_API_KEY", "HF_TOKEN", "ANTHROPIC_API_KEY")   # en auto, con TYPESAFE_API_KEY gana Jev
LIVE = os.environ.get("ANGRYROBOT_JUDGE_LIVE") == "1" and any(os.environ.get(k) for k in KEYS)
pytestmark = pytest.mark.skipif(not LIVE, reason="juez real: exporta ANGRYROBOT_JUDGE_LIVE=1 y una clave (TYPESAFE_API_KEY / OPENROUTER_API_KEY / HF_TOKEN)")

with open(os.path.join(HERE, "lab", "judge_cases.json"), encoding="utf-8") as fh:
    CASES = json.load(fh)


@pytest.fixture(autouse=True)
def real_judge(monkeypatch):
    # Los demás tests fijan el juez en mock al importarse; aquí queremos el de verdad.
    monkeypatch.setenv("ANGRYROBOT_JUDGE_PROVIDER", os.environ.get("ANGRYROBOT_JUDGE_LIVE_PROVIDER", "auto"))


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_live_case(case):
    import yaml

    import auditor
    with open(os.path.join(HERE, "config.yaml"), encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    prof = cfg["workflow_profiles"][case.get("profile", "desk")]
    out = auditor.score_dimensions(prof["goal"], prof.get("constraints", []), case.get("reasoning", ""), case["action"],
                                   case.get("history", []), case.get("conversation", []),
                                   sibling_tools=case.get("sibling_tools") or None)
    meta = out.pop("_meta", {})
    assert not meta.get("error"), f"el juez no respondió: {meta}"
    scores = {k: v["score"] for k, v in out.items()}
    why = {k: v.get("reason", "") for k, v in out.items()}
    exp = case["expect"]
    if "max_score" in exp:
        worst = max(scores, key=scores.get)
        assert scores[worst] <= exp["max_score"], f"{case['seen']}\n{worst}={scores[worst]}: {why[worst]}\n{scores}"
    if "min_score" in exp:
        dims = exp.get("dims") or list(scores)
        assert max(scores[d] for d in dims) >= exp["min_score"], f"el juez ya no ve la violación: {scores} · {why}"
