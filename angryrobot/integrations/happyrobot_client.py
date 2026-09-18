"""
Adaptador hacia la API de HappyRobot.

POR QUÉ ESTE ARCHIVO EXISTE SEPARADO DEL RESTO:
El motor de AngryRobot (filters.py, loop_detector.py, auditor.py, scoring.py)
no sabe nada de HappyRobot. No importa "HappyRobot" en ningún sitio, no
conoce sus nombres de campos ni sus endpoints. Eso es intencional: si mañana
queréis usar AngryRobot para vigilar OTRO agente (uno construido con otra
plataforma), no tocáis ni una línea del motor — solo escribiríais otro
archivo como este, para esa plataforma.

Este archivo es la ÚNICA pieza que sabe hablar el idioma específico de
HappyRobot: sus endpoints, su forma de autenticar, sus nombres de campo.
Si HappyRobot cambia su API mañana, es el único archivo que tocáis.

⚠️ IMPORTANTE — estado de esto: la documentación de docs.happyrobot.ai está
protegida con un código de acceso al que no llegué (no tengo vuestra sesión
logueada), así que las rutas y campos exactos de abajo son mi mejor hipótesis
a partir de los títulos de endpoint que sí son públicos vía buscador
("Create a Use Case", "Get Call", "Create Outbound Call", "Post use cases
add webhook"). Antes de confiar en esto, entrad a vuestra cuenta, abrid esos
endpoints en la doc real y ajustad BASE_URL, las rutas y los nombres de campo
marcados con TODO. Es un esqueleto para arrancar rápido, no una integración
verificada.
"""
import os

import requests

BASE_URL = os.environ.get("HAPPYROBOT_API_BASE_URL", "https://api.happyrobot.ai")  # TODO: confirmar
API_KEY = os.environ.get("HAPPYROBOT_API_KEY")


def _headers() -> dict:
    # TODO: confirmar si es "Bearer <key>" o un header propio tipo "x-api-key"
    return {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}


def register_webhook(use_case_id: str, webhook_url: str, secret: str) -> dict:
    """
    Da de alta la URL de AngryRobot como webhook de un 'use case' de HappyRobot.
    Esto se hace UNA VEZ al configurar el proyecto, no en cada llamada — es
    configuración, no runtime.
    """
    # TODO: confirmar ruta exacta y forma del payload (endpoint real:
    # "Post use cases add webhook" en docs.happyrobot.ai/api-reference/usecases/post-use-cases-add-webhook)
    resp = requests.post(
        f"{BASE_URL}/usecases/{use_case_id}/webhook",
        headers=_headers(),
        json={"url": webhook_url, "secret": secret},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def get_call(call_id: str) -> dict:
    """
    Recupera los datos de una llamada ya terminada (transcripción, duración,
    metadata). Se usa DESPUÉS de la llamada, para la auditoría longitudinal
    (la media móvil del IRA a lo largo de toda la sesión) — complementa,
    no sustituye, la vigilancia en tiempo real durante la llamada.
    """
    resp = requests.get(f"{BASE_URL}/calls/{call_id}", headers=_headers(), timeout=10)
    resp.raise_for_status()
    return resp.json()


def create_outbound_call(to_number: str, context: dict) -> dict:
    """
    Dispara una llamada saliente. Uso pensado para AngryRobot: en un veredicto
    DEFER/KILL, en vez de (o además de) transferir dentro del mismo workflow,
    podéis usar esto para que HappyRobot llame automáticamente a un supervisor
    humano y le resuma la situación — un canal de alerta adicional, útil sobre
    todo para la demo (es un momento de pitch muy visual: "AngryRobot detecta
    el problema y hace que HappyRobot llame a un humano").
    """
    resp = requests.post(
        f"{BASE_URL}/dial/outbound",
        headers=_headers(),
        json={"to": to_number, "context": context},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()
