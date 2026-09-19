# HackSpainTeam

Repositorio del equipo HackSpain '26 · HappyRobot track.

> ⚠️ **`angryrobot/` vs `angryrobots/`** — dos carpetas, nombres casi idénticos, cosas distintas:
> - **`angryrobot/`** (singular) — **nuestro entregable**: el servicio guardián/auditor (FastAPI, Python), desplegado en Render vía [`render.yaml`](render.yaml).
> - **`angryrobots/`** (plural) — la **base del proyecto**: el fork de PhoneFlow (frontend/demo), desplegado a GitHub Pages.

| Folder | What |
|---|---|
| [`knowledge/`](knowledge/README.md) | Shared, published research — start with the index and read in order |
| [`angryrobot/`](angryrobot/README.md) | **Deliverable** — the guardian/audit service (FastAPI). Deployed on Render (`render.yaml`, rootDir `angryrobot`) |
| [`angryrobots/`](angryrobots/README.md) | **Project base (AngryRobots)** — our fork of [getphoneflow/phoneflow](https://github.com/getphoneflow/phoneflow) (git subtree, `git subtree pull --prefix=angryrobots https://github.com/getphoneflow/phoneflow main --squash` to update). Frontend deploys to GitHub Pages via `.github/workflows/pages.yml` |
| [`insights/`](insights/README.md) | Personal work folders (one per person); promote to `knowledge/` when it becomes team truth |
| [`tools/`](tools/README.md) | HappyRobot API scripts (watcher, explorer, extractor, dashboard, probes, rogue lab) — needs `HR_API_KEY` |
| [`redwood-ai-control-reading-list.md`](redwood-ai-control-reading-list.md) | Redwood Research AI-control reading list (Luis) |
| [`render.yaml`](render.yaml) | Render Blueprint for the `angryrobot/` service |
