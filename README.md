# HackSpainTeam

Repositorio del equipo HackSpain '26 · HappyRobot track.

> ⚠️ **`angryrobot/` vs `angryrobots/`** — dos carpetas, nombres casi idénticos, cosas distintas:
> - **`angryrobot/`** (singular) — **nuestro entregable**: el servicio guardián/auditor (FastAPI, Python), desplegado en Render vía [`render.yaml`](render.yaml).
> - **`angryrobots/`** (plural) — la **base del proyecto**: el fork de PhoneFlow (frontend/demo). Ya no se despliega a Pages: Pages sirve `frontend/`.

| Folder | What |
|---|---|
| [`knowledge/`](knowledge/README.md) | Shared, published research — start with the index and read in order |
| [`angryrobot/`](angryrobot/README.md) | **Deliverable** — the guardian/audit service (FastAPI). Deployed on Render (`render.yaml`, rootDir `angryrobot`) |
| [`angryrobots/`](angryrobots/README.md) | **Project base (AngryRobots)** — our fork of [getphoneflow/phoneflow](https://github.com/getphoneflow/phoneflow) (git subtree, `git subtree pull --prefix=angryrobots https://github.com/getphoneflow/phoneflow main --squash` to update). No longer deployed to Pages |
| [`frontend/`](frontend/README.md) | **AngryRobot web** — landing + operator console on the new design system, deployed to GitHub Pages via `.github/workflows/pages.yml` |
| [`insights/`](insights/README.md) | Personal work folders (one per person); promote to `knowledge/` when it becomes team truth |
| [`tools/`](tools/README.md) | HappyRobot API scripts (watcher, explorer, extractor, dashboard, probes, rogue lab) — needs `HR_API_KEY` |
| `ar_*.py` | **The guard and its test bench** — `ar_guard.py` (escalation engine: risk vector → severity → lever), `ar_score.py` (scores it against a labelled corpus), `ar_fixtures.py` (the hand-written fixtures), [`ar_redteam.py`](knowledge/16-rogue-agent-factory.md) (generates new rogue agents and attacks), `ar_dashboard.py` (live verdicts) |
| [`fixtures/`](fixtures/README.md) | The labelled test set: 14 curated fixtures + [`fixtures/generated/`](fixtures/generated/README.md) authored by `ar_redteam.py`. Synthetic and safe to publish by construction |
| [`redwood-ai-control-reading-list.md`](redwood-ai-control-reading-list.md) | Redwood Research AI-control reading list (Luis) |
| [`render.yaml`](render.yaml) | Render Blueprint for the `angryrobot/` service |
