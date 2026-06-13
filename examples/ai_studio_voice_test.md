# Gemini TTS voice audition — Google AI Studio

Use this to pick Ada's and Alan's voices by ear. The show's locked-in pair is
**Ada = Laomedeia, Alan = Iapetus** (also the code default); override without code
changes by setting `GEMINI_VOICE_A` / `GEMINI_VOICE_B` in `.env`.

## How to run it

1. Open https://aistudio.google.com → **Generate speech** (speech generation mode).
2. Model: `gemini-3.1-flash-tts-preview`.
3. Switch to **Multi-speaker** mode and name the two speakers exactly `Ada` and `Alan`
   (they must match the names in the transcript below).
4. Pick a voice for each, paste the transcript, generate, listen. Swap voices, repeat.
5. If there's a style-instructions field, paste the style note below (it's the same one
   `make_audio.py` sends in production, so what you hear is what the show will sound like).

## Style note (paste as instructions, or leave at the top of the prompt)

This matches the `GEMINI_STYLE` constant `make_audio.py` sends with every chunk
(see the canonical copy there).

```
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

### SAMPLE CONTEXT
This is one continuous stretch of an episode already in progress: the hosts are
warmed up and mid-flow, talking to a smart general audience that listens every
morning.
```

## Test transcript (~75 seconds)

Written to stress the things that make dialogue feel real: reactions, an interruption,
a laugh, numbers and acronyms read aloud, and a quiet aside.

```
Ada: Okay, before we get to the news — Alan, did you actually run that fine-tune last night, or did you just say you would?
Alan: [laughs] I ran it! Twelve hours on a rented A100, and the loss curve looks... let's say "artistic."
Ada: Artistic. That's what we're calling divergence now?
Alan: It recovered! Mostly. Anyway — the real story today is the new eval suite. Eighty-four point two on the hard split, up from seventy-one.
Ada: Right, and that's a thirteen-point jump, which historically — and I say this as the resident historian — is exactly the kind of jump that turns out to be a data leak.
Alan: Oh come on—
Ada: I'm just saying! GPT-2 to GPT-3 was the last time a jump that size held up under replication.
Alan: Okay, fair. [short pause] But the authors did publish the contamination check, and it's actually pretty thorough.
Ada: It is. I read it twice. Which, for the record, is once more than you read your own loss curves.
Alan: [laughs] That's... probably true. Alright — should we get into the papers?
Ada: Let's do it.
```

## The 30 prebuilt voices

Bright/upbeat: **Zephyr**, **Puck**, **Autonoe**, **Laomedeia**, **Sadachbia** (lively)
Breezy/easy-going: **Aoede**, **Callirrhoe**, **Umbriel**, **Zubenelgenubi** (casual)
Firm/clear: **Kore**, **Orus**, **Alnilam**, **Iapetus**, **Erinome**
Informative/knowledgeable: **Charon**, **Rasalgethi**, **Sadaltager**
Smooth/warm/gentle: **Algieba**, **Despina**, **Sulafat**, **Achernar** (soft), **Vindemiatrix**, **Achird** (friendly)
Textured: **Enceladus** (breathy), **Algenib** (gravelly), **Gacrux** (mature), **Pulcherrima** (forward), **Schedar** (even), **Leda** (youthful), **Fenrir** (excitable)

## Pairings worth auditioning

| Ada | Alan | Flavor |
|---|---|---|
| Zephyr | Puck | Current default — bright + upbeat, classic NotebookLM energy |
| Kore | Charon | Firmer, more NPR — historian gravitas + informative builder |
| Aoede | Fenrir | Breezy + excitable — looser, more banter-forward |
| Sulafat | Sadaltager | Warm + knowledgeable — slower evening feel |

When you've picked, set in `.env`:

```
GEMINI_VOICE_A="Kore"   # Ada
GEMINI_VOICE_B="Charon" # Alan
```
