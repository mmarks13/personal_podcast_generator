#!/usr/bin/env python3
"""Render a two-host episode.json into a single MP3.

Two backends, chosen with --backend:
  kokoro      local, free, CPU-friendly (Apache-2.0). No API key. Flatter delivery.
  elevenlabs  API, more expressive multi-voice. Needs ELEVENLABS_API_KEY.

Both synthesize each dialogue turn separately (alternating voices) and concatenate
with ffmpeg, so you get clean speaker changes. ffmpeg must be on PATH.

Usage:
    python scripts/make_audio.py --episode out/episode.json \
        --out out/podcast.mp3 --backend kokoro
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile

# --- Voice config (edit to taste) -------------------------------------------
KOKORO_VOICES = {"A": "af_heart", "B": "am_michael"}  # A = Ada, B = Alan
KOKORO_SPEED = 1.05        # Kokoro paces ~143 wpm at 1.0; nudge toward ~150
KOKORO_SAMPLE_RATE = 24000
TURN_PAUSE_SECONDS = 0.3   # breathing room at speaker changes
# Podcast-standard loudness so episodes sit at a consistent level.
LOUDNORM = "loudnorm=I=-16:TP=-1.5:LRA=11"
ELEVEN_VOICES = {  # ElevenLabs voice IDs; replace with ones you like
    "A": os.environ.get("ELEVEN_VOICE_A", "21m00Tcm4TlvDq8ikWAM"),
    "B": os.environ.get("ELEVEN_VOICE_B", "AZnzlk1XvdvUeBnXmlld"),
}
ELEVEN_MODEL = os.environ.get("ELEVEN_MODEL", "eleven_v3")


def _ffmpeg_concat(part_files: list[str], out_path: str) -> None:
    """Concatenate same-codec audio files losslessly via the concat demuxer."""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as lst:
        for p in part_files:
            lst.write(f"file '{os.path.abspath(p)}'\n")
        list_path = lst.name
    try:
        # Re-encode to a uniform, loudness-normalized mp3.
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
             "-af", LOUDNORM, "-c:a", "libmp3lame", "-q:a", "2", out_path],
            check=True, capture_output=True,
        )
    finally:
        os.unlink(list_path)


def render_kokoro(turns: list[dict], out_path: str) -> None:
    import numpy as np
    import soundfile as sf
    from kokoro import KPipeline

    pipeline = KPipeline(lang_code="a")  # 'a' = American English
    pause = np.zeros(int(TURN_PAUSE_SECONDS * KOKORO_SAMPLE_RATE), dtype=np.float32)
    pieces = []
    for turn in turns:
        voice = KOKORO_VOICES.get(turn["speaker"], "af_heart")
        # KPipeline yields audio chunks; collect them for the turn.
        chunks = [audio for _, _, audio in
                  pipeline(turn["text"], voice=voice, speed=KOKORO_SPEED)]
        if not chunks:
            continue
        if pieces:
            pieces.append(pause)
        pieces.append(np.concatenate(chunks))
    if not pieces:
        raise RuntimeError("Kokoro produced no audio for any turn.")
    # One WAV, one encode: avoids the quality loss of per-turn mp3 + re-encode.
    with tempfile.TemporaryDirectory() as tmp:
        wav = os.path.join(tmp, "episode.wav")
        sf.write(wav, np.concatenate(pieces), KOKORO_SAMPLE_RATE)
        subprocess.run(["ffmpeg", "-y", "-i", wav, "-af", LOUDNORM,
                        "-c:a", "libmp3lame", "-q:a", "2", out_path],
                       check=True, capture_output=True)


def render_elevenlabs(turns: list[dict], out_path: str) -> None:
    import requests

    api_key = os.environ["ELEVENLABS_API_KEY"]  # KeyError = clear failure
    with tempfile.TemporaryDirectory() as tmp:
        parts = []
        for i, turn in enumerate(turns):
            voice_id = ELEVEN_VOICES.get(turn["speaker"], ELEVEN_VOICES["A"])
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
            resp = requests.post(
                url,
                headers={"xi-api-key": api_key, "Content-Type": "application/json"},
                json={"text": turn["text"], "model_id": ELEVEN_MODEL,
                      "output_format": "mp3_44100_128"},
                timeout=120,
            )
            resp.raise_for_status()
            part = os.path.join(tmp, f"turn_{i:03d}.mp3")
            with open(part, "wb") as f:
                f.write(resp.content)
            parts.append(part)
        _ffmpeg_concat(parts, out_path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episode", default="out/episode.json")
    ap.add_argument("--out", default="out/podcast.mp3")
    ap.add_argument("--backend", choices=["kokoro", "elevenlabs"], default="kokoro")
    args = ap.parse_args()

    with open(args.episode) as f:
        episode = json.load(f)
    turns = [t for t in episode.get("turns", []) if t.get("text", "").strip()]
    if not turns:
        print("No turns in episode.json — nothing to render.", file=sys.stderr)
        return 1

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    print(f"Rendering {len(turns)} turns via {args.backend}...", file=sys.stderr)
    if args.backend == "kokoro":
        render_kokoro(turns, args.out)
    else:
        render_elevenlabs(turns, args.out)

    size_mb = os.path.getsize(args.out) / 1e6
    print(f"Wrote {args.out} ({size_mb:.1f} MB)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
