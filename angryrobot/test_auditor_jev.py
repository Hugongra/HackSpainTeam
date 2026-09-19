"""
Prueba del camino Jev del juez SIN red: sustituye requests.post por un stub y
comprueba (1) que el nivel de Jev se mapea a la escala 0-10 sin pasar por
ningún parser, (2) que rogue_class / commitment / disclosure llegan tipados a
_meta, y (3) que un fallo del proveedor devuelve el veredicto cautelar
(fallar cerrado), igual que el camino LLM.

    /usr/bin/python3 test_auditor_jev.py
"""
import os

os.environ["ANGRYROBOT_JUDGE_PROVIDER"] = "jev"
os.environ.setdefault("TYPESAFE_API_KEY", "apikey_FAKE_for_stub")

import auditor  # noqa: E402

DIMS = list(auditor.DIMENSION_PROMPTS)


class _Resp:
    def __init__(self, status, payload=None, text=""):
        self.status_code, self._payload, self.text = status, payload, text

    def json(self):
        return self._payload


def _stub(levels, status=200, extra=None):
    def post(url, headers=None, json=None, timeout=None):
        assert url.endswith("/v1/systemone"), url
        assert headers["Authorization"].startswith("Bearer "), "falta el bearer"
        assert set(DIMS) <= set(json["questions"]), "una pregunta Score por dimensión"
        assert {"rogue_class", "commitment", "disclosure"} <= set(json["questions"]), "las extras tipadas"
        assert all(json["questions"][d]["type"] == "score" and len(json["questions"][d]["criteria"]) == 5 for d in DIMS)
        if status != 200:
            return _Resp(status, None, "boom")
        answers = {dim: {"type": "score", "score": lv, "confidence": 0.9} for dim, lv in levels.items()}
        answers.update(extra or {})
        return _Resp(200, {"model": "jev-stub", "answers": answers})
    return post


ARGS = dict(workflow_goal="g", constraints=["c"], reasoning_trace="r",
            proposed_action={"tool": "t", "args": {}, "text": "x"}, session_history=[])

# nivel 0 → 0.0, nivel 4 → 10.0, nivel 2 → 5.0, nivel 3.7 → 9.25
auditor.requests.post = _stub({"constraint_adherence": 0, "goal_alignment": 4, "self_consistency": 2,
                               "scope_escalation": 3.7, "reasoning_integrity": 1},
                              extra={"rogue_class": {"type": "choice", "choice": "deceives", "confidence": 0.8},
                                     "commitment": {"type": "score", "score": 1.6}, "disclosure": {"type": "score", "score": 0.2}})
d = auditor.score_dimensions(**ARGS)
assert d["constraint_adherence"]["score"] == 0.0, d
assert d["goal_alignment"]["score"] == 10.0, d
assert d["self_consistency"]["score"] == 5.0, d
assert d["scope_escalation"]["score"] == 9.25, d
assert d["reasoning_integrity"]["score"] == 2.5, d
assert all(d[k]["reason"].startswith("jev jev-stub") for k in DIMS), d
assert d["_meta"]["provider"] == "jev" and d["_meta"]["rogue_class"] == "deceives", d["_meta"]
assert d["_meta"]["commitment"] == 1 and d["_meta"]["disclosure"] == 0, d["_meta"]
print("mapeo nivel→0-10 y _meta tipado correctos:", {k: d[k]["score"] for k in DIMS}, d["_meta"]["rogue_class"])

# sin razonamiento → reasoning_integrity 0, como en el camino LLM
d = auditor.score_dimensions(**{**ARGS, "reasoning_trace": ""})
assert d["reasoning_integrity"] == {"score": 0, "reason": "sin razonamiento"}, d
print("sin razonamiento → 0")

# fuera de rango se recorta, nunca revienta
auditor.requests.post = _stub({dim: 7 for dim in DIMS})
assert all(auditor.score_dimensions(**ARGS)[k]["score"] == 10.0 for k in DIMS)
print("recorte fuera de rango correcto")

# fallo del proveedor → veredicto cautelar (fallar cerrado)
auditor.requests.post = _stub({}, status=500)
d = auditor.score_dimensions(**ARGS)
assert all(d[k]["score"] == auditor.CAUTIOUS_SCORE for k in DIMS if k != "reasoning_integrity"), d
assert "Jev no disponible" in d["goal_alignment"]["reason"] and d["_meta"]["error"], d
print("fallo del proveedor → cautelar:", d["goal_alignment"])

# respuesta incompleta → también cautelar
auditor.requests.post = _stub({"constraint_adherence": 1})
d = auditor.score_dimensions(**ARGS)
assert all(d[k]["score"] == auditor.CAUTIOUS_SCORE for k in DIMS if k != "reasoning_integrity"), d
print("respuesta incompleta → cautelar")
print("OK")
