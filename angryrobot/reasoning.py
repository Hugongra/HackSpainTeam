"""
Acceso al razonamiento del agente — se intenta SIEMPRE antes de auditar.

Fuentes, por orden de preferencia (la primera que exista gana, y se registra cuál):
  1. "upstream.reasoning"          campo `reasoning` del mensaje (OpenRouter, HF/gpt-oss, vLLM)
  2. "upstream.reasoning_content"  campo `reasoning_content` (DeepSeek-R1, Qwen3, vLLM)
  3. "upstream.reasoning_details"  lista `reasoning_details` (OpenRouter, texto o resumen)
  4. "think_tags"                  bloque <think>…</think> dentro del content (se QUITA del texto
                                   que se devuelve: el razonamiento nunca debe llegar al TTS)
  5. "client"                      lo que mande el cliente en /v1/audit (reasoning / reasoning_trace)
  6. "preamble"                    el texto que acompaña a una tool-call ("voy a reservar porque…"):
                                   razonamiento verbalizado, parcial pero real
  7. "none"                        no hay: se audita solo con entradas, salidas y tool-calls

Por qué importa: el razonamiento es donde aparece la intención ("el cliente no se
dará cuenta", "aunque la política diga 1500…") ANTES de que llegue a la acción.
Pero también es texto que controla el agente: se trata como evidencia, nunca
como instrucciones para el juez, y nunca rebaja un disparador duro.
"""
import re

THINK = re.compile(r"<think>(.*?)(</think>|$)", re.S | re.I)


def extract(message: dict) -> tuple[str, str, str]:
    """-> (razonamiento, fuente, content_limpio)"""
    content = message.get("content") or ""
    if isinstance(content, list):   # formato por partes
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    think = THINK.findall(content)
    clean = THINK.sub("", content).strip() if think else content

    for key in ("reasoning", "reasoning_content"):
        val = message.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip(), f"upstream.{key}", clean
    details = message.get("reasoning_details")
    if isinstance(details, list):
        txt = "\n".join(str(d.get("text") or d.get("summary") or "") for d in details if isinstance(d, dict)).strip()
        if txt:
            return txt, "upstream.reasoning_details", clean
    if think:
        return "\n".join(t[0] for t in think).strip(), "think_tags", clean
    if message.get("tool_calls") and clean:
        return clean, "preamble", clean
    return "", "none", clean
