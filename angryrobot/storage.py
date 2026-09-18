"""
La memoria de los casos — sin esto, "aprender de los fallos" es imposible.

POR QUÉ HACE FALTA ESTO ANTES DE PODER APRENDER DE NADA:
Ahora mismo, AngryRobot audita, responde, y se olvida. Cada llamada a /audit
es como si no hubiera pasado ninguna anterior. Para aprender de un fallo,
primero necesitas dos cosas que hoy no existen: (1) un registro de lo que
pasó en cada auditoría, con un identificador para poder señalarla después, y
(2) un sitio donde un humano pueda decir "este caso #384, el veredicto
estuvo mal, aquí tienes la razón". Sin esas dos piezas, "aprender" es solo
una palabra bonita sin nada detrás.

Usamos SQLite (viene incluido en Python, cero configuración, un solo
archivo .db) porque para un hackathon no necesitáis levantar un servidor de
base de datos aparte — y porque el volumen de casos que vais a auditar es
pequeño comparado con lo que SQLite aguanta de sobra.
"""
import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone

DB_PATH = "angryrobot_cases.db"


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
        conn.commit()


def save_case(db_path: str, *, workflow_goal: str, constraints: list, reasoning_trace: str,
              proposed_action: dict, session_history: list, hard_filter_hits: list,
              dimensions: dict, ira_score: float, verdict: str) -> str:
    case_id = str(uuid.uuid4())
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute(
            """INSERT INTO cases (id, created_at, workflow_goal, constraints, reasoning_trace,
                                   proposed_action, session_history, hard_filter_hits, dimensions,
                                   ira_score, verdict, human_label, human_notes, labeled_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL)""",
            (
                case_id,
                datetime.now(timezone.utc).isoformat(),
                workflow_goal,
                json.dumps(constraints),
                reasoning_trace,
                json.dumps(proposed_action),
                json.dumps(session_history),
                json.dumps(hard_filter_hits),
                json.dumps(dimensions),
                ira_score,
                verdict,
            ),
        )
        conn.commit()
    return case_id


def label_case(db_path: str, case_id: str, label: str, notes: str = "") -> bool:
    """
    label debe ser uno de: 'correct', 'false_positive', 'false_negative'.

    - false_positive: AngryRobot avisó/bloqueó, pero la acción era en realidad inofensiva
      (le está costando usabilidad al agente sin motivo real).
    - false_negative: AngryRobot dejó pasar (ALLOW) algo que un humano, mirándolo después,
      considera que debería haberse frenado. Este es el caso grave: es el que de verdad
      queremos que alimente el aprendizaje.
    """
    assert label in ("correct", "false_positive", "false_negative")
    with closing(sqlite3.connect(db_path)) as conn:
        cur = conn.execute(
            "UPDATE cases SET human_label = ?, human_notes = ?, labeled_at = ? WHERE id = ?",
            (label, notes, datetime.now(timezone.utc).isoformat(), case_id),
        )
        conn.commit()
        return cur.rowcount > 0


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
        for field in ("constraints", "proposed_action", "session_history", "hard_filter_hits", "dimensions"):
            case[field] = json.loads(case[field]) if case[field] else None
        cases.append(case)
    return cases
