"""
Stage 0 — Filtros duros ("el guardia de la puerta").

No razonan, no dudan, no se pueden convencer con un buen argumento:
solo comparan texto y nombres de herramientas contra una lista negra.
Por eso van PRIMERO: son gratis, instantáneos, y capturan el 100% de
lo que está en la lista (a cambio de no detectar nada que no esté en
la lista — para eso están las siguientes fases).
"""
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class HardFilterHit:
    rule: str
    reason: str
    severity: str


@dataclass
class HardFilterResult:
    hits: list = field(default_factory=list)

    @property
    def is_kill(self) -> bool:
        return any(h.severity == "kill" for h in self.hits)


def run_hard_filters(config: dict, proposed_action: dict) -> HardFilterResult:
    """
    proposed_action = {
        "tool": "nombre_de_la_herramienta" | None,
        "args": {...},
        "text": "texto libre de lo que el agente va a decir/hacer",
    }
    """
    result = HardFilterResult()
    text_blob = " ".join(
        str(v) for v in [
            proposed_action.get("text", ""),
            proposed_action.get("tool", ""),
            proposed_action.get("args", {}),
        ]
    )

    for rule in config.get("hard_filters", {}).get("banned_patterns", []):
        if re.search(rule["pattern"], text_blob):
            result.hits.append(
                HardFilterHit(rule=rule["pattern"], reason=rule["reason"], severity=rule["severity"])
            )

    tool_name = proposed_action.get("tool")
    if tool_name:
        for restricted in config.get("hard_filters", {}).get("restricted_tools", []):
            if restricted["name"] == tool_name:
                amount = _extract_amount(proposed_action.get("args", {}))
                max_amount = restricted.get("max_amount")
                if max_amount is None or amount is None or amount > max_amount:
                    result.hits.append(
                        HardFilterHit(
                            rule=f"restricted_tool:{tool_name}",
                            reason=restricted["reason"],
                            severity="kill",
                        )
                    )

    return result


def _extract_amount(args: dict) -> float | None:
    for key in ("amount", "monto", "cantidad", "importe"):
        if key in args:
            try:
                return float(args[key])
            except (TypeError, ValueError):
                return None
    return None
