// AudioWorklet: microphone level meter + sample-accurate recording that starts at a given context frame.
class Recorder extends AudioWorkletProcessor {
  constructor() {
    super();
    this.armed = false;
    this.startFrame = 0;
    this.stopFrame = Infinity;
    this.buf = [];
    this.bufLen = 0;
    this.firstFrame = null;
    this.blocks = 0;
    this.peak = 0;
    this.sum = 0;
    this.n = 0;
    this.port.onmessage = (e) => {
      const m = e.data;
      if (m.cmd === "start") {
        this.armed = true;
        this.startFrame = m.frame;
        this.stopFrame = m.stopFrame || Infinity;
        this.firstFrame = null;
        this.buf = [];
        this.bufLen = 0;
      } else if (m.cmd === "stop") {
        this.finish();
      }
    };
  }

  flush(final) {
    if (this.bufLen === 0 && !final) return;
    const out = new Float32Array(this.bufLen);
    let o = 0;
    for (const c of this.buf) { out.set(c, o); o += c.length; }
    this.buf = [];
    this.bufLen = 0;
    this.port.postMessage({ type: "chunk", samples: out, final: !!final, firstFrame: this.firstFrame }, [out.buffer]);
  }

  finish() {
    if (!this.armed) return;
    this.armed = false;
    this.flush(true);
  }

  process(inputs, outputs) {
    const input = inputs[0];
    const ch = input && input[0];
    if (!ch) return true;
    // level meter (~every 50 ms)
    for (let i = 0; i < ch.length; i++) { const v = ch[i]; const a = v < 0 ? -v : v; if (a > this.peak) this.peak = a; this.sum += v * v; }
    this.n += ch.length;
    if (++this.blocks % 18 === 0) {
      this.port.postMessage({ type: "level", rms: Math.sqrt(this.sum / Math.max(1, this.n)), peak: this.peak });
      this.peak = 0; this.sum = 0; this.n = 0;
    }
    if (this.armed) {
      const f0 = currentFrame;
      const f1 = f0 + ch.length;
      if (f1 > this.startFrame) {
        const a = Math.max(0, this.startFrame - f0);
        const b = Math.min(ch.length, Math.max(a, this.stopFrame - f0));
        if (b > a) {
          if (this.firstFrame === null) this.firstFrame = f0 + a;
          this.buf.push(ch.slice(a, b));
          this.bufLen += b - a;
        }
        if (this.bufLen >= sampleRate / 4) this.flush(false);
        if (f1 >= this.stopFrame) this.finish();
      }
    }
    return true;
  }
}

registerProcessor("gyeol-recorder", Recorder);
