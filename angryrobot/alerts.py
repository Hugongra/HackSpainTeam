"""
Registro de alarmas en memoria: cada acción con veredicto distinto de ALLOW, venga del proxy
(Custom LLM) o del gate (/v1/audit). Lo lee el panel /dashboard.

En memoria a propósito: es la vista "en vivo" de quien vigila. El registro permanente de TODAS
las auditorías (con sus señales) está en SQLite (storage.py).
"""
import threading
from collections import deque

_ALERTS: deque = deque(maxlen=500)
_LOCK = threading.Lock()


def record(source: str, profile: str | None, audit: dict, context: str = "") -> None:
    if audit.get("verdict") == "ALLOW":
        return
    with _LOCK:
        _ALERTS.append({
            "at": audit.get("at"), "source": source, "workflow": profile, "run_id": audit.get("run_id"),
            "verdict": audit.get("verdict"), "ira_score": audit.get("ira_score"), "severity": audit.get("severity"),
            "action": {"tool": audit["action"].get("tool"), "args": audit["action"].get("args"),
                       "text": (audit["action"].get("text") or "")[:300]},
            "impact": audit.get("impact", {}).get("level"), "suspicion": audit.get("suspicion", {}).get("S"),
            "signals": [{"name": s["name"], "evidence": s["evidence"][:160], "floor": s["floor"],
                         "pw": round(s["p"] * s["w"], 2)} for s in audit.get("signals", [])[:6]],
            "reasoning_source": audit.get("reasoning", {}).get("source"),
            "explanation": audit.get("explanation"), "enforcement": audit.get("enforcement", ""),
            "context": (context or "")[:300], "case_id": audit.get("case_id"),
        })


def recent(limit: int = 100) -> list[dict]:
    with _LOCK:
        return list(_ALERTS)[-limit:][::-1]
