export type GeminiVoiceState = 'REQUESTING_TOKEN' | 'REQUESTING_MICROPHONE' | 'CONNECTING' | 'LISTENING' | 'TRANSCRIBING' | 'STOPPING' | 'CLOSED' | 'ERROR';
export type GeminiVoiceHandle = { stop: () => Promise<void> };

function floatToPcm16(input: Float32Array, sourceRate: number): Int16Array {
  const ratio = sourceRate / 16000;
  const output = new Int16Array(Math.floor(input.length / ratio));
  for (let i = 0; i < output.length; i += 1) {
    const start = Math.floor(i * ratio);
    const end = Math.min(input.length, Math.floor((i + 1) * ratio));
    let total = 0;
    for (let j = start; j < end; j += 1) total += input[j] ?? 0;
    const sample = Math.max(-1, Math.min(1, total / Math.max(1, end - start)));
    output[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
  }
  return output;
}

function toBase64(pcm: Int16Array): string {
  const bytes = new Uint8Array(pcm.buffer, pcm.byteOffset, pcm.byteLength);
  let binary = '';
  const chunk = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunk) {
    binary += String.fromCharCode(...bytes.subarray(offset, Math.min(bytes.length, offset + chunk)));
  }
  return btoa(binary);
}

export async function startGeminiLiveVoice(
  apiUrl: string,
  onTranscript: (text: string, interim: boolean) => void,
  onState: (state: GeminiVoiceState) => void,
  onError: (message: string) => void,
): Promise<GeminiVoiceHandle> {
  onState('REQUESTING_TOKEN');
  const tokenResponse = await fetch(`${apiUrl}/api/voice/gemini/token`, { method: 'POST' });
  const tokenPayload = await tokenResponse.json() as { token?: string; model?: string; detail?: string };
  if (!tokenResponse.ok || !tokenPayload.token || !tokenPayload.model) throw new Error(tokenPayload.detail ?? 'Gemini voice token could not be issued.');

  onState('REQUESTING_MICROPHONE');
  const media = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
  const context = new AudioContext();
  const source = context.createMediaStreamSource(media);
  const processor = context.createScriptProcessor(2048, 1, 1);
  const socketUrl = `wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContentConstrained?access_token=${encodeURIComponent(tokenPayload.token)}`;
  const socket = new WebSocket(socketUrl);
  let stopped = false;
  let connected = false;
  let closeContext = false;
  let readyTimer: number | undefined;
  const shutdown = async () => {
    if (stopped) return;
    stopped = true;
    onState('STOPPING');
    window.clearTimeout(readyTimer);
    processor.onaudioprocess = null;
    processor.disconnect(); source.disconnect();
    media.getTracks().forEach((track) => track.stop());
    if (socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ realtimeInput: { audioStreamEnd: true } }));
      socket.close(1000, 'Operator stopped voice capture');
    } else if (socket.readyState === WebSocket.CONNECTING) socket.close();
    if (closeContext) await context.close().catch(() => undefined);
    onState('CLOSED');
  };
  const connectMic = () => {
    if (connected || stopped) return;
    connected = true;
    source.connect(processor); processor.connect(context.destination);
    processor.onaudioprocess = (event) => {
      if (socket.readyState !== WebSocket.OPEN || stopped) return;
      const pcm = floatToPcm16(event.inputBuffer.getChannelData(0), context.sampleRate);
      if (!pcm.length) return;
      socket.send(JSON.stringify({ realtimeInput: { audio: { data: toBase64(pcm), mimeType: 'audio/pcm;rate=16000' } } }));
    };
    onState('LISTENING');
  };
  socket.onopen = () => {
    onState('CONNECTING');
    socket.send(JSON.stringify({ setup: { model: `models/${tokenPayload.model}`, generationConfig: { responseModalities: ['TEXT'] }, inputAudioTranscription: { languageCodes: [], customVocabulary: ['KAVACH', 'Silk Board', 'Koramangala', 'Bengaluru', 'ambulance', 'replan'] } } }));
    readyTimer = window.setTimeout(() => { if (!connected && !stopped) { onError('Gemini Live did not confirm setup in time.'); void shutdown(); } }, 12000);
  };
  socket.onmessage = (event) => {
    try {
      const message = JSON.parse(String(event.data)) as { setupComplete?: unknown; error?: { message?: string }; serverContent?: { interimInputTranscription?: { text?: string }; inputTranscription?: { text?: string } } };
      if (message.error) { onError(message.error.message ?? 'Gemini Live rejected the voice session.'); void shutdown(); return; }
      if (message.setupComplete !== undefined) { window.clearTimeout(readyTimer); connectMic(); return; }
      const content = message.serverContent;
      if (content?.interimInputTranscription?.text) { onState('TRANSCRIBING'); onTranscript(content.interimInputTranscription.text, true); }
      if (content?.inputTranscription?.text?.trim()) { onState('TRANSCRIBING'); onTranscript(content.inputTranscription.text.trim(), false); }
    } catch { /* Ignore malformed or non-JSON frames. */ }
  };
  socket.onerror = () => { if (!stopped) onError('Gemini Live voice connection failed.'); };
  socket.onclose = () => {
    if (!stopped) {
      stopped = true; processor.onaudioprocess = null; processor.disconnect(); source.disconnect();
      media.getTracks().forEach((track) => track.stop());
      closeContext = true; void context.close().catch(() => undefined); onState('CLOSED');
    }
  };
  return { stop: shutdown };
}
