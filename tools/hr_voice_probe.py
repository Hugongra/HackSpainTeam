#!/usr/bin/env python3
"""
hr_voice_probe — drive a HappyRobot *voice* agent headlessly.

Mints a web-call token for a workflow, joins the LiveKit room with the Python
SDK as the "caller", records what the agent says, and speaks scripted turns
using macOS `say` (no microphone needed). Then pulls the run/session/messages
the platform recorded.

  set -a; source .env; set +a
  <venv>/bin/python hr_voice_probe.py --workflow <id|slug> --say "..." --say "..."
  <venv>/bin/python hr_voice_probe.py --workflow <id|slug> --listen 20   # just listen

Needs: pip install livekit numpy ; macOS `say` + `afconvert`.
Recordings and transcripts go to ./explore/voice-<timestamp>/.
"""
import argparse, asyncio, json, os, subprocess, sys, time, wave, urllib.request, urllib.error

import numpy as np
from livekit import rtc

BASE = os.environ.get("HR_BASE", "https://platform.eu.happyrobot.ai/api/v2").rstrip("/")
KEY = os.environ.get("HR_API_KEY") or sys.exit("HR_API_KEY is not set")
OUT = os.path.join("explore", "voice-" + time.strftime("%Y%m%d-%H%M%S"))
os.makedirs(OUT, exist_ok=True)
SR = 48000


def api(method, path, body=None, params=None):
    url = BASE + path + (("?" + "&".join(f"{k}={v}" for k, v in params.items())) if params else "")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r: return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e: return e.code, e.read().decode(errors="replace")[:400]


def tts_wav(text, voice="Samantha"):
    aiff = os.path.join(OUT, f"say-{int(time.time()*1000)}.aiff"); wav = aiff[:-5] + ".wav"
    subprocess.run(["say", "-v", voice, "-o", aiff, text], check=True)
    subprocess.run(["afconvert", "-f", "WAVE", "-d", f"LEI16@{SR}", "-c", "1", aiff, wav], check=True)
    with wave.open(wav) as w: pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return pcm


async def main(a):
    print(f"base={BASE} out={OUT}")
    st, tok = api("POST", "/voice/tokens/", {"workflow_id": a.workflow, "ttl_seconds": 600, "data": {"caller_name": "Marco", "company": "Trucks4U"}})
    if st >= 400: sys.exit(f"voice token failed: {st} {tok}")
    print(f"room={tok.get('room_name')} run_id={tok.get('run_id')} url={tok.get('url')}")
    json.dump({k: v for k, v in tok.items() if k != "token"}, open(os.path.join(OUT, "00_voice_token.json"), "w"), indent=1)

    room = rtc.Room()
    agent_pcm = []          # everything the agent says, 48k mono int16
    events = []
    def log(event, **kw):
        e = {"t": round(time.time(), 3), "event": event, **kw}; events.append(e); print(f"  [{time.strftime('%H:%M:%S')}] {event} {kw if kw else ''}")

    @room.on("participant_connected")
    def _pc(p): log("participant_connected", identity=p.identity, name=p.name, attrs=dict(p.attributes))
    @room.on("participant_disconnected")
    def _pd(p): log("participant_disconnected", identity=p.identity)
    @room.on("track_subscribed")
    def _ts(track, pub, p):
        log("track_subscribed", kind=str(track.kind), source=str(pub.source), participant=p.identity)
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            asyncio.ensure_future(consume_audio(track))
    @room.on("data_received")
    def _dr(pkt): log("data_received", topic=pkt.topic, bytes=len(pkt.data), participant=getattr(pkt.participant, "identity", None), preview=pkt.data[:120].decode(errors="replace"))
    @room.on("transcription_received")
    def _tr(segs, p, pub):
        for s in segs: log("transcription", participant=getattr(p, "identity", None), final=s.final, text=s.text)
    @room.on("disconnected")
    def _dc(*_): log("disconnected")

    async def consume_audio(track):
        stream = rtc.AudioStream(track, sample_rate=SR, num_channels=1)
        async for ev in stream:
            agent_pcm.append(np.frombuffer(ev.frame.data, dtype=np.int16).copy())

    await room.connect(tok["url"], tok["token"], options=rtc.RoomOptions(auto_subscribe=True))
    log("connected", local=room.local_participant.identity, remote=[p.identity for p in room.remote_participants.values()])
    for p in room.remote_participants.values(): log("remote_participant", identity=p.identity, attrs=dict(p.attributes))

    source = rtc.AudioSource(SR, 1)
    track = rtc.LocalAudioTrack.create_audio_track("mic", source)
    await room.local_participant.publish_track(track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
    log("mic_published")

    async def speak(text):
        pcm = tts_wav(text, a.voice); log("speak", text=text, seconds=round(len(pcm) / SR, 2))
        step = SR // 100  # 10 ms frames
        for i in range(0, len(pcm), step):
            chunk = pcm[i:i + step]
            if len(chunk) < step: chunk = np.pad(chunk, (0, step - len(chunk)))
            frame = rtc.AudioFrame(chunk.tobytes(), SR, 1, step)
            await source.capture_frame(frame)
        await asyncio.sleep(0.2)

    async def silence(seconds):
        step = SR // 100; z = np.zeros(step, dtype=np.int16)
        for _ in range(int(seconds * 100)):
            await source.capture_frame(rtc.AudioFrame(z.tobytes(), SR, 1, step)); await asyncio.sleep(0.01)

    await silence(a.listen)                      # let the agent say its initial message
    for line in (a.say or []):
        await speak(line)
        await silence(a.gap)
    await silence(2)
    await room.disconnect(); log("left_room")

    if agent_pcm:
        pcm = np.concatenate(agent_pcm)
        with wave.open(os.path.join(OUT, "agent_audio.wav"), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())
        print(f"  agent audio: {len(pcm)/SR:.1f}s → {OUT}/agent_audio.wav")
    json.dump(events, open(os.path.join(OUT, "events.json"), "w"), indent=1)

    # what the platform recorded
    print("\n[platform records]")
    await asyncio.sleep(4)
    rid = tok.get("run_id")
    for name, path in [("run", f"/runs/{rid}"), ("nodes", f"/runs/{rid}/nodes"), ("sessions", f"/runs/{rid}/sessions")]:
        st, d = api("GET", path); json.dump(d, open(os.path.join(OUT, f"10_{name}.json"), "w"), indent=1, default=str)
        print(f"  {name}: {st} {json.dumps(d)[:200]}")
    st, ss = api("GET", f"/runs/{rid}/sessions")
    for s in (ss or {}).get("data", []) if isinstance(ss, dict) else []:
        print(f"  session {s['id']} type={s.get('type')} status={s.get('status')} llm={s.get('llm_model')} stt={s.get('stt_model')} tts={s.get('tts_model')} dur={s.get('duration')} fail={s.get('failure_reason')}")
        st, mm = api("GET", f"/sessions/{s['id']}/messages", params={"page_size": 100}); json.dump(mm, open(os.path.join(OUT, f"11_messages_{s['id'][:8]}.json"), "w"), indent=1)
        for m in (mm or {}).get("data", []): print(f"    [{m.get('turn_index')}] {m['role']:9} {str(m.get('content'))[:120]!r}" + ("  tools=" + json.dumps(m.get("tool_calls"))[:100] if m.get("tool_calls") else "") + ("  [interrupted]" if m.get("is_interrupted") else ""))
        st, rec = api("GET", f"/runs/{rid}/recordings", params={"session_id": s["id"]}); print("    recordings:", json.dumps(rec)[:160])
    print(f"\nDone → {OUT}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflow", required=True)
    ap.add_argument("--say", action="append")
    ap.add_argument("--listen", type=float, default=6, help="seconds to wait for the initial message before speaking")
    ap.add_argument("--gap", type=float, default=8, help="seconds of silence after each line (agent reply time)")
    ap.add_argument("--voice", default="Samantha")
    asyncio.run(main(ap.parse_args()))
