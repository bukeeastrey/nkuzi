// Microphone capture. Turns the mic into chunks of 16 kHz, mono, 16-bit audio,
// which is exactly what the speech model (Whisper) wants.
//
// We don't use MediaRecorder: its chunks can't be decoded on their own.

const TARGET_RATE = 16000;
const MIN_FINAL_SECONDS = 1; // on stop, a leftover shorter than this is thrown away

// Human-readable message for the ways getUserMedia can fail.
function explainMicError(error) {
  if (error.name === "NotAllowedError") {
    return "Nkuzi isn't allowed to use the microphone. Click the icon at the left of the address bar, allow the microphone, then try again.";
  }
  if (error.name === "NotFoundError") {
    return "No microphone found. Plug one in, or check your sound settings.";
  }
  if (error.name === "NotReadableError") {
    return "Another app is using the microphone. Close it, or pick a different microphone, then try again.";
  }
  return `Couldn't start the microphone (${error.message}).`;
}

// The browser can clean up background noise before we get the audio. It is on
// by default. Open the page with "?ns=off" in the address to switch it off
// (useful for comparing transcription quality).
function wantNoiseSuppression() {
  return new URLSearchParams(window.location.search).get("ns") !== "off";
}

// Start listening.
//   chunkSeconds: length of each chunk
//   onChunk(Int16Array): called with each finished chunk
//   onLevel(number 0..1): called often with the current loudness, for the meter
// Returns {stop, label}: stop() turns the mic off (and sends the last partial
// chunk); label describes the mic setup, e.g. "16000hz-ns-on".
export async function startMic({ chunkSeconds, onChunk, onLevel }) {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error("This browser can't record audio here. Use a recent Chrome or Edge, on localhost or an https:// address.");
  }

  const noiseSuppression = wantNoiseSuppression();
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression, autoGainControl: true, channelCount: 1 },
    });
  } catch (error) {
    throw new Error(explainMicError(error));
  }

  // Ask the browser for a 16 kHz audio context. Chrome and Edge then convert
  // the microphone to 16 kHz themselves, with a proper low-pass filter, which
  // is better than anything we would write by hand.
  let context;
  try {
    context = new AudioContext({ sampleRate: TARGET_RATE });
  } catch {
    context = new AudioContext(); // the device's own rate, usually 44.1 or 48 kHz
  }

  let source;
  let worklet;
  const filters = [];
  try {
    await context.audioWorklet.addModule("/pcm-worklet.js");
    source = context.createMediaStreamSource(stream);
    worklet = new AudioWorkletNode(context, "pcm-processor");
  } catch (error) {
    stream.getTracks().forEach((track) => track.stop());
    context.close();
    throw new Error(`Couldn't start audio capture (${error.message}).`);
  }

  // --- Fallback downsampling, only if the context is NOT already at 16 kHz ---
  // Sounds above 8 kHz can't exist in 16 kHz audio; left in, they fold back as
  // noise ("aliasing"). So we first remove them with two low-pass filters,
  // then average each group of `ratio` samples into one.
  const ratio = context.sampleRate / TARGET_RATE;
  let input = source;
  if (ratio > 1) {
    for (let i = 0; i < 2; i++) {
      const filter = context.createBiquadFilter();
      filter.type = "lowpass";
      filter.frequency.value = 7000;
      input.connect(filter);
      filters.push(filter);
      input = filter;
    }
  }
  let sum = 0;
  let count = 0;
  let inputIndex = 0;
  let nextBoundary = ratio;

  // --- The chunk being filled ---
  const chunkSize = TARGET_RATE * chunkSeconds;
  let chunk = new Int16Array(chunkSize);
  let filled = 0;

  worklet.port.onmessage = (event) => {
    const samples = event.data; // Float32Array, values from -1 to 1
    let squares = 0;

    for (let i = 0; i < samples.length; i++) {
      const sample = samples[i];
      squares += sample * sample;
      sum += sample;
      count++;
      inputIndex++;
      if (inputIndex >= nextBoundary) {
        // Float (-1..1) -> 16-bit integer (-32768..32767)
        const value = Math.max(-1, Math.min(1, sum / count));
        chunk[filled++] = value < 0 ? value * 32768 : value * 32767;
        sum = 0;
        count = 0;
        nextBoundary += ratio;
        if (filled === chunkSize) {
          onChunk(chunk);
          chunk = new Int16Array(chunkSize);
          filled = 0;
        }
      }
    }

    // Loudness (RMS) of this block, scaled so normal speech fills most of the meter.
    onLevel(Math.min(1, Math.sqrt(squares / samples.length) * 6));
  };

  input.connect(worklet);
  worklet.connect(context.destination); // outputs silence; needed so the browser keeps it running

  const label = `${Math.round(context.sampleRate)}hz-ns-${noiseSuppression ? "on" : "off"}`;
  console.info("Nkuzi microphone:", label, stream.getAudioTracks()[0].getSettings());

  function stop() {
    worklet.port.onmessage = null;
    source.disconnect();
    filters.forEach((filter) => filter.disconnect());
    worklet.disconnect();
    stream.getTracks().forEach((track) => track.stop()); // turns off the mic light
    context.close();
    if (filled >= TARGET_RATE * MIN_FINAL_SECONDS) onChunk(chunk.slice(0, filled));
    onLevel(0);
  }

  return { stop, label };
}
