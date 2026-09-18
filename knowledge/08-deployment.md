# Deployment — where PhoneFlow's backend can run

*2026-09-18. **AngryRobots** (`angryrobots/`, our fork of PhoneFlow — getphoneflow/phoneflow@40db1ad) is our project base. The frontend goes to GitHub Pages via `.github/workflows/pages.yml`; this doc is about everything else.*

## What actually has to run

From `angryrobots/apps/*`, `packages/db`, `infra/*` and the `.env.example`s:

| Component | What it is | Needs |
|---|---|---|
| `apps/api` | Node HTTP API + better-auth (Google OAuth optional, Stripe only when `IS_CLOUD`) | Postgres, Redis, S3, LiveKit creds |
| `apps/worker` | BullMQ jobs (recordings, emails, downloads) | Redis, Postgres, S3 |
| `apps/voice-agent` | LiveKit Agents process — joins rooms, runs STT→LLM→TTS, plays background audio | LiveKit server, provider API keys (OpenAI/Deepgram/ElevenLabs/Google…) |
| Postgres | drizzle-orm schema (`packages/db`) | — |
| Redis | BullMQ + ioredis | — |
| LiveKit server | WebRTC media + rooms | public IP, UDP 50000–60000, TCP 7880/7881 |
| LiveKit SIP | phone numbers ↔ rooms (`infra/livekit-sip`) | SIP trunk from Twilio/Telnyx/Zadarma, UDP 5060 + RTP |
| LiveKit Egress | call recordings (`infra/livekit-egress`) | S3 |
| S3 (private + public buckets) | recordings, exports, avatars; `REGION=auto` in the examples is a Cloudflare R2 tell | — |
| Frontend | static Vite build, talks to `VITE_API_URL` | GitHub Pages |

Hard parts are the media plane (LiveKit + SIP + egress). Everything else is ordinary Node + Postgres.

## Three ways to run it

### A. Managed media, cheap compute — *recommended for the hackathon*

| Piece | Where | Cost / notes |
|---|---|---|
| LiveKit server + SIP + egress | **LiveKit Cloud** free tier | SIP trunks and egress are built in; removes the three `infra/livekit-*` stacks entirely. Point `LIVEKIT_URL/API_KEY/API_SECRET` at the cloud project. |
| Postgres | Neon or Supabase free | `DATABASE_URL` |
| Redis | Upstash free (ioredis-compatible) | BullMQ works with Upstash; keep job counts low |
| S3 | Cloudflare R2 free (10 GB) | two buckets (private/public); `REGION=auto`, endpoint from R2 |
| api + worker + voice-agent | **Railway** (trial credit) or **Fly.io** (3 small VMs) from the existing Dockerfiles | voice-agent must never sleep → don't use Render's free web service for it |
| Frontend | GitHub Pages | set repo variable `VITE_API_URL` to the Railway/Fly API URL |

Setup time ≈ 2–3 h. Zero servers to babysit. Phone numbers: buy/import a Twilio or Telnyx number, attach it as a SIP trunk in LiveKit Cloud, then register it in PhoneFlow's *Phone numbers* screen.

### B. One VPS with docker compose — *most faithful to upstream*

Hetzner CX22 (~€4/mo) or a DigitalOcean droplet; run `infra/livekit-server`, `infra/livekit-sip`, `infra/livekit-egress`, `infra/voice-agent` compose stacks as shipped (they include Caddy for TLS and `deploy.sh`), plus api/worker/postgres/redis/MinIO in one more compose file. Needs a domain, open UDP ranges, and someone owning ops during the demo. Setup ≈ half a day. Use this if we want to show "fully self-hosted" or need SIP features LiveKit Cloud's free tier caps.

### C. Laptop + tunnels — *demo-only fallback*

api/worker/postgres/redis in docker compose on a laptop, exposed with `cloudflared tunnel` (free, stable URL) or ngrok; media still on LiveKit Cloud (WebRTC from behind NAT is not worth fighting). Works for a 5-minute demo; dies when the laptop sleeps. Keep as plan B.

## The HappyRobot angle

For the track, telephony and the agent runtime are HappyRobot's; PhoneFlow gives us a flow builder, versioning, call monitoring and a LiveKit-native voice agent we control end to end. Two ways to combine them:

1. **PhoneFlow as the guard's control plane**: keep its UI (calls table, flow canvas) and point the *voice-agent* at HappyRobot via the Custom-LLM proxy — PhoneFlow shows what our Ring 1 decided per turn.
2. **PhoneFlow as the reference "actual agent"**: run its voice-agent as the thing we audit — we own every hook (STT, LLM, TTS, tool calls), so Ring 1 can be embedded directly in `apps/voice-agent` instead of proxied.

Either way LiveKit Cloud is the common substrate — HappyRobot's observer tokens are LiveKit tokens too (see `01-happyrobot-watcher-and-api.md`).

## Env checklist (fill in a private `.env`, never commit)

`DATABASE_URL`, `REDIS_URL`, `BETTER_AUTH_SECRET`, `LIVEKIT_URL/API_KEY/API_SECRET`, `PRIVATE_S3_*`, `PUBLIC_S3_*` + `PUBLIC_S3_URL`, `API_TOKEN`, provider keys for STT/LLM/TTS, optional `GOOGLE_CLIENT_ID/SECRET`. Leave `STRIPE_*` empty and `VITE_IS_CLOUD` unset (self-host mode skips billing).

## Decision needed

Pick A unless someone specifically wants to own a VPS. Whoever takes it: create the LiveKit Cloud project first (everything else depends on its URL/keys), then Neon → Upstash → R2 → Railway, then set `VITE_API_URL` on the repo and re-run the `pages` workflow.
