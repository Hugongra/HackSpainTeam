"""
Registro de alarmas en memoria: cada acción con veredicto distinto de ALLOW,
venga del gate (/audit) o del inline. Lo lee el panel /alerts/view.

En memoria a propósito: es la vista "en vivo" para quien vigila las llamadas.
El registro permanente de TODAS las auditorías ya está en SQLite (storage.py).
"""
import threading
import time
from collections import deque

_ALERTS: deque = deque(maxlen=500)
_LOCK = threading.Lock()


def record(source: str, workflow: str | None, action: dict, result: dict,
           enforcement: str = "", context: str = "") -> None:
    if result.get("verdict") == "ALLOW":
        return
    with _LOCK:
        _ALERTS.append({
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "source": source,
            "workflow": workflow,
            "verdict": result.get("verdict"),
            "ira_score": result.get("ira_score"),
            "action": {"tool": action.get("tool"), "args": action.get("args"),
                       "text": (action.get("text") or "")[:300]},
            "explanation": result.get("explanation"),
            "enforcement": enforcement,
            "context": context[:300],
            "case_id": result.get("case_id"),
        })


def recent(limit: int = 100) -> list[dict]:
    with _LOCK:
        return list(_ALERTS)[-limit:][::-1]
