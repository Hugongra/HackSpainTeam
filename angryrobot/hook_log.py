"""
Registro compartido de los webhooks capturados en /hook y /hook/fail (ver main.py).

Módulo aparte (en vez de vivir dentro de main.py) para que rounds.py / hr_live.py
puedan leerlo sin crear un import circular: main.py importa rounds, así que rounds
no puede importar main.
"""
import time
from collections import deque

LOG: deque = deque(maxlen=500)


def add(query: dict, body, fail: bool = False) -> dict:
    record = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "ts": time.time(), "query": dict(query or {}), "body": body, "fail_injected": fail}
    LOG.append(record)
    return record


def since(ts: float, tag: str | None = None) -> list[dict]:
    """Registros más nuevos que ts (time.time()), opcionalmente solo los de un tag (round_id:seat)."""
    return [r for r in LOG if r["ts"] > ts and (tag is None or r["query"].get("tag") == tag)]
