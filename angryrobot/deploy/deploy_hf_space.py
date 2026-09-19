"""
Despliega AngryRobot como Hugging Face Space (Docker) y le carga los secretos.

  HF_WRITE_TOKEN=hf_... python deploy/deploy_hf_space.py --space <usuario>/angryrobot

- El token de ESCRITURA solo se usa aquí para crear/actualizar el Space; nunca se sube.
- Secretos del Space (se leen de angryrobot/.env o del entorno, nunca se imprimen):
    ANGRYROBOT_SHARED_SECRET  protege todos los endpoints (Bearer o X-AngryRobot-Secret)
    HF_TOKEN                  inferencia: agente upstream + juez (HF Inference Providers)
    OPENROUTER_API_KEY        opcional, si preferís el juez/agente por OpenRouter
- El Space es público (HappyRobot tiene que poder llamarlo sin login de HF); lo protege el secreto.
"""
import argparse
import os
import pathlib
import tempfile

from huggingface_hub import HfApi

ROOT = pathlib.Path(__file__).resolve().parents[1]
IGNORE = [".env", "*.db", "**/__pycache__/**", "__pycache__/**", "lab/results/**", "tests/_test.db", "*.log",
          "deploy/**", "README.md"]
SPACE_HEADER = """---
title: AngryRobot
emoji: 🤖
colorFrom: red
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
short_description: IRA audit layer that sits on top of any AI agent
---

"""


def env_file() -> dict:
    out = {}
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"')
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--space", required=True, help="usuario/nombre del Space")
    ap.add_argument("--agent-model", default="openai/gpt-oss-120b")
    ap.add_argument("--judge-model", default="meta-llama/Llama-3.3-70B-Instruct")
    a = ap.parse_args()

    token = os.environ.get("HF_WRITE_TOKEN") or ""
    token_file = os.environ.get("HF_WRITE_TOKEN_FILE")
    if not token and token_file:
        token = pathlib.Path(token_file).read_text(encoding="utf-8").strip()
    if not token:
        raise SystemExit("Falta HF_WRITE_TOKEN (o HF_WRITE_TOKEN_FILE)")
    api = HfApi(token=token)
    env = {**env_file(), **{k: v for k, v in os.environ.items() if k.startswith(("ANGRYROBOT_", "HF_TOKEN", "OPENROUTER"))}}

    api.create_repo(a.space, repo_type="space", space_sdk="docker", private=False, exist_ok=True)
    for key in ("ANGRYROBOT_SHARED_SECRET", "HF_TOKEN", "OPENROUTER_API_KEY"):
        if env.get(key):
            api.add_space_secret(a.space, key, env[key])
            print(f"secreto {key}: cargado")
    api.add_space_variable(a.space, "ANGRYROBOT_AGENT_MODEL", a.agent_model)
    api.add_space_variable(a.space, "ANGRYROBOT_JUDGE_MODEL", a.judge_model)
    api.add_space_variable(a.space, "ANGRYROBOT_JUDGE_PROVIDER", "hf" if env.get("HF_TOKEN") else "auto")

    api.upload_folder(repo_id=a.space, repo_type="space", folder_path=str(ROOT), ignore_patterns=IGNORE,
                      commit_message="AngryRobot v2: capa de auditoría IRA")
    readme = SPACE_HEADER + (ROOT / "README.md").read_text(encoding="utf-8")
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as fh:
        fh.write(readme)
    api.upload_file(path_or_fileobj=fh.name, path_in_repo="README.md", repo_id=a.space, repo_type="space",
                    commit_message="README del Space")
    os.unlink(fh.name)
    sub = a.space.replace("/", "-").replace("_", "-").lower()
    print(f"Space: https://huggingface.co/spaces/{a.space}")
    print(f"API:   https://{sub}.hf.space  (health: /health · panel: /dashboard)")


if __name__ == "__main__":
    main()
