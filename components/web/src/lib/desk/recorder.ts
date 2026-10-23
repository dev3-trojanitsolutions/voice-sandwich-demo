// Records the microphone and converts the take to the WAV format the voice
// service clones from: 16-bit mono at 24 kHz.

export const SAMPLE_RATE = 24000;

export interface Recording {
  stop: () => Promise<Blob>;
  cancel: () => void;
}

export async function startRecording(): Promise<Recording> {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
  });
  const recorder = new MediaRecorder(stream);
  const parts: Blob[] = [];
  recorder.ondataavailable = (event) => parts.push(event.data);
  recorder.start();

  const release = () => stream.getTracks().forEach((track) => track.stop());

  return {
    stop: () =>
      new Promise((resolve, reject) => {
        recorder.onstop = () => {
          release();
          toWav(new Blob(parts, { type: recorder.mimeType })).then(resolve, reject);
        };
        recorder.stop();
      }),
    cancel: () => {
      recorder.onstop = release;
      recorder.stop();
    },
  };
}

/** Any audio file the browser can play, as 16-bit mono WAV at 24 kHz. */
export async function toWav(audio: Blob): Promise<Blob> {
  const context = new AudioContext();
  let decoded: AudioBuffer;
  try {
    decoded = await context.decodeAudioData(await audio.arrayBuffer());
  } finally {
    context.close();
  }
  const length = Math.ceil(decoded.duration * SAMPLE_RATE);
  const offline = new OfflineAudioContext(1, length, SAMPLE_RATE);
  const source = offline.createBufferSource();
  source.buffer = decoded;
  source.connect(offline.destination);
  source.start();
  const samples = (await offline.startRendering()).getChannelData(0);

  const view = new DataView(new ArrayBuffer(44 + samples.length * 2));
  const text = (offset: number, value: string) =>
    [...value].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)));
  text(0, 'RIFF');
  view.setUint32(4, 36 + samples.length * 2, true);
  text(8, 'WAVE');
  text(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, SAMPLE_RATE, true);
  view.setUint32(28, SAMPLE_RATE * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  text(36, 'data');
  view.setUint32(40, samples.length * 2, true);
  samples.forEach((sample, i) => {
    const s = Math.max(-1, Math.min(1, sample));
    view.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  });
  return new Blob([view], { type: 'audio/wav' });
}

export function wavSeconds(wav: Blob): number {
  return (wav.size - 44) / (SAMPLE_RATE * 2);
}
