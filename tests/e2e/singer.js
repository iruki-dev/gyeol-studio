// Browser-side test double for the microphone: a "virtual singer".
// getUserMedia returns a stream from a separate AudioContext; when the app's recorder is told to start at a frame
// (the AudioWorklet "start" message), the singer plays the next queued take so that the phrase begins
// `__singerLead` seconds after that frame (count-in lead-in + a simulated singer/device latency).
// Everything after the microphone — recorder worklet, trimming, upload, analysis — is the real app.
(() => {
  const S = { ctx: null, dest: null, queue: [], armed: false, lead: 3.11, mainCtx: null, noise: null,
    // echo mode (start check): sing back the tones the app just played, `echoError` cents off, from note_<cents>.wav clips
    echo: false, echoError: 20, tones: [], noteGap: 0.55, noteLen: 0.5 };
  window.__singer = S;
  const md = navigator.mediaDevices;
  if (!md) return;
  md.getUserMedia = async () => {
    if (!S.ctx) {
      S.ctx = new AudioContext();
      S.dest = S.ctx.createMediaStreamDestination();
      // a quiet noise floor, like a real room
      const n = S.ctx.createBuffer(1, S.ctx.sampleRate * 2, S.ctx.sampleRate);
      const d = n.getChannelData(0);
      for (let i = 0; i < d.length; i++) d[i] = (Math.random() * 2 - 1) * 0.0015;
      const src = S.ctx.createBufferSource();
      src.buffer = n; src.loop = true; src.connect(S.dest); src.start();
    }
    await S.ctx.resume();
    return S.dest.stream;
  };
  // remember every stimulus tone the app plays (engine.tone uses a triangle oscillator)
  const oscStart = OscillatorNode.prototype.start;
  OscillatorNode.prototype.start = function (when, ...rest) {
    if (this.type === "triangle") S.tones.push({ hz: this.frequency.value, when: when || 0 });
    return oscStart.call(this, when, ...rest);
  };
  const decode = (url) => fetch(url).then((r) => r.arrayBuffer()).then((b) => S.ctx.decodeAudioData(b));
  function echo(startIn, due) {
    const heard = S.tones.splice(0);
    const files = heard.length
      ? heard.map((t) => { const c = 1200 * Math.log2(t.hz / 440) + S.echoError; return `/__test_audio/note_${Math.round(c / 25) * 25}.wav`; })
      : S.queue.splice(0, 1);
    Promise.all(files.map(decode)).then((bufs) => {
      const base = S.ctx.currentTime + Math.max(0, (due - performance.now()) / 1000);
      bufs.forEach((buf, k) => {
        const src = S.ctx.createBufferSource();
        src.buffer = buf;
        src.connect(S.dest);
        const t = base + (heard.length ? 0.25 + k * S.noteGap : 0);
        src.start(t);
        if (heard.length > 1) src.stop(t + S.noteLen);
      });
      S.lastStarted = { files, startIn };
    });
  }
  const OrigNode = window.AudioWorkletNode;
  window.AudioWorkletNode = function (context, name, opts) {
    const node = new OrigNode(context, name, opts);
    S.mainCtx = context;
    const post = node.port.postMessage.bind(node.port);
    node.port.postMessage = (msg, ...rest) => {
      if (msg && msg.cmd === "start" && S.echo) {
        const startIn = msg.frame / context.sampleRate - context.currentTime;
        echo(startIn, performance.now() + startIn * 1000);
      } else if (msg && msg.cmd === "start" && S.armed && S.queue.length) {
        S.armed = false;
        const url = S.queue.shift();
        const startIn = msg.frame / context.sampleRate - context.currentTime;
        const due = performance.now() + (startIn + S.lead) * 1000; // wall-clock time the phrase should start
        fetch(url).then((r) => r.arrayBuffer()).then((b) => S.ctx.decodeAudioData(b)).then((buf) => {
          const src = S.ctx.createBufferSource();
          src.buffer = buf;
          src.connect(S.dest);
          src.start(S.ctx.currentTime + Math.max(0, (due - performance.now()) / 1000));
          S.lastStarted = { url, startIn };
        });
      }
      return post(msg, ...rest);
    };
    return node;
  };
  window.AudioWorkletNode.prototype = OrigNode.prototype;
})();
