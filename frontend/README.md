# AngryRobot frontend

Landing page and operator console for AngryRobot, built on the **Angry Robots logo rework** design
system (tokens in `src/styles/tokens/`, primitives ported to `src/ds/`). Deployed to GitHub Pages by
`.github/workflows/pages.yml` on every push to `main` that touches `frontend/`.

| Route | What it is |
|---|---|
| `#/` | Landing: glass nav over the dark hero, flat editorial body |
| `#/console/workflows` | **Platform**: connected workflows, global pause / resume / kill, connect a new workflow |
| `#/console/workflows/<id>` | One workflow: flow diagram, webhook + token + snippets, escalations, runs, policy editor, kill switch |
| `#/console/escalations` | Human-in-the-loop inbox: approve, deny or take over held actions |
| `#/console/overview` | Alerts: held (DEFER) and stopped (KILL) actions |
| `#/console/runs` | Every run in the service's memory; a row opens its timeline (inputs, actions, verdicts, signals, agent reasoning, lever applied) |
| `#/console/try` | Audit one action against a policy profile (observe mode, nothing executes) |
| `#/console/signals` | The signal catalog served by `GET /v1/signals` |
| `#/console/connection` | Service URL and shared secret |

Without the shared secret the console shows **example data**: the nine rogue-lab runs from 19 Sep,
clearly bannered. The secret is typed by the operator, kept in `sessionStorage` for that tab and sent
as `X-AngryRobot-Secret`; nothing secret is built into the site. The service must allow the Pages
origin (`ANGRYROBOT_CORS_ORIGINS`, default includes `https://hugongra.github.io`).

```bash
npm install
npm run dev            # http://localhost:5173
BASE_PATH=/HackSpainTeam/ npm run build
```

Design-system rules kept on purpose: glass only over the dark hero (nav and stat panes); everything
else square and hairline-bounded; Hazard Orange only for the primary action, the active nav rule and
"needs a human"; Signal Yellow once, on "why this reached you"; Outfit only; no emoji. Verdict chips map
ALLOW → positive, WARN → caution, DEFER → negative, KILL → accent.
