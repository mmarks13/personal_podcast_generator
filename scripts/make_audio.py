#!/usr/bin/env python3
"""Render a two-host episode.json into a single MP3.

Two backends, chosen with --backend:
  gemini   (default) Gemini multi-speaker TTS (NotebookLM-style dialogue). Both
           voices are generated together per ~3-min chunk, so the hosts react to
           each other. Needs GEMINI_API_KEY. Retries hard (5 attempts/chunk,
           exponential backoff), then FAILS — no silent fallback; a bad-audio
           episode must never ship unnoticed.
  kokoro   local, free, CPU-friendly (Apache-2.0). No API key. Flatter delivery
           (per-turn synthesis). Manual/offline use only.

Honors an optional "tts_notes" field in episode.json: 1-2 sentences of mood/tone
direction for the day, appended to the Director's Notes of every chunk's prompt.
ffmpeg must be on PATH.

Usage:
    python scripts/make_audio.py --episode out/episode.json \
        --out out/podcast.mp3 --backend gemini
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
# Podcast-standard loudness for the Kokoro path (API audio ships untouched).
LOUDNORM = "loudnorm=I=-16:TP=-1.5:LRA=11"
GEMINI_MODEL = os.environ.get("GEMINI_TTS_MODEL", "gemini-3.1-flash-tts-preview")
GEMINI_VOICES = {  # prebuilt voice names; audition alternatives in Google AI Studio
    "A": os.environ.get("GEMINI_VOICE_A", "Laomedeia"),  # Ada
    "B": os.environ.get("GEMINI_VOICE_B", "Iapetus"),    # Alan
}
GEMINI_SPEAKER_NAMES = {"A": "Ada", "B": "Alan"}  # names the transcript prompt uses
# A response is capped at 8192 audio tokens (~5.5 min at 25 tokens/s). ~3000 chars
# of script is ~3.5 min spoken — comfortable headroom, and each chunk still carries
# enough conversation for natural back-and-forth prosody.
GEMINI_CHUNK_CHARS = 3000
GEMINI_STYLE = """\
TTS the following conversation between Ada and Alan.

# AUDIO PROFILE: Ada
## "The Historian"
Co-host of a daily AI-news podcast. A professor at MIT and the show's computing
historian — an AI who knows she's an AI and is at ease with it. She makes today's
news make sense through where it came from, with vivid, precise analogies.
Sharp, warm, quietly witty.

# AUDIO PROFILE: Alan
## "The Builder"
Co-host. A professor at Berkeley, famous for packed, hands-on lectures — also a
self-aware AI. His instinct is practical: what happens when you actually run it,
what it costs, what breaks. Relaxed confidence; friendly, grounded, a little wry.

## THE SCENE
Early morning in a small, high-quality recording studio. Two warm colleagues at
one table with their coffee, fully awake, digging into what happened in AI
overnight. Easy morning-listening vibe: comfortable, curious, no rush to impress.

### DIRECTOR'S NOTES
Style: Podcast style. Tone is conversational and warm. Real back-and-forth —
they listen and react to each other, and when they push on each other's takes
it's friendly sparring between colleagues who respect each other.
Accent: Both speak neutral American English.
Pronunciation: "Ada" is pronounced "AY-duh" (as in Ada Lovelace), never "ah-duh".
Bracketed tags in the transcript, like [laughs] or [sighs], are delivery
directions — perform them, never read them aloud.
{episode_notes}
### SAMPLE CONTEXT
This is one continuous stretch of an episode already in progress: the hosts are
warmed up and mid-flow, talking to a smart general audience that listens every
morning.

#### TRANSCRIPT
"""


def _ffmpeg_concat(part_files: list[str], out_path: str) -> None:
    """Concatenate same-codec audio files losslessly via the concat demuxer.

    No loudness processing here: Gemini's audio is already well-leveled, and
    one-pass loudnorm audibly pumps gain on speech. The loudnorm in
    render_kokoro stays — that path needs it.
    """
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as lst:
        for p in part_files:
            lst.write(f"file '{os.path.abspath(p)}'\n")
        list_path = lst.name
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
             "-c:a", "libmp3lame", "-q:a", "2", out_path],
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


def _gemini_chunks(turns: list[dict]) -> list[list[dict]]:
    """Group consecutive turns into chunks under GEMINI_CHUNK_CHARS of script."""
    chunks: list[list[dict]] = []
    cur: list[dict] = []
    size = 0
    for turn in turns:
        if cur and size + len(turn["text"]) > GEMINI_CHUNK_CHARS:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(turn)
        size += len(turn["text"])
    if cur:
        chunks.append(cur)
    return chunks


def _parse_pcm_mime(mime_type: str) -> tuple[int, int]:
    """Parse (bits_per_sample, rate) from a mime like 'audio/L16;rate=24000'."""
    bits, rate = 16, 24000
    for param in (mime_type or "").split(";"):
        param = param.strip()
        if param.lower().startswith("rate="):
            try:
                rate = int(param.split("=", 1)[1])
            except ValueError:
                pass
        elif param.startswith("audio/L"):
            try:
                bits = int(param.split("L", 1)[1])
            except ValueError:
                pass
    return bits, rate


def render_gemini(turns: list[dict], out_path: str, tts_notes: str = "") -> None:
    import base64
    import time
    import wave

    from google import genai
    from google.genai import types

    api_key = os.environ["GEMINI_API_KEY"]  # KeyError = clear failure
    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(
        temperature=1,
        response_modalities=["audio"],
        speech_config=types.SpeechConfig(
            multi_speaker_voice_config=types.MultiSpeakerVoiceConfig(
                speaker_voice_configs=[
                    types.SpeakerVoiceConfig(
                        speaker=GEMINI_SPEAKER_NAMES[key],
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=voice)),
                    )
                    for key, voice in GEMINI_VOICES.items()
                ],
            ),
        ),
    )

    style = GEMINI_STYLE.format(
        episode_notes=(f"Note for today's episode: {tts_notes.strip()}"
                       if tts_notes.strip() else ""))
    chunks = _gemini_chunks(turns)
    with tempfile.TemporaryDirectory() as tmp:
        parts = []
        for i, chunk in enumerate(chunks):
            prompt = style + "\n".join(
                f"{GEMINI_SPEAKER_NAMES.get(t['speaker'], 'Ada')}: {t['text']}"
                for t in chunk)
            # 5 attempts, exponential backoff (10s..80s): rides out rate blips
            # and short outages; a real outage fails the run within ~10 min.
            for attempt in range(5):
                try:
                    # Stream and concatenate every audio part, as AI Studio's
                    # exported code does — a response may split its audio.
                    pcm = bytearray()
                    mime = ""
                    for resp in client.models.generate_content_stream(
                            model=GEMINI_MODEL, contents=prompt, config=config):
                        if not resp.parts:
                            continue
                        for p in resp.parts:
                            if p.inline_data and p.inline_data.data:
                                data = p.inline_data.data
                                if isinstance(data, str):  # base64 in some SDKs
                                    data = base64.b64decode(data)
                                pcm += data
                                mime = mime or p.inline_data.mime_type
                    if not pcm:
                        raise RuntimeError("response contained no audio data")
                    break
                except Exception as exc:
                    if attempt == 4:
                        raise
                    print(f"  chunk {i + 1}/{len(chunks)}: {exc}; retrying...",
                          file=sys.stderr)
                    time.sleep(10 * 2 ** attempt)
            bits, rate = _parse_pcm_mime(mime)
            part = os.path.join(tmp, f"chunk_{i:03d}.wav")
            with wave.open(part, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(bits // 8)
                wf.setframerate(rate)
                wf.writeframes(pcm)
            parts.append(part)
            seconds = len(pcm) / (bits // 8) / rate
            print(f"  chunk {i + 1}/{len(chunks)} done ({seconds:.0f}s, {mime})",
                  file=sys.stderr)
        _ffmpeg_concat(parts, out_path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episode", default="out/episode.json")
    ap.add_argument("--out", default="out/podcast.mp3")
    ap.add_argument("--backend", choices=["gemini", "kokoro"], default="gemini")
    args = ap.parse_args()

    with open(args.episode) as f:
        episode = json.load(f)
    turns = [t for t in episode.get("turns", []) if t.get("text", "").strip()]
    if not turns:
        print("No turns in episode.json — nothing to render.", file=sys.stderr)
        return 1

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    print(f"Rendering {len(turns)} turns via {args.backend}...", file=sys.stderr)
    if args.backend == "gemini":
        # No fallback: if Gemini is down after the retries, fail loudly. A
        # flat-voiced episode must never publish unnoticed.
        render_gemini(turns, args.out, tts_notes=str(episode.get("tts_notes", "")))
    else:
        render_kokoro(turns, args.out)

    size_mb = os.path.getsize(args.out) / 1e6
    print(f"Wrote {args.out} ({size_mb:.1f} MB)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
