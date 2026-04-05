const API_BASE = '/api/v1';

const API_KEY = 'dev'; // matches .env default

async function request<T>(path: string, opts?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-API-Key': API_KEY,
    ...(opts?.headers as Record<string, string> || {}),
  };
  const res = await fetch(`${API_BASE}${path}`, { ...opts, headers });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

// System
export const getHealth = () => request<import('./types').HealthCheck>('/health');
export const getStatus = () => request<import('./types').StatusResponse>('/status');

// Incidents
export const getIncidents = (limit = 50) =>
  request<import('./types').Incident[]>(`/incidents?limit=${limit}`);
export const getIncident = (id: string) =>
  request<import('./types').Incident>(`/incidents/${encodeURIComponent(id)}`);
export const escalateIncident = (id: string) =>
  request<unknown>(`/incidents/${encodeURIComponent(id)}/escalate`, { method: 'POST' });

// Approvals
export const getPendingApprovals = () =>
  request<import('./types').ApprovalRequest[]>('/approval/pending');
export const approvalDecision = (id: string, decision: 'approve' | 'deny' | 'investigate') =>
  request<unknown>(`/approval/${encodeURIComponent(id)}/${decision}`, { method: 'POST' });

// Playbooks
export const getPlaybooks = () =>
  request<import('./types').Playbook[]>('/playbooks');
export const getPlaybook = (id: string) =>
  request<import('./types').Playbook>(`/playbooks/${encodeURIComponent(id)}`);
export const reloadPlaybooks = () =>
  request<unknown>('/playbooks/reload', { method: 'POST' });

// Agent
export const startAgent = () =>
  request<unknown>('/agent/start', { method: 'POST' });
export const stopAgent = () =>
  request<unknown>('/agent/stop', { method: 'POST' });
export const getAgentConfig = () =>
  request<import('./types').AgentConfig>('/agent/config');

// Chat
export const getChat = (incidentId: string) =>
  request<import('./types').ChatMessage[]>(`/chat/${encodeURIComponent(incidentId)}`);
export const sendChatMessage = (question: string, incidentId?: string) =>
  request<{ response: string; incident_id: string | null }>('/chat', {
    method: 'POST',
    body: JSON.stringify({ question, incident_id: incidentId }),
  });

/** Stream chat tokens via SSE. Calls onToken for each token, onDone when complete. */
export async function streamChatMessage(
  question: string,
  onToken: (token: string) => void,
  onDone: (fullResponse: string) => void,
  incidentId?: string,
): Promise<void> {
  const res = await fetch(`${API_BASE}/chat/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-API-Key': API_KEY,
    },
    body: JSON.stringify({ question, incident_id: incidentId }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `HTTP ${res.status}`);
  }

  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      const payload = JSON.parse(line.slice(6));
      if (payload.done) {
        onDone(payload.full_response);
        return;
      }
      onToken(payload.token);
    }
  }

  // Flush remaining buffer
  if (buffer.startsWith('data: ')) {
    const payload = JSON.parse(buffer.slice(6));
    if (payload.done) {
      onDone(payload.full_response);
    } else {
      onToken(payload.token);
    }
  }
}
