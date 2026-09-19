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
| [`tools/`](tools/README.md) | All the scripts, in two groups: `hr_*` talk to the HappyRobot API (watcher, probes, live rogue lab), `ar_*` are the guard and its test bench (engine, fixtures, [red-team generator](knowledge/16-rogue-agent-factory.md), scorer, dashboard). Run them from the repo root |
| [`fixtures/`](fixtures/README.md) | The labelled test set the guard is scored against: 14 curated fixtures + [`generated/`](fixtures/generated/README.md) authored by `tools/ar_redteam.py`. Synthetic and safe to publish by construction |
| [`README-JEV.md`](README-JEV.md) | **TypeSafe Jev** as the guard's typed semantic judge (`tools/ar_jev.py`, `tools/ar_compare.py`) and as AngryRobot's judge; plus the training-data pipeline (`tools/ar_augment.py` → `ar_dataset.py` → `ar_train.py`), the pipeline UI (`tools/ar_pipeline_ui.py`, `:8793`) and the activation probe (`tools/ar_probe.py`, [knowledge/19](knowledge/19-activation-probe.md)) |
| [`redwood-ai-control-reading-list.md`](redwood-ai-control-reading-list.md) | Redwood Research AI-control reading list (Luis) |
| [`render.yaml`](render.yaml) | Render Blueprint: the `angryrobot/` service and the pipeline UI (`angryrobots-pipeline`, basic-auth via `AR_UI_TOKEN`) |
