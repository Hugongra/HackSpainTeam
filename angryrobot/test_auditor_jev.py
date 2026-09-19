"""
Prueba del camino Jev del juez SIN red: sustituye requests.post por un stub y
comprueba (1) que el nivel de Jev se mapea a la escala 0-10 sin pasar por
ningún parser, y (2) que un fallo del proveedor devuelve el veredicto cautelar
(fallar cerrado), igual que el camino LLM.

    /usr/bin/python3 test_auditor_jev.py
"""
import os

os.environ["ANGRYROBOT_JUDGE"] = "jev"
os.environ.setdefault("TYPESAFE_API_KEY", "apikey_FAKE_for_stub")

import auditor  # noqa: E402


class _Resp:
    def __init__(self, status, payload=None, text=""):
        self.status_code, self._payload, self.text = status, payload, text

    def json(self):
        return self._payload


def _stub(levels, status=200):
    def post(url, headers=None, json=None, timeout=None):
        assert url.endswith("/v1/systemone"), url
        assert headers["Authorization"].startswith("Bearer "), "falta el bearer"
        assert set(json["questions"]) == set(auditor.DIMENSION_PROMPTS), "una pregunta por dimensión"
        assert all(q["type"] == "score" and len(q["criteria"]) == 5 for q in json["questions"].values()), "Score con 5 niveles"
        if status != 200:
            return _Resp(status, None, "boom")
        return _Resp(200, {"model": "jev-stub", "answers": {dim: {"type": "score", "score": lv, "confidence": 0.9}
                                                             for dim, lv in levels.items()}})
    return post


ARGS = dict(workflow_goal="g", constraints=["c"], reasoning_trace="r",
            proposed_action={"tool": "t", "args": {}, "text": "x"}, session_history=[])

# nivel 0 → 0.0, nivel 4 → 10.0, nivel 2 → 5.0, nivel 3.7 → 9.25
auditor.requests.post = _stub({"constraint_adherence": 0, "goal_alignment": 4, "self_consistency": 2, "scope_escalation": 3.7})
d = auditor.score_dimensions(**ARGS)
assert d["constraint_adherence"]["score"] == 0.0, d
assert d["goal_alignment"]["score"] == 10.0, d
assert d["self_consistency"]["score"] == 5.0, d
assert d["scope_escalation"]["score"] == 9.25, d
assert all(v["reason"].startswith("jev jev-stub") for v in d.values()), d
print("mapeo nivel→0-10 correcto:", {k: v["score"] for k, v in d.items()})

# fuera de rango se recorta, nunca revienta
auditor.requests.post = _stub({dim: 7 for dim in auditor.DIMENSION_PROMPTS})
assert all(v["score"] == 10.0 for v in auditor.score_dimensions(**ARGS).values())
print("recorte fuera de rango correcto")

# fallo del proveedor → veredicto cautelar (fallar cerrado)
auditor.requests.post = _stub({}, status=500)
d = auditor.score_dimensions(**ARGS)
assert all(v["score"] == auditor.CAUTIOUS_SCORE for v in d.values()), d
assert "Jev no disponible" in d["goal_alignment"]["reason"], d
print("fallo del proveedor → cautelar:", d["goal_alignment"])

# respuesta incompleta → también cautelar
auditor.requests.post = _stub({"constraint_adherence": 1})
d = auditor.score_dimensions(**ARGS)
assert all(v["score"] == auditor.CAUTIOUS_SCORE for v in d.values()), d
print("respuesta incompleta → cautelar")
print("OK")
