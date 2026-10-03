# Nkuzi

Nkuzi (Igbo for "teaching") is a study-group co-pilot for students who teach each other from slides. It listens while you explain, ticks off the points you cover, checks what you said against your slides, and writes a recap for the group chat. Everything runs on your own laptop with no internet.

## What it does

1. **Upload your slides** (PDF, PowerPoint or Word). Nkuzi builds an outline of the points to cover. You can edit it.
2. **Press "Start listening"** and explain. Nkuzi transcribes your microphone and ticks points off as you cover them.
3. **"What did I miss?"** shows the points you haven't covered yet.
4. **"Check me"** compares what you just said with your slides and lists contradictions, each with the exact slide line. If Nkuzi misheard you, press "That's not what I said".
5. **End the session** to get a recap (covered, missed, corrections) ready to paste into WhatsApp.

Nkuzi is a companion, not the meeting: keep it open as a narrow window beside Google Meet or WhatsApp.

## Why local and open source

- **No data costs.** Streaming audio to a cloud API is not realistic on expensive mobile data. After the one-time model downloads, Nkuzi uses no internet at all.
- **Works when the network doesn't.** Wi-Fi off, power cut, hotspot only: it still runs.
- **Private.** Your voice and your lecture notes never leave the laptop.
- **Runs on old hardware.** It was built and measured on a 2014 laptop (Intel Core i5-4310U, 2 cores, 8 GB RAM, no usable GPU).
- **Swappable models.** Gemma, Whisper and the embedding model are each one setting in `backend/app/config.py`.

## How it works

Nkuzi has a **fast path** and a **slow path**, and the fast path does not depend on a language model.

**Fast path (every 8 seconds, no language model):**
- The browser captures the microphone at 16 kHz and sends 8-second chunks to the backend.
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (`tiny.en`, CPU, int8) transcribes each chunk. It is given the **key terms from your slides as a hint**, so it spells "propranolol" and "bisoprolol" the way your slides do.
- [fastembed](https://github.com/qdrant/fastembed) (`bge-small-en-v1.5`) compares what you said with each outline point. A point is ticked when it is similar enough and most of its key terms were said. You can tick or untick by hand, and your click always wins.

**Slow path (Gemma 4 through [Ollama](https://ollama.com), only when asked):**
- **Outline.** Gemma reads one slide at a time and picks its most important lines, shortened. Every point is then **verified in code**: all its words must come from one single line of the slide. If not, the slide's own wording is used. Title, outline, reference and thank-you slides are skipped, and points are spread over the whole deck so the last slides are not cut off.
- **Check me.** Gemma is shown the three slides closest to your last 90 seconds of speech and proposes contradictions. Code keeps one only if its quote really is on the slide and the claim really is in the transcript. Gemma is then asked a yes/no second opinion on each. Nothing is shown that isn't backed by a quote from your slides.

The recap is built with plain code, so it is instant.

## Setup on Windows

You need Python (3.10 or newer), Node.js and [Ollama](https://ollama.com/download).

```powershell
# one-time
ollama pull gemma4:e2b-it-qat     # about 4.3 GB, start it early (uses about 3.6 GB of RAM)
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1      # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r requirements.txt
python scripts\check_setup.py     # first run downloads Whisper (~75 MB) and embeddings (~130 MB)
cd ..\frontend
npm install

# every time (two terminals)
cd backend; .\run.ps1             # http://localhost:8000
cd frontend; npm run dev          # open http://localhost:5173
```

After the downloads above, Nkuzi works with Wi-Fi turned off. Use Chrome or Edge.

If `ollama` is not recognised, it is at `%LOCALAPPDATA%\Programs\Ollama\ollama.exe`.

### On a small laptop

Gemma 4 needs about 3.6 GB of free RAM. Close other apps before a session. If it is still too tight, use the much smaller Gemma 3 (the outline still works; "Check me" is not reliable with it):

```powershell
ollama pull gemma3:1b
$env:OLLAMA_MODEL = "gemma3:1b"; .\run.ps1
```

Every setting in `backend/app/config.py` can be overridden the same way, with an environment variable of the same name.

## LAN mode: letting a friend use it over Wi-Fi

A friend on the same Wi-Fi or hotspot can use Nkuzi from their own laptop or phone. The AI still runs on your laptop; their device only shows the page and sends its microphone audio to you.

```powershell
.\run-lan.ps1
```

It starts the backend if needed, prints the address to open (for example `https://192.168.1.20:5174`), and starts the page over HTTPS. HTTPS is needed because browsers only allow the microphone on secure pages.

- **The browser will warn that the connection isn't private.** That is expected: the certificate is made by your laptop. Choose Advanced, then Proceed.
- **Windows Firewall.** If the friend's device can't open the page, run this once in PowerShell opened as administrator:
  ```powershell
  New-NetFirewallRule -DisplayName 'Nkuzi LAN' -Direction Inbound -Protocol TCP -LocalPort 5174 -Action Allow
  ```
  This is usually needed when Windows has marked the network as "Public", which is common for phone hotspots.
- Only one person should be explaining at a time: the laptop transcribes one audio stream at a time.

## Try it without a microphone

With the backend running:

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\send_wav.py
.\.venv\Scripts\python.exe scripts\send_wav.py samples\beta_blockers.pptx samples\sample_mistakes.wav --check
```

The first plays a 47-second explanation of the sample deck through Nkuzi and prints what it heard, how long each chunk took, and which points it ticked. The second plays a recording with two deliberate mistakes and then presses "Check me".

## Manual test

1. Upload `backend\samples\beta_blockers.pptx`. An outline appears; Gemma's version replaces it after a minute or so.
2. Press **Start listening**, allow the microphone, and explain three points. They turn green.
3. Press **What did I miss?**.
4. Say something wrong on purpose, for example "atenolol is a non-selective beta blocker", then press **Check me**. After a minute or two it shows what it heard next to the slide line.
5. Press **End session and see recap**, then **Copy for WhatsApp**.

## Measured performance

All numbers are from the 2014 laptop (i5-4310U, 8 GB RAM, no GPU) on 3 October 2026, with a browser and an editor open.

| What | Result |
|---|---|
| Whisper `tiny.en`, per 8-second chunk, with Gemma 4 loaded | 1.2 to 2.4 s |
| Coverage matching, per chunk | about 0.3 s |
| Gemma 4 outline, 35-slide lecture (16 Gemma calls, 38 points) | 274 s |
| Gemma 4 outline, per slide | 16 to 32 s, depending on free RAM |
| Gemma 4 first load into RAM | about 2 minutes |
| "Check me" (one proposal call, one yes/no call per candidate) | about 100 s |
| Recap | instant |

On test recordings (synthetic speech, so treat these as a best case):

- **Ticking:** 8 of 8 explained points ticked, no false ticks.
- **Check me:** two deliberate mistakes caught with the right slide lines; a correct statement that Gemma first flagged was rejected by the second opinion.
- **Gemma 4 vs Gemma 3 (1B)** on a four-case contradiction test: Gemma 4 got 4 of 4. Gemma 3 answered "contradicts" every time.

Two things learned from measuring:

- Whisper retries unclear audio by default, which made some chunks take 8 to 13 s. One pass keeps every chunk under 2.5 s.
- Whisper and Gemma compete for the CPU. Running together, Whisper took 20 to 30 s per chunk. So while "Check me" runs, new audio waits in the browser and is transcribed as soon as the check finishes.

## Limitations

- **English only.**
- **Transcription is the weak point.** `tiny.en` mishears uncommon terms and accents, and a word cut by a chunk boundary can be lost. `base.en` and `distil-small.en` are more accurate but slower: `python scripts\compare_whisper.py` compares them on your own recordings.
- **Ticking follows the topic, not the truth.** If you say the wrong thing about atenolol, the atenolol point is still ticked. That is what "Check me" is for.
- **A small model misses subtle errors.** "Check me" catches clear contradictions with a slide line. It will not catch an error the slides don't mention.
- **Slides need real text.** Scanned or picture-only slides can't be read. Old `.ppt` and `.doc` files must be saved as `.pptx` / `.docx` first.
- **"Check me" is slow** on this hardware: one to two minutes.

## What's next

Scheduling group discussions and keeping a history of topics per group; Igbo and Pidgin, then more languages through Gemma's multilingual support; a larger Whisper model where the laptop can afford it.

## License and credits

MIT. Built on [Gemma](https://ai.google.dev/gemma) (Apache 2.0) through [Ollama](https://ollama.com), [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [fastembed](https://github.com/qdrant/fastembed), PyMuPDF, python-pptx, python-docx, FastAPI and React.
