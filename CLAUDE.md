# CLAUDE.md — Project brief for Claude Code

> App name: **Nkuzi** (Igbo for "teaching").
> Keep the name in ONE place (`frontend/src/config.js` → `APP_NAME`, and `backend/app/config.py` → `APP_NAME`) so renaming is a one-line change.

Read this whole file before writing any code. It is the single source of truth for this project.

---

## 1. What we are building and why

**Nkuzi is a local, offline study-session assistant for students who teach each other in group discussions** (in person or on Google Meet / WhatsApp calls).

The user is Bukee, a medical student in Nigeria. In his class, students take turns explaining a topic to their group from a slide deck. Today the explainer just talks, forgets points, sometimes says things that contradict the slides, and nobody has a clean record afterwards.

Nkuzi fixes that:

1. The explainer uploads the **slides (PDF, PowerPoint `.pptx`, or Word `.docx`)**.
2. Nkuzi uses a local open model (**Gemma via Ollama**) to build an **outline of key points** from the slides. The explainer can edit it.
3. During the explanation, Nkuzi **listens to the explainer's microphone**, transcribes locally (**faster-whisper**), and **ticks off outline points as they are covered** in real time.
4. On request, the explainer (or anyone watching the screen) presses:
   - **"What did I miss?"** → shows uncovered points instantly.
   - **"Check me"** → Gemma compares what was just said against the relevant slides and lists contradictions, each **backed by an exact quote from the slides**.
5. At the end, Nkuzi produces a **recap**: covered points, missed points, corrections with slide references, formatted to paste into the group's **WhatsApp** chat.

### Nkuzi is a companion, not the meeting
Nkuzi sits **beside** Google Meet or WhatsApp; it is not the call itself. The explainer keeps it open as a narrow side panel (about 400–500 px wide) next to the call window, or full width on a second screen. Everything needed while preparing and explaining is on **one screen** (the Session screen, §8.2).

### Why it must be local and open-source (this is the heart of the hackathon entry)
- Data in Nigeria is expensive and the network is unreliable; streaming audio to a cloud API is not realistic. Nkuzi works with **no internet** once models are downloaded.
- Students' voices and study material never leave the laptop.
- It must run on a **2014 laptop with no GPU** (see §3). That is a feature we will brag about in the write-up.

### Context: the hackathon
- DEV Hacktoberfest 2026 Weekend Challenge, prompt "Build for a Friend": build something with **open-source AI at its core** for a real person.
- Judging: writing quality (heaviest), relevance (open AI must be core), creativity, technical execution, partner tech (we are entering **Best Use of Gemma**).
- **Deadline: Monday Oct 5, 2026, 06:59 UTC (07:59 Lagos).** We must have a working demo by **Sunday afternoon** so there is time to hand it to a friend, record a demo, and write the post.
- Consequence: **working > fancy.** Every milestone in §10 must leave the app in a runnable, demoable state.

---

## 2. Hard rules for Claude Code

1. **No cloud AI APIs. No API keys.** All AI runs locally: Ollama (Gemma), faster-whisper, fastembed. The app must work with Wi-Fi turned off (after first-time model downloads).
2. **Do not install PyTorch** (`torch`, `sentence-transformers`, `openai-whisper`, `transformers`). They are huge downloads on slow data and heavy on 8 GB RAM. Use `faster-whisper` (CTranslate2) and `fastembed` (ONNX) instead.
3. **CPU only.** Never assume CUDA. Use `device="cpu"`, `compute_type="int8"`.
4. **Windows first.** The dev machine is Windows (PowerShell). Use `pathlib`, no bash-only scripts. Provide `.ps1` or `npm`/Python commands that work in PowerShell.
5. **Keep dependencies minimal.** Ask the user before adding any dependency not listed in §6.
6. **Build in milestones (§10).** After each milestone: run it, tell the user exactly how to test it, and wait for confirmation before the next one.
7. **Never let the LLM block the live loop.** Gemma is slow on this machine. Live transcription + coverage tracking must never wait on Gemma.
8. **Never show a correction that isn't grounded in the slides** (see §7.5). A false correction to a medical student is worse than none. The same goes for the outline: **every Gemma outline point is verified in code against a single slide line** (§7.4). Keep this guardrail whatever model is used.
9. Make model names, thresholds, and chunk sizes configurable in `backend/app/config.py` (with env-var overrides), not hard-coded across files.
10. Write clear code with short comments. Bukee is learning React/JS/Python and will read it.
11. **Only one backend process at a time.** RAM is tight; a leftover backend plus Ollama can push the laptop into swap. Stop the backend before running `compare_models.py`.

---

## 3. Target hardware (design everything around this)

| | |
|---|---|
| CPU | Intel Core i5-4310U (2014, 2 cores / 4 threads, AVX2) |
| RAM | 8 GB (7.46 GB usable) |
| GPU | Intel HD integrated, **none usable for AI** |
| Disk | 238 GB SSD |
| OS | Windows 64-bit |
| Network | Slow / expensive mobile data, unreliable power |

Implications:
- **Model: `gemma4:e2b-it-qat`** (smallest Gemma 4, QAT build, ~4.3 GB download, ~3.6 GB in RAM). It is the default `OLLAMA_MODEL`. **Documented fallback: `gemma3:1b`** (815 MB download, ~0.8 GB in RAM) for when RAM is too tight: `$env:OLLAMA_MODEL = "gemma3:1b"`.
- Why Gemma 4 (measured on this laptop with `scripts/compare_models.py`, sample `.pptx`, VS Code and Chrome open, so RAM was already ~5.7 GB in use before any model loaded):

  | | gemma3:1b | gemma4:e2b-it-qat |
  |---|---|---|
  | Load time | 16 s | 124 s |
  | Outline, per slide | 31 s | 32 s |
  | Peak laptop RAM | 7.17 GB | 7.42 GB (of 7.46) |
  | Errors | 1 unreadable answer | none |
  | Outline points: reworded and passed / copied a slide line / fell back to the slide line / dropped | 1 / 2 / 11 / 1 | 0 / 11 / 4 / 0 |
  | Contradiction test (4 cases) | 2 right, 1 wrong, 1 unreadable; answered "contradicts" every time | 4 right, each with the correct slide line |

- **RAM is the risk with Gemma 4.** It ran at the ceiling. Close VS Code and spare browser tabs before a session. With more free RAM, gemma3:1b did the outline in about 10 s per slide; the 31–32 s figures above are under memory pressure. Re-measure in M2 with Whisper running live; if it swaps, lower `OLLAMA_KEEP_ALIVE` or fall back.
- Gemma answers can be slow. Keep prompts short and outputs short and in JSON (use a JSON schema as Ollama's `format` to force the shape).
- **Gemma 4 is a "thinking" model.** Always send `"think": false` (done in `llm.py`); otherwise the small token budget is spent on thinking and the answer comes back empty.
- Ollama defaults to a small context window. Set `num_ctx` explicitly (default 4096; never above 8192 on this machine).
- Whisper: default `tiny.en` (fast), allow `base.en` via config (more accurate, slower). int8, CPU, `cpu_threads=4`.
- Embeddings: `BAAI/bge-small-en-v1.5` via fastembed (small, ONNX, fast on CPU).
- RAM budget: Gemma + Whisper tiny + bge-small must fit together **alongside a browser running the call**. Load Whisper and the embedder once at startup; let Ollama manage Gemma with `keep_alive` (config, default `"10m"`).
- Whisper and embedding models are cached in `backend/model_cache/` (gitignored) and loaded with `local_files_only=True` first, so startup never touches the network once they are downloaded.

---

## 4. Architecture

```
┌──────────────────────── Browser (React + Vite) ────────────────────────┐
│ Setup → Session (outline + listening on one screen) → Recap            │
│ Mic capture: AudioWorklet → 16 kHz mono Int16 PCM chunks (~8 s)        │
└───────────────┬────────────────────────────────────────────────────────┘
                │ HTTP (localhost:8000)
┌───────────────▼──────────────── FastAPI backend (Python) ──────────────┐
│ slides.py     picks the reader by file type (PDF / .pptx / .docx)      │
│ pdf.py        PyMuPDF: extract text per slide                          │
│ office.py     python-pptx / python-docx: slides, tables, speaker notes │
│ outline.py    Gemma → outline points, verified in code; fallback       │
│ transcribe.py faster-whisper (tiny.en, int8, VAD, slide-vocab prompt)  │
│ coverage.py   fastembed similarity + keyword overlap → tick points     │
│ check.py      Gemma contradiction check, quote-verified                │
│ recap.py      covered / missed / corrections → WhatsApp text           │
│ store.py      sessions saved as JSON in backend/data/sessions/         │
└───────────────┬────────────────────────────────────────────────────────┘
                │ HTTP localhost:11434
         ┌──────▼──────┐
         │   Ollama    │  Gemma (model set by OLLAMA_MODEL)
         └─────────────┘
```

Everything runs on `localhost`. No database server: sessions are JSON files.

---

## 5. Folder structure

```
nkuzi/
├── CLAUDE.md
├── README.md                 # setup + usage + "why open source" (draft for the DEV post)
├── LICENSE                   # MIT
├── .gitignore                # venv, node_modules, backend/data/, model caches, .env
├── backend/
│   ├── requirements.txt
│   ├── run.ps1               # activates venv, starts uvicorn
│   ├── app/
│   │   ├── main.py           # FastAPI app, CORS, routes, startup model loading
│   │   ├── config.py         # all settings + env overrides
│   │   ├── models.py         # Pydantic schemas
│   │   ├── slides.py         # extract(filename, bytes): dispatches on file type
│   │   ├── pdf.py            # PDF reader + shared helpers (SlidesError, vocab, key terms)
│   │   ├── office.py         # .pptx and .docx readers
│   │   ├── llm.py            # thin Ollama client (httpx), JSON mode / schema, timeouts, retries
│   │   ├── outline.py
│   │   ├── transcribe.py
│   │   ├── coverage.py
│   │   ├── check.py
│   │   ├── recap.py
│   │   ├── store.py
│   │   └── prompts.py        # every prompt in one file
│   ├── scripts/
│   │   ├── check_setup.py    # verifies Ollama running, model pulled, whisper + embedder load, prints timings
│   │   ├── make_samples.py   # writes samples/beta_blockers.pdf, .pptx and .docx
│   │   ├── compare_models.py # outline speed, RAM, verification pass rate and a contradiction test per model
│   │   └── transcribe_file.py# transcribe a .wav for quick testing
│   ├── samples/              # sample deck (.pdf, .pptx, .docx) + sample wav for testing (small)
│   ├── model_cache/          # downloaded Whisper + embedding models, gitignored
│   └── data/sessions/        # runtime, gitignored
└── frontend/
    ├── package.json
    ├── vite.config.js        # proxy /api → http://localhost:8000
    ├── index.html
    ├── public/
    │   └── pcm-worklet.js    # AudioWorklet processor
    └── src/
        ├── main.jsx
        ├── App.jsx           # two screens chosen by the URL hash (#/session/<id>), problem banner, footer
        ├── config.js         # APP_NAME, API base, chunk seconds
        ├── api.js            # fetch wrappers
        ├── audio.js          # mic start/stop, resample to 16 kHz, Int16 chunks, callback per chunk
        ├── styles.css
        └── screens/
            ├── Setup.jsx     # home: the upload form
            ├── Session.jsx   # outline (editable) + "Start listening" + live checklist, on one screen
            └── Recap.jsx
```

---

## 6. Dependencies

### Backend (`backend/requirements.txt`)
```
fastapi
uvicorn[standard]
python-multipart
pydantic>=2
httpx
pymupdf
faster-whisper
fastembed
numpy
rapidfuzz
python-pptx
python-docx
```
- Python 3.10–3.14 (the dev laptop runs 3.14; every dependency has a wheel for it). Use a venv: `python -m venv .venv` then `.\.venv\Scripts\Activate.ps1`.
- If PowerShell blocks activation: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.
- First run downloads the Whisper model (~75 MB for tiny.en) and bge-small (~130 MB). Tell the user this once, clearly.

### Frontend
- React 18 + Vite. **Plain CSS** (no Tailwind, no UI library) to keep setup tiny.
- No other npm dependencies unless the user agrees.

### External
- **Ollama** installed on Windows, running at `http://localhost:11434`. (`ollama.exe` may not be on PATH: it lives in `%LOCALAPPDATA%\Programs\Ollama\`.)
- `ollama pull gemma4:e2b-it-qat` (about 4.3 GB; tell the user to start it early), or `ollama pull gemma3:1b` for the fallback.

---

## 7. Backend detail

### 7.1 `config.py`
Settings (each overridable by env var of the same name):
```
APP_NAME = "Nkuzi"
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "gemma4:e2b-it-qat"   # fallback: "gemma3:1b"
OLLAMA_NUM_CTX = 4096
OLLAMA_KEEP_ALIVE = "10m"
OLLAMA_TIMEOUT_S = 300          # CPU is slow; be generous
WHISPER_MODEL = "tiny.en"       # or "base.en"
WHISPER_THREADS = 4
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
CHUNK_SECONDS = 8               # must match frontend
COVER_THRESHOLD = 0.62          # cosine sim to mark a point covered (tune in M3)
COVER_KEYWORD_BONUS = 0.08      # added when key terms of a point appear in transcript
MAX_OUTLINE_POINTS = 25
CHECK_WINDOW_SECONDS = 90       # how much recent speech "Check me" looks at
OUTLINE_SLIDE_WORDS = 400       # longer slides are cut to this in the prompt
OUTLINE_NOTES_WORDS = 120       # speaker notes are cut to this in the prompt
OUTLINE_POINTS_PER_SLIDE = 3
OUTLINE_DEDUPE_SIM = 0.9
MAX_UPLOAD_MB = 50
LARGE_DECK_SLIDES = 60          # warn above this many slides
DATA_DIR = backend/data/sessions
MODEL_CACHE_DIR = backend/model_cache
```

### 7.2 Reading slide files: `slides.py`, `pdf.py`, `office.py`
- `slides.extract(filename, bytes) -> (slides, unit)` looks at the file's first bytes (not only its name) and calls the right reader. `unit` is `"Slide"`, or `"Section"` for Word files (the UI uses it as the label).
- Every reader returns the same shape: `Slide = {index: int (1-based), title: str, text: str, notes: str}`. `text` has the title on line 1 and one body line per bullet / table row. `notes` is kept separate and is empty except for `.pptx`.
- All readers raise `SlidesError` (defined in `pdf.py`) with a message the UI shows verbatim.

**PDF** (`pdf.extract_slides`, PyMuPDF):
- Title = the line with the largest font (first one if several tie). Clean whitespace, strip bullet symbols, drop page numbers / repeated footers (lines that appear on >50% of slides, when there are at least 4 slides). Wrapped bullet lines are joined.
- Skip empty slides (image-only). If the whole PDF has no extractable text, return a clear error: "This PDF has no selectable text (it may be scanned images). Export your slides to PDF from PowerPoint/Google Slides instead." (No OCR, out of scope.)

**PowerPoint `.pptx`** (`office.extract_pptx`, python-pptx):
- Title placeholder, body text top-to-bottom, **table rows** as `cell | cell | cell`, text inside grouped shapes, and **speaker notes** in `notes`.
- Footer / date / slide-number placeholders are skipped. A picture-only slide that has notes is kept (title + notes).

**Word `.docx`** (`office.extract_docx`, python-docx):
- Each **Title / Heading 1 / Heading 2** starts a new "slide"; the paragraphs and table rows under it are the body. Lower headings are body lines.
- Paragraphs over 25 words are split into sentences. A heading with nothing under it is dropped. A document with no headings is cut into sections of 8 lines.

**Old `.ppt` / `.doc`** (detected by extension or OLE header): error "Please open this in PowerPoint/Word and Save As .pptx/.docx."
Anything else: "Nkuzi reads .pdf, .pptx and .docx files. Export your slides to one of those and try again."

**Vocabulary string for Whisper** (`pdf.build_vocab`, used for every file type): the most distinctive terms across slides **and speaker notes** (capitalized words, long words ≥ 8 letters, words with digits/units, acronyms, deduplicated, most frequent first), capped at ~700 characters so it fits Whisper's prompt.

### 7.3 `llm.py`
- `async def generate_json(prompt: str, system: str, max_tokens: int, schema: dict | None = None) -> dict`
- Calls `POST {OLLAMA_URL}/api/generate` with `format: schema or "json"`, `stream: false`, `think: false`, `options: {temperature: 0.2, num_ctx, num_predict: max_tokens}`, `keep_alive`.
- Parse JSON; on parse failure retry once with "Return valid JSON only." appended; then raise a clean `LLMError`.
- `async def is_ready() -> {ok, model_present, message}` using `/api/tags`.
- Log timing of every call (so we can report speed honestly in the post).

### 7.4 `outline.py`: building the outline (slow path, runs before the session)
- **One slide per Gemma call** (short prompts suit small models and keep every call inside `num_ctx`). Slides with almost no body text (< 12 words, e.g. a title slide) are not sent to Gemma; they keep a single title point.
- Prompt (in `prompts.py`), deliberately tiny:
  - System: "You turn lecture slides into a short checklist of the key points a student must explain. Use only information in the slides."
  - User: slide title + slide text (+ "Speaker notes (extra context only)" when the slide has notes), then "Choose the N most important lines of this slide. Shorten each one to at most 15 words, using only words from that line."
  - Output is forced with a **JSON schema**: `{"points": ["...", "..."]}` with exactly N strings (N = up to `OUTLINE_POINTS_PER_SLIDE`).
- **Verification guardrail (keep it whatever the model).** Small models glue two bullets into a false statement ("Bradycardia is contraindicated in asthma"). So each Gemma point is checked in code (`_ground`):
  1. every content word of the point must come from **one single line** of the slide (title words are allowed too), and
  2. the point must keep every key term (drug names, acronyms, long words) of that line.
  If it passes, Gemma's wording is used. If not, **the slide's own line is used instead**. Points that match no line, or the same line twice, are dropped.
- **Speaker notes** are extra context in the prompt. Points must still come from the slide's lines, except when the slide is nearly empty (picture + notes): then the notes' sentences are the lines.
- `outline["stats"]` records per outline: `slides_asked, reworded, copied, fell_back, dropped, seconds` (honest numbers for the write-up).
- Keywords for each point are computed in code from the point's text (not by Gemma).
- Dedupe near-duplicates using embeddings (sim > 0.9). Cap at `MAX_OUTLINE_POINTS`, spread fairly across slides, keeping slide order.
- **Deterministic fallback** (shown instantly while Gemma runs, and used if Ollama is down or a slide's call fails): slide title + up to 2 top bullet lines per slide. The app must work without Gemma.
- Runs as a **background task**; progress (`done / total` slides) is polled by the UI.
- Saving an edited outline (PUT) **cancels** a running Gemma job: the explainer's version wins.
- After the outline is final, precompute and cache the embedding of each point (point text + keywords).

### 7.5 `check.py`: "Check me" (on request only) — the anti-hallucination rules
1. Take transcript text from the last `CHECK_WINDOW_SECONDS`.
2. Retrieve the **top 3 slides** most similar to that text (embeddings over slide text).
3. Prompt Gemma with ONLY those slides + the transcript window:
   - System: "You check a student's spoken explanation against their lecture slides. Report only clear factual contradictions between what the student said and what the slides say. Do not report omissions, opinions, style, or anything the slides don't mention. If nothing contradicts the slides, return an empty list."
   - Output JSON: `{"issues": [{"said": "what the student said (short)", "slide": <number>, "slide_quote": "exact words copied from the slide", "fix": "one short sentence"}]}`
4. **Verify every issue in code**: `slide_quote` must fuzzy-match text in the cited slide (`rapidfuzz.fuzz.partial_ratio >= 85`). If not, **discard it**. Also discard issues whose `said` doesn't fuzzy-match the transcript window (≥ 70).
5. Return verified issues; also store them on the session for the recap.
6. If none: return `{"issues": [], "message": "No contradictions with your slides found."}`.
7. This call can take 20–60 s on this laptop. The UI shows a non-blocking "Checking against slides…" state while live tracking continues.
8. Preview result (from `compare_models.py`): with one slide and one sentence, asking for `{"slide_quote", "contradicts"}` (quote first, then the verdict) and a JSON schema, `gemma4:e2b-it-qat` got 4 of 4 right in 17–21 s each. `gemma3:1b` said "contradicts" for everything, so **"Check me" must not be trusted on gemma3:1b**: when that model is configured, disable the button or label results as unreliable.

### 7.6 `transcribe.py`: live speech-to-text (fast path)
- Load `WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8", cpu_threads=WHISPER_THREADS)` **once at startup**.
- `transcribe_chunk(pcm_int16: bytes, vocab: str, prev_text: str) -> str`
  - Convert Int16 PCM → float32 numpy in [-1, 1] at 16 kHz.
  - `model.transcribe(audio, language="en", beam_size=1, vad_filter=True, initial_prompt=(vocab + " " + prev_text[-200:]), condition_on_previous_text=False)`
  - The `initial_prompt` with slide vocabulary is **important**: it makes Whisper spell medical terms correctly. Keep it.
- Each chunk must finish transcribing faster than `CHUNK_SECONDS`. Measure in M2; if too slow, keep `tiny.en` and/or raise `CHUNK_SECONDS` to 10.
- Process chunks **sequentially per session** (a simple asyncio lock / queue) so the CPU isn't thrashed. Run blocking Whisper calls in a thread (`run_in_threadpool` / `asyncio.to_thread`).

### 7.7 `coverage.py`: ticking off points (fast path, no LLM)
- Maintain per-session: transcript segments with timestamps, set of covered point ids, `covered_at` time and the matching snippet for each.
- After each new chunk:
  - Text window = last 2 chunks joined (catches points that span a chunk boundary).
  - Split into sentences (simple regex). Embed sentences + the whole window.
  - For each **uncovered** point: score = max cosine sim between point embedding and any sentence/window embedding; add `COVER_KEYWORD_BONUS` if ≥ 1 of the point's keywords appears in the window (case-insensitive, fuzzy ≥ 85 for long terms).
  - If score ≥ `COVER_THRESHOLD`, mark covered, store the snippet.
- Return newly covered point ids so the UI can animate them.
- Also support **manual tick/untick** from the UI (the explainer can correct it). Manual always wins.

### 7.8 `recap.py`
- Build deterministically (no LLM needed, so it's instant):
  - Topic, explainer name, date, duration.
  - Covered points ✓ (count / total).
  - Missed points ✗ (with slide numbers).
  - Corrections (verified issues) with slide numbers and the fix.
- `whatsapp_text`: plain text using WhatsApp formatting (`*bold*`, `_italic_`, line breaks, ✅ ❌ ⚠️ emoji). Keep it under ~1500 characters; truncate long lists with "+N more".
- Optional (only if time allows, behind a button): Gemma writes a 2-sentence summary of the transcript. Never block the recap on this.
- Save full transcript too (downloadable as .txt).

### 7.9 `store.py`
- One JSON file per session: `data/sessions/<session_id>.json` holding title, explainer, created_at, unit, slides, vocab, outline (+ status, source, progress, stats), transcript segments, covered map, issues, started_at, ended_at.
- Embeddings stay in memory only (recompute on load if needed).
- Write after every state change (small files, fine). Written to a temp file first, then renamed.

### 7.10 API endpoints (all under `/api`)
| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | `{ollama_ok, model_present, whisper_loaded, embedder_loaded, model_name, problems: [{title, fix}]}`. `problems` is empty when all is well; the UI shows one banner line per problem |
| POST | `/sessions` | multipart: `pdf` (the file: .pdf, .pptx or .docx), `title`, `explainer` → creates session, extracts slides, builds the fallback outline, starts the background Gemma outline, returns `{session_id, warning}`. The UI then loads `GET /sessions/{id}` |
| GET | `/sessions` | list past sessions (id, title, explainer, date, covered/total) |
| GET | `/sessions/{id}` | full session state |
| GET | `/sessions/{id}/outline` | `{status: generating\|ready\|fallback_only, source: slides\|gemma\|edited, progress, message, points}` |
| PUT | `/sessions/{id}/outline` | save user-edited outline (re-embed points); cancels a running Gemma outline |
| POST | `/sessions/{id}/start` | mark live start time |
| POST | `/sessions/{id}/audio` | body: raw Int16 PCM (`application/octet-stream`), query `seq` → `{text, newly_covered: [ids], covered_count, total}` |
| POST | `/sessions/{id}/points/{pid}/toggle` | manual tick/untick |
| GET | `/sessions/{id}/missed` | uncovered points (instant) |
| POST | `/sessions/{id}/check` | starts "Check me" job → `{job_id}` |
| GET | `/sessions/{id}/check/{job_id}` | `{status, issues, message}` |
| POST | `/sessions/{id}/end` | finalize → recap object incl. `whatsapp_text` |
| GET | `/sessions/{id}/transcript.txt` | download transcript |

- CORS: allow `http://localhost:5173`.
- Startup: load Whisper + embedder in the background, check Ollama; log clear messages. If Ollama is down, the app still starts (fallback outline, "Check me" disabled with an explanation).
- Return friendly error messages (the UI shows them verbatim).

---

## 8. Frontend detail

### 8.1 Audio capture (`audio.js` + `public/pcm-worklet.js`)
- `navigator.mediaDevices.getUserMedia({audio: {echoCancellation: true, noiseSuppression: true, channelCount: 1}})`.
- AudioContext (whatever native rate, usually 44.1/48 kHz) → AudioWorkletNode that posts Float32 frames to the main thread.
- Main thread: downsample to **16 kHz** (simple linear/averaging resampler), accumulate, and every `CHUNK_SECONDS` convert to Int16 and call `onChunk(Int16Array)`.
- `api.js` POSTs each chunk to `/audio` with an increasing `seq`. If a request is still in flight, **queue** chunks (don't drop; don't send in parallel).
- Show a small live mic-level meter so the user knows it's hearing them.
- **Do not use MediaRecorder** (its chunks aren't independently decodable).
- Note in the UI: on a call, the explainer should use Nkuzi on **their own device and mic**, so it only hears the explainer. That is intended.

### 8.2 Screens (chosen by the URL hash in `App.jsx`)
The open session's id is in the address bar (`#/session/<id>`), so a reload or a window resize keeps your place.

**Always visible**
- **Problem banner** (top): shows **nothing when everything is fine**. When something is broken it says what and how to fix it: Ollama not running, model not pulled (with the exact `ollama pull …` command), speech/embedding model failed to load, backend unreachable. It polls `/health` every 5 s and clears itself. **There is no health strip.**
- **Footer badge**: "Running offline · Gemma".

1. **Home / Setup**
   - App name + one-line tagline ("Your study-group co-pilot. Runs offline.").
   - Form: topic title, explainer name, slides upload (drag & drop + button) accepting **.pdf, .pptx, .docx**. Old .ppt/.doc get the "Save As" message. Submit → Session screen.
   - Below (M5): list of past sessions (click → open their recap).
2. **Session** (one screen for preparing *and* explaining; the demo screen)
   - A sticky **mic bar** at the top: a big round **"Start listening"** button, a status line, and the progress count.
   - **Before listening**: the outline is editable. The fallback outline shows immediately with a progress bar while Gemma builds the real one ("Gemma is reading your slides… 3/7"), then Gemma's outline swaps in (note: "Generated by Gemma, running on this laptop. Every point is checked against your slides."). Each point: editable text, slide number chip, up/down, delete; "Add point"; "Save changes".
   - **"Start listening"** saves the outline as it is (stopping Gemma if still running) and switches the same screen to the **checklist**: large points (≥ 18px) grouped by slide. "Edit outline" switches back.
   - **While listening** (M2/M3 fill these in): points animate to ✓ when covered (gentle highlight, no jarring motion); click a point to toggle manually; "7 / 18 points covered"; level meter + elapsed timer; collapsible live transcript (last ~6 lines, auto-scroll).
   - **"What did I miss?"** button → panel listing uncovered points (instant).
   - **"Check me"** button → non-blocking "Checking against your slides…" → results panel. Each issue shows: what you said, slide N quote, fix. Empty result shows a reassuring message.
   - Corrections never pop up uninvited; they appear only after "Check me".
   - "End session" button → Recap.
3. **Recap**
   - Summary cards: covered ✓, missed ✗, corrections ⚠️, duration.
   - Missed list, corrections list.
   - **"Copy for WhatsApp"** button (copies `whatsapp_text`, shows "Copied!").
   - "Download transcript" link. "New session" button.

### 8.3 Visual design
- Calm, focused, high-contrast. Should feel like a quiet co-pilot, not a dashboard.
- One accent colour (deep green `#1F7A5C` for "covered"; amber for corrections and problems; muted red only for "missed" in the recap and for errors).
- System font stack, generous spacing, large text on the checklist (points ≥ 18px) so it's readable when shared on a call.
- Light and dark mode via `prefers-color-scheme` with CSS variables.
- **Must work as a narrow side panel (400–500 px wide) beside a call window**, as well as full width (1366×768 is the target screen). Below 560 px each point's tools drop under its text.
- Footer badge: "Running offline · Gemma".

---

## 9. Testing & verification

- `backend/scripts/check_setup.py`: checks Ollama is reachable, model pulled, loads Whisper + embedder, runs a tiny Gemma JSON prompt, transcribes `samples/sample.wav`, and **prints timings** for each. Run this first on the real laptop.
- `backend/scripts/make_samples.py` writes the same "Beta blockers" deck to `backend/samples/` as `.pdf`, `.pptx` (with a table slide, speaker notes and a notes-only slide) and `.docx` (headings, long paragraphs, a table). A short wav of someone explaining it is still needed (the user can record one).
- `backend/scripts/compare_models.py <model> <model>` measures each model on the sample `.pptx`: load time, seconds per slide, peak RAM, verification stats, and a 4-case contradiction test. **Stop the backend first.** Results are saved to `backend/data/model_comparison.json`.
- Unit-ish tests (plain `pytest`, optional): quote verification in `check.py` rejects fabricated quotes; coverage marks a point covered for a paraphrase and not for an unrelated sentence.
- Manual end-to-end test script in README: upload a sample deck → review outline → Start listening → speak 3 points → see ticks → "What did I miss?" → deliberately say something wrong (e.g. wrong drug class) → "Check me" catches it with the slide quote → End → copy WhatsApp recap.
- Record measured numbers (outline time, chunk transcription time, check time) in README. We'll use them in the post.

---

## 10. Milestones (do them in order; stop after each for the user to test)

**M0 — Setup check (DONE)**
Scaffold folders, `requirements.txt`, venv instructions, `config.py`, `llm.py`, `check_setup.py`, `/health`. Frontend Vite scaffold.

**M1 — Slides → outline (DONE)**
`slides.py` / `pdf.py` / `office.py`, fallback outline, verified Gemma outline in background with progress, `/sessions` create, outline GET/PUT, Setup + Session screens (Session has the outline editor and a placeholder checklist behind "Start listening").
✅ Done when: user uploads a real lecture file (.pdf, .pptx or .docx) and gets an editable outline from Gemma.

**M2 — Live transcription (≈1.5 h)**
AudioWorklet capture wired to the "Start listening" button, 16 kHz Int16 chunks, `/audio`, `transcribe.py` with vocab prompt, live transcript on the Session screen. Print per-chunk timing.
✅ Done when: user speaks and sees accurate text within ~10 s, including medical terms from the slides.

**M3 — Coverage ticking (≈1.5 h)**
`coverage.py`, newly-covered animation, manual toggle, progress, "What did I miss?". Tune `COVER_THRESHOLD` with the user by speaking real explanations (log scores per point to the console to tune).
✅ Done when: explaining points ticks them off reliably with few false ticks.
→ **This is the minimum demoable product. Commit and tag it.**

**M4 — Check me (≈1.5 h)**
`check.py` with retrieval, Gemma prompt, quote verification, job polling, results panel.
✅ Done when: a deliberate mistake is caught with a correct slide quote, and correct explanations return "no contradictions".

**M5 — Recap + polish (≈1.5 h)**
`recap.py`, Recap screen, WhatsApp copy, transcript download, past sessions list, visual polish, empty/error states, README.
✅ Done when: full end-to-end flow works smoothly and looks good for a screen recording.

**Stretch (only if everything above is solid):** Gemma 2-sentence summary in recap; keyboard shortcuts (M = missed, C = check); scheduling of group discussions and topic history (otherwise mention as "what's next" in the post).

---

## 11. Edge cases to handle

- Ollama not running / model not pulled → problem banner with the exact command (`ollama pull <model>`); fallback outline; "Check me" disabled.
- Gemma returns invalid JSON → one retry, then fallback / friendly error.
- Gemma very slow → never freeze UI; show progress; allow starting the session with the fallback outline.
- Scanned/image-only PDF, or a .pptx with no text → clear message (§7.2).
- Old `.ppt` / `.doc` → "Please open this in PowerPoint/Word and Save As .pptx/.docx."
- Very large deck (60+ slides) → warn and allow it, but cap outline points.
- Mic permission denied → instructions to allow mic in browser settings.
- Silence / noise chunks → VAD returns empty text; skip without error.
- Backend restarted mid-session → session reloads from JSON; embeddings recomputed lazily. An outline that was still "generating" becomes `fallback_only`.
- Laptop is slow: avoid re-embedding the whole transcript each chunk; only new text.

---

## 12. README.md contents (also feeds the DEV post)

1. What Nkuzi is, in two sentences, and who it was built for (leave a placeholder: `<!-- FRIEND STORY: Bukee fills this in -->`).
2. Screenshot/GIF placeholders.
3. Why open source / local matters (no data costs, works offline, privacy, runs on a 2014 laptop without GPU, swappable models).
4. How it works (the fast path vs slow path design; slide-vocabulary prompting for Whisper; code-verified outline points; quote-verified corrections).
5. Setup on Windows (Python venv, Ollama + model pull, npm install, run commands).
6. Measured performance on the i5-4310U (including the model comparison).
7. Limitations (English only, needs files with real text, small model can miss subtle errors) and what's next (scheduling, topic history, Igbo/Pidgin support, more languages via Gemma's multilingual support).
8. License: MIT. Credits: Gemma (Apache 2.0), faster-whisper, fastembed, Ollama.

---

## 13. How to run (target end state)

```powershell
# one-time
ollama pull gemma4:e2b-it-qat     # about 4.3 GB (fallback: gemma3:1b, 815 MB)
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python scripts\check_setup.py

# every time (two terminals)
cd backend; .\run.ps1             # http://localhost:8000
cd frontend; npm install; npm run dev   # http://localhost:5173
```
