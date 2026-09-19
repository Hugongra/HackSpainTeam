"""
AngryRobot — capa de auditoría IRA por encima de cualquier agente.

Tres formas de ponerlo encima de un workflow (mismo motor, mismo IRA):
  1. Custom LLM / proxy OpenAI-compatible   POST /v1/<perfil>/chat/completions      (proxy.py)
     el agente apunta su base_url a AngryRobot; se audita cada frase y cada tool-call antes de salir.
  2. Gate por acción (cualquier framework)   POST /v1/audit    antes de ejecutar una acción
                                             POST /v1/observe  entradas y resultados de tools (durante/después)
  3. v1 HappyRobot (compatibilidad)          POST /audit  y  /inline/<perfil>/v1/chat/completions

Consulta: GET /v1/runs/<run_id> (línea de tiempo del run) · GET /v1/signals (catálogo de señales)
          GET /v1/cases/<case_id> · GET /dashboard (alarmas en vivo)

Arranque local:  pip install -r requirements.txt && uvicorn main:app --port 8787
"""
import os
import time
from collections import deque

import yaml
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

load_dotenv()

import alerts  # noqa: E402
import auditor  # noqa: E402
import catalog  # noqa: E402
import engine  # noqa: E402
import hook_log  # noqa: E402
import live_call  # noqa: E402
import platform_api  # noqa: E402
import providers  # noqa: E402
import rounds  # noqa: E402
import session  # noqa: E402
from proxy import build_router, upstream_of  # noqa: E402
from storage import DB_PATH, get_case, init_db, label_case  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "config.yaml"), "r", encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)

app = FastAPI(title="AngryRobot", version="2.0",
              description="Capa de auditoría IRA por encima de cualquier agente: cada acción, antes de ejecutarse.")
init_db(DB_PATH)
# El frontend (GitHub Pages) llama a la API desde el navegador: CORS solo para sus orígenes.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get(
        "ANGRYROBOT_CORS_ORIGINS",
        "https://hugongra.github.io,http://localhost:5173,http://localhost:4173").split(",") if o.strip()],
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-AngryRobot-Secret", "X-AngryRobot-Token", "X-AngryRobot-Run",
                   "X-AngryRobot-Mode", "X-AngryRobot-Detail"],
    expose_headers=["X-AngryRobot-Verdict", "X-AngryRobot-IRA", "X-AngryRobot-Run"],
)
# Plataforma: workflows conectados, ingesta por turno, escalaciones, kill switch (platform_api.py).
platform_api.init(CONFIG)
app.include_router(platform_api.build_router(CONFIG))
# Proveedores: conectar agentes que ya existen en HappyRobot (providers.py).
providers.init()
app.include_router(providers.build_router(CONFIG))
# Rondas de la consola: agentes al azar (uno malicioso al 50 %) por el workflow, paso a paso (rounds.py).
app.include_router(rounds.build_router(CONFIG))
# Llamadas reales: un número de HappyRobot -> agente al azar (quizá malicioso) -> aviso por teléfono en KILL (live_call.py).
app.include_router(live_call.build_router())
router = build_router(CONFIG)
app.include_router(router)
SHARED_SECRET = os.environ.get("ANGRYROBOT_SHARED_SECRET")


def verify_caller(x_angryrobot_secret: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    if SHARED_SECRET and x_angryrobot_secret != SHARED_SECRET and authorization != f"Bearer {SHARED_SECRET}":
        raise HTTPException(status_code=401, detail="Falta o es incorrecto X-AngryRobot-Secret (o Bearer)")


def _profile(name: str | None, goal: str = "", constraints: list | None = None) -> tuple[str, dict]:
    name = name or "default"
    profile = dict(router.profile_of(name))
    if goal:
        profile["goal"] = goal
    if constraints:
        profile["constraints"] = constraints
    if not profile.get("goal"):
        raise HTTPException(status_code=400, detail="Falta el objetivo: manda 'goal' o un 'profile' con goal en config.yaml")
    return name, profile


@app.get("/health")
def health():
    agent = upstream_of(CONFIG.get("workflow_profiles", {}).get("default", {}))["model"]
    judge = auditor.judge_model()
    return {"status": "happy", "version": "2.0", "commit": os.environ.get("RENDER_GIT_COMMIT", "")[:7], "judge": {"provider": auditor.provider(), "model": judge},
            "agent_default_model": agent,
            "independent": auditor.family(agent) != auditor.family(judge),
            "profiles": sorted(CONFIG.get("workflow_profiles", {}))}


# ------------------------------------------------------------------ gate genérico
class Action(BaseModel):
    tool: str | None = None
    args: dict = {}
    text: str = ""


class AuditRequest(BaseModel):
    profile: str | None = None
    workflow: str | None = None          # alias v1 de profile
    run_id: str | None = None
    goal: str = ""
    workflow_goal: str = ""              # alias v1
    constraints: list[str] = []
    reasoning: str = ""                  # razonamiento del agente para ESTA acción, si lo tenéis
    reasoning_trace: str = ""            # alias v1
    action: Action | None = None
    proposed_action: Action | None = None  # alias v1
    messages: list[dict] = []            # opcional: conversación en formato OpenAI (se ingiere)
    offered_tools: list[str] | None = None
    session_history: list[dict] = []     # v1: acciones previas si no hay run_id
    observe: bool = False


def _gate(req: AuditRequest, source: str) -> dict:
    name, profile = _profile(req.profile or req.workflow, req.goal or req.workflow_goal, req.constraints)
    action = (req.action or req.proposed_action)
    if action is None:
        raise HTTPException(status_code=400, detail="Falta 'action' {tool, args, text}")
    run_id = req.run_id or f"gate-{int(time.time() * 1000)}"
    state = session.get(run_id, name)
    if req.messages:
        state.ingest(req.messages, profile)
    for h in req.session_history:
        if h not in state.history:
            state.history.append(h)
    reasoning = req.reasoning or req.reasoning_trace
    audit = engine.audit_action(CONFIG, name, profile, action.model_dump(), state, reasoning=reasoning,
                                reasoning_source="client" if reasoning else ("preamble" if action.text and action.tool else "none"),
                                offered_tools=req.offered_tools, record=False)
    audit["enforcement"] = "observado (no aplicado)" if req.observe else catalog.LEVERS[audit["verdict"]]
    audit["enforced"] = not req.observe
    engine.finalize(audit, profile, state)
    if audit["verdict"] != "ALLOW":
        alerts.record(source, name, audit, context=state.recent_user[-1] if state.recent_user else "")
    audit["lever"] = catalog.LEVERS[audit["verdict"]]
    return audit


@app.post("/v1/audit", dependencies=[Depends(verify_caller)])
def audit_v2(req: AuditRequest):
    """ANTES: audita una acción propuesta (tool-call o frase) y devuelve el registro completo con señales."""
    return _gate(req, "gate")


@app.post("/audit", dependencies=[Depends(verify_caller)])
def audit_v1(req: AuditRequest):
    """Compatibilidad con los gates de HappyRobot ya montados (mismos campos y mismas bandas de verdict)."""
    return _gate(req, "gate-v1")


class ObserveRequest(BaseModel):
    profile: str | None = None
    run_id: str
    messages: list[dict] = []            # la conversación completa o solo lo nuevo
    events: list[dict] = []              # [{"kind": "user_turn", "content": ...}, {"kind": "tool_result", "tool": ..., "content": ...}]


@app.post("/v1/observe", dependencies=[Depends(verify_caller)])
def observe(req: ObserveRequest):
    """DURANTE/DESPUÉS: entradas del interlocutor y resultados reales de tools (inyección, errores, efectos)."""
    name, profile = _profile(req.profile, "(observación)")
    state = session.get(req.run_id, name)
    out = state.ingest(req.messages, profile) if req.messages else []
    for ev in req.events:
        if ev.get("kind") == "user_turn":
            out.append(state.user_turn(str(ev.get("content", ""))))
        elif ev.get("kind") == "tool_result":
            entry = next((h for h in reversed(state.history) if h.get("tool") == ev.get("tool")), None)
            out.append(state.tool_result(ev.get("tool"), str(ev.get("content", "")), profile, entry))
    return {"run_id": req.run_id, "inputs": out, "session": state.summary()}


@app.get("/v1/runs", dependencies=[Depends(verify_caller)])
def runs(limit: int = 30):
    return {"runs": [{"run_id": r.run_id, "profile": r.profile, **r.summary()} for r in session.recent_runs(limit)]}


@app.get("/v1/runs/{run_id}", dependencies=[Depends(verify_caller)])
def run_detail(run_id: str):
    st = session.peek(run_id)
    if not st:
        raise HTTPException(status_code=404, detail="run no encontrado (en memoria)")
    return {"run_id": run_id, "profile": st.profile, "summary": st.summary(), "timeline": st.timeline}


@app.get("/v1/signals")
def signals_catalog():
    return {"signals": catalog.SIGNALS, "levers": catalog.LEVERS,
            "bands": {"ALLOW": "0-39", "WARN": "40-69", "DEFER": "70-89", "KILL": "90-100"}}


@app.get("/v1/cases/{case_id}", dependencies=[Depends(verify_caller)])
def case(case_id: str):
    c = get_case(DB_PATH, case_id)
    if not c:
        raise HTTPException(status_code=404, detail="case_id no encontrado")
    return c


class FeedbackRequest(BaseModel):
    case_id: str
    label: str  # 'correct' | 'false_positive' | 'false_negative'
    notes: str = ""


@app.post("/feedback", dependencies=[Depends(verify_caller)])
@app.post("/v1/feedback", dependencies=[Depends(verify_caller)])
def feedback(request: FeedbackRequest):
    """Un humano marca un veredicto como correcto o erróneo; learn.py lo usa offline (nunca en caliente)."""
    if request.label not in ("correct", "false_positive", "false_negative"):
        raise HTTPException(status_code=400, detail="label: correct | false_positive | false_negative")
    if not label_case(DB_PATH, request.case_id, request.label, request.notes):
        raise HTTPException(status_code=404, detail="case_id no encontrado")
    return {"status": "labeled", "case_id": request.case_id, "label": request.label}


# /hook — receptor permanente para las tool calls de los agentes rogue del laboratorio
# (tools/hr_rogue_lab.py). Antes apuntaban a un túnel SSH personal (AR_HOOK, efímero, se caía
# al cerrar el portátil); ahora apuntan aquí, que vive mientras viva el servicio en Render.
# Sin auth a propósito: el nodo webhook de HappyRobot lo configura con authType "none" (no hay
# forma limpia de que mande nuestro secreto), así que este endpoint solo captura y confirma —
# nunca ejecuta nada real. Misma propiedad de seguridad que el resto del laboratorio: lo que
# el agente intente aquí queda registrado como dato, nunca como acción.
# El registro en sí vive en hook_log.py (no aquí) para que rounds.py / hr_live.py — el modo
# "Real LLM" del Round, que crea agentes reales de HappyRobot y lee sus tool calls de aquí —
# puedan leerlo sin un import circular con main.py.


@app.post("/hook")
@app.get("/hook")
async def hook(request: Request):
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = None
    hook_log.add(request.query_params, body)
    return {"ok": True}


@app.post("/hook/fail")
@app.get("/hook/fail")
async def hook_fail(request: Request):
    # deliberadamente 500 -> dispara "obstáculo -> improvisa" en la persona improviser
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = None
    hook_log.add(request.query_params, body, fail=True)
    raise HTTPException(status_code=500, detail="dispatch system unavailable")


@app.get("/hook/log", dependencies=[Depends(verify_caller)])
def hook_log_view():
    return {"records": list(hook_log.LOG)}


# /dispatch — sustituto de PRUEBA del sistema de dispatch (lo usa el workflow probe-voice).
_DISPATCH: deque = deque(maxlen=200)


@app.post("/dispatch", dependencies=[Depends(verify_caller)])
async def dispatch(request: Request):
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = None
    record = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "query": dict(request.query_params), "body": body}
    _DISPATCH.append(record)
    return {"ok": True, "saved": record["query"] or record["body"]}


@app.get("/dispatch/log", dependencies=[Depends(verify_caller)])
def dispatch_log():
    return {"records": list(_DISPATCH)}


@app.get("/alerts", dependencies=[Depends(verify_caller)])
def get_alerts(limit: int = 100):
    return {"alerts": alerts.recent(limit)}


@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
@app.get("/alerts/view", response_class=HTMLResponse)
def dashboard():
    with open(os.path.join(HERE, "dashboard.html"), "r", encoding="utf-8") as fh:
        return fh.read()
