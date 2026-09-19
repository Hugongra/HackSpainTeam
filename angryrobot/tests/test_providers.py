"""
Tests del conector de proveedores (providers.py) con la API de HappyRobot simulada: no hay red.
python -m pytest -q tests/test_providers.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
# Comparte proceso con los demás tests: no recarga módulos ni cambia la BD si otro fichero ya la fijó.
os.environ.setdefault("ANGRYROBOT_DB", os.path.join(tempfile.mkdtemp(), "providers_test.db"))
os.environ["ANGRYROBOT_SHARED_SECRET"] = "test-secret"
os.environ["ANGRYROBOT_JUDGE_PROVIDER"] = "mock"
os.environ["HAPPYROBOT_API_KEY"] = "sk_test_fake"
os.chdir(HERE)

import providers  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

client = TestClient(main.app)
ADMIN = {"X-AngryRobot-Secret": "test-secret"}

ORG = [
    {"id": "hr-1", "slug": "angryrobots-probe-voice", "name": "Carrier intake", "description": "voice intake",
     "latest_version": {"version_number": 3, "is_live": True}},
    {"id": "hr-2", "slug": "rogue-closer", "name": "Rogue closer", "latest_version": {"version_number": 1, "is_live": False}},
]
CALLS = []


def fake_hr(method, path, body=None, params=None, timeout=20):
    CALLS.append((method, path, body))
    if method == "GET" and path == "/workflows/":
        return {"data": ORG, "pagination": {"has_next_page": False}}
    if method == "POST" and path.endswith("/create-credential"):
        return {"id": f"cred-{len(CALLS)}", "title": body["title"]}
    raise AssertionError(f"unexpected call {method} {path}")


providers.hr = fake_hr


def test_providers_catalog_marks_only_happyrobot_available():
    r = client.get("/v1/providers", headers=ADMIN)
    assert r.status_code == 200
    ps = {p["id"]: p for p in r.json()["providers"]}
    assert ps["happyrobot"]["available"] and ps["happyrobot"]["configured"]
    assert not ps["openai"]["available"] and not ps["claude"]["available"] and not ps["gemini"]["available"]


def test_needs_the_secret():
    assert client.get("/v1/providers/happyrobot/workflows").status_code == 401


def test_lists_org_workflows_unlinked_first_time():
    r = client.get("/v1/providers/happyrobot/workflows", headers=ADMIN)
    assert r.status_code == 200, r.text
    ws = r.json()["workflows"]
    assert [w["id"] for w in ws] == ["hr-1", "hr-2"]          # live first
    assert all(w["linked_workflow"] is None for w in ws)


def test_connect_creates_workflow_credential_and_link():
    r = client.post("/v1/providers/happyrobot/connect", headers=ADMIN,
                    json={"workflow_ids": ["hr-1"], "base_profile": "probe-voice", "mode": "enforce"})
    assert r.status_code == 200, r.text
    res = r.json()["results"][0]
    wf = res["workflow"]
    assert wf["source"] == "happyrobot" and wf["base_profile"] == "probe-voice" and wf["token"].startswith("arw_")
    assert res["credential"]["id"] and res["credential"]["title"] == f"AngryRobot · {wf['name']}"
    assert res["credential"]["endpoint"].endswith(f"/v1/{wf['id']}")
    # la credencial se creó en HappyRobot con el proxy como endpoint y el token del workflow como bearer
    cred_call = next(c for c in CALLS if c[0] == "POST")
    assert cred_call[2]["data"]["endpoint"] == res["credential"]["endpoint"]
    assert cred_call[2]["data"]["api_key"] == wf["token"]
    assert cred_call[2]["data"]["auth_type"] == "bearer"
    assert len(res["next_steps"]) == 3
    # y ahora el listado lo muestra enlazado
    ws = {w["id"]: w for w in client.get("/v1/providers/happyrobot/workflows", headers=ADMIN).json()["workflows"]}
    assert ws["hr-1"]["linked_workflow"] == wf["id"]
    assert client.get(f"/v1/providers/links/{wf['id']}", headers=ADMIN).json()["link"]["external_id"] == "hr-1"


def test_connect_again_is_idempotent_and_sync_takes_the_rest():
    r = client.post("/v1/providers/happyrobot/connect", headers=ADMIN, json={"workflow_ids": ["hr-1"]})
    assert r.json()["results"][0]["already"] is True and r.json()["connected"] == 0
    r = client.post("/v1/providers/happyrobot/connect", headers=ADMIN, json={"all_unlinked": True, "base_profile": "rogue-guard"})
    assert r.status_code == 200, r.text
    assert r.json()["connected"] == 1
    assert r.json()["results"][0]["external_id"] == "hr-2"
    ws = client.get("/v1/providers/happyrobot/workflows", headers=ADMIN).json()
    assert ws["linked"] == 2


def test_connect_without_credential_when_asked():
    before = len([c for c in CALLS if c[0] == "POST"])
    providers_links = providers.links()
    # desenlaza hr-2 para poder repetir sin credencial
    import sqlite3
    with sqlite3.connect(os.environ["ANGRYROBOT_DB"]) as c:
        c.execute("DELETE FROM provider_links WHERE external_id = 'hr-2'")
    r = client.post("/v1/providers/happyrobot/connect", headers=ADMIN, json={"workflow_ids": ["hr-2"], "create_credential": False})
    assert r.status_code == 200
    assert r.json()["results"][0]["credential"]["id"] is None
    assert len([c for c in CALLS if c[0] == "POST"]) == before
    assert providers_links is not None


def test_unknown_profile_is_rejected():
    r = client.post("/v1/providers/happyrobot/connect", headers=ADMIN, json={"workflow_ids": ["hr-1"], "base_profile": "nope"})
    assert r.status_code == 400
