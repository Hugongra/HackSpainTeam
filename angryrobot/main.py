"""
AngryRobot — servicio de auditoría en tiempo real para workflows de HappyRobot.

Expone un único endpoint, POST /audit, pensado para ser llamado desde un
paso de "Custom Code" o un webhook DENTRO de un workflow de HappyRobot,
justo antes de ejecutar cualquier tool-call sensible.

Arranque local:
    pip install -r requirements.txt
    export OPENROUTER_API_KEY=sk-or-...  # o ANTHROPIC_API_KEY; sin ninguna, corre en modo mock
    uvicorn main:app --reload --port 8787

Prueba rápida:
    curl -X POST http://localhost:8787/audit -H "Content-Type: application/json" -d @example_payload.json
"""
import os
import threading
from collections import OrderedDict, deque

import yaml
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from filters import run_hard_filters
from inline import build_router
from loop_detector import loop_score
from auditor import score_dimensions
from scoring import compute_ira
from storage import DB_PATH, init_db, label_case, save_case

# En local lee angryrobot/.env; en Render no hay .env y manda el panel de variables.
load_dotenv()

app = FastAPI(title="AngryRobot", description="Capa de control sobre agentes de HappyRobot")

with open("config.yaml", "r", encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)

# Por qué se inicializa aquí y no en cada request: crear la tabla es una
# operación de una sola vez; hacerlo en el arranque del servicio (y no en
# cada /audit) evita trabajo repetido innecesario en el camino caliente.
init_db(DB_PATH)

# Posición inline (Custom LLM server de HappyRobot): ver inline.py.
app.include_router(build_router(CONFIG))

# Por qué existe esto: este endpoint va a estar expuesto en internet (HappyRobot
# tiene que poder llamarlo desde fuera). Sin esta comprobación, CUALQUIERA que
# encuentre la URL podría llamar a /audit directamente y mentir sobre el
# contexto (por ejemplo, mandar una acción peligrosa etiquetada como si fuera
# inofensiva, o simplemente spamear el servicio). Un secreto compartido simple
# —no es criptografía avanzada, es solo una contraseña que solo vosotros y
# HappyRobot conocéis— cierra esa puerta con una comprobación de una línea.
SHARED_SECRET = os.environ.get("ANGRYROBOT_SHARED_SECRET")


def verify_caller(x_angryrobot_secret: str | None = Header(default=None)):
    if SHARED_SECRET and x_angryrobot_secret != SHARED_SECRET:
        raise HTTPException(status_code=401, detail="Falta o es incorrecto el header X-AngryRobot-Secret")


class ProposedAction(BaseModel):
    tool: str | None = None
    args: dict = {}
    text: str = ""


class AuditRequest(BaseModel):
    # Con "workflow", objetivo y restricciones salen del perfil en config.yaml;
    # workflow_goal / constraints explícitos tienen prioridad sobre el perfil.
    workflow: str | None = None
    workflow_goal: str = ""
    constraints: list[str] = []
    # Con "run_id" (en HappyRobot: current.run_id), AngryRobot recuerda las
    # últimas acciones del run y no hace falta mandar session_history.
    run_id: str | None = None
    reasoning_trace: str = ""
    proposed_action: ProposedAction
    session_history: list[dict] = []  # últimas acciones: [{"tool":..., "args":...}, ...]


def _resolve_context(request: AuditRequest) -> tuple[str, list[str]]:
    profile = {}
    if request.workflow:
        profile = CONFIG.get("workflow_profiles", {}).get(request.workflow)
        if profile is None:
            raise HTTPException(status_code=400, detail=f"workflow '{request.workflow}' no tiene perfil en config.yaml")
    goal = request.workflow_goal or profile.get("goal", "")
    if not goal:
        raise HTTPException(status_code=400, detail="Falta workflow_goal (o un 'workflow' con perfil en config.yaml)")
    return goal, request.constraints or profile.get("constraints", [])


# Historial corto por run, en memoria. Por qué aquí y no en HappyRobot: el
# workflow no tiene una forma sencilla de acumular una lista de acciones entre
# nodos, y sin historial el detector de bucles nunca ve nada. Por qué en memoria
# y no en SQLite: solo hace falta mientras dura la llamada; si el servicio se
# reinicia se pierde el historial de los runs en curso, nada más.
MAX_TRACKED_RUNS = 1000
_RUNS: "OrderedDict[str, deque]" = OrderedDict()
_RUNS_LOCK = threading.Lock()


def _run_history(run_id: str | None) -> list[dict]:
    if not run_id:
        return []
    with _RUNS_LOCK:
        return list(_RUNS.get(run_id, []))


def _remember(run_id: str | None, action: dict) -> None:
    if not run_id:
        return
    with _RUNS_LOCK:
        runs = _RUNS.setdefault(run_id, deque(maxlen=CONFIG["history_window"]))
        runs.append({"tool": action.get("tool"), "args": action.get("args", {})})
        _RUNS.move_to_end(run_id)
        while len(_RUNS) > MAX_TRACKED_RUNS:
            _RUNS.popitem(last=False)


@app.get("/health")
def health():
    return {"status": "happy"}


@app.post("/audit", dependencies=[Depends(verify_caller)])
def audit(request: AuditRequest):
    action = request.proposed_action.model_dump()
    goal, constraints = _resolve_context(request)
    history = (request.session_history or _run_history(request.run_id))[-CONFIG["history_window"]:]
    # Se registra ANTES de decidir: un intento bloqueado también cuenta para
    # detectar que el agente insiste en lo mismo.
    _remember(request.run_id, action)

    # Stage 0: filtros duros. Si ya está claro que es un KILL, no gastamos ni un
    # euro en el LLM auditor — cortamos aquí mismo.
    hard = run_hard_filters(CONFIG, action)
    if hard.is_kill:
        case_id = save_case(
            DB_PATH,
            workflow_goal=goal, constraints=constraints,
            reasoning_trace=request.reasoning_trace, proposed_action=action,
            session_history=history, hard_filter_hits=[h.reason for h in hard.hits],
            dimensions={}, ira_score=100.0, verdict="KILL",
        )
        return {
            "case_id": case_id,
            "ira_score": 100.0,
            "verdict": "KILL",
            "dimensions": {},
            "hard_filter_hits": [h.reason for h in hard.hits],
            "explanation": f"Filtro duro activado: {hard.hits[0].reason}",
        }

    # Stage 1: detector de bucles (barato, sin LLM).
    loop_val, loop_reason = loop_score(
        action, history, similarity_threshold=CONFIG["loop_similarity_threshold"]
    )

    # Stage 2: juez independiente (LLM distinto al agente).
    dims = score_dimensions(
        workflow_goal=goal,
        constraints=constraints,
        reasoning_trace=request.reasoning_trace,
        proposed_action=action,
        session_history=history,
    )

    # Stage 3: semáforo.
    result = compute_ira(CONFIG, dims, loop_val, hard_filter_is_kill=False, loop_reason=loop_reason)

    # Guardamos SIEMPRE, no solo los KILL. Por qué: para poder calcular después
    # una tasa de falsos positivos necesitas también los casos que se dejaron
    # pasar tranquilamente — si solo guardaras lo sospechoso, nunca podrías
    # medir cuánto estáis molestando al agente con avisos innecesarios.
    case_id = save_case(
        DB_PATH,
        workflow_goal=goal, constraints=constraints,
        reasoning_trace=request.reasoning_trace, proposed_action=action,
        session_history=history, hard_filter_hits=[h.reason for h in hard.hits],
        dimensions=result.dimensions, ira_score=result.ira_score, verdict=result.verdict,
    )

    return {
        "case_id": case_id,
        "ira_score": result.ira_score,
        "verdict": result.verdict,
        "dimensions": {**result.dimensions, "loop_detection_reason": loop_reason},
        "hard_filter_hits": [h.reason for h in hard.hits],
        "explanation": result.explanation,
    }


class FeedbackRequest(BaseModel):
    case_id: str
    label: str  # 'correct' | 'false_positive' | 'false_negative'
    notes: str = ""


@app.post("/feedback", dependencies=[Depends(verify_caller)])
def feedback(request: FeedbackRequest):
    """
    Aquí es donde un humano (el equipo de operaciones, o vosotros revisando
    logs) le dice a AngryRobot que se equivocó. Este endpoint NO cambia nada
    en tiempo real — solo etiqueta el caso guardado. El aprendizaje de verdad
    pasa después, offline, ejecutando learn.py sobre todos los casos
    etiquetados. Por qué separar "etiquetar" de "aprender" en dos pasos en
    vez de uno: etiquetar es barato y lo puede hacer cualquiera en cualquier
    momento; recalibrar el sistema es una decisión que debería revisar un
    humano antes de desplegarla, no algo que pase solo porque alguien marcó
    un caso a las 3 de la mañana.
    """
    ok = label_case(DB_PATH, request.case_id, request.label, request.notes)
    if not ok:
        raise HTTPException(status_code=404, detail="case_id no encontrado")
    return {"status": "labeled", "case_id": request.case_id, "label": request.label}
