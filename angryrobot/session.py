"""
Estado por run: lo que AngryRobot sabe de una conversación ANTES, DURANTE y DESPUÉS de cada acción.

  antes    -> contexto con el que se audita la acción propuesta (ctx())
  durante  -> cada entrada nueva (turno del interlocutor, resultado de tool) se audita al llegar:
              inyecciones (contaminan las acciones siguientes), errores de tools (deriva)
  después  -> el resultado real de cada tool-call ejecutada: éxito/fallo, qué efectos se han
              producido de verdad (para cazar "ya está reservado" sin reserva), y el escalado de
              sesión (3×WARN -> DEFER, 2×DEFER -> KILL) + la línea de tiempo del run.

En memoria a propósito (solo vive lo que dura la conversación); el registro permanente de cada
auditoría está en SQLite (storage.py).
"""
import hashlib
import re
import threading
import time
from collections import Counter, OrderedDict

import signals as sig

MAX_RUNS = 2000
_RUNS: "OrderedDict[str, RunState]" = OrderedDict()
_LOCK = threading.Lock()
ERROR_RE = re.compile(r'"error"|\berror\b|\bfail(ed|ure)?\b|\bexception\b|\b5\d\d\b|"ok"\s*:\s*false|timed? ?out|activity error', re.I)
DECAY = 0.6


def _values(text: str) -> set:
    t = str(text or "")
    vals = {sig._digits(m.group(0)) for m in sig.PHONE.finditer(t)}
    vals |= {m.group(0) for m in re.finditer(r"\d{3,}", t)}
    vals |= {m.group(0).lower() for m in sig.EMAIL.finditer(t)}
    return {v for v in vals if v}


class RunState:
    def __init__(self, run_id: str, profile: str):
        self.run_id, self.profile, self.created = run_id, profile, time.time()
        self.seen = 0
        self.conversation: list[dict] = []
        self.history: list[dict] = []
        self.calls: dict[str, dict] = {}
        self.served: dict[str, dict] = {}          # respuestas que devolvimos -> veredicto
        self.succeeded: set = set()
        self.recent_error: dict | None = None
        self.contamination: dict | None = None
        self.user_turns = 0
        self.recent_user: list[str] = []
        self.caller_values: set = set()
        self.known_values: set = set()
        self.counts: Counter = Counter()
        self.iras: list[float] = []
        self.killed = False
        self.notes: list[dict] = []
        self.timeline: list[dict] = []

    # --------------------------------------------------------------- entradas
    def ingest(self, messages: list, profile: dict) -> list[dict]:
        """Procesa los mensajes nuevos desde la última vez. Devuelve auditorías de entrada."""
        if len(messages) < self.seen:
            self.__init__(self.run_id, self.profile)
        events = []
        for m in messages[self.seen:]:
            ev = self.add_message(m, profile)
            if ev:
                events.append(ev)
        self.seen = len(messages)
        return events

    def add_message(self, m: dict, profile: dict) -> dict | None:
        role, content = m.get("role"), m.get("content")
        if isinstance(content, list):
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        content = content or ""
        self.conversation.append({k: v for k, v in {"role": role, "content": content, "tool_calls": m.get("tool_calls"),
                                                    "tool_call_id": m.get("tool_call_id")}.items() if v})
        self.conversation = self.conversation[-40:]
        if role == "system":
            self.known_values |= _values(content)
            return None
        if role == "user":
            return self.user_turn(content)
        if role == "assistant":
            served = self.served.get(_h(content)) if content else None
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function", {})
                entry = {"tool": fn.get("name"), "args": _args(fn.get("arguments")), "id": tc.get("id")}
                meta = self.served.get(f"call:{tc.get('id')}")
                if meta:
                    entry["verdict"] = meta["verdict"]
                self.calls[tc.get("id") or f"n{len(self.calls)}"] = entry
                self.history.append(entry)
            if content:
                self.history.append({"tool": "say", "args": {"text": content[:300]},
                                     **({"verdict": served["verdict"]} if served else {})})
            self.history = self.history[-20:]
            return None
        if role == "tool":
            entry = self.calls.get(m.get("tool_call_id")) or {"tool": m.get("name") or "?"}
            return self.tool_result(entry.get("tool"), content, profile, entry)
        return None

    def user_turn(self, content: str) -> dict:
        self.user_turns += 1
        self.recent_user = (self.recent_user + [content])[-4:]
        self.caller_values |= _values(content)
        self.known_values |= _values(content)
        p, ev = sig.injection_in(content)
        signals = []
        if p:
            self.contamination = {"p0": p, "turn": self.user_turns, "evidence": f"interlocutor: «{ev}»"}
            signals.append(sig.Signal("input.injection", p, 0.9, 0, f"«{ev}»").as_dict())
        return self._input_event("user_turn", content, signals)

    def tool_result(self, tool: str | None, content: str, profile: dict, entry: dict | None = None) -> dict:
        ok = not ERROR_RE.search(str(content))
        effect = sig.tool_profile(profile, tool).get("side_effect")
        if entry is not None:
            entry["outcome"] = "ok" if ok else "falló"
        signals = []
        if ok:
            self.succeeded.add(effect)
            self.known_values |= _values(content)
        else:
            self.recent_error = {"tool": tool, "detail": str(content)[:160], "turn": self.user_turns}
            signals.append(sig.Signal("input.tool_error", 0.4, 1.0, 0, f"{tool}: {str(content)[:120]}").as_dict())
        p, ev = sig.injection_in(str(content))
        if p:   # inyección indirecta: instrucciones dentro de datos que el agente lee
            self.contamination = {"p0": max(p, 0.8), "turn": self.user_turns, "evidence": f"resultado de {tool}: «{ev}»"}
            signals.append(sig.Signal("input.indirect_injection", max(p, 0.8), 0.9, 0, f"«{ev}»").as_dict())
        return self._input_event("tool_result", f"{tool}: {str(content)[:300]}", signals, ok=ok)

    def _input_event(self, kind: str, content: str, signals: list, ok: bool = True) -> dict:
        top = max((s["p"] * s["w"] for s in signals), default=0)
        ev = {"at": time.strftime("%H:%M:%S"), "phase": "input", "kind": kind, "content": content[:300], "ok": ok,
              "verdict": "WARN" if top >= 0.5 else "ALLOW", "signals": signals}
        self.timeline.append(ev)
        return ev

    # --------------------------------------------------------------- contexto
    def contamination_now(self) -> dict:
        if not self.contamination:
            return {}
        p = self.contamination["p0"] * DECAY ** max(0, self.user_turns - self.contamination["turn"])
        return {"p": round(p, 3), "evidence": self.contamination["evidence"]} if p >= 0.05 else {}

    def ctx(self, offered_tools=None, reasoning: str = "", sibling_tools=None, window: int = 5,
            environment: str = "production", loop_similarity: float = 0.9) -> dict:
        err = self.recent_error if self.recent_error and self.user_turns - self.recent_error["turn"] <= 2 else None
        return {"offered_tools": offered_tools, "last_user": self.recent_user[-1] if self.recent_user else "",
                "recent_user": self.recent_user, "caller_values": self.caller_values, "known_values": self.known_values,
                "contamination": self.contamination_now(), "recent_error": err, "succeeded_effects": set(self.succeeded),
                "history": self.history[-window:], "conversation": self.conversation[-10:], "reasoning": reasoning,
                "sibling_tools": sibling_tools or [], "environment": environment, "loop_similarity": loop_similarity}

    def session_floor(self, cfg: dict) -> tuple[int, str] | None:
        s = cfg.get("session", {})
        if self.counts["DEFER"] + self.counts["KILL"] >= s.get("defer_to_kill", 2):
            return 3, f"{self.counts['DEFER']}×DEFER en este run"
        if self.counts["WARN"] >= s.get("warn_to_defer", 3):
            return 2, f"{self.counts['WARN']}×WARN en este run"
        return None

    # --------------------------------------------------------------- después
    def record(self, audit: dict) -> None:
        self.counts[audit["verdict"]] += 1
        self.iras.append(audit["ira_score"])
        self.timeline.append({"at": time.strftime("%H:%M:%S"), "phase": audit.get("phase", "pre"), "kind": audit["kind"],
                              "action": audit["action"], "verdict": audit["verdict"], "ira": audit["ira_score"],
                              "top_signal": audit["signals"][0]["name"] if audit["signals"] else None,
                              "explanation": audit["explanation"], "enforcement": audit.get("enforcement")})
        self.timeline = self.timeline[-300:]
        if audit["verdict"] == "KILL" and audit.get("enforced", True):
            self.killed = True

    def mark_served(self, message: dict, verdict: str) -> None:
        if message.get("content"):
            self.served[_h(message["content"])] = {"verdict": verdict}
        for tc in message.get("tool_calls") or []:
            self.served[f"call:{tc.get('id')}"] = {"verdict": verdict}

    def summary(self) -> dict:
        return {"actions": sum(self.counts.values()), "counts": dict(self.counts),
                "ira_avg": round(sum(self.iras) / len(self.iras), 1) if self.iras else 0.0,
                "ira_max": max(self.iras, default=0.0), "killed": self.killed,
                "contaminated": bool(self.contamination_now())}


def _h(text: str) -> str:
    return hashlib.sha1((text or "").strip().encode("utf-8")).hexdigest()


def _args(raw) -> dict:
    import json
    if isinstance(raw, dict):
        return raw
    try:
        v = json.loads(raw or "{}")
        return v if isinstance(v, dict) else {"value": v}
    except (TypeError, ValueError):
        return {"raw": str(raw)[:300]}


def get(run_id: str, profile: str) -> RunState:
    with _LOCK:
        st = _RUNS.get(run_id)
        if st is None:
            st = _RUNS[run_id] = RunState(run_id, profile)
        _RUNS.move_to_end(run_id)
        while len(_RUNS) > MAX_RUNS:
            _RUNS.popitem(last=False)
        return st


def peek(run_id: str) -> RunState | None:
    with _LOCK:
        return _RUNS.get(run_id)


def recent_runs(limit: int = 50) -> list[RunState]:
    with _LOCK:
        return list(_RUNS.values())[-limit:][::-1]


def fingerprint(profile: str, messages: list) -> str:
    """Id de run cuando el cliente no manda uno: perfil + sistema + primer turno del interlocutor."""
    first_sys = next((str(m.get("content")) for m in messages if m.get("role") == "system"), "")
    first_user = next((str(m.get("content")) for m in messages if m.get("role") == "user"), "")
    return "fp-" + hashlib.sha1(f"{profile}|{first_sys[:2000]}|{first_user[:500]}".encode()).hexdigest()[:16]
