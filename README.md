# HackSpainTeam

Repositorio del equipo HackSpain '26 · HappyRobot track.

| Folder | What |
|---|---|
| [`knowledge/`](knowledge/README.md) | Shared, published research — start with the index and read 01→07 |
| [`angryrobots/`](angryrobots/README.md) | **Project base (AngryRobots)** — our fork of [getphoneflow/phoneflow](https://github.com/getphoneflow/phoneflow) (git subtree, `git subtree pull --prefix=angryrobots https://github.com/getphoneflow/phoneflow main --squash` to update). Frontend deploys to GitHub Pages via `.github/workflows/pages.yml` |
| [`insights/`](insights/README.md) | Personal work folders (one per person); promote to `knowledge/` when it becomes team truth |
| [`hr_watch.py`](hr_watch.py) | All-layers HappyRobot watcher (`whoami`, `map`, `poll`, `stream`, `listen`, `realtime`, `sql`, `get`) — needs `HR_API_KEY` |
| [`ar_pipeline_ui.py`](ar_pipeline_ui.py) | **Training-data pipeline UI** (`http://localhost:8793`): augment → lint → dataset → train, Claude synth and the live lab as buttons. Method in [`knowledge/17`](knowledge/17-training-data-pipeline.md) |
| [`README-JEV.md`](README-JEV.md) | **Rama `jev`**: TypeSafe Jev como juez semántico tipado del guard (`ar_jev.py`, `ar_compare.py`) y del auditor de AngryRobot; método, medidas y cómo enseñarlo |
| [`link`](link) | Redwood Research AI-control reading list (Luis) |
