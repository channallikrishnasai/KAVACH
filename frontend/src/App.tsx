import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import MapView from './components/MapView';
import LegacyApp from './LegacyApp';
import { API_URL, EMERGENCY_INFRA, VIEW_STATE_3D } from './constants';
import type { EmergencyFacility, RouteSegment, ViewState } from './types';
import { createWorker } from 'tesseract.js';
import { startAssemblyAIStreaming } from './voice/assemblyAi';
import { startGeminiLiveVoice, type GeminiVoiceHandle } from './voice/geminiLive';
import './kavach.css';

type Agent = { id: string; name: string; responsibility: string; tools: string[]; status: string; confidence: number | null; summary: string };
type AgentOutput = { agent: string; findings: string[]; evidence: string[]; evidence_records?: { tool: string; source: string; timestamp: string; freshness: string; confidence: number; result: string }[]; recommendations: string[]; confidence: number; status: string; trace_id?: string; durationMs?: number };
type Incident = {
  incident_id: string; incident_type: string; severity: string; description: string; location_name: string;
  lat: number; lon: number; location_source?: string; status: string; data_state: string; transitions: { from: string | null; to: string; at: string; reason: string }[];
  agent_outputs: AgentOutput[]; route?: { status: string; provider: string; distance_km?: number | null; coordinates?: number[][]; nodes?: (string | number)[] } | null;
  simulation?: { selected_eta_minutes_estimate?: number | null; risk?: string; data_state?: string };
  recommended_hospital?: { name: string; beds_available: number } | null;
  local_notification_draft?: { status: string; sent: boolean; message: string };
  communication_result?: { provider: string; status: string; externalDelivery: boolean }; source?: string; source_id?: string; camera_evidence_id?: string;
  gemini_analysis?: { status: string; mode: string; provider: string; model: string; classification?: string; summary?: string; hazards_to_check?: string[]; data_uncertainties?: string[]; reason?: string };
  verification?: { passed: boolean; checks: string[] };
};
type CityState = { city: string; data_state: string; incidents: Incident[]; road_blocks: { block_id: string; node_id?: number | null; active: boolean; lon?: number; lat?: number }[]; resources: { id: string; type: string; name: string; status: string }[]; hospitals: { id: string; name: string; beds_available: number; status: string }[]; road_hazards?: RoadAnalysis[]; active_incidents: number; critical_events: number; agent_count: number; audit_count: number; camera_count?: number; online_camera_count?: number; pending_approvals?: number };
type AuditEvent = { id: string; timestamp: string; type: string; summary: string; data_state: string; incident_id?: string };
type RoadAnalysis = { analysis_id: string; status: string; media_type: string; frames_analyzed: number; cue_count: number; provider?: string; model_mode?: string; model_error?: string | null; classification?: string | null; severity?: string | null; severity_reason?: string | null; detections?: { damageType: string; confidence: number; boundingBox: number[]; severity: string; reason: string; frameIndex: number }[]; surface_cues: { bbox_px: number[]; brightness_delta: number; interpretation: string; frame_index: number }[]; ocr_text: string; ocr?: { text: string; confidence: number | null; provider: string | null; mode: string }; gps: { lat: number; lon: number } | null; location_status: string; disclaimer: string };
type VoiceCommand = { transcript: string; command: string; intent: string; legacyIntent?: string; intentCode?: string; incident_type: string | null; location: { name: string; text?: string; lat: number | null; lon: number | null; lng?: number | null; locationSource: string; confirmed: boolean } | null; priority: string | null; severity?: string; confidence: number; parser: string; requiresApproval: boolean; confirmationRequired: boolean };
type ProviderHealth = { name: string; type: string; status: string; mode: string; source: string; lastUpdated: string | null; freshness: string; requiresAuth: boolean; configured: boolean; error: string | null; capabilities: string[] };
type CommunicationDraft = { id: string; incident_id: string; department: string; recipient: string | null; subject: string; body: string; status: string; created_at: string; provider: string; mode: string; reason: string; smtp_result?: { status: string; acceptedBySmtp?: boolean; deliveryVerified?: boolean } | null };
type Camera = { camera_id: string; name: string; location_name: string; lat: number; lon: number; status: string; vision_status: string };
type View = 'command' | 'legacy';

function speakResponse(text: string) {
  if (!('speechSynthesis' in window) || !('SpeechSynthesisUtterance' in window)) return;
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
}

const EMPTY_CITY: CityState = { city: 'Bengaluru · KC Valley map extent', data_state: 'SIMULATED', incidents: [], road_blocks: [], resources: [], hospitals: [], active_incidents: 0, critical_events: 0, agent_count: 10, audit_count: 0 };
const INITIAL_VIEW: ViewState = { ...VIEW_STATE_3D, longitude: 77.645, latitude: 12.935, zoom: 14.7, pitch: 58, bearing: -22 };

export default function App() {
  const [view, setView] = useState<View>('command');
  const [city, setCity] = useState<CityState>(EMPTY_CITY);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [audit, setAudit] = useState<AuditEvent[]>([]);
  const [activeIncidentId, setActiveIncidentId] = useState('');
  const [viewState, setViewState] = useState<ViewState>(INITIAL_VIEW);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [assistantResponse, setAssistantResponse] = useState('');
  const [voiceState, setVoiceState] = useState('Voice ready');
  const [eventStreamState, setEventStreamState] = useState('EVENT STREAM CONNECTING');
  const [assemblyAIReady, setAssemblyAIReady] = useState(false);
  const [geminiReady, setGeminiReady] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [voiceTranscript, setVoiceTranscript] = useState('');
  const [selectedAgent, setSelectedAgent] = useState('');
  const [commandText, setCommandText] = useState('');
  const auditCursor = useRef(0);
  const eventRefreshTimer = useRef<number | null>(null);
  const [providers, setProviders] = useState<{ stgcn?: { status: string }; prediction?: { provider: string; data_state: string }; city?: { data_state: string }; weather?: { freshness: string; source: string; retrievedAt: string }; providerHealth?: ProviderHealth[] }>({});
  const [roadFile, setRoadFile] = useState<File | null>(null);
  const [roadAnalysis, setRoadAnalysis] = useState<RoadAnalysis | null>(null);
  const [roadBusy, setRoadBusy] = useState(false);
  const [selectedCoords, setSelectedCoords] = useState<[number, number] | null>(null);
  const [communicationDrafts, setCommunicationDrafts] = useState<CommunicationDraft[]>([]);
  const [emailProvider, setEmailProvider] = useState<{ status: string; reason?: string }>({ status: 'NOT_CONFIGURED' });
  const [reviewDraft, setReviewDraft] = useState<CommunicationDraft | null>(null);
  const [reportOpen, setReportOpen] = useState(false);
  const [reportType, setReportType] = useState('collision');
  const [reportSeverity, setReportSeverity] = useState('critical');
  const [reportLocation, setReportLocation] = useState('Silk Board');
  const [reportDescription, setReportDescription] = useState('Multi-vehicle collision with possible injuries.');
  const [cameraOpen, setCameraOpen] = useState(false);
  const [cameraStream, setCameraStream] = useState<MediaStream | null>(null);
  const [camera, setCamera] = useState<Camera | null>(null);
  const [cameraIncidentType, setCameraIncidentType] = useState('collision');
  const [cameraDescription, setCameraDescription] = useState('Operator confirmed a possible traffic incident from the live camera image.');
  const [cameraBusy, setCameraBusy] = useState(false);
  const [cameraEvidence, setCameraEvidence] = useState<{ image_data: string; captured_at: string; camera_id: string; sha256: string } | null>(null);
  const cameraVideo = useRef<HTMLVideoElement | null>(null);
  const geminiVoice = useRef<GeminiVoiceHandle | null>(null);
  const recognition = useRef<{ start: () => void; stop: () => void; lang: string; interimResults: boolean; onresult: ((event: { results: { [index: number]: { transcript: string } }[] }) => void) | null; onerror: (() => void) | null; onend: (() => void) | null } | null>(null);
  const stopStreamingVoice = useRef<(() => Promise<void>) | null>(null);
  const activeIncident = city.incidents.find((item) => item.incident_id === activeIncidentId) ?? city.incidents[0];

  useEffect(() => {
    let cancelled = false;
    const evidenceId = activeIncident?.camera_evidence_id;
    if (!evidenceId) return;
    void fetch(`${API_URL}/api/cameras/evidence/${evidenceId}`).then(async (response) => {
      if (!response.ok) return null;
      return await response.json() as { image_data: string; captured_at: string; camera_id: string; sha256: string };
    }).then((evidence) => { if (!cancelled) setCameraEvidence(evidence); }).catch(() => { if (!cancelled) setCameraEvidence(null); });
    return () => { cancelled = true; };
  }, [activeIncident?.camera_evidence_id]);

  const refresh = useCallback(async () => {
    const [cityResponse, agentsResponse, auditResponse, providersResponse, voiceProvidersResponse, commResponse] = await Promise.all([
      fetch(`${API_URL}/api/city/state`), fetch(`${API_URL}/api/agents/status`), fetch(`${API_URL}/api/audit`), fetch(`${API_URL}/api/providers/status`), fetch(`${API_URL}/api/voice/providers`), fetch(`${API_URL}/api/communications`),
    ]);
    if (!cityResponse.ok || !agentsResponse.ok || !auditResponse.ok) throw new Error('KAVACH service did not return a successful response. Start the backend and check its health endpoint.');
    const nextCity = await cityResponse.json() as CityState;
    const nextAgents = await agentsResponse.json() as { agents: Agent[] };
    const nextAudit = await auditResponse.json() as AuditEvent[];
    setCity(nextCity); setAgents(nextAgents.agents); setAudit(nextAudit);
    auditCursor.current = Math.max(auditCursor.current, ...nextAudit.map((event) => Number((event as AuditEvent & { sequence?: number }).sequence ?? 0)), 0);
    if (providersResponse.ok) setProviders(await providersResponse.json());
    if (voiceProvidersResponse.ok) { const data = await voiceProvidersResponse.json() as { selected: string }; setGeminiReady(data.selected === 'GEMINI'); setAssemblyAIReady(data.selected === 'ASSEMBLYAI'); }
    if (commResponse.ok) { const data = await commResponse.json() as { drafts: CommunicationDraft[]; provider: { status: string; reason?: string } }; setCommunicationDrafts(data.drafts); setEmailProvider(data.provider); }
    if (!activeIncidentId && nextCity.incidents[0]) setActiveIncidentId(nextCity.incidents[0].incident_id);
  }, [activeIncidentId]);

  useEffect(() => {
    if (cameraVideo.current && cameraStream) cameraVideo.current.srcObject = cameraStream;
  }, [cameraStream, cameraOpen]);

  useEffect(() => () => { cameraStream?.getTracks().forEach((track) => track.stop()); }, [cameraStream]);

  useEffect(() => {
    let source: EventSource | null = null;
    source = new EventSource(`${API_URL}/api/events/stream?after=${auditCursor.current}`);
    source.onopen = () => {
      setEventStreamState('EVENT STREAM LIVE');
      void refresh().then(() => setError('')).catch((e: unknown) => setError(e instanceof Error ? e.message : 'Backend unavailable'));
    };
    source.onerror = () => setEventStreamState('EVENT STREAM RECONNECTING');
    source.addEventListener('kavach', () => {
      if (eventRefreshTimer.current !== null) return;
      eventRefreshTimer.current = window.setTimeout(() => {
        eventRefreshTimer.current = null;
        void refresh().catch(() => setEventStreamState('EVENT STREAM DEGRADED'));
      }, 120);
    });
    return () => { source?.close(); recognition.current?.stop(); if (eventRefreshTimer.current !== null) window.clearTimeout(eventRefreshTimer.current); eventRefreshTimer.current = null; };
  }, [refresh]);

  const request = useCallback(async <T,>(path: string, body?: unknown, method = 'POST'): Promise<T> => {
    setBusy(true); setError('');
    try {
      const response = await fetch(`${API_URL}${path}`, { method, ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }) });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`);
      await refresh();
      return data as T;
    } catch (e) {
      const message = e instanceof Error ? e.message : 'KAVACH request failed'; setError(message); throw e;
    } finally { setBusy(false); }
  }, [refresh]);

  const runDemo = useCallback(async (command?: VoiceCommand) => {
    try {
      const location = command?.location;
      if (command?.confirmationRequired || (location && (location.lat === null || location.lon === null))) {
        const message = `I could not safely resolve ${location?.name ?? 'that location'} to a known map area. Choose a location on the map before creating an incident.`;
        setAssistantResponse(message); speakResponse(message); return;
      }
      const incident = await request<Incident>('/api/kavach/incidents', { incident_type: command?.incident_type ?? 'collision', severity: command?.priority ?? 'critical', description: command?.transcript ?? 'Two-vehicle collision with a blocked lane. Deterministic demo scenario.', location_name: location ? `${location.name}, Bengaluru` : 'Koramangala, Bengaluru', lat: location?.lat ?? 12.935, lon: location?.lon ?? 77.62, location_source: location?.locationSource ?? 'SIMULATED' });
      setActiveIncidentId(incident.incident_id);
      await request('/api/agents/run', { incident_id: incident.incident_id });
      setViewState((current) => ({ ...current, latitude: incident.lat, longitude: incident.lon, zoom: 15.5, pitch: 62, transitionDuration: 1000 }));
      const message = `Incident near ${incident.location_name} investigated. The response plan is ready and requires operator approval.`;
      setAssistantResponse(message); speakResponse(message);
    } catch { /* request has set a visible error */ }
  }, [request]);

  const activateReportedIncident = useCallback(async () => {
    const knownLocations: Record<string, [number, number]> = { 'Silk Board': [12.917, 77.623], Koramangala: [12.935, 77.62], 'HSR Layout': [12.918, 77.644], Bellandur: [12.925, 77.668] };
    const location = reportLocation === 'Map selection' ? selectedCoords : knownLocations[reportLocation];
    if (!location) { setError('Select a known demo location or click the map to confirm coordinates.'); return; }
    try {
      const incident = await request<Incident>('/api/kavach/incidents', { incident_type: reportType, severity: reportSeverity, description: reportDescription, location_name: `${reportLocation === 'Map selection' ? 'Operator selected map location' : reportLocation}, Bengaluru`, lat: location[1], lon: location[0], location_source: reportLocation === 'Map selection' ? 'USER_SELECTED' : 'SIMULATED_STATIC_PLACE_MATCH' });
      setActiveIncidentId(incident.incident_id); setReportOpen(false);
      await request('/api/agents/run', { incident_id: incident.incident_id });
      setViewState((current) => ({ ...current, latitude: incident.lat, longitude: incident.lon, zoom: 15.5, pitch: 62, transitionDuration: 900 }));
      setAssistantResponse(`KAVACH investigated the ${reportType.replace('_', ' ')} report. The response plan and communications drafts are ready for review.`);
    } catch { /* request sets a visible error */ }
  }, [reportDescription, reportLocation, reportSeverity, reportType, request, selectedCoords]);

  const openCameraCenter = async () => {
    setError(''); setCameraBusy(true);
    let stream: MediaStream | null = null;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment', width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false });
      const known: Record<string, [number, number]> = { 'Silk Board': [12.917, 77.623], Koramangala: [12.935, 77.62], 'HSR Layout': [12.918, 77.644], Bellandur: [12.925, 77.668] };
      const location = known[reportLocation] ?? known['Silk Board'];
      const payload = { camera_id: 'CAM-KAVACH-LOCAL-01', name: 'KAVACH Local Webcam', location_name: `${reportLocation}, Bengaluru`, lat: location[1], lon: location[0] };
      const register = await fetch(`${API_URL}/api/cameras`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      if (!register.ok && register.status !== 409) throw new Error('Could not register local camera');
      const start = await fetch(`${API_URL}/api/cameras/${payload.camera_id}/start`, { method: 'POST' });
      if (!start.ok) throw new Error('Could not start local camera');
      const registeredCamera = await start.json() as Camera;
      setCamera(registeredCamera); setCameraStream(stream); setCameraOpen(true); await refresh();
    } catch (e) {
      stream?.getTracks().forEach((track) => track.stop());
      setError(e instanceof Error ? `${e.message}. Allow camera access or use Report Incident.` : 'Camera could not start.');
    } finally { setCameraBusy(false); }
  };

  const stopCameraCenter = async () => {
    cameraStream?.getTracks().forEach((track) => track.stop()); setCameraStream(null);
    if (camera) await fetch(`${API_URL}/api/cameras/${camera.camera_id}/stop`, { method: 'POST' }).catch(() => undefined);
    setCameraOpen(false); await refresh().catch(() => undefined);
  };

  const confirmCameraObservation = async () => {
    if (!camera || !cameraVideo.current || !cameraStream) return;
    setCameraBusy(true); setError('');
    try {
      const video = cameraVideo.current; const scale = Math.min(1, 640 / Math.max(video.videoWidth, 1));
      const canvas = document.createElement('canvas'); canvas.width = Math.max(1, Math.round(video.videoWidth * scale)); canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
      canvas.getContext('2d')?.drawImage(video, 0, 0, canvas.width, canvas.height);
      const frame = await new Promise<Blob>((resolve, reject) => canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error('Could not capture a webcam frame')), 'image/jpeg', 0.72));
      const form = new FormData(); form.append('file', frame, 'camera-evidence.jpg'); form.append('incident_type', cameraIncidentType); form.append('severity', cameraIncidentType === 'collision' ? 'critical' : 'high'); form.append('description', cameraDescription); form.append('detection_type', 'OPERATOR_CONFIRMED_CAMERA_REPORT');
      const response = await fetch(`${API_URL}/api/cameras/${camera.camera_id}/observations/confirm`, { method: 'POST', body: form });
      const result = await response.json() as { incident?: Incident; detail?: string };
      if (!response.ok || !result.incident) throw new Error(result.detail ?? `Camera report failed (${response.status})`);
      setActiveIncidentId(result.incident.incident_id); setCameraOpen(false);
      cameraStream.getTracks().forEach((track) => track.stop()); setCameraStream(null);
      await refresh(); setViewState((current) => ({ ...current, latitude: result.incident!.lat, longitude: result.incident!.lon, zoom: 15.5, pitch: 62, transitionDuration: 900 }));
      setAssistantResponse('Camera evidence was captured and operator-confirmed. KAVACH automatically started its investigation; no AI vision model is configured.');
    } catch (e) { setError(e instanceof Error ? e.message : 'Camera report failed.'); }
    finally { setCameraBusy(false); }
  };

  const approveEmailDraft = async (draft: CommunicationDraft) => {
    if (!window.confirm(`Approve this external email to ${draft.recipient ?? 'an unconfigured recipient'}?`)) return;
    try {
      let latest = await request<CommunicationDraft>(`/api/communications/${draft.id}/approve`, { actor: 'demo_commander', role: 'COMMANDER' });
      if (emailProvider.status === 'READY') latest = await request<CommunicationDraft>(`/api/communications/${draft.id}/send`, { actor: 'demo_commander', role: 'COMMANDER' });
      setReviewDraft(latest);
    } catch { /* visible error */ }
  };

  const sendApprovedEmail = async (draft: CommunicationDraft) => {
    if (!window.confirm(`Send the approved email to ${draft.recipient}? The SMTP server may accept the message; recipient delivery is not verified.`)) return;
    try { const sent = await request<CommunicationDraft>(`/api/communications/${draft.id}/send`, { actor: 'demo_commander', role: 'COMMANDER' }); setReviewDraft(sent); }
    catch { /* visible error */ }
  };

  const simulateEmailDraft = async (draft: CommunicationDraft) => {
    if (!window.confirm('Record this approved email as a demo action? No message will be sent.')) return;
    try { await request(`/api/communications/${draft.id}/simulate-send`, { actor: 'demo_commander', role: 'COMMANDER' }); setReviewDraft(null); }
    catch { /* visible error */ }
  };

  const saveEmailDraft = async () => {
    if (!reviewDraft) return;
    try { const updated = await request<CommunicationDraft>(`/api/communications/${reviewDraft.id}`, { subject: reviewDraft.subject, body: reviewDraft.body, actor: 'demo_commander', role: 'COMMANDER' }, 'PUT'); setReviewDraft(updated); }
    catch { /* visible error */ }
  };

  const runAgents = useCallback(async () => { if (activeIncident) try { await request('/api/agents/run', { incident_id: activeIncident.incident_id }); speakResponse('Investigation complete. The response plan requires operator authorization.'); } catch { /* visible error */ } }, [activeIncident, request]);
  const approve = useCallback(async () => { if (activeIncident) try { await request(`/api/commands/${activeIncident.incident_id}/approve`, { actor: 'local_operator', role: 'OPERATOR' }); speakResponse('Approval recorded. The local response can now be executed by a commander.'); } catch { /* visible error */ } }, [activeIncident, request]);
  const execute = useCallback(async () => { if (activeIncident) try { const result = await request<{ incident: Incident }>(`/api/commands/${activeIncident.incident_id}/execute`, { actor: 'local_commander', role: 'COMMANDER' }); speakResponse(result.incident.verification?.passed ? 'Local response executed and verified.' : 'Local response verification failed. Operator review is required.'); } catch { /* visible error */ } }, [activeIncident, request]);
  const sendNotice = useCallback(async () => { if (activeIncident) try { const result = await request<{ provider: string; status: string; externalDelivery: boolean }>('/api/communications/send', { incident_id: activeIncident.incident_id, actor: 'local_commander', role: 'COMMANDER' }); const message = result.externalDelivery ? 'The approved notice was delivered to the configured webhook.' : 'The approved notice was recorded locally. No external delivery occurred.'; setAssistantResponse(message); speakResponse(message); } catch { /* visible error */ } }, [activeIncident, request]);
  const injectRoadBlock = useCallback(async () => { try { const result = await request<{ incident?: Incident; route_change?: { previous_distance_km?: number; new_distance_km?: number; path_changed?: boolean; failure_verified?: boolean } }>('/api/simulation/inject', { event: 'road_block', actor: 'local_operator', role: 'OPERATOR' }); if (result.incident) setActiveIncidentId(result.incident.incident_id); if (result.route_change) { const change = result.route_change; const message = `Closure verified against the previous path: ${change.failure_verified ? 'yes' : 'no'}. New route ${change.new_distance_km ?? 'unavailable'} km; path changed: ${change.path_changed ? 'yes' : 'no'}. The revised plan requires approval.`; setAssistantResponse(message); speakResponse(message); } } catch { /* visible error */ } }, [request]);
  const reset = useCallback(async () => { try { await request('/api/simulation/reset', { actor: 'local_commander', role: 'COMMANDER' }); setActiveIncidentId(''); setSelectedAgent(''); setAssistantResponse(''); } catch { /* visible error */ } }, [request]);

  const analyzeRoadMedia = useCallback(async () => {
    if (!roadFile) return;
    setRoadBusy(true); setError('');
    let worker: Awaited<ReturnType<typeof createWorker>> | null = null;
    try {
      worker = await createWorker('eng');
      let ocrTarget: File | Blob = roadFile;
      if (roadFile.type.startsWith('video/')) {
        const video = document.createElement('video'); video.muted = true; video.preload = 'metadata';
        const url = URL.createObjectURL(roadFile); video.src = url;
        await new Promise<void>((resolve, reject) => { video.onloadeddata = () => resolve(); video.onerror = () => reject(new Error('Could not read a frame from this video')); });
        video.currentTime = Math.min(1, Math.max(0, video.duration / 2));
        await new Promise<void>((resolve) => { video.onseeked = () => resolve(); });
        const canvas = document.createElement('canvas'); canvas.width = video.videoWidth; canvas.height = video.videoHeight;
        canvas.getContext('2d')?.drawImage(video, 0, 0); URL.revokeObjectURL(url);
        ocrTarget = await new Promise<Blob>((resolve, reject) => canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error('Could not prepare video frame for OCR')), 'image/jpeg'));
      }
      const ocr = await worker.recognize(ocrTarget);
      const form = new FormData(); form.append('file', roadFile); form.append('ocr_text', ocr.data.text.trim().slice(0, 1000)); form.append('ocr_confidence', String(ocr.data.confidence)); form.append('ocr_provider', 'Tesseract.js');
      const response = await fetch(`${API_URL}/api/road-analysis`, { method: 'POST', body: form });
      const result = await response.json() as RoadAnalysis & { detail?: string };
      if (!response.ok) throw new Error(result.detail || `Road media request failed (${response.status})`);
      setRoadAnalysis(result); await refresh();
    } catch (e) { setError(e instanceof Error ? e.message : 'Road media analysis failed'); }
    finally { if (worker) await worker.terminate(); setRoadBusy(false); }
  }, [roadFile, refresh]);

  const createRoadIncident = useCallback(async () => {
    if (!roadAnalysis) return;
    const location = selectedCoords ?? (roadAnalysis.gps ? [roadAnalysis.gps.lon, roadAnalysis.gps.lat] as [number, number] : null);
    if (!location) { setError('Media has no GPS. Click the road location on the map to confirm where it was reported.'); return; }
    try {
      const severity = roadAnalysis.severity === 'CRITICAL' ? 'critical' : roadAnalysis.severity === 'HIGH' ? 'high' : roadAnalysis.severity === 'LOW' ? 'low' : 'moderate';
      const detectionSummary = roadAnalysis.detections?.map((item) => `${item.damageType} model confidence ${Math.round(item.confidence * 100)}%`).join('; ') || 'No compatible model detection';
      const incident = await request<Incident>(`/api/road-analysis/${roadAnalysis.analysis_id}/incident`, { location_name: 'Operator-confirmed Bengaluru road location', lon: location[0], lat: location[1], location_source: roadAnalysis.gps ? 'EXIF' : 'USER_SELECTED', severity, description: `Road hazard report. ${detectionSummary}. OCR is supplemental evidence: ${roadAnalysis.ocr_text || 'no readable text'}` });
      setActiveIncidentId(incident.incident_id); setViewState((current) => ({ ...current, longitude: location[0], latitude: location[1], zoom: 16, transitionDuration: 700 }));
    } catch { /* visible error */ }
  }, [roadAnalysis, request, selectedCoords]);

  const handleCommand = useCallback(async (raw: string) => {
    if (!raw.trim()) return;
    setCommandText('');
    try {
      const parsed = await request<VoiceCommand>('/api/voice/command', { transcript: raw });
      const response = await fetch(`${API_URL}/api/city/state`);
      const currentCity = response.ok ? await response.json() as CityState : city;
      const incident = currentCity.incidents.find((item) => item.incident_id === activeIncidentId) ?? currentCity.incidents[0];
      const speak = (message: string) => { setAssistantResponse(message); speakResponse(message); };
      switch (parsed.intent) {
        case 'RESET_DEMO': return reset();
        case 'INVESTIGATE_INCIDENT':
          if (!parsed.location?.lat || !parsed.location.lon) {
            speak(`I could not resolve ${parsed.location?.name ?? 'that location'} to a known map area. Select its location on the map before creating the incident.`); return;
          }
          return runDemo(parsed);
        case 'CREATE_RESPONSE_PLAN':
          if (!incident) return runDemo(parsed);
          if (['DETECTED', 'TRIAGED', 'INVESTIGATING', 'REPLANNING'].includes(incident.status)) return runAgents();
          speak(`Incident ${incident.status.toLowerCase().replace('_', ' ')}. Review its current plan and approval state.`); return;
        case 'SIMULATE_RESPONSE':
          if (!incident) {
            speak('I need an active incident location before creating an ambulance response plan. Say “investigate a major accident near Silk Board” first.'); return;
          }
          if (['DETECTED', 'TRIAGED', 'INVESTIGATING', 'REPLANNING'].includes(incident.status)) return runAgents();
          if (incident.status === 'APPROVED') { speak('The simulated ambulance allocation is approved and ready. Use Execute Demo Actions to perform the local simulation.'); return; }
          if (incident.status === 'RESOLVED') { speak('The incident is already resolved in the local simulation.'); return; }
          speak(`A simulated ambulance allocation is proposed for ${incident.location_name}. It awaits operator approval; no unit was dispatched.`); return;
        case 'FIND_HOSPITAL': {
          const hospitals = [...currentCity.hospitals].sort((a, b) => b.beds_available - a.beds_available);
          speak(hospitals.length ? `Simulated hospital inventory: ${hospitals.slice(0, 3).map((hospital) => `${hospital.name}, ${hospital.beds_available} demo beds`).join('; ')}. This is not live capacity.` : 'No hospital records are available.'); return;
        }
        case 'FIND_FIRE_RESOURCE': {
          const stations = currentCity.resources.filter((resource) => resource.type === 'fire_engine');
          speak(stations.length ? `Simulated fire resources: ${stations.map((station) => `${station.name}, ${station.status}`).join('; ')}. Their locations are demonstration data.` : 'No fire resources are listed in the local demo inventory.'); return;
        }
        case 'FIND_AMBULANCE': {
          const units = currentCity.resources.filter((resource) => resource.type === 'ambulance');
          speak(units.length ? `Demo ambulance inventory: ${units.map((unit) => `${unit.name}, ${unit.status}, simulated availability`).join('; ')}.` : 'No ambulance is listed in the local demo inventory.'); return;
        }
        case 'FIND_POLICE_RESOURCE': {
          const units = currentCity.resources.filter((resource) => resource.type === 'police_unit');
          speak(units.length ? `Demo police inventory: ${units.map((unit) => `${unit.name}, ${unit.status}`).join('; ')}. Personnel availability and jurisdiction are not live verified.` : 'No police resource is listed in the local demo inventory.'); return;
        }
        case 'CALCULATE_ROUTE':
          speak(incident?.route?.status === 'calculated' ? `The bundled OpenStreetMap graph route is ${incident.route.distance_km ?? 'unknown'} kilometers, with a simulated heuristic ETA of about ${incident.simulation?.selected_eta_minutes_estimate ?? 'unknown'} minutes. There is no live traffic feed, so this is not a live fastest corridor.` : 'No incident route is ready. Investigate an incident first.'); return;
        case 'CHECK_ROUTE': {
          const blocked = Boolean(incident?.route?.nodes?.some((node) => currentCity.road_blocks.some((block) => block.active && block.node_id === node)));
          speak(incident?.route ? (blocked ? 'The selected route intersects a simulated road closure. Replanning is required.' : `No known simulated closure intersects the current route. There are ${currentCity.road_blocks.filter((block) => block.active).length} simulated active closure records. No live traffic feed is connected.`) : 'No current incident route is available to check.'); return;
        }
        case 'SHOW_DELAYS':
          speak(incident?.route?.distance_km ? `The route is ${incident.route.distance_km} kilometers. The deterministic simulator estimates about ${incident.simulation?.selected_eta_minutes_estimate ?? 'unknown'} minutes using a fixed speed heuristic. No live traffic data is connected.` : 'No route estimate is available yet. Investigate an incident first.'); return;
        case 'PRIORITIZE_INCIDENT':
          if (!incident) { speak('There is no active incident to prioritize.'); return; }
          await request(`/api/kavach/incidents/${incident.incident_id}/prioritize`, { actor: 'local_operator', role: 'OPERATOR' }); speak('Incident priority raised to critical in the local demo and recorded in the audit.'); return;
        case 'ANALYZE_ROAD':
          speak(`There are ${currentCity.road_hazards?.length ?? 0} local road-media submissions. They require human review; there is no damage classifier.`); return;
        case 'GET_AGENT_STATUS':
          speak(`${agents.filter((agent) => agent.status === 'complete').length} of 10 specialists currently report complete. Specialist assessments are deterministic local demo outputs.`); return;
        case 'VERIFY_INCIDENT':
          speak(incident?.verification ? (incident.verification.passed ? 'The latest local simulation verification passed.' : 'The latest verification did not pass; review the checks and replan.') : 'There is no completed verification for the current incident.'); return;
        case 'GET_CITY_STATUS':
          speak(`${currentCity.active_incidents} active demo incident(s), ${currentCity.critical_events} critical, ${currentCity.resources.filter((resource) => resource.status === 'available').length} available simulated units, and ${currentCity.road_blocks.filter((block) => block.active).length} simulated road closure(s).`); return;
        case 'APPROVE_PLAN': return approve();
        case 'EXECUTE_RESPONSE': return execute();
        case 'REPLAN':
          if (!incident) { speak('There is no investigated incident to replan.'); return; }
          await request(`/api/commands/${incident.incident_id}/replan`, { actor: 'local_commander', role: 'COMMANDER' }); speak('The response was recalculated against the current city snapshot. Review and approve the updated plan.'); return;
        default: {
          const message = 'I could not map that phrase to a supported city command. Try investigating an accident, finding hospitals, checking the route, prioritizing an incident, approving the plan, or replanning.';
          setError(message); speak(message); return;
        }
      }
    } catch { /* request has set a visible error */ }
  }, [activeIncidentId, agents, approve, city, execute, request, reset, runAgents, runDemo]);

  const toggleVoice = async () => {
    if (geminiVoice.current) { const active = geminiVoice.current; geminiVoice.current = null; await active.stop(); setIsListening(false); setVoiceState('Gemini voice ready'); return; }
    if (stopStreamingVoice.current) { const stop = stopStreamingVoice.current; stopStreamingVoice.current = null; await stop(); setIsListening(false); setVoiceState('Voice ready'); return; }
    if (recognition.current) { recognition.current.stop(); recognition.current = null; setIsListening(false); setVoiceState('Voice ready'); return; }
    if (geminiReady) {
      try {
        setVoiceState('REQUESTING GEMINI VOICE…');
        const session = await startGeminiLiveVoice(API_URL, (phrase, interim) => {
          setVoiceTranscript(phrase);
          if (interim) setVoiceState('GEMINI HEARING…');
          else { setVoiceState('GEMINI TRANSCRIBING…'); void handleCommand(phrase); }
        }, (state) => {
          setVoiceState(`GEMINI ${state.replaceAll('_', ' ')}`);
          setIsListening(['REQUESTING_MICROPHONE', 'CONNECTING', 'LISTENING', 'TRANSCRIBING'].includes(state));
          if (state === 'CLOSED' && geminiVoice.current) geminiVoice.current = null;
        }, (message) => setError(message));
        geminiVoice.current = session; setIsListening(true);
      } catch (e) { setIsListening(false); setVoiceState('Browser voice fallback'); setError(e instanceof Error ? e.message : 'Gemini voice unavailable'); }
      return;
    }
    if (assemblyAIReady) {
      try {
        setVoiceState('REQUESTING TOKEN…');
        const stream = await startAssemblyAIStreaming(API_URL, (phrase) => { setVoiceTranscript(phrase); setVoiceState('UNDERSTANDING…'); void handleCommand(phrase); }, (state) => { setVoiceState(state.replaceAll('_', ' ')); setIsListening(state === 'LISTENING' || state === 'TRANSCRIBING'); if (state === 'CLOSED') stopStreamingVoice.current = null; }, (message) => setError(message));
        stopStreamingVoice.current = stream.stop; setIsListening(true);
      } catch (e) { setIsListening(false); setVoiceState('Browser voice fallback'); setError(e instanceof Error ? e.message : 'Streaming voice unavailable'); }
      return;
    }
    const browser = window as Window & { SpeechRecognition?: new () => NonNullable<typeof recognition.current>; webkitSpeechRecognition?: new () => NonNullable<typeof recognition.current> };
    const Speech = browser.SpeechRecognition ?? browser.webkitSpeechRecognition;
    if (!Speech) { setVoiceState('Speech recognition is not supported here; use the command box.'); return; }
    const instance = new Speech(); recognition.current = instance; setIsListening(true); setVoiceState('LISTENING');
    instance.lang = 'en-IN'; instance.interimResults = false;
    instance.onresult = (event) => { const phrase = event.results[0]?.[0]?.transcript ?? ''; setVoiceTranscript(phrase); setVoiceState('UNDERSTANDING'); void handleCommand(phrase); };
    instance.onerror = () => { setIsListening(false); setVoiceState('Voice unavailable; use the command box.'); };
    instance.onend = () => { recognition.current = null; setIsListening(false); setVoiceState('Voice ready'); };
    instance.start();
  };

  const routeCoords = activeIncident?.route?.coordinates ?? null;
  const routeSegments = useMemo<RouteSegment[]>(() => routeCoords && routeCoords.length > 1 ? [{ path: routeCoords, depth: 0, color: [40, 238, 202, 235] }] : [], [routeCoords]);
  const roadBlocks = useMemo(() => city.road_blocks.filter((item) => item.active && Number.isFinite(item.lon) && Number.isFinite(item.lat)).map((item) => ({ ...item, road_name: 'Simulated road closure', zone_id: 'demo', reason: 'Scenario failure injection', depth_at_block: 0, status: 'active' as const })), [city.road_blocks]);
  const emergencyData = useMemo<EmergencyFacility[]>(() => EMERGENCY_INFRA, []);
  const selectedOutput = activeIncident?.agent_outputs?.find((item) => item.agent === selectedAgent);
  const approvalNeeded = activeIncident?.status === 'AWAITING_APPROVAL';
  const routeDistance = activeIncident?.route?.distance_km;

  if (view === 'legacy') return <><button className="kv-legacy-return" onClick={() => setView('command')}>← KAVACH command view</button><LegacyApp /></>;

  return (
    <main className="kv-shell">
      <MapView viewState={viewState} onViewStateChange={setViewState} is3D={viewState.pitch > 0}
        activeFloodPoints={[]} emergencyData={emergencyData} clickPoints={[]} routeCoords={routeCoords} routeSegments={routeSegments}
        onMapClick={(coordinate) => setSelectedCoords(coordinate)} currentPoint={activeIncident ? [activeIncident.lon, activeIncident.lat] : selectedCoords} roadBlocks={roadBlocks} />
      <div className="kv-vignette" />
      <header className="kv-topbar">
        <div className="kv-brand"><span className="kv-sigil">K</span><div><strong>KAVACH</strong><small>THE INTELLIGENCE WATCHING OVER THE CITY</small></div></div>
        <div className="kv-city"><span className="kv-live-dot" /> KAVACH ACTIVE <i>/</i> BENGALURU · KC VALLEY <span className="kv-tag">CITY {city.data_state}</span>{providers.weather && <span className="kv-tag">WEATHER {providers.weather.freshness}</span>}</div>
        <div className="kv-top-actions"><span className="kv-model">{providers.prediction?.provider ?? 'SIMULATION'} · {providers.stgcn?.status === 'available' ? 'MODEL' : 'NO STGCN DATASET'} · CAMERAS {city.online_camera_count ?? 0}/{city.camera_count ?? 0} · {city.pending_approvals ?? 0} APPROVALS · DEMO AUTH</span><button onClick={() => setReportOpen(true)}>REPORT INCIDENT</button><button onClick={() => void openCameraCenter()} disabled={cameraBusy}>CONNECT CAMERA</button><button onClick={() => setView('legacy')}>OPERATIONS</button></div>
      </header>

      <section className="kv-left glass-panel">
        <div className="kv-section-head"><span>CITY STATE</span><span className="kv-tag">{city.data_state}</span></div>
        <div className="kv-stats"><div><b>{city.active_incidents}</b><small>ACTIVE</small></div><div><b className="kv-red">{city.critical_events}</b><small>CRITICAL</small></div><div><b>{city.resources.filter((r) => r.status === 'available').length}</b><small>UNITS FREE</small></div></div>
        <div className="kv-divider" />
        <div className="kv-section-head"><span>INCIDENTS</span><button className="kv-link" disabled={busy} onClick={() => setReportOpen(true)}>+ REPORT</button></div>
        {city.incidents.length === 0 ? <div className="kv-empty">No local demo incident yet.<br />Load a deterministic response scenario.</div> : <div className="kv-incident-list">{city.incidents.map((incident) => <button key={incident.incident_id} className={`kv-incident ${activeIncident?.incident_id === incident.incident_id ? 'selected' : ''}`} onClick={() => setActiveIncidentId(incident.incident_id)}><i className={incident.severity === 'critical' ? 'critical' : ''} /><span><b>{incident.incident_type.replace('_', ' ').toUpperCase()}</b><small>{incident.location_name}</small></span><em>{incident.status.replace('_', ' ')}</em></button>)}</div>}
        <div className="kv-divider" />
        <div className="kv-section-head"><span>RESPONSE ASSETS</span><span className="kv-tag">DEMO INVENTORY</span></div>
        <div className="kv-asset-row"><span>Hospitals</span><b>{city.hospitals.length}</b><small>{city.hospitals.reduce((n, h) => n + h.beds_available, 0)} demo beds</small></div>
        <div className="kv-asset-row"><span>Emergency units</span><b>{city.resources.length}</b><small>{city.resources.filter((r) => r.status === 'available').length} available</small></div>
        <p className="kv-source-note">Operational inventory is simulated for this local demo. No dispatch or external alert is sent.</p>
        <div className="kv-divider" />
        <div className="kv-section-head"><span>ROAD INTELLIGENCE</span><span className="kv-tag">HUMAN REVIEW</span></div>
        <label className="kv-upload"><span>{roadFile ? roadFile.name : 'Choose road photo or short video'}</span><input type="file" accept="image/*,video/mp4,video/webm,video/quicktime" onChange={(event) => { setRoadFile(event.target.files?.[0] ?? null); setRoadAnalysis(null); }} /></label>
        <button className="kv-road-button" disabled={!roadFile || roadBusy} onClick={() => void analyzeRoadMedia()}>{roadBusy ? 'READING MEDIA…' : 'ANALYZE LOCAL MEDIA'}</button>
        {roadAnalysis && <div className="kv-road-result"><b>{roadAnalysis.model_mode === 'LIVE' ? `${roadAnalysis.detections?.length ?? 0} MODEL DETECTION(S) · ${roadAnalysis.severity ?? 'NO DAMAGE'} ${roadAnalysis.severity ? 'PRIORITY' : ''}` : `${roadAnalysis.frames_analyzed} FRAME(S) · ${roadAnalysis.cue_count} NON-CLASSIFYING CUE(S)`}</b>{roadAnalysis.detections?.map((item, index) => <small key={`${item.frameIndex}-${index}`}>{item.damageType} · {Math.round(item.confidence * 100)}% model output · {item.severity} · frame {item.frameIndex + 1}</small>)}<p>{roadAnalysis.disclaimer}</p>{roadAnalysis.ocr_text && <small>OCR {roadAnalysis.ocr?.confidence === null || !roadAnalysis.ocr?.confidence ? 'confidence unavailable' : `${Math.round(roadAnalysis.ocr.confidence * 100)}%`} · {roadAnalysis.ocr_text}</small>}<small>{roadAnalysis.gps ? `EXIF GPS ${roadAnalysis.gps.lat.toFixed(5)}, ${roadAnalysis.gps.lon.toFixed(5)}` : selectedCoords ? `Map location ${selectedCoords[1].toFixed(5)}, ${selectedCoords[0].toFixed(5)}` : 'No GPS found · click the map to set a report location.'}</small><button onClick={() => void createRoadIncident()} disabled={busy}>CONFIRM AS ROAD INCIDENT</button></div>}
        <div className="kv-divider" />
        <div className="kv-section-head"><span>DATA PROVIDERS</span><span className="kv-tag">{eventStreamState}</span></div>
        <div className="kv-provider-list">{providers.providerHealth?.map((provider) => <div className="kv-provider-row" key={provider.type}><span className={`kv-provider-dot ${provider.mode.toLowerCase()}`} /><b>{provider.name.replace('KAVACH local demo inventory', 'Demo inventory').replace('Bundled OSM extract', 'OSM roads')}</b><em>{provider.mode}</em></div>) ?? <small>Provider status is loading.</small>}</div>
      </section>

      <aside className="kv-right glass-panel">
        <div className="kv-section-head"><span>AGENT NETWORK</span><span className="kv-tag">{agents.filter((a) => a.status === 'complete').length}/10 · RULE HEURISTIC</span></div>
        <div className="kv-agent-list">{agents.map((agent) => <button key={agent.id} className={`kv-agent ${selectedAgent === agent.id ? 'selected' : ''}`} onClick={() => setSelectedAgent((current) => current === agent.id ? '' : agent.id)}><span className={`kv-agent-orb ${agent.status}`} /> <span className="kv-agent-main"><b>{agent.name}</b><small>{agent.summary}</small></span><span className="kv-agent-confidence">{agent.confidence === null ? '—' : `${Math.round(agent.confidence * 100)}%`}</span></button>)}</div>
        {selectedOutput && <div className="kv-agent-detail"><b>{agents.find((a) => a.id === selectedAgent)?.name} · {selectedOutput.status} · {Math.round(selectedOutput.confidence * 100)}% HEURISTIC</b><p>{selectedOutput.findings.join(' ')}</p><small>{selectedOutput.evidence.join(' · ')}</small>{selectedOutput.evidence_records?.map((item, index) => <small key={`${item.tool}-${index}`}>{item.tool} · {item.freshness} · {item.source} · {item.result}</small>)}{selectedOutput.trace_id && <small>Trace {selectedOutput.trace_id} · {selectedOutput.durationMs ?? 0} ms</small>}</div>}
        {cameraEvidence && activeIncident?.camera_evidence_id && <div className="kv-camera-evidence"><b>OPERATOR-CONFIRMED CAMERA EVIDENCE</b><img src={cameraEvidence.image_data} alt="Captured local webcam frame linked to the incident" /><small>{cameraEvidence.camera_id} · {new Date(cameraEvidence.captured_at).toLocaleString()} · SHA256 {cameraEvidence.sha256.slice(0, 14)}… · no AI model confidence</small></div>}
        <div className="kv-divider" />
        <div className="kv-section-head"><span>COMMUNICATIONS</span><span className="kv-tag">SMTP {emailProvider.status}</span></div>
        {communicationDrafts.length === 0 ? <div className="kv-empty">Incident recommendations create reviewable email drafts here.</div> : <div className="kv-comms-list">{communicationDrafts.slice(0, 5).map((draft) => <button className="kv-comms-card" key={draft.id} onClick={() => setReviewDraft(draft)}><span><b>{draft.department}</b><small>{draft.subject}</small><small>{draft.recipient ?? 'TEST RECIPIENT NOT CONFIGURED'}</small></span><em>{draft.status.replaceAll('_', ' ')}</em></button>)}</div>}
        <small className="kv-source-note">Approval-gated. Demo send records SIMULATED only. External email needs a configured recipient and SMTP app password.</small>
      </aside>

      <div className="kv-map-label"><strong>GOD VIEW</strong><span>3D OSM BUILDING EXTRUSIONS · KC VALLEY EXTRACT</span><small>Not photogrammetry. Snapshot date unknown.</small></div>
      <div className="kv-map-controls"><button onClick={() => setViewState((current) => ({ ...current, pitch: current.pitch > 0 ? 0 : 58, bearing: current.pitch > 0 ? 0 : -22, zoom: current.pitch > 0 ? 13.5 : 14.7, transitionDuration: 700 }))}>{viewState.pitch > 0 ? '3D ON' : '2D VIEW'}</button><button onClick={() => setViewState((current) => ({ ...current, longitude: 77.645, latitude: 12.935, zoom: 14.7, pitch: 58, bearing: -22, transitionDuration: 800 }))}>CENTER CITY</button></div>

      <section className="kv-bottom glass-panel">
        <div className="kv-bottom-top"><div><span className="kv-section-kicker">COMMAND STREAM</span><strong>{activeIncident ? `${activeIncident.incident_type.toUpperCase()} · ${activeIncident.status.replace('_', ' ')}` : 'CITY MONITORING · STANDBY'}</strong></div><span className="kv-tag">{audit.length} AUDIT EVENTS</span></div>
        <div className="kv-stream">{audit.slice(0, 5).map((event) => <div key={event.id}><time>{new Date(event.timestamp).toLocaleTimeString('en-IN', { hour12: false })}</time><span className="kv-event-dot" /><p>{event.summary}</p><small>{event.data_state}</small></div>)}</div>
        <form className="kv-command" onSubmit={(event) => { event.preventDefault(); void handleCommand(commandText); }}><button type="button" className="kv-mic" onClick={toggleVoice} title={isListening ? 'Stop listening' : geminiReady ? 'Start Gemini Live voice recognition' : 'Start browser speech recognition'}>{isListening ? '■' : '◉'}</button><input value={commandText} onChange={(event) => setCommandText(event.target.value)} placeholder="Command KAVACH · investigate, approve, execute, replan…" /><button type="submit" disabled={busy}>SEND</button><span className="kv-voice-state">{voiceState}</span></form>
        {voiceTranscript && <div className="kv-voice-transcript" aria-live="polite">TRANSCRIPT · “{voiceTranscript}”</div>}
        {assistantResponse && <div className="kv-assistant-response" role="status">KAVACH · {assistantResponse}</div>}
        {error && <div className="kv-error">{error}</div>}
      </section>

      {activeIncident && <section className="kv-approval glass-panel"><div><span className="kv-section-kicker">RESPONSE PLAN</span><b>{activeIncident.recommended_hospital?.name ?? activeIncident.route?.status ?? 'Investigation needed'}</b><small>{routeDistance ? `${routeDistance} km · ${activeIncident.route?.provider}` : 'Route pending'}</small><small>LOCATION {activeIncident.location_source ?? 'SIMULATED'} · {activeIncident.data_state}</small></div><div className="kv-approval-actions">{['DETECTED', 'TRIAGED', 'INVESTIGATING'].includes(activeIncident.status) && <button onClick={() => void runAgents()} disabled={busy}>INVESTIGATE</button>}{approvalNeeded && <button className="approve" onClick={() => void approve()} disabled={busy}>APPROVE PLAN</button>}{activeIncident.status === 'APPROVED' && <><button className="execute" onClick={() => void execute()} disabled={busy}>EXECUTE DEMO ACTIONS</button><button className="replan" onClick={() => void sendNotice()} disabled={busy}>SEND / LOG NOTICE</button></>}{['RESOLVED', 'FAILED'].includes(activeIncident.status) && <button className="replan" onClick={() => void injectRoadBlock()} disabled={busy}>INJECT FAILURE · REPLAN</button>}{activeIncident.status === 'AWAITING_APPROVAL' && <button className="replan" onClick={() => void injectRoadBlock()} disabled={busy}>ROAD BLOCK · REPLAN</button>}</div>{activeIncident.local_notification_draft && <small className="kv-no-send">LOCAL DRAFT ONLY · NOT SENT</small>}{activeIncident.gemini_analysis && <div className="kv-no-send"><b>GEMINI ADVISORY · {activeIncident.gemini_analysis.mode}</b><small>{activeIncident.gemini_analysis.summary ?? activeIncident.gemini_analysis.reason ?? 'No advisory returned; deterministic plan remains active.'}</small>{activeIncident.gemini_analysis.hazards_to_check?.map((item) => <small key={item}>CHECK · {item}</small>)}{activeIncident.gemini_analysis.data_uncertainties?.map((item) => <small key={item}>UNCERTAINTY · {item}</small>)}</div>}</section>}

      {reportOpen && <div className="kv-modal-backdrop" role="presentation"><section className="kv-modal glass-panel" role="dialog" aria-modal="true" aria-labelledby="kv-report-title"><button className="kv-modal-close" onClick={() => setReportOpen(false)}>×</button><span className="kv-section-kicker">INCIDENT INTAKE · DEMO</span><h2 id="kv-report-title">Activate KAVACH</h2><label>Incident type<select value={reportType} onChange={(event) => setReportType(event.target.value)}><option value="collision">Major accident</option><option value="fire">Fire</option><option value="medical_emergency">Medical emergency</option><option value="road_hazard">Road hazard</option><option value="flood">Flooding</option><option value="infrastructure_failure">Infrastructure failure</option><option value="public_gathering">Public gathering</option></select></label><label>Known demo location<select value={reportLocation} onChange={(event) => setReportLocation(event.target.value)}><option>Silk Board</option><option>Koramangala</option><option>HSR Layout</option><option>Bellandur</option><option>Map selection</option></select></label>{reportLocation === 'Map selection' && <small>{selectedCoords ? `Operator-selected: ${selectedCoords[1].toFixed(5)}, ${selectedCoords[0].toFixed(5)}` : 'Click the map first to set the location.'}</small>}<label>Severity<select value={reportSeverity} onChange={(event) => setReportSeverity(event.target.value)}><option value="low">Low</option><option value="moderate">Moderate</option><option value="high">High</option><option value="critical">Critical</option></select></label><label>Description<textarea value={reportDescription} onChange={(event) => setReportDescription(event.target.value)} maxLength={2000} /></label><small>Known places use fixed demo coordinates. Location provenance is shown on the incident.</small><button className="kv-modal-primary" disabled={busy} onClick={() => void activateReportedIncident()}>{busy ? 'INITIALIZING RESPONSE…' : 'ACTIVATE KAVACH'}</button></section></div>}

      {cameraOpen && camera && <div className="kv-modal-backdrop" role="presentation"><section className="kv-modal kv-camera-modal glass-panel" role="dialog" aria-modal="true" aria-labelledby="kv-camera-title"><button className="kv-modal-close" onClick={() => void stopCameraCenter()}>×</button><span className="kv-section-kicker">LOCAL CAMERA · OPERATOR REVIEW</span><h2 id="kv-camera-title">{camera.name}</h2><video ref={cameraVideo} autoPlay playsInline muted /><p className="kv-camera-warning">Camera online · vision model unavailable. KAVACH does not auto-detect from this feed. Only submit an event you personally confirm.</p><label>Operator-reported event<select value={cameraIncidentType} onChange={(event) => setCameraIncidentType(event.target.value)}><option value="collision">Possible collision</option><option value="fire">Possible fire</option><option value="road_hazard">Road hazard</option><option value="medical_emergency">Medical emergency</option></select></label><label>Situation<textarea value={cameraDescription} onChange={(event) => setCameraDescription(event.target.value)} /></label><button className="kv-modal-primary" disabled={cameraBusy} onClick={() => void confirmCameraObservation()}>{cameraBusy ? 'CAPTURING AND STARTING RESPONSE…' : 'CONFIRM EVENT AND ACTIVATE KAVACH'}</button><small>The captured frame is stored in process memory for this local demo. The observation is marked USER CONFIRMED with no model confidence.</small></section></div>}

      {reviewDraft && <div className="kv-modal-backdrop" role="presentation"><section className="kv-modal kv-email-modal glass-panel" role="dialog" aria-modal="true" aria-labelledby="kv-email-title"><button className="kv-modal-close" onClick={() => setReviewDraft(null)}>×</button><span className="kv-section-kicker">COMMUNICATION REVIEW · {reviewDraft.status}</span><h2 id="kv-email-title">{reviewDraft.department} email draft</h2><p>{reviewDraft.reason}</p><label>To · configured recipient only<input value={reviewDraft.recipient ?? 'NOT CONFIGURED'} readOnly /></label><label>Subject<input value={reviewDraft.subject} readOnly={reviewDraft.status !== 'AWAITING_APPROVAL'} onChange={(event) => setReviewDraft({ ...reviewDraft, subject: event.target.value })} /></label><label>Message<textarea value={reviewDraft.body} readOnly={reviewDraft.status !== 'AWAITING_APPROVAL'} onChange={(event) => setReviewDraft({ ...reviewDraft, body: event.target.value })} /></label><small>SMTP {emailProvider.status} · {reviewDraft.mode} · SMTP acceptance is not recipient delivery verification.</small><div className="kv-modal-actions">{reviewDraft.status === 'AWAITING_APPROVAL' && <><button onClick={() => void saveEmailDraft()}>SAVE EDIT</button><button className="replan" onClick={() => void request(`/api/communications/${reviewDraft.id}/reject`, { actor: 'demo_commander', role: 'COMMANDER' }).then(() => setReviewDraft(null))}>REJECT</button><button className="approve" disabled={!reviewDraft.recipient} onClick={() => void approveEmailDraft(reviewDraft)}>APPROVE{emailProvider.status === 'READY' ? ' & SEND' : ''}</button></>}{reviewDraft.status === 'APPROVED' && <><button className="execute" onClick={() => void simulateEmailDraft(reviewDraft)}>SIMULATE SEND · NO EMAIL SENT</button>{emailProvider.status === 'READY' && <button className="approve" onClick={() => void sendApprovedEmail(reviewDraft)}>SEND APPROVED EMAIL</button>}</>}{reviewDraft.status === 'SENT' && <b>EMAIL ACCEPTED BY SMTP SERVER · DELIVERY NOT VERIFIED</b>}{reviewDraft.status === 'SIMULATED' && <b>SIMULATED · NO EMAIL SENT</b>}{reviewDraft.status === 'FAILED' && <b>SMTP SEND FAILED · REVIEW PROVIDER STATUS</b>}</div></section></div>}

      <footer className="kv-attribution">© OpenStreetMap contributors · CARTO · Terrain © Mapzen · source labels shown per provider</footer>
      <button className="kv-reset" onClick={() => void reset()} disabled={busy}>RESET DEMO</button>
    </main>
  );
}
