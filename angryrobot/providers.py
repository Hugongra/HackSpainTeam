"""
Proveedores: conectar a AngryRobot agentes que YA existen en una plataforma.

Hoy solo HappyRobot. Flujo (lo que la consola llama "Connect" / "Sync"):
  1. GET  /v1/providers/happyrobot/workflows  -> los workflows de la org (API de HappyRobot, clave de org)
     con el workflow de AngryRobot al que ya están enlazados, si lo están.
  2. POST /v1/providers/happyrobot/connect     -> por cada workflow elegido (o todos los no enlazados):
       a) crea el workflow en AngryRobot (source=happyrobot, perfil y modo elegidos),
       b) crea en la org de HappyRobot una credencial "Custom LLM Server" que apunta al proxy
          /v1/<workflow> con el token del workflow como bearer,
       c) guarda el enlace en provider_links.
     Queda UN paso manual, que la API no permite hacer con garantías (knowledge/12): en el builder,
     nodo Prompt -> Model -> Custom LLM server -> elegir la credencial "AngryRobot · <nombre>" y publicar.

Hechos verificados (knowledge/01, 12; tools/hr_watch.py): base EU https://platform.eu.happyrobot.ai/api/v2,
Authorization: Bearer <clave de org>, listado paginado page/page_size con pagination.has_next_page,
integración Custom LLM 019d75d2-9590-75c3-a924-dc1afbd61000 y su create-credential.
"""
import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from contextlib import closing

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

import platform_api as P

HR_BASE = (os.environ.get("HR_BASE") or os.environ.get("HAPPYROBOT_API_BASE_URL")
           or "https://platform.eu.happyrobot.ai/api/v2").rstrip("/")
CUSTOM_LLM_INTEGRATION = os.environ.get("HAPPYROBOT_CUSTOM_LLM_INTEGRATION", "019d75d2-9590-75c3-a924-dc1afbd61000")

PROVIDERS = [
    {"id": "happyrobot", "name": "HappyRobot", "kind": "voice + tool agents", "available": True},
    {"id": "openai", "name": "OpenAI", "kind": "Assistants / Agents SDK", "available": False},
    {"id": "claude", "name": "Claude", "kind": "Agent SDK · PreToolUse hook", "available": False},
    {"id": "gemini", "name": "Gemini", "kind": "ADK", "available": False},
]


def _key() -> str | None:
    return os.environ.get("HAPPYROBOT_API_KEY") or os.environ.get("HR_API_KEY")


def _ssl_context():
    # Algunos python3 de macOS no traen CAs: si certifi está instalado, úsalo; si no, el contexto por defecto.
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


# ---------------------------------------------------------------- HTTP hacia HappyRobot
def hr(method: str, path: str, body: dict | None = None, params: dict | None = None, timeout: int = 20):
    key = _key()
    if not key:
        raise HTTPException(status_code=503, detail="HAPPYROBOT_API_KEY no está configurada en el servicio")
    url = HR_BASE + path
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {key}", "Accept": "application/json",
        **({"Content-Type": "application/json"} if data else {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
            txt = resp.read().decode()
            return json.loads(txt) if txt else None
    except urllib.error.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"HappyRobot {method} {path} -> {e.code}: {e.read().decode(errors='replace')[:300]}")
    except urllib.error.URLError as e:
        raise HTTPException(status_code=502, detail=f"HappyRobot no responde: {e.reason}")


def hr_paged(path: str, page_size: int = 100):
    page = 1
    while True:
        res = hr("GET", path, params={"page": page, "page_size": page_size})
        items = res.get("data", []) if isinstance(res, dict) else (res or [])
        yield from items
        pg = res.get("pagination", {}) if isinstance(res, dict) else {}
        if not (pg.get("has_next_page") or pg.get("hasNextPage")):
            return
        page += 1


# ---------------------------------------------------------------- enlaces (nuestro workflow <-> el suyo)
def init() -> None:
    with closing(P._conn()) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS provider_links (
            workflow_id TEXT PRIMARY KEY, provider TEXT, external_id TEXT, external_slug TEXT, external_name TEXT,
            credential_id TEXT, credential_title TEXT, created_at TEXT)""")
        c.commit()


def links(provider: str = "happyrobot") -> dict:
    with closing(P._conn()) as c:
        rows = c.execute("SELECT * FROM provider_links WHERE provider = ?", (provider,)).fetchall()
    return {r["external_id"]: dict(r) for r in rows}


def link_of(workflow_id: str) -> dict | None:
    with closing(P._conn()) as c:
        r = c.execute("SELECT * FROM provider_links WHERE workflow_id = ?", (workflow_id,)).fetchone()
    return dict(r) if r else None


def _unique_slug(name: str) -> str:
    base = P._slug(name) or "workflow"
    wid, n = base, 2
    while P.get_workflow(wid):
        wid, n = f"{base}-{n}", n + 1
    return wid


def _create_workflow(name: str, source: str, base_profile: str, mode: str, goal: str = "") -> dict:
    wid = _unique_slug(name)
    with closing(P._conn()) as c:
        c.execute("INSERT INTO workflows VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (wid, name.strip(), source, base_profile, goal or None, None, mode, "live", None, 1, 0, P._now(), P._now()))
        c.commit()
    return P.get_workflow(wid)


def _summarize(wf: dict, linked: dict | None) -> dict:
    lv = wf.get("latest_version") or {}
    return {"id": wf.get("id"), "slug": wf.get("slug"), "name": wf.get("name"), "description": wf.get("description"),
            "version": lv.get("version_number"), "is_live": bool(lv.get("is_live")), "updated_at": wf.get("updated_at"),
            "linked_workflow": linked["workflow_id"] if linked else None,
            "credential_title": linked["credential_title"] if linked else None}


class ConnectIn(BaseModel):
    workflow_ids: list[str] = []      # ids de HappyRobot; vacío + all_unlinked=True -> todos los no enlazados
    all_unlinked: bool = False
    base_profile: str = "default"
    mode: str = "enforce"
    create_credential: bool = True


def build_router(config: dict) -> APIRouter:
    router = APIRouter()

    def admin(x_secret, authorization):
        s = os.environ.get("ANGRYROBOT_SHARED_SECRET")
        if s and x_secret != s and authorization != f"Bearer {s}":
            raise HTTPException(status_code=401, detail="Falta o es incorrecto X-AngryRobot-Secret")

    def base_url(request: Request) -> str:
        if os.environ.get("ANGRYROBOT_PUBLIC_URL"):
            return os.environ["ANGRYROBOT_PUBLIC_URL"].rstrip("/")
        url = str(request.base_url).rstrip("/")
        return url.replace("http://", "https://", 1) if request.headers.get("x-forwarded-proto") == "https" else url

    @router.get("/v1/providers")
    def providers(x_angryrobot_secret: str | None = Header(default=None), authorization: str | None = Header(default=None)):
        admin(x_angryrobot_secret, authorization)
        out = []
        for p in PROVIDERS:
            item = dict(p)
            if p["id"] == "happyrobot":
                item["configured"] = bool(_key())
                item["base"] = HR_BASE
                item["linked"] = len(links())
            out.append(item)
        return {"providers": out}

    @router.get("/v1/providers/happyrobot/workflows")
    def hr_workflows(x_angryrobot_secret: str | None = Header(default=None), authorization: str | None = Header(default=None)):
        admin(x_angryrobot_secret, authorization)
        lk = links()
        items = [_summarize(w, lk.get(w.get("id"))) for w in hr_paged("/workflows/")]
        items.sort(key=lambda w: (w["linked_workflow"] is None, not w["is_live"], w["name"] or ""))
        return {"workflows": items, "linked": len([w for w in items if w["linked_workflow"]])}

    @router.get("/v1/providers/links/{workflow_id}")
    def link(workflow_id: str, x_angryrobot_secret: str | None = Header(default=None), authorization: str | None = Header(default=None)):
        admin(x_angryrobot_secret, authorization)
        return {"link": link_of(workflow_id)}

    @router.post("/v1/providers/happyrobot/connect")
    def connect(body: ConnectIn, request: Request, x_angryrobot_secret: str | None = Header(default=None),
                authorization: str | None = Header(default=None)):
        admin(x_angryrobot_secret, authorization)
        if body.base_profile not in (config.get("workflow_profiles") or {}):
            raise HTTPException(status_code=400, detail=f"base_profile '{body.base_profile}' no existe")
        if body.mode not in ("enforce", "observe"):
            raise HTTPException(status_code=400, detail="mode: enforce | observe")
        lk = links()
        org = {w["id"]: w for w in hr_paged("/workflows/")}
        wanted = [i for i in org if i not in lk] if body.all_unlinked else body.workflow_ids
        base = base_url(request)
        results = []
        for ext_id in wanted:
            src = org.get(ext_id)
            if not src:
                results.append({"external_id": ext_id, "error": "no existe en la org"}); continue
            if ext_id in lk:
                results.append({"external_id": ext_id, "workflow": P.public(P.get_workflow(lk[ext_id]["workflow_id"]), config, base),
                                "link": lk[ext_id], "already": True}); continue
            wf = _create_workflow(src.get("name") or src.get("slug") or ext_id, "happyrobot", body.base_profile, body.mode,
                                  goal=(src.get("description") or ""))
            token = P.token_for(wf)
            title = f"AngryRobot · {wf['name']}"
            cred_id, cred_err = None, None
            if body.create_credential:
                try:
                    cred = hr("POST", f"/integrations/{CUSTOM_LLM_INTEGRATION}/create-credential",
                              {"credential_type": "endpoint", "title": title,
                               "data": {"endpoint": f"{base}/v1/{wf['id']}", "auth_type": "bearer", "api_key": token}})
                    cred_id = (cred or {}).get("id") or (cred or {}).get("credential_id")
                except HTTPException as e:
                    cred_err = e.detail
            with closing(P._conn()) as c:
                c.execute("INSERT OR REPLACE INTO provider_links VALUES (?,?,?,?,?,?,?,?)",
                          (wf["id"], "happyrobot", ext_id, src.get("slug"), src.get("name"), cred_id, title if cred_id else None, P._now()))
                c.commit()
            results.append({
                "external_id": ext_id, "external_slug": src.get("slug"), "external_name": src.get("name"),
                "workflow": P.public(wf, config, base, with_token=True),
                "credential": {"id": cred_id, "title": title, "endpoint": f"{base}/v1/{wf['id']}", "error": cred_err},
                # Lo que queda por hacer a mano en el builder de HappyRobot.
                "next_steps": [
                    f"HappyRobot builder → {src.get('name')} → Prompt node → Model → Custom LLM server → choose “{title}”.",
                    "Append `\\n[ar] run={{current.run_id}}` at the end of the prompt (the proxy strips it and uses the id for levers).",
                    "Publish a new version (fork it; re-publishing the live one fails with 400).",
                ],
            })
        return {"results": results, "connected": len([r for r in results if r.get("workflow") and not r.get("already")])}

    return router
