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
GEMINI_MODEL = os.environ.get("GEMINI_TTS_MODEL", "gemini-2.5-pro-preview-tts")
GEMINI_VOICES = {  # prebuilt voice names; audition alternatives in Google AI Studio
    "A": os.environ.get("GEMINI_VOICE_A", "Laomedeia"),  # Ada
    "B": os.environ.get("GEMINI_VOICE_B", "Iapetus"),    # Alan
    # C = occasional guest (episode.json "guest" can override name/voice/bio).
    "C": os.environ.get("GEMINI_VOICE_C", "Sulafat"),
}
GEMINI_SPEAKER_NAMES = {"A": "Ada", "B": "Alan", "C": "Guest"}  # transcript names
# A response is capped at 8192 audio tokens (~5.5 min at 25 tokens/s). ~2000 chars
# of script is ~2.3 min spoken — comfortable headroom, and each chunk still carries
# enough conversation for natural back-and-forth prosody.
GEMINI_CHUNK_CHARS = 2000
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


def _gemini_chunks(turns: list[dict],
                   breaks: set[int] | None = None) -> list[tuple[int, list[dict]]]:
    """Group consecutive turns into chunks under GEMINI_CHUNK_CHARS of script.

    Returns (start_turn_index, turns) per chunk. A chunk also breaks:
    - at any turn index in `breaks` (chapter starts), so chapter timestamps fall
      exactly on chunk boundaries, and
    - before a turn whose speaker would give the chunk a third distinct speaker —
      the multi-speaker API takes exactly two voices per request (guest scenes
      are written as guest + one host, so this split is rare).
    """
    breaks = breaks or set()
    chunks: list[tuple[int, list[dict]]] = []
    cur: list[dict] = []
    start = 0
    size = 0
    speakers: set[str] = set()
    for i, turn in enumerate(turns):
        third_voice = len(speakers | {turn["speaker"]}) > 2
        if cur and (size + len(turn["text"]) > GEMINI_CHUNK_CHARS
                    or i in breaks or third_voice):
            chunks.append((start, cur))
            cur, size, speakers, start = [], 0, set(), i
        cur.append(turn)
        size += len(turn["text"])
        speakers.add(turn["speaker"])
    if cur:
        chunks.append((start, cur))
    return chunks


def _write_id3_chapters(mp3_path: str, chapters: list[dict]) -> None:
    """Embed ID3v2 CHAP/CTOC frames ({'title', 'start_s'} per chapter)."""
    from mutagen.id3 import CHAP, CTOC, ID3, TIT2, CTOCFlags
    from mutagen.mp3 import MP3

    total_ms = int(MP3(mp3_path).info.length * 1000)
    tags = ID3(mp3_path) if MP3(mp3_path).tags else ID3()
    ids = []
    for n, ch in enumerate(chapters):
        start = int(ch["start_s"] * 1000)
        end = (int(chapters[n + 1]["start_s"] * 1000)
               if n + 1 < len(chapters) else total_ms)
        cid = f"chp{n}"
        ids.append(cid)
        tags.add(CHAP(element_id=cid, start_time=start, end_time=end,
                      sub_frames=[TIT2(encoding=3, text=[ch["title"]])]))
    tags.add(CTOC(element_id="toc", flags=CTOCFlags.TOP_LEVEL | CTOCFlags.ORDERED,
                  child_element_ids=ids, sub_frames=[]))
    tags.save(mp3_path)


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


def render_gemini(turns: list[dict], out_path: str, tts_notes: str = "",
                  chapters: list[dict] | None = None,
                  guest: dict | None = None) -> None:
    import base64
    import time
    import wave

    from google import genai
    from google.genai import types

    api_key = os.environ["GEMINI_API_KEY"]  # KeyError = clear failure
    # Per-request timeout (ms) so a stalled stream raises and the retry loop
    # below catches it, instead of blocking forever on an open socket. A chunk
    # is ~3 min of audio; 600s leaves headroom for a slow-but-real response.
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=600_000),
    )
    voices = dict(GEMINI_VOICES)
    speaker_names = dict(GEMINI_SPEAKER_NAMES)
    guest = guest or {}
    if guest.get("name"):
        speaker_names["C"] = guest["name"]
    if guest.get("voice"):
        voices["C"] = guest["voice"]

    def chunk_config(chunk: list[dict]) -> "types.GenerateContentConfig":
        # The multi-speaker API takes exactly two voices; give it the chunk's
        # speakers, padded with a host if a chunk is single-voiced.
        present = {t["speaker"] for t in chunk}
        if len(present) < 2:
            present.add("A" if "A" not in present else "B")
        return types.GenerateContentConfig(
            temperature=1,
            response_modalities=["audio"],
            speech_config=types.SpeechConfig(
                multi_speaker_voice_config=types.MultiSpeakerVoiceConfig(
                    speaker_voice_configs=[
                        types.SpeakerVoiceConfig(
                            speaker=speaker_names[key],
                            voice_config=types.VoiceConfig(
                                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                    voice_name=voices[key])),
                        )
                        for key in sorted(present)
                    ],
                ),
            ),
        )

    guest_block = ""
    if guest.get("name"):
        bio = guest.get("bio") or "A guest contributor on the show."
        guest_block = (f"\n# AUDIO PROFILE: {guest['name']}\n"
                       f"## \"The Guest\"\n{bio}\n")
    style = GEMINI_STYLE.format(
        episode_notes=(f"Note for today's episode: {tts_notes.strip()}"
                       if tts_notes.strip() else ""))
    if guest_block:
        style = style.replace("\n## THE SCENE", guest_block + "\n## THE SCENE")

    breaks = {ch["turn"] for ch in (chapters or [])}
    chunks = _gemini_chunks(turns, breaks)
    chunk_start_s: dict[int, float] = {}  # start turn index -> seconds into episode
    elapsed = 0.0
    with tempfile.TemporaryDirectory() as tmp:
        parts = []
        for i, (start_turn, chunk) in enumerate(chunks):
            prompt = style + "\n".join(
                f"{speaker_names.get(t['speaker'], 'Ada')}: {t['text']}"
                for t in chunk)
            # 5 attempts, exponential backoff (10s..80s): rides out rate blips
            # and short outages; a real outage fails the run within ~10 min.
            for attempt in range(5):
                try:
                    # Non-streaming: Gemini TTS does not support streaming, and
                    # the streaming path intermittently 504s / stalls past ~60s
                    # of audio for this model — generate_content returns the full
                    # chunk in one response. Concatenate every audio part in case
                    # the response splits its audio across parts.
                    pcm = bytearray()
                    mime = ""
                    resp = client.models.generate_content(
                        model=GEMINI_MODEL, contents=prompt,
                        config=chunk_config(chunk))
                    for p in (resp.candidates[0].content.parts
                              if resp.candidates
                              and resp.candidates[0].content else []):
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
            chunk_start_s[start_turn] = elapsed
            elapsed += seconds
            print(f"  chunk {i + 1}/{len(chunks)} done ({seconds:.0f}s, {mime})",
                  file=sys.stderr)
        _ffmpeg_concat(parts, out_path)

    if chapters:
        # Chapter turns were forced onto chunk boundaries, so each start time is
        # exact; fall back to the nearest earlier chunk if a turn was filtered.
        resolved = []
        for ch in chapters:
            starts = [s for t, s in chunk_start_s.items() if t <= ch["turn"]]
            resolved.append({"title": ch["title"],
                             "start_s": max(starts) if starts else 0.0})
        _write_id3_chapters(out_path, resolved)
        print(f"  wrote {len(resolved)} ID3 chapters", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episode", default="out/episode.json")
    ap.add_argument("--out", default="out/podcast.mp3")
    ap.add_argument("--backend", choices=["gemini", "kokoro"], default="gemini")
    args = ap.parse_args()

    with open(args.episode) as f:
        episode = json.load(f)
    raw = episode.get("turns", [])
    turns = [t for t in raw if t.get("text", "").strip()]
    if not turns:
        print("No turns in episode.json — nothing to render.", file=sys.stderr)
        return 1
    # Re-map chapter turn indices past any filtered-out empty turns.
    kept_before = [0] * (len(raw) + 1)
    for i, t in enumerate(raw):
        kept_before[i + 1] = kept_before[i] + bool(t.get("text", "").strip())
    chapters = [{"title": c["title"], "turn": kept_before[min(c["turn"], len(raw))]}
                for c in episode.get("chapters", []) or []]

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    print(f"Rendering {len(turns)} turns via {args.backend}...", file=sys.stderr)
    if args.backend == "gemini":
        # No fallback: if Gemini is down after the retries, fail loudly. A
        # flat-voiced episode must never publish unnoticed.
        render_gemini(turns, args.out, tts_notes=str(episode.get("tts_notes", "")),
                      chapters=chapters, guest=episode.get("guest"))
    else:
        render_kokoro(turns, args.out)  # manual/offline path: no chapters

    size_mb = os.path.getsize(args.out) / 1e6
    print(f"Wrote {args.out} ({size_mb:.1f} MB)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
