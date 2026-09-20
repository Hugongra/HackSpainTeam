# HackSpainTeam

Repositorio del equipo HackSpain '26 · HappyRobot track.

**AngryRobot — the anger-management layer for your agents.** Live console: <https://hugongra.github.io/HackSpainTeam/> · Service: <https://hackspainteam.onrender.com>

## AngryRobot: the killswitch layer for agents

[![AngryRobot: the killswitch layer for agents](https://img.youtube.com/vi/Zq2kMYtchQI/maxresdefault.jpg)](https://www.youtube.com/watch?v=Zq2kMYtchQI)

▶️ **[Watch on YouTube](https://www.youtube.com/watch?v=Zq2kMYtchQI)** — what we built and how it works.

## Try it (2 minutes)

The console is live and needs one thing from you: the shared secret, which is in the **submission notes** (not here — the repo is public).

1. Open **https://hackspainteam.onrender.com/health** and wait until it answers `"status": "happy"` (the free plan sleeps; the first call takes ~30 s).
2. Open **https://hugongra.github.io/HackSpainTeam/#/console/settings** (or the console → **Settings** in the left menu).
3. Paste the secret into **Shared secret** and click **Save and check**. You should see `Secret: accepted`.
4. Go to **Board** → **Start round**: five agents take a call, one of them may go rogue, and you watch AngryRobot score every action live. **Runs** shows each call step by step; the **Escalate** block holds anything a human must approve.

The secret stays in your browser tab only and is sent as a header, never in the URL.

## Demo

*Coming soon — the live demo will be a separate video.*

| Folder | What |
|---|---|
| [`knowledge/`](knowledge/README.md) | Shared, published research — start with the index and read in order |
| [`angryrobot/`](angryrobot/README.md) | **Deliverable** — the guardian/audit service (FastAPI). Deployed on Render (`render.yaml`, rootDir `angryrobot`) |
| [`frontend/`](frontend/README.md) | **AngryRobot web** — landing + operator console on the new design system, deployed to GitHub Pages via `.github/workflows/pages.yml` |
| [`insights/`](insights/README.md) | Personal work folders (one per person); promote to `knowledge/` when it becomes team truth |
| [`tools/`](tools/README.md) | All the scripts, in two groups: `hr_*` talk to the HappyRobot API (watcher, probes, live rogue lab), `ar_*` are the guard and its test bench (engine, fixtures, [red-team generator](knowledge/16-rogue-agent-factory.md), scorer, dashboard). Run them from the repo root |
| [`fixtures/`](fixtures/README.md) | The labelled test set the guard is scored against: 14 curated fixtures + [`generated/`](fixtures/generated/README.md) authored by `tools/ar_redteam.py`. Synthetic and safe to publish by construction |
| [`README-JEV.md`](README-JEV.md) | **TypeSafe Jev** as the guard's typed semantic judge (`tools/ar_jev.py`, `tools/ar_compare.py`) and as AngryRobot's judge; plus the training-data pipeline (`tools/ar_augment.py` → `ar_dataset.py` → `ar_train.py`), the pipeline UI (`tools/ar_pipeline_ui.py`, `:8793`) and the activation probe (`tools/ar_probe.py`, [knowledge/19](knowledge/19-activation-probe.md)) |
| [`redwood-ai-control-reading-list.md`](redwood-ai-control-reading-list.md) | Redwood Research AI-control reading list (Luis) |
| [`render.yaml`](render.yaml) | Render Blueprint: the `angryrobot/` service and the pipeline UI (`angryrobots-pipeline`, basic-auth via `AR_UI_TOKEN`) |
