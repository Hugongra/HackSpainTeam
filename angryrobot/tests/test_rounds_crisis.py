"""
Tests del modo crisis (crisis.py + integrations/notify.py): varios maliciosos a la vez, detección por ventana,
postura estricta, reencaminado tras un KILL, avisos por orden de gravedad por canales reales (webhook contra un
servidor HTTP local, correo contra un SMTP falso), pool de operadores con triaje, resultado contra la verdad, rutas.
Juez en modo mock y sin red. python -m pytest -q tests
"""
import json
import os
import random
import sys
import tempfile
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("ANGRYROBOT_DB", os.path.join(tempfile.mkdtemp(), "rounds_test.db"))
os.environ.setdefault("ANGRYROBOT_SHARED_SECRET", "test-secret")
os.environ["ANGRYROBOT_JUDGE_PROVIDER"] = "mock"
os.chdir(HERE)

from fastapi.testclient import TestClient  # noqa: E402

import crisis  # noqa: E402
import main  # noqa: E402
import rounds  # noqa: E402
from integrations import notify  # noqa: E402

client = TestClient(main.app)
ADMIN = {"X-AngryRobot-Secret": os.environ["ANGRYROBOT_SHARED_SECRET"]}
CHANNEL_VARS = ("HAPPYROBOT_ALERT_WEBHOOK_URL", "HAPPYROBOT_API_KEY", "HAPPYROBOT_ALERT_WORKFLOW_ID", "SMTP_HOST", "SMTP_USER",
                "SMTP_PASS", "ANGRYROBOT_ALERT_WEBHOOK_URL", "ANGRYROBOT_ALERT_EMAIL", "HAPPYROBOT_SMS_WEBHOOK_URL",
                "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM", "ANGRYROBOT_SMS_PHONE", "ANGRYROBOT_SMS_MESSAGE")


@pytest.fixture(autouse=True)
def no_real_channels(monkeypatch):
    """Ningún test sale hacia fuera de verdad: sin variables, cada canal responde not_configured."""
    for k in CHANNEL_VARS:
        monkeypatch.delenv(k, raising=False)
    crisis.seed_pool(2, force=True)


def crisis_seed(pred, mode="crisis", **mal):
    for seed in range(1, 4000):
        d = rounds.draw(random.Random(seed), malicious={"mode": mode, **mal})
        if pred(d["truth"]):
            return seed
    raise AssertionError("no seed")


def play(seed, **opts):
    rounds.ensure_workflows()
    r = rounds.Round(main.CONFIG, {"pace": "none", "judge": False, "call_on_kill": True, "malicious": {"mode": "crisis"}, **opts}, seed)
    r._run()
    return r


def fake_channels(monkeypatch, sent):
    """Los tres canales 'configurados' y capturados (nada sale de verdad)."""
    monkeypatch.setenv("SMTP_HOST", "smtp.test"); monkeypatch.setenv("ANGRYROBOT_ALERT_EMAIL", "ops@test.invalid")
    monkeypatch.setenv("ANGRYROBOT_ALERT_WEBHOOK_URL", "https://discord.com/api/webhooks/1/x")
    monkeypatch.setenv("HAPPYROBOT_ALERT_WEBHOOK_URL", "https://hooks.test.invalid/abc")
    monkeypatch.setenv("HAPPYROBOT_SMS_WEBHOOK_URL", "https://hooks.test.invalid/sms")
    for ch in notify.CHANNELS:
        monkeypatch.setitem(notify.SENDERS, ch, lambda t, m, c, ch=ch: sent.append((ch, t, m, c)) or {"status": "sent", "detail": f"{ch} ok"})


# ---------------------------------------------------------------- sorteo
def test_crisis_draw_has_two_or_more_rogues_in_distinct_seats_with_compatible_traits():
    rng = random.Random(0)
    counts = Counter()
    for _ in range(400):
        d = rounds.draw(random.Random(rng.randrange(2 ** 31)), malicious={"mode": "crisis"})
        rg = d["truth"]["rogues"]
        assert 2 <= len(rg) <= 5 and d["truth"]["mode"] == "crisis" and d["truth"]["chosen_by"] == "crisis"
        counts[len(rg)] += 1
        assert len({r["seat"] for r in rg}) == len(rg)                                   # puestos distintos
        assert sum(bool(s["malicious"]) for s in d["seats"]) == len(rg)
        for r in rg:
            assert r["seat"] in rounds.TRAITS[r["trait"]]["seats"]
            assert rounds.TRAIT_AT[(r["trait"], r["seat"])] in d["plan"][r["seat"]]      # su momento llega siempre
        assert rounds.SEV[d["truth"]["expect"]] == max(rounds.SEV[r["expect"]] for r in rg)   # seat/trait = el más grave
    assert set(counts) == {2, 3, 4, 5}, counts
    assert len(rounds.draw(random.Random(1), malicious={"mode": "all"})["truth"]["rogues"]) == 5
    assert len(rounds.draw(random.Random(1), malicious={"mode": "crisis", "count": 3})["truth"]["rogues"]) == 3
    assert len(rounds.draw(random.Random(1), 8, malicious={"mode": "crisis", "count": 99})["truth"]["rogues"]) == 8


def test_normal_rounds_are_untouched():
    rounds.ensure_workflows()
    r = rounds.Round(main.CONFIG, {"pace": "none", "judge": False, "call_on_kill": False}, 11)
    r._run()
    assert r.crisis is None and r.view()["crisis"] is None and "rogues" not in r.truth
    assert not any(e["kind"] in ("crisis_detected", "crisis_plan", "notice", "triage") for e in r.events)
    assert not r.outcome.get("crisis")


# ---------------------------------------------------------------- detección, reacción, avisos
def test_crisis_is_detected_reroutes_after_kill_and_notifies_worst_first(monkeypatch):
    sent = []
    fake_channels(monkeypatch, sent)
    seed = crisis_seed(lambda t: len(t["rogues"]) == 5 and t["rogues"][0]["expect"] == "KILL")
    r = play(seed)
    assert r.crisis.detected and r.outcome["crisis"] and r.outcome["label"] in ("contained", "partial"), r.outcome
    assert all(s["status"] != "skipped" for s in r.seats)                     # tras un KILL la llamada sigue: nadie se salta
    assert [s for s in r.seats if s["status"] == "killed"]
    kinds = [e["kind"] for e in r.events]
    assert kinds.index("crisis_detected") < kinds.index("crisis_plan") < kinds.index("notice")
    det = next(e for e in r.events if e["kind"] == "crisis_detected")
    assert len(det["crisis"]["detected"]["seats"]) >= 2 and det["crisis"]["detected"]["span"] <= 10
    plan = next(e for e in r.events if e["kind"] == "crisis_plan")["notices"]
    assert plan[0]["channel"] == "call" and plan[0]["to"] == "Seguridad de guardia" and plan[0]["priority"] == 1   # un KILL: seguridad primero, por teléfono
    assert all("(" in n["to"] for n in plan[1:]) and not any(n["channel"] == "sms" for n in r.crisis.notices)   # luego un responsable por puesto; el SMS es del segundo grado
    # los avisos a responsables de puesto van del más grave al menos grave (lo que luego se compara con la verdad)
    owners = [n for n in r.crisis.notices if n.get("roster") == "seat_owner"][:len(det["crisis"]["detected"]["seats"])]
    blocked = {b["seat"]: b for b in r.crisis.blocked}
    keys = [(rounds.SEV[blocked[n["seat"]]["verdict"]], blocked[n["seat"]]["ira"]) for n in owners]
    assert keys == sorted(keys, reverse=True) and all(n["channel"] == "email" for n in owners)
    assert [n["priority"] for n in r.crisis.notices] == list(range(1, len(r.crisis.notices) + 1))
    assert all(n["status"] == "sent" for n in r.crisis.notices) and len(sent) == len(r.crisis.notices)
    assert r.call["via"] == "crisis" and r.call["status"] == "sent"             # la llamada es un aviso del plan, no el disparo fijo
    assert sum(1 for n in r.crisis.notices if n["channel"] == "call") == 1       # y solo una, por mucho que caigan más
    assert len(notify.recent(100, r.id)) == len(r.crisis.notices)               # cada aviso queda registrado
    assert r.outcome["notified_order"][0] == r.outcome["truth_order"][0] == r.truth["seat"] and r.outcome["top1_correct"]
    assert r.outcome["coverage"] == 1.0 and r.outcome["noise"] == []
    row = crisis.stored_crises(5)[0]
    assert row["round_id"] == r.id and row["outcome"]["label"] == r.outcome["label"] and len(row["notices"]) == len(r.crisis.notices)


def test_without_kill_operations_leads_and_channels_fall_back_to_what_is_configured(monkeypatch):
    sent = []
    fake_channels(monkeypatch, sent)
    monkeypatch.delenv("SMTP_HOST")                                              # sin correo: los responsables van por webhook
    seed = crisis_seed(lambda t: len(t["rogues"]) == 2 and all(x["expect"] == "DEFER" for x in t["rogues"]))
    r = play(seed, crisis={"posture": "same"})
    if not r.crisis.detected:
        pytest.skip("con esta semilla los dos DEFER no caen en la ventana")
    plan = next(e for e in r.events if e["kind"] == "crisis_plan")["notices"]
    assert plan[0]["to"] == "Responsable de operaciones" and plan[0]["channel"] == "sms" and plan[0]["target_label"] == "+347…624"
    assert plan[0]["message"] == "Mon amour, les agents ont torné rogue!! Besu!!" == notify.sms_message()    # el texto fijo del segundo grado
    assert [n["channel"] for n in r.crisis.notices].count("sms") == 1                                         # y solo un SMS por crisis
    assert all(n["channel"] == "webhook" for n in plan[1:])                                                    # los responsables, por lo que haya: webhook
    assert all(n["channel"] != "call" for n in r.crisis.notices) and r.call["status"] == "crisis"   # sin disparo fijo: lo decidió el plan


def test_call_lever_off_means_no_phone_channel(monkeypatch):
    sent = []
    fake_channels(monkeypatch, sent)
    seed = crisis_seed(lambda t: len(t["rogues"]) == 5 and t["rogues"][0]["expect"] == "KILL")
    r = play(seed, call_on_kill=False)
    assert r.crisis.detected and all(n["channel"] != "call" for n in r.crisis.notices)
    assert r.call["status"] == "crisis" and not any(e["kind"] == "call" for e in r.events)   # ni llamada ni tarjeta de "último trigger"
    assert next(e for e in r.events if e["kind"] == "crisis_plan")["notices"][0]["channel"] == "log"   # sin palanca de llamada, seguridad solo queda en el registro


def test_strict_posture_holds_a_warn_after_detection_and_opens_an_escalation():
    for seed in range(1, 300):
        d = rounds.draw(random.Random(seed), malicious={"mode": "crisis"})
        if len(d["truth"]["rogues"]) < 3:
            continue
        r = play(seed)
        up = [e for e in r.events if e["kind"] == "agent" and e.get("posture_upgrade")]
        if up:
            break
    else:
        pytest.skip("ninguna semilla produjo un WARN tras la detección")
    e = up[0]
    assert e["verdict"] == "DEFER" and e["escalation_id"] and any(a.get("verdict_raw") == "WARN" for a in e["audits"])
    assert e["i"] > next(x["i"] for x in r.events if x["kind"] == "crisis_detected")
    lever = next(x for x in r.events if x["kind"] == "lever" and x["i"] > e["i"])
    assert "Postura de crisis" in lever["text"]
    assert next(s for s in r.seats if s["seat"] == e["seat"])["status"] == "held"
    esc = client.get("/v1/escalations", headers=ADMIN, params={"status": "open"}).json()["escalations"]
    assert any(x["id"] == e["escalation_id"] for x in esc)


def test_posture_same_never_upgrades():
    for seed in range(1, 120):
        r = play(seed, crisis={"posture": "same"})
        assert not any(e.get("posture_upgrade") for e in r.events if e["kind"] == "agent")
        if r.crisis.detected:
            return
    pytest.skip("sin detección en 120 semillas")


# ---------------------------------------------------------------- recursos: el pool de operadores
def test_operator_pool_is_consumed_and_triage_decides_who_waits():
    found = None
    for seed in range(1, 400):
        r = play(seed, crisis={"operators": 1})
        if any(t["decision"] in ("queued", "preempted") for t in r.crisis.triage):
            found = r
            break
    assert found, "ninguna semilla agotó el pool"
    r = found
    tr = r.crisis.triage
    assert tr[0]["decision"] == "assigned" and tr[0]["free_after"] == 0 and "atiende" in tr[0]["text"]
    later = next(t for t in tr[1:] if t["decision"] in ("queued", "preempted"))
    if later["decision"] == "queued":
        assert later["behind"] and "NO se atiende todavía" in later["text"]
    else:
        assert later["displaced"] and later["ira"] >= later["displaced"]["ira"] + crisis.PREEMPT_MARGIN and "vuelve a la cola" in later["text"]
    assert r.outcome["operators_exhausted"] is True
    ev = [e for e in r.events if e["kind"] == "triage"]
    assert [e["decision"] for e in ev] == [t["decision"] for t in tr] and all(e["pool"]["total"] == 1 for e in ev)
    assert crisis.pool_state() == {**crisis.pool_state(), "total": 1, "free": 1, "busy": 0}     # liberado al acabar


def test_pool_api_resizes_and_reports():
    assert client.get("/v1/crisis/operators").status_code == 401
    out = client.post("/v1/crisis/operators", headers=ADMIN, json={"count": 3}).json()
    assert out["total"] == 3 and out["free"] == 3 and [o["name"] for o in out["operators"]] == ["Marta", "Jon", "Carla"]
    assert client.post("/v1/crisis/operators", headers=ADMIN, json={"count": 99}).status_code == 400
    assert client.get("/v1/crisis/operators", headers=ADMIN).json()["total"] == 3


# ---------------------------------------------------------------- los canales de notify.py
class _Hook(BaseHTTPRequestHandler):
    got = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        _Hook.got.append(json.loads(body))
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


def test_webhook_channel_posts_for_real_to_a_local_server(monkeypatch):
    srv = HTTPServer(("127.0.0.1", 0), _Hook)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("ANGRYROBOT_ALERT_WEBHOOK_URL", f"http://127.0.0.1:{srv.server_port}/hook")
        assert notify.configured()["webhook"]["ready"] and notify.configured()["webhook"]["how"] == "generic"
        rec = notify.notify("webhook", None, "CRISIS de prueba", {"lines": ["1. Iker KILL 96"], "event": "crisis_detected", "n_blocked": 2},
                            to="Canal de operaciones", priority=4, reason="resumen", round_id="r-test")
        assert rec["status"] == "sent" and rec["target_label"].startswith("http://127.0.0.1")
        got = _Hook.got[-1]
        assert got["source"] == "angryrobot" and got["message"] == "CRISIS de prueba" and got["lines"] == ["1. Iker KILL 96"]
        assert got["event"] == "crisis_detected" and got["n_blocked"] == 2 and got["round_id"] == "r-test"
        assert notify.recent(5, "r-test")[0]["to"] == "Canal de operaciones"
    finally:
        srv.shutdown()
    assert notify.webhook_payload("https://hooks.slack.com/services/x", "m", {"lines": ["a"]}) == {"text": "m\n• a"}
    assert notify.webhook_payload("https://discord.com/api/webhooks/1/x", "m", {})["content"] == "m"
    assert notify.mask("webhook", "https://hooks.slack.com/services/T/B/secret") == "Slack webhook"
    monkeypatch.setenv("ANGRYROBOT_ALERT_WEBHOOK_URL", "http://127.0.0.1:9/nope")
    assert notify.notify("webhook", None, "x", {})["status"] == "failed"


def test_email_channel_uses_smtp(monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            sent["host"], sent["port"] = host, port

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def ehlo(self):
            pass

        def starttls(self):
            sent["tls"] = True

        def login(self, u, p):
            sent["login"] = (u, p)

        def send_message(self, msg):
            sent["msg"] = msg

    monkeypatch.setattr(notify.smtplib, "SMTP", FakeSMTP)
    assert notify.notify("email", None, "hola", {})["status"] == "not_configured"
    monkeypatch.setenv("SMTP_HOST", "smtp.test"); monkeypatch.setenv("SMTP_USER", "bot@test"); monkeypatch.setenv("SMTP_PASS", "pw")
    monkeypatch.setenv("ANGRYROBOT_ALERT_EMAIL", "guardia@test.invalid")
    assert notify.configured()["email"] == {"ready": True, "target": "gu…@test.invalid", "how": "SMTP smtp.test"}
    rec = notify.notify("email", None, "Iker ha sido cortado", {"subject": "AngryRobot · KILL", "lines": ["motivo: x"], "round_id": "r-1"},
                        to="Jefe de Reservas", priority=2, reason="peor IRA")
    assert rec["status"] == "sent" and sent["login"] == ("bot@test", "pw") and sent["tls"] and sent["port"] == 587
    m = sent["msg"]
    assert m["To"] == "guardia@test.invalid" and m["Subject"] == "AngryRobot · KILL" and "motivo: x" in m.get_content()
    with pytest.raises(ValueError):
        notify.notify("pigeon", None, "x")


class _Resp:
    def __init__(self, code, body):
        self.status_code, self.text, self._body = code, str(body), body

    def json(self):
        return self._body


def test_sms_channel_by_happyrobot_webhook_or_twilio(monkeypatch):
    sent = []
    monkeypatch.setattr(notify.requests, "post", lambda url, **kw: sent.append((url, kw)) or _Resp(201 if "twilio" in url else 200, {"sid": "SM1", "ok": True}))
    assert notify.notify("sms", None, "x")["status"] == "not_configured"                       # sin nada: no sale, y lo dice
    assert notify.configured()["sms"] == {"ready": False, "target": "+347…624", "how": "not configured"}
    monkeypatch.setenv("HAPPYROBOT_SMS_WEBHOOK_URL", "https://workflows.platform.eu.happyrobot.ai/hooks/sms1")
    rec = notify.notify("sms", None, notify.sms_message(), {"round_id": "r-1"}, to="Responsable de operaciones", priority=1)
    assert rec["status"] == "sent" and rec["target"] == "+34722222624" and notify.configured()["sms"]["how"] == "HappyRobot webhook"
    assert sent[-1][0].endswith("/hooks/sms1") and sent[-1][1]["json"] == {"phone_number": "+34722222624", "message": "Mon amour, les agents ont torné rogue!! Besu!!"}
    monkeypatch.delenv("HAPPYROBOT_SMS_WEBHOOK_URL")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACtest"); monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok"); monkeypatch.setenv("TWILIO_FROM", "+16402214277")
    monkeypatch.setenv("ANGRYROBOT_SMS_PHONE", "+34600000001"); monkeypatch.setenv("ANGRYROBOT_SMS_MESSAGE", "hola")
    rec = notify.notify("sms", None, notify.sms_message(), {})
    url, kw = sent[-1]
    assert rec["status"] == "sent" and rec["response"] == "SM1" and notify.configured()["sms"]["how"] == "Twilio"
    assert url == "https://api.twilio.com/2010-04-01/Accounts/ACtest/Messages.json" and kw["auth"] == ("ACtest", "tok")
    assert kw["data"] == {"To": "+34600000001", "From": "+16402214277", "Body": "hola"}
    monkeypatch.setattr(notify.requests, "post", lambda url, **kw: _Resp(400, {"message": "bad"}))
    assert notify.notify("sms", None, "x")["status"] == "failed"
    assert notify.notify("log", None, "x", to="Alguien")["status"] == "logged"                  # el último recurso: solo registro


def test_call_channel_reuses_the_happyrobot_alert(monkeypatch):
    seen = {}
    monkeypatch.setattr(notify.happyrobot_call, "alert_call", lambda ctx, phone=None, message=None: seen.update(phone=phone, message=message) or {"status": "sent", "detail": "ok"})
    rec = notify.notify("call", "+34600000000", "Crisis", {"round_id": "r-1"}, to="Seguridad de guardia", priority=1)
    assert rec["status"] == "sent" and seen == {"phone": "+34600000000", "message": "Crisis"} and rec["target_label"] == "+346…000"
    rec = notify.notify("call", None, "x")                                       # sin destino: el teléfono de prueba del equipo
    assert rec["target"] == notify.happyrobot_call.alert_phone() and seen["phone"] == rec["target"]


# ---------------------------------------------------------------- resultado contra la verdad
def _crisis(threshold=2, window=10, seats=None):
    return crisis.Crisis("r-score", seats or [], {"crisis": {"threshold": threshold, "window": window}, "call_on_kill": False},
                         lambda *a, **k: None, lambda reason: None, lambda: False)


def test_score_compares_the_notice_order_with_the_real_severity(monkeypatch):
    for ch in notify.CHANNELS:
        monkeypatch.setitem(notify.SENDERS, ch, lambda t, m, c: {"status": "not_configured", "detail": "off"})
    seats = [{"seat": "intake", "kind": "intake", "agent": "A", "role": "Recepción", "source_label": "HappyRobot", "malicious": "deny_ai", "status": "killed", "worst": "DEFER"},
             {"seat": "booking", "kind": "booking", "agent": "B", "role": "Reservas", "source_label": "Gemini", "malicious": "rate_floor", "status": "held", "worst": "KILL"},
             {"seat": "comms", "kind": "comms", "agent": "C", "role": "Avisos", "source_label": "Webhook", "malicious": None, "status": "done", "worst": "ALLOW"}]
    truth = {"rogues": [{"seat": "intake", "trait": "deny_ai", "expect": "KILL"}, {"seat": "booking", "trait": "rate_floor", "expect": "DEFER"}]}
    c = _crisis(seats=seats)
    c.on_turn(); c.on_blocked(seats[0], "DEFER", 60, "x", None)
    c.on_turn(); c.on_blocked(seats[1], "KILL", 95, "y", None)
    assert c.detected and c.detected["at_turn"] == 2
    out = c.score(seats, truth)
    assert out["notified_order"] == ["booking", "intake"] and out["truth_order"] == ["intake", "booking"]   # avisamos primero del que parecía peor...
    assert out["top1_correct"] is False and out["order_agreement"] == 0.0 and out["coverage"] == 1.0            # ...y no era el más grave de verdad
    assert out["label"] == "contained" and out["detected"] and out["should_detect"] and out["crisis"] is True
    # una ventana corta que no llega: crisis sin declarar
    c = _crisis(window=1, seats=seats)
    c.on_turn(); c.on_blocked(seats[0], "DEFER", 60, "x", None)
    for _ in range(3):
        c.on_turn()
    c.on_blocked(seats[1], "KILL", 95, "y", None)
    out = c.score(seats, truth)
    assert not c.detected and out["label"] == "missed_crisis" and out["notified_order"] == [] and out["met_expectation"] is False
    # por debajo del umbral no hay crisis, y está bien no declararla
    out = _crisis(threshold=3, seats=seats).score(seats, truth)
    assert out["label"] == "quiet" and out["met_expectation"] is True
    rep = crisis.crisis_stats([{"round_id": "a", "outcome": out, "notices": []},
                               {"round_id": "b", "outcome": c.score(seats, truth), "notices": [{"channel": "email", "status": "sent"}]}])
    assert rep["crises"] == 2 and rep["detection_rate"] == 0.0 and rep["notices"] == {"email:sent": 1}


# ---------------------------------------------------------------- por la API
def test_crisis_round_over_the_api_config_history_and_report():
    cfg = client.get("/v1/rounds/config", headers=ADMIN).json()["crisis"]
    assert cfg["defaults"]["threshold"] == 2 and "security_oncall" in cfg["roster"] and set(cfg["channels"]) == {"call", "sms", "email", "webhook", "log"}
    assert not any(v["ready"] for k, v in cfg["channels"].items() if k != "log") and cfg["channels"]["log"]["ready"]
    bad = client.post("/v1/rounds", headers=ADMIN, json={"malicious": {"mode": "nope"}})
    assert bad.status_code == 400
    assert client.post("/v1/rounds", headers=ADMIN, json={"malicious": {"mode": "crisis", "count": 99}}).status_code == 400
    assert client.post("/v1/rounds", headers=ADMIN, json={"malicious": {"mode": "crisis"}, "crisis": {"posture": "x"}}).status_code == 400
    r = client.post("/v1/rounds", headers=ADMIN, json={"pace": "auto", "delay": 0, "call_on_kill": False, "autostart": True,
                                                       "malicious": {"mode": "crisis", "count": 3}, "crisis": {"threshold": 2, "window": 12}}).json()
    assert len(r["truth"]["rogues"]) == 3 and all("label" in x for x in r["truth"]["rogues"])
    assert r["crisis"]["threshold"] == 2 and r["crisis"]["window"] == 12 and r["options"]["crisis"] == {"threshold": 2, "window": 12}
    assert sum(1 for s in r["seats"] if s["malicious"]) == 3
    for _ in range(400):
        v = client.get(f"/v1/rounds/{r['id']}", headers=ADMIN).json()
        if v["status"] in ("done", "error"):
            break
        time.sleep(0.05)
    assert v["status"] == "done" and v["outcome"]["crisis"] and v["crisis"]["blocked"]
    assert v["outcome"]["label"] in ("contained", "partial", "missed_crisis")
    hist = client.get("/v1/crisis/history", headers=ADMIN).json()["crises"]
    assert hist[0]["round_id"] == r["id"] and hist[0]["outcome"]["label"] == v["outcome"]["label"]
    rep = client.get("/v1/crisis/report", headers=ADMIN).json()
    assert rep["crises"] >= 1 and rep["last"][0]["round_id"] == r["id"]
    stats = client.get("/v1/rounds/stats", headers=ADMIN).json()
    assert not {"contained", "partial", "missed_crisis"} & set(stats["outcomes"])          # las crisis no distorsionan las métricas de ronda
    if v["crisis"]["detected"]:
        assert client.get("/v1/crisis/notices", headers=ADMIN, params={"round_id": r["id"]}).json()["notices"]
    t = client.post("/v1/crisis/test-notice", headers=ADMIN, json={"channel": "webhook"}).json()
    assert t["status"] == "not_configured" and t["to"] == "Prueba desde la consola"
    assert client.post("/v1/crisis/test-notice", headers=ADMIN, json={"channel": "pigeon"}).status_code == 400


def test_blind_crisis_round_hides_who_but_says_how_many():
    r = client.post("/v1/rounds", headers=ADMIN, json={"pace": "step", "blind": True, "call_on_kill": False, "malicious": {"mode": "all"}}).json()
    assert r["truth"] == {"hidden": True, "crisis": True, "count": 5} and all(s["malicious"] == "hidden" for s in r["seats"])
    client.post(f"/v1/rounds/{r['id']}/stop", headers=ADMIN)


def test_step_mode_pauses_before_the_notices_go_out(monkeypatch):
    """Paso a paso: la ronda se para con el plan decidido y visible (status planned) ANTES de que salga nada;
    el siguiente Next lo dispara."""
    sent = []
    fake_channels(monkeypatch, sent)
    seed = crisis_seed(lambda t: len(t["rogues"]) == 5 and t["rogues"][0]["expect"] == "KILL" and t["rogues"][1]["expect"] == "KILL")
    r = client.post("/v1/rounds", headers=ADMIN, json={"pace": "step", "autostart": True, "seed": seed, "malicious": {"mode": "crisis"}}).json()
    rid = r["id"]

    def wait_pause():
        for _ in range(300):
            v = client.get(f"/v1/rounds/{rid}", headers=ADMIN).json()
            if v["status"] in ("waiting", "done", "error"):
                return v
            time.sleep(0.02)
        raise AssertionError("la ronda no se para")

    v = wait_pause()
    for _ in range(40):
        if v["waiting_for"] == "before_notify" or v["status"] != "waiting":
            break
        client.post(f"/v1/rounds/{rid}/next", headers=ADMIN)
        time.sleep(0.03)
        v = wait_pause()
    assert v["status"] == "waiting" and v["waiting_for"] == "before_notify", (v["status"], v.get("waiting_for"))
    assert v["crisis"]["notices"] and all(n["status"] == "planned" for n in v["crisis"]["notices"]) and not sent
    assert any(e["kind"] == "crisis_plan" for e in v["events"]) and not any(e["kind"] == "notice" for e in v["events"])
    client.post(f"/v1/rounds/{rid}/pace", headers=ADMIN, json={"pace": "auto", "delay": 0})
    for _ in range(400):
        v = client.get(f"/v1/rounds/{rid}", headers=ADMIN).json()
        if v["status"] in ("done", "error"):
            break
        time.sleep(0.02)
    assert v["status"] == "done" and sent and v["crisis"]["notices"][0]["status"] == "sent"
    assert len(notify.recent(100, rid)) == len(v["crisis"]["notices"])                   # planned -> sent: una fila por aviso
