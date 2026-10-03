// Runs on the browser's audio thread. It receives the microphone signal in
// tiny blocks (128 samples) and passes it on to the page in bigger blocks,
// so the page isn't flooded with hundreds of messages per second.
class PcmProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.block = new Float32Array(2048);
    this.filled = 0;
  }

  process(inputs) {
    const channel = inputs[0][0]; // first input, first (mono) channel
    if (channel) {
      for (let i = 0; i < channel.length; i++) {
        this.block[this.filled++] = channel[i];
        if (this.filled === this.block.length) {
          this.port.postMessage(this.block.slice(0));
          this.filled = 0;
        }
      }
    }
    return true; // keep the processor alive
  }
}

registerProcessor("pcm-processor", PcmProcessor);
