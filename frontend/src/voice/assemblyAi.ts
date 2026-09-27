export type StreamState = 'REQUESTING_TOKEN' | 'LISTENING' | 'TRANSCRIBING' | 'STOPPING' | 'CLOSED' | 'ERROR';
export type StreamHandle = { stop: () => Promise<void> };

function floatToPcm16(input: Float32Array, sourceRate: number): Int16Array {
  const targetRate = 16000;
  const ratio = sourceRate / targetRate;
  const outputLength = Math.floor(input.length / ratio);
  const output = new Int16Array(outputLength);
  for (let i = 0; i < outputLength; i += 1) {
    const start = Math.floor(i * ratio);
    const end = Math.min(input.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = start; j < end; j += 1) sum += input[j] ?? 0;
    const sample = Math.max(-1, Math.min(1, sum / Math.max(1, end - start)));
    output[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
  }
  return output;
}

export async function startAssemblyAIStreaming(
  apiUrl: string,
  onTranscript: (transcript: string) => void,
  onState: (state: StreamState) => void,
  onError: (message: string) => void,
): Promise<StreamHandle> {
  onState('REQUESTING_TOKEN');
  const tokenResponse = await fetch(`${apiUrl}/api/voice/assemblyai/token`, { method: 'POST' });
  const tokenPayload = await tokenResponse.json() as { token?: string; detail?: string };
  if (!tokenResponse.ok || !tokenPayload.token) throw new Error(tokenPayload.detail ?? 'Could not authorize streaming speech.');

  const media = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
  const context = new AudioContext();
  const source = context.createMediaStreamSource(media);
  const processor = context.createScriptProcessor(4096, 1, 1);
  const socket = new WebSocket(`wss://streaming.assemblyai.com/v3/ws?sample_rate=16000&speech_model=u3-rt-pro&format_turns=true&token=${encodeURIComponent(tokenPayload.token)}`);
  let stopped = false;
  const shutdown = async () => {
    if (stopped) return;
    stopped = true;
    onState('STOPPING');
    processor.onaudioprocess = null;
    processor.disconnect(); source.disconnect();
    media.getTracks().forEach((track) => track.stop());
    if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'Terminate' }));
    if (socket.readyState === WebSocket.CONNECTING || socket.readyState === WebSocket.OPEN) socket.close();
    await context.close().catch(() => undefined);
    onState('CLOSED');
  };
  socket.onopen = () => {
    source.connect(processor); processor.connect(context.destination);
    processor.onaudioprocess = (event) => {
      if (socket.readyState !== WebSocket.OPEN || stopped) return;
      const pcm = floatToPcm16(event.inputBuffer.getChannelData(0), context.sampleRate);
      if (pcm.length) socket.send(new Uint8Array(pcm.buffer, pcm.byteOffset, pcm.byteLength).slice().buffer);
    };
    onState('LISTENING');
  };
  socket.onmessage = (event) => {
    try {
      const message = JSON.parse(String(event.data)) as { type?: string; transcript?: string; end_of_turn?: boolean };
      if (message.type === 'Turn' && message.transcript) {
        onState('TRANSCRIBING');
        if (message.end_of_turn) onTranscript(message.transcript.trim());
      }
    } catch { /* Ignore non-JSON service frames. */ }
  };
  socket.onerror = () => { onError('AssemblyAI streaming connection failed.'); void shutdown(); };
  socket.onclose = () => { if (!stopped) { onState('CLOSED'); media.getTracks().forEach((track) => track.stop()); void context.close().catch(() => undefined); } };
  return { stop: shutdown };
}
