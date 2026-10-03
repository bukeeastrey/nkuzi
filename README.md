# Nkuzi

Nkuzi (Igbo for "teaching") is a study-session co-pilot for students who teach each other from slides. It listens while you explain, ticks off the points you cover, and checks what you said against your slides, all on your own laptop with no internet.

<!-- FRIEND STORY: Bukee fills this in -->

> Status: Milestone 3. Upload a .pdf, .pptx or .docx, get an editable outline, press "Start listening", and points tick off as you explain them. The sections on how it works, measured performance and limitations are written in Milestone 5.

## Setup on Windows

You need Python, Node.js and [Ollama](https://ollama.com/download).

```powershell
# one-time
ollama pull gemma4:e2b-it-qat     # about 4.3 GB, start it early (needs ~3.6 GB of free RAM)
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1      # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r requirements.txt
python scripts\check_setup.py     # first run downloads Whisper (~75 MB) and embeddings (~130 MB)

# every time (two terminals)
cd backend; .\run.ps1                    # http://localhost:8000
cd frontend; npm install; npm run dev    # http://localhost:5173
```

After the downloads above, Nkuzi works with Wi-Fi turned off.

Settings (model names, thresholds, chunk size) are in `backend/app/config.py`. Each one can be overridden with an environment variable of the same name, for example `$env:OLLAMA_MODEL = "gemma3:1b"` (a much smaller model, for when RAM is tight; its "Check me" results are not reliable).

## Try it without a microphone

With the backend running:

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\send_wav.py
```

This plays `samples\sample.wav` (a 47-second explanation of the sample deck) through Nkuzi and prints what it heard, how long each chunk took, and which points it ticked.

## License

MIT. Built on Gemma, Ollama, faster-whisper and fastembed.
