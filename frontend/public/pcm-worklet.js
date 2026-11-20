class PcmCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.phase = 0;
    this.samples = new Int16Array(320);
    this.length = 0;
    this.sampleSum = 0;
    this.sampleCount = 0;
    this.energy = 0;
  }

  process(inputs) {
    const channel = inputs[0]?.[0];
    if (!channel) return true;

    for (const sample of channel) {
      this.sampleSum += sample;
      this.sampleCount += 1;
      this.phase += 16000;
      if (this.phase < sampleRate) continue;
      this.phase -= sampleRate;
      const value = Math.max(-1, Math.min(1, this.sampleSum / this.sampleCount));
      this.sampleSum = 0;
      this.sampleCount = 0;
      this.energy += value * value;
      this.samples[this.length++] = value < 0 ? value * 32768 : value * 32767;
      if (this.length === this.samples.length) {
        this.port.postMessage({
          pcm: this.samples.buffer,
          rms: Math.sqrt(this.energy / this.samples.length),
        }, [this.samples.buffer]);
        this.samples = new Int16Array(320);
        this.length = 0;
        this.energy = 0;
      }
    }
    return true;
  }
}

registerProcessor("pcm-capture", PcmCapture);
