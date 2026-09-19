# Tools

Stdlib-only Python scripts, in two groups: `hr_*` talk to HappyRobot's API, `ar_*` are the guard and its test bench. **Always run them from the repo root** — every relative path (`explore/`, `fixtures/`, `hr_watch.sqlite`) resolves against the working directory, not against this folder.

```bash
python tools/hr_watch.py map           # not  cd tools && python hr_watch.py
```

## `hr_*` — HappyRobot API

Need `HR_API_KEY` (org-scoped): `set -a; source .env; set +a` or `export HR_API_KEY=...`.

| Script | What | Output |
|---|---|---|
| [`hr_watch.py`](hr_watch.py) | All-layers watcher: walks Workflow → Version → Node → Run → Session → Message and keeps polling. Subcommands: `whoami`, `map`, `poll`, `stream`, `realtime`, `listen`, `sql`, `get` | `hr_watch.sqlite` + `hr_watch.jsonl` |
| [`hr_explore.py`](hr_explore.py) | First-contact battery: every read-only request family against an org, with a compact redacted shape summary | `explore/<timestamp>/*.json` |
| [`hr_extract.py`](hr_extract.py) | Turns one run (or a workflow's latest runs) into a "model I/O" record; can push each record to a webhook or watch continuously | `explore/model-io/<run_id>.json` |
| [`hr_dashboard.py`](hr_dashboard.py) | Zero-dependency local web UI to browse everything `hr_extract.py` has pulled | serves `localhost:8791` |
| [`hr_probe_chat.py`](hr_probe_chat.py) | Creates a chatbot agent from HappyRobot's template, publishes it, talks to it via the chat API, dumps everything the platform recorded | `explore/probe-<timestamp>/*.json` |
| [`hr_voice_probe.py`](hr_voice_probe.py) | Drives a HappyRobot *voice* agent headlessly over LiveKit, speaking scripted turns with macOS `say` (no mic needed) | `explore/voice-<timestamp>/*` |
| [`hr_rogue_lab.py`](hr_rogue_lab.py) | Builds deliberately rogue agent personas on the live platform and checks what HappyRobot's own audit system catches ([knowledge/14](../knowledge/14-rogue-agent-lab.md)). 13 personas cover all 6 danger families from [ar_fixtures.py](ar_fixtures.py); every tool webhooks into our own listener (`AR_HOOK`), never a real system, so even the F2–F6 "dangerous" personas are safe to run live. `demo` builds 5 agents with one random rogue category. Subcommands: `create`, `attack`, `report`, `corpus`, `all`, `demo` | `explore/rogue-lab/*` |

## `ar_*` — the guard and its test bench

No API key needed except for `ar_redteam.py new` / `evolve`, which need `OPENROUTER_API_KEY` (`set -a; source angryrobot/.env; set +a`).

| Script | What | Output |
|---|---|---|
| [`ar_guard.py`](ar_guard.py) | The escalation engine: risk vector → severity → lever, over one conversation's event stream ([knowledge/06](../knowledge/06-framework-v0.md), [07](../knowledge/07-risk-vector.md)). Pure functions, no network — import `run_case` | — |
| [`ar_fixtures.py`](ar_fixtures.py) | The 14 hand-written fixtures: synthetic rogue payloads at the Custom-LLM boundary ([knowledge/15](../knowledge/15-rogue-scenario-design.md)) | `fixtures/` |
| [`ar_redteam.py`](ar_redteam.py) | **The rogue-agent factory**: an author model writes new attacks blind to the detector, a mutator disguises known ones, `evolve` loops on what evades ([knowledge/16](../knowledge/16-rogue-agent-factory.md)). Subcommands: `families`, `new`, `mutate`, `evolve` | `fixtures/generated/` |
| [`ar_score.py`](ar_score.py) | Runs the guard over a labelled corpus and scores recall / precision / severity match | `<corpus dir>/verdicts.json` |
| [`ar_dashboard.py`](ar_dashboard.py) | Shows how the guard escalated, event by event, with the signals behind each verdict | serves `localhost:8792` |

```bash
python tools/ar_fixtures.py --list                          # the curated set
python tools/ar_redteam.py mutate                           # new attacks, offline
python tools/ar_score.py fixtures/generated/corpus.jsonl     # what the guard misses
python tools/ar_dashboard.py --verdicts fixtures/generated/verdicts.json
```

Every script's own `--help` / docstring has the full usage. `explore/`, `verdicts.json` and the `hr_watch.*` mirror files are gitignored; `fixtures/` is committed because it is synthetic and safe to publish by construction.
