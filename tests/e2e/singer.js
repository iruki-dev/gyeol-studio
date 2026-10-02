// Browser-side test double for the microphone: a "virtual singer".
// getUserMedia returns a stream from a separate AudioContext; when the app's recorder is told to start at a frame
// (the AudioWorklet "start" message), the singer plays the next queued take so that the phrase begins
// `__singerLead` seconds after that frame (count-in lead-in + a simulated singer/device latency).
// Everything after the microphone — recorder worklet, trimming, upload, analysis — is the real app.
(() => {
  const S = { ctx: null, dest: null, queue: [], armed: false, lead: 3.11, mainCtx: null, noise: null };
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
  const OrigNode = window.AudioWorkletNode;
  window.AudioWorkletNode = function (context, name, opts) {
    const node = new OrigNode(context, name, opts);
    S.mainCtx = context;
    const post = node.port.postMessage.bind(node.port);
    node.port.postMessage = (msg, ...rest) => {
      if (msg && msg.cmd === "start" && S.armed && S.queue.length) {
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
