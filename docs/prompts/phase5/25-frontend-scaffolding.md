# [Step 25] — React Frontend Scaffolding

## Context

Steps 01-24 are complete. The backend exposes:
- REST API at `http://localhost:8000/api/v1`
- WebSocket at `ws://localhost:8000/api/v1/ws/events`
- All endpoints from step 23 are active

The `frontend/` directory exists (currently just a `.gitkeep`).

## Objective

Scaffold the React + TypeScript + Tailwind CSS frontend: Vite project, folder structure, API client, WebSocket hook, React Router, Zustand state store, and TypeScript types matching the backend API models.

## Files to Create

```
frontend/
├── package.json
├── vite.config.ts
├── tailwind.config.js
├── tsconfig.json
├── index.html
└── src/
    ├── main.tsx
    ├── App.tsx
    ├── types/
    │   └── api.ts          ← TypeScript types matching backend models
    ├── api/
    │   └── client.ts       ← axios-based API client with X-API-Key header
    ├── hooks/
    │   ├── useWebSocket.ts ← WebSocket hook with auto-reconnect
    │   └── useAuth.ts      ← placeholder (JWT wired in step 29)
    ├── store/
    │   └── index.ts        ← Zustand stores (incidents, events, services)
    ├── components/
    │   └── layout/
    │       ├── Shell.tsx       ← App shell with sidebar + header
    │       ├── Sidebar.tsx     ← Navigation links
    │       └── Header.tsx      ← Title + connection status badge
    └── pages/
        ├── HealthPage.tsx      ← placeholder for step 26
        ├── IncidentsPage.tsx   ← placeholder for step 26
        ├── ApprovalPage.tsx    ← placeholder for step 27
        ├── ChatPage.tsx        ← placeholder for step 27
        ├── PlaybooksPage.tsx   ← placeholder for step 28
        └── AnalyticsPage.tsx   ← placeholder for step 28
```

## Key Requirements

**package.json dependencies:**
```json
{
  "dependencies": {
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "react-router-dom": "^6.26.0",
    "axios": "^1.7.0",
    "zustand": "^4.5.0",
    "@tanstack/react-query": "^5.51.0",
    "recharts": "^2.12.0",
    "lucide-react": "^0.436.0",
    "clsx": "^2.1.0",
    "date-fns": "^3.6.0"
  },
  "devDependencies": {
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.0",
    "autoprefixer": "^10.4.0",
    "postcss": "^8.4.0",
    "tailwindcss": "^3.4.0",
    "typescript": "^5.5.0",
    "vite": "^5.4.0"
  }
}
```

**vite.config.ts:**
```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
      '/ws': { target: 'ws://localhost:8000', ws: true },
    },
  },
})
```

**src/types/api.ts — TypeScript types (must match backend Pydantic models exactly):**

```typescript
export type ServiceState = 'running' | 'stopped' | 'error' | 'starting'
export type Severity = 'LOW' | 'MEDIUM' | 'HIGH'
export type IncidentStatus = 'active' | 'resolved' | 'escalated' | 'denied'
export type ApprovalStatus = 'pending' | 'approved' | 'denied' | 'investigating' | 'timed_out'

export interface ServiceStatus {
  name: string
  state: ServiceState
  cpu_percent: number
  memory_percent: number
  healthy: boolean
  uptime_seconds: number
  last_error?: string
}

export interface Diagnosis {
  summary: string
  confidence: number
  llm_reasoning?: string
  matched_playbook?: string
}

export interface TimelineAction {
  type: string
  timestamp: string
  detail: string
  result?: string
}

export interface Incident {
  id: string
  title: string
  severity: Severity
  status: IncidentStatus
  service: string
  detected_at: string
  resolved_at?: string
  resolution_time_seconds?: number
  auto_resolved: boolean
  playbook_id?: string
  diagnosis?: Diagnosis
  actions?: TimelineAction[]
  rollback_plan?: string
  metrics_at_detection?: Record<string, unknown>
}

export interface PendingApproval {
  incident_id: string
  title: string
  severity: Severity
  proposed_action: string
  rollback_plan?: string
  requested_at: string
  timeout_at?: string
  timeout_default?: string
}

export interface PlaybookSummary {
  id: string
  name: string
  severity: Severity
  provider?: string
  detection_type: string
  file: string
}

export interface ChatMessage {
  role: 'agent' | 'human'
  timestamp: string
  content: string
  type?: 'message' | 'approval_card'
  card?: {
    severity: Severity
    proposed_action: string
    rollback_plan?: string
    timeout_at?: string
    timeout_default?: string
  }
}

// WebSocket event envelope
export interface WSEvent {
  type: string
  data: Record<string, unknown>
  timestamp: string
}
```

**src/api/client.ts:**

```typescript
import axios from 'axios'

const BASE_URL = '/api/v1'
const API_KEY = import.meta.env.VITE_API_KEY || 'changeme'

export const apiClient = axios.create({
  baseURL: BASE_URL,
  headers: { 'X-API-Key': API_KEY },
})

// Response interceptor for consistent error handling
apiClient.interceptors.response.use(
  (res) => res,
  (error) => {
    // JWT 401 handling added in step 29
    return Promise.reject(error)
  }
)

// API functions
export const api = {
  // System
  getHealth: () => apiClient.get('/health').then(r => r.data),
  getStatus: () => apiClient.get<{ services: ServiceStatus[] }>('/status').then(r => r.data),

  // Incidents
  listIncidents: (params?: Record<string, string | number>) =>
    apiClient.get<{ incidents: Incident[]; total: number }>('/incidents', { params }).then(r => r.data),
  getIncident: (id: string) => apiClient.get<Incident>(`/incidents/${id}`).then(r => r.data),
  escalateIncident: (id: string, reason?: string) =>
    apiClient.post(`/incidents/${id}/escalate`, { reason }).then(r => r.data),

  // Approvals
  getPendingApprovals: () =>
    apiClient.get<{ pending: PendingApproval[] }>('/approval/pending').then(r => r.data),
  approveIncident: (id: string, approvedBy: string) =>
    apiClient.post(`/approval/${id}/approve`, { approved_by: approvedBy }).then(r => r.data),
  denyIncident: (id: string, deniedBy: string, reason?: string) =>
    apiClient.post(`/approval/${id}/deny`, { denied_by: deniedBy, reason }).then(r => r.data),
  investigateIncident: (id: string) =>
    apiClient.post(`/approval/${id}/investigate`).then(r => r.data),

  // Playbooks
  listPlaybooks: (params?: Record<string, string>) =>
    apiClient.get<{ playbooks: PlaybookSummary[] }>('/playbooks', { params }).then(r => r.data),
  getPlaybook: (id: string) => apiClient.get(`/playbooks/${id}`).then(r => r.data),
  createPlaybook: (body: Record<string, unknown>) =>
    apiClient.post('/playbooks', body).then(r => r.data),
  updatePlaybook: (id: string, body: Record<string, unknown>) =>
    apiClient.put(`/playbooks/${id}`, body).then(r => r.data),
  deletePlaybook: (id: string) => apiClient.delete(`/playbooks/${id}`).then(r => r.data),

  // Chat
  getChatLog: (incidentId: string) =>
    apiClient.get<{ messages: ChatMessage[] }>(`/chat/${incidentId}`).then(r => r.data),
  sendChatMessage: (message: string) =>
    apiClient.post<{ response: string }>('/chat', { message }).then(r => r.data),

  // Agent control
  getAgentConfig: () => apiClient.get('/agent/config').then(r => r.data),
  startAgent: () => apiClient.post('/agent/start').then(r => r.data),
  stopAgent: () => apiClient.post('/agent/stop').then(r => r.data),
}
```

**src/hooks/useWebSocket.ts:**

```typescript
import { useEffect, useRef, useCallback, useState } from 'react'
import type { WSEvent } from '../types/api'

const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/api/v1/ws/events'
const MAX_RECONNECT_DELAY = 30000
const BASE_RECONNECT_DELAY = 1000

interface UseWebSocketOptions {
  onEvent?: (event: WSEvent) => void
  enabled?: boolean
}

export function useWebSocket({ onEvent, enabled = true }: UseWebSocketOptions = {}) {
  const ws = useRef<WebSocket | null>(null)
  const reconnectDelay = useRef(BASE_RECONNECT_DELAY)
  const reconnectTimeout = useRef<ReturnType<typeof setTimeout>>()
  const [connected, setConnected] = useState(false)

  const connect = useCallback(() => {
    if (!enabled) return
    ws.current = new WebSocket(WS_URL)

    ws.current.onopen = () => {
      setConnected(true)
      reconnectDelay.current = BASE_RECONNECT_DELAY
    }

    ws.current.onmessage = (e) => {
      try {
        const event: WSEvent = JSON.parse(e.data)
        onEvent?.(event)
      } catch { /* ignore non-JSON */ }
    }

    ws.current.onclose = () => {
      setConnected(false)
      reconnectTimeout.current = setTimeout(() => {
        reconnectDelay.current = Math.min(reconnectDelay.current * 2, MAX_RECONNECT_DELAY)
        connect()
      }, reconnectDelay.current)
    }

    ws.current.onerror = () => ws.current?.close()
  }, [enabled, onEvent])

  useEffect(() => {
    connect()
    return () => {
      clearTimeout(reconnectTimeout.current)
      ws.current?.close()
    }
  }, [connect])

  return { connected }
}
```

**src/store/index.ts (Zustand):**

```typescript
import { create } from 'zustand'
import type { Incident, PendingApproval, ServiceStatus, WSEvent } from '../types/api'

interface AppStore {
  services: ServiceStatus[]
  incidents: Incident[]
  pendingApprovals: PendingApproval[]
  lastEvent: WSEvent | null

  setServices: (s: ServiceStatus[]) => void
  setIncidents: (i: Incident[]) => void
  setPendingApprovals: (p: PendingApproval[]) => void
  handleWSEvent: (event: WSEvent) => void
}

export const useAppStore = create<AppStore>((set, get) => ({
  services: [],
  incidents: [],
  pendingApprovals: [],
  lastEvent: null,

  setServices: (services) => set({ services }),
  setIncidents: (incidents) => set({ incidents }),
  setPendingApprovals: (pendingApprovals) => set({ pendingApprovals }),

  handleWSEvent: (event) => {
    set({ lastEvent: event })
    // Real-time updates: handled in each view component via useAppStore subscription
  },
}))
```

**src/App.tsx:**

```typescript
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Shell } from './components/layout/Shell'
import { HealthPage } from './pages/HealthPage'
import { IncidentsPage } from './pages/IncidentsPage'
import { ApprovalPage } from './pages/ApprovalPage'
import { ChatPage } from './pages/ChatPage'
import { PlaybooksPage } from './pages/PlaybooksPage'
import { AnalyticsPage } from './pages/AnalyticsPage'

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Shell />}>
          <Route index element={<Navigate to="/health" replace />} />
          <Route path="/health" element={<HealthPage />} />
          <Route path="/incidents" element={<IncidentsPage />} />
          <Route path="/incidents/:id" element={<IncidentsPage />} />
          <Route path="/approvals" element={<ApprovalPage />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/chat/:incidentId" element={<ChatPage />} />
          <Route path="/playbooks" element={<PlaybooksPage />} />
          <Route path="/analytics" element={<AnalyticsPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
```

**src/components/layout/Shell.tsx:**

- Uses `Outlet` from react-router-dom
- Sidebar on the left (fixed width 240px), main content fills the rest
- Header at top shows "AutoOps AI", connection status badge (green dot = connected, grey = disconnected)
- WebSocket is initialized here and events dispatched to Zustand store
- Tailwind classes: dark sidebar (`bg-slate-900 text-white`), light content area (`bg-slate-50`)

**Placeholder pages (all 6):**

Each placeholder: `export function XxxPage() { return <div className="p-6"><h1>Xxx View</h1><p>Coming in step XX.</p></div> }`. Enough to verify routing works.

## Test Criteria

```bash
cd /Users/dattaikhe/LLM/AutoOpsAI/frontend

npm install
# Expected: installs without errors

npm run build
# Expected: build succeeds, dist/ directory created

# Dev server (verify in browser)
npm run dev
# Navigate to http://localhost:5173 — should show Shell with sidebar
# Sidebar links should navigate without 404
# Header should show connection status badge
```

## Dependencies

- Step 23 (API endpoints — types derived from API responses)
- Step 21 (WebSocket endpoint — `WS /api/v1/ws/events`)
