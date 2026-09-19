# Tools — HappyRobot API scripts

Stdlib-only Python scripts that talk to the HappyRobot v2 API. All need `HR_API_KEY` (org-scoped) in the environment — `set -a; source .env; set +a` or `export HR_API_KEY=...`. Run from the repo root so relative output paths (`explore/`, `hr_watch.sqlite`, `hr_watch.jsonl`) land at the top level.

| Script | What | Output |
|---|---|---|
| [`hr_watch.py`](hr_watch.py) | All-layers watcher: walks Workflow → Version → Node → Run → Session → Message and keeps polling. Subcommands: `whoami`, `map`, `poll`, `stream`, `realtime`, `listen`, `sql`, `get` | `../hr_watch.sqlite` + `../hr_watch.jsonl` |
| [`hr_explore.py`](hr_explore.py) | First-contact battery: every read-only request family against an org, with a compact redacted shape summary | `explore/<timestamp>/*.json` |
| [`hr_extract.py`](hr_extract.py) | Turns one run (or a workflow's latest runs) into a "model I/O" record; can push each record to a webhook or watch continuously | `explore/model-io/<run_id>.json` |
| [`hr_dashboard.py`](hr_dashboard.py) | Zero-dependency local web UI to browse everything `hr_extract.py` has pulled | serves `http://localhost:8791` from `explore/model-io/` |
| [`hr_probe_chat.py`](hr_probe_chat.py) | Creates a chatbot agent from HappyRobot's template, publishes it, talks to it via the chat API, dumps everything the platform recorded | `explore/probe-<timestamp>/*.json` |
| [`hr_voice_probe.py`](hr_voice_probe.py) | Drives a HappyRobot *voice* agent headlessly over LiveKit, speaking scripted turns with macOS `say` (no mic needed) | `explore/voice-<timestamp>/*` (audio + transcripts) |
| [`hr_rogue_lab.py`](hr_rogue_lab.py) | Builds deliberately rogue agent personas ([`knowledge/13-rogue-scenario-triggers.md`](../knowledge/13-rogue-scenario-triggers.md)) and checks what HappyRobot's own audit system catches. Subcommands: `create`, `attack`, `report`, `all` | `explore/rogue-lab.json` + `explore/rogue-lab/*` |

Every script's own `--help` / docstring has the full usage. `explore/` and the `hr_watch.*` mirror files are gitignored.
