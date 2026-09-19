"""
La memoria de los casos — sin esto, "aprender de los fallos" es imposible.

Cada auditoría (también las ALLOW, para poder medir falsos positivos) se guarda
con un case_id que la respuesta devuelve. Un humano puede después marcar ese caso
con /feedback ('correct' | 'false_positive' | 'false_negative') y learn.py
propone recalibraciones offline, siempre con revisión humana.

v2: además de las columnas de v1, guarda el REGISTRO COMPLETO de la auditoría
(`record`: señales con su evidencia, impacto, sospecha, juez, razonamiento,
palanca aplicada), el run y el perfil. SQLite: un archivo, cero configuración.
En el Space de Hugging Face el disco es efímero (ANGRYROBOT_DB=/tmp/...).
"""
import json
import os
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone

DB_PATH = os.environ.get("ANGRYROBOT_DB", "angryrobot_cases.db")


def init_db(db_path: str = DB_PATH) -> None:
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cases (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                workflow_goal TEXT,
                constraints TEXT,
                reasoning_trace TEXT,
                proposed_action TEXT,
                session_history TEXT,
                hard_filter_hits TEXT,
                dimensions TEXT,
                ira_score REAL,
                verdict TEXT,
                human_label TEXT,
                human_notes TEXT,
                labeled_at TEXT
            )
        """)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(cases)")}
        for col in ("record", "run_id", "profile"):
            if col not in cols:
                conn.execute(f"ALTER TABLE cases ADD COLUMN {col} TEXT")
        conn.commit()


def save_case(db_path: str, *, workflow_goal: str, constraints: list, reasoning_trace: str,
              proposed_action: dict, session_history: list, hard_filter_hits: list,
              dimensions: dict, ira_score: float, verdict: str, record: dict | None = None,
              run_id: str | None = None, profile: str | None = None) -> str:
    case_id = str(uuid.uuid4())
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute(
            """INSERT INTO cases (id, created_at, workflow_goal, constraints, reasoning_trace,
                                   proposed_action, session_history, hard_filter_hits, dimensions,
                                   ira_score, verdict, human_label, human_notes, labeled_at,
                                   record, run_id, profile)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?, ?)""",
            (case_id, datetime.now(timezone.utc).isoformat(), workflow_goal, json.dumps(constraints),
             reasoning_trace, json.dumps(proposed_action, default=str), json.dumps(session_history, default=str),
             json.dumps(hard_filter_hits), json.dumps(dimensions), ira_score, verdict,
             json.dumps(record, default=str) if record else None, run_id, profile),
        )
        conn.commit()
    return case_id


def label_case(db_path: str, case_id: str, label: str, notes: str = "") -> bool:
    """
    label: 'correct' | 'false_positive' | 'false_negative'.
    - false_positive: AngryRobot frenó algo inofensivo (le cuesta usabilidad al agente).
    - false_negative: dejó pasar algo que un humano habría frenado. El caso grave.
    """
    assert label in ("correct", "false_positive", "false_negative")
    with closing(sqlite3.connect(db_path)) as conn:
        cur = conn.execute("UPDATE cases SET human_label = ?, human_notes = ?, labeled_at = ? WHERE id = ?",
                           (label, notes, datetime.now(timezone.utc).isoformat(), case_id))
        conn.commit()
        return cur.rowcount > 0


def get_case(db_path: str, case_id: str) -> dict | None:
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    if not row:
        return None
    case = dict(row)
    case["record"] = json.loads(case["record"]) if case.get("record") else None
    return case


def get_labeled_cases(db_path: str, label: str | None = None) -> list[dict]:
    query = "SELECT * FROM cases WHERE human_label IS NOT NULL"
    params = ()
    if label:
        query += " AND human_label = ?"
        params = (label,)
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query, params).fetchall()

    cases = []
    for row in rows:
        case = dict(row)
        for field in ("constraints", "proposed_action", "session_history", "hard_filter_hits", "dimensions", "record"):
            case[field] = json.loads(case[field]) if case.get(field) else None
        cases.append(case)
    return cases
