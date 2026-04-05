# [Step 26] — Health & Incidents Views

## Context

Step 25 is complete. The following exist:
- `frontend/src/api/client.ts` — `api.*` functions
- `frontend/src/types/api.ts` — `ServiceStatus`, `Incident`, `WSEvent`
- `frontend/src/store/index.ts` — Zustand `useAppStore`
- `frontend/src/hooks/useWebSocket.ts` — WebSocket hook
- `frontend/src/pages/HealthPage.tsx` — placeholder
- `frontend/src/pages/IncidentsPage.tsx` — placeholder

## Objective

Implement the Health and Incidents views with real-time service status cards, incident list, and incident detail drawer. All data fetched via React Query; real-time updates via the WebSocket store.

## Files to Modify

- `frontend/src/pages/HealthPage.tsx` — Replace placeholder with full implementation.
- `frontend/src/pages/IncidentsPage.tsx` — Replace placeholder with full implementation.
- `frontend/src/components/layout/Shell.tsx` — Wire WebSocket `metric_update` events to store.

## Files to Create

```
frontend/src/components/
├── health/
│   ├── ServiceCard.tsx        ← Individual service status card
│   └── ServiceGrid.tsx        ← Grid of ServiceCards
└── incidents/
    ├── IncidentRow.tsx         ← Table row with severity badge
    ├── IncidentTable.tsx       ← Sortable/filterable table
    ├── IncidentDetail.tsx      ← Detail drawer/panel
    ├── SeverityBadge.tsx       ← Colored severity pill
    ├── StatusBadge.tsx         ← Colored status pill
    └── DiagnosisPanel.tsx      ← Diagnosis + confidence + reasoning
```

## Key Requirements

**HealthPage.tsx:**

```tsx
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { ServiceGrid } from '../components/health/ServiceGrid'
import { useAppStore } from '../store'

export function HealthPage() {
  // Initial load from REST API
  const { data, isLoading, error } = useQuery({
    queryKey: ['status'],
    queryFn: api.getStatus,
    refetchInterval: 30_000,   // fallback polling every 30s
  })

  // Real-time override from WebSocket metric_update events
  const wsServices = useAppStore((s) => s.services)
  const services = wsServices.length > 0 ? wsServices : (data?.services ?? [])

  if (isLoading) return <LoadingSpinner />
  if (error) return <ErrorBanner message="Failed to load service status" />

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold mb-4">Infrastructure Health</h1>
      <ServiceGrid services={services} />
    </div>
  )
}
```

**ServiceCard.tsx:**

```tsx
interface Props {
  service: ServiceStatus
}

export function ServiceCard({ service }: Props) {
  // Color coding: green = healthy, amber = warning (cpu/memory > 80%), red = down
  // Show: service name, state badge (running/stopped/error), CPU gauge bar,
  // memory gauge bar, uptime formatted as "2h 15m" or "3d 4h"

  const stateColor = service.healthy
    ? 'bg-green-100 border-green-300'
    : service.state === 'stopped' || service.state === 'error'
    ? 'bg-red-100 border-red-300'
    : 'bg-amber-100 border-amber-300'

  return (
    <div className={`rounded-lg border-2 p-4 ${stateColor}`}>
      <div className="flex items-center justify-between mb-2">
        <span className="font-semibold text-sm">{service.name}</span>
        <StateBadge state={service.state} healthy={service.healthy} />
      </div>
      <GaugeBar label="CPU" value={service.cpu_percent} warnAt={80} />
      <GaugeBar label="MEM" value={service.memory_percent} warnAt={85} />
      <div className="text-xs text-slate-500 mt-2">
        Uptime: {formatUptime(service.uptime_seconds)}
      </div>
      {service.last_error && (
        <div className="text-xs text-red-600 mt-1 truncate" title={service.last_error}>
          {service.last_error}
        </div>
      )}
    </div>
  )
}
```

`GaugeBar`: thin progress bar with label and percentage. Green below warnAt, amber above warnAt, red above 95%.
`StateBadge`: small colored pill — green/running, amber/starting, red/stopped or error.
`formatUptime(seconds)`: `"2h 15m"` format; `"< 1m"` if under 60s; `"3d 4h"` if over 24h.

**ServiceGrid.tsx:**

```tsx
// Responsive grid: 1 col mobile, 2 cols sm, 3 cols lg, 4 cols xl
export function ServiceGrid({ services }: { services: ServiceStatus[] }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
      {services.map((s) => <ServiceCard key={s.name} service={s} />)}
    </div>
  )
}
```

**Shell.tsx WebSocket wiring:** In the Shell, handle `metric_update` events from WebSocket to update service state in Zustand in real-time:

```tsx
useWebSocket({
  onEvent: (event) => {
    if (event.type === 'metric_update') {
      // Update the service in the services array
      const { service, cpu_percent, memory_percent } = event.data as any
      useAppStore.getState().updateServiceMetrics(service, { cpu_percent, memory_percent })
    }
    if (event.type === 'anomaly_detected' || event.type === 'incident_resolved') {
      // Invalidate incidents query to refresh list
      queryClient.invalidateQueries({ queryKey: ['incidents'] })
    }
    if (event.type === 'approval_requested') {
      queryClient.invalidateQueries({ queryKey: ['pending-approvals'] })
    }
  }
})
```

Add `updateServiceMetrics` to the Zustand store.

**IncidentsPage.tsx:**

```tsx
export function IncidentsPage() {
  const { id: selectedId } = useParams()   // incident detail if :id provided
  const [filters, setFilters] = useState({ status: '', severity: '', service: '' })

  const { data, isLoading } = useQuery({
    queryKey: ['incidents', filters],
    queryFn: () => api.listIncidents(filters),
    refetchInterval: 30_000,
  })

  return (
    <div className="p-6 flex gap-6">
      <div className="flex-1">
        <div className="flex items-center justify-between mb-4">
          <h1 className="text-2xl font-bold">Incidents</h1>
          <FilterBar filters={filters} onChange={setFilters} />
        </div>
        <IncidentTable incidents={data?.incidents ?? []} isLoading={isLoading}
                       selectedId={selectedId} />
      </div>
      {selectedId && <IncidentDetail incidentId={selectedId} />}
    </div>
  )
}
```

**IncidentTable.tsx:**

- Table with columns: Severity, Title, Service, Status, Detected, Resolution Time
- Each row is clickable → navigate to `/incidents/:id`
- Selected row highlighted
- Empty state: "No incidents found" with icon
- Loading state: skeleton rows

**SeverityBadge.tsx:**

```tsx
const colors: Record<Severity, string> = {
  LOW: 'bg-blue-100 text-blue-800',
  MEDIUM: 'bg-amber-100 text-amber-800',
  HIGH: 'bg-red-100 text-red-800',
}
export function SeverityBadge({ severity }: { severity: Severity }) {
  return <span className={`px-2 py-0.5 rounded text-xs font-medium ${colors[severity]}`}>{severity}</span>
}
```

**StatusBadge.tsx:**

Colors: `active` → amber, `resolved` → green, `escalated` → red, `denied` → slate.

**IncidentDetail.tsx:**

Side panel (fixed width 480px, slides in from right):
1. Header: title, severity badge, status badge, close button (navigate back)
2. Timing: Detected at, Resolved at (if resolved), Resolution time
3. **Diagnosis panel**: LLM summary, confidence bar (0-100%), playbook matched
4. **Agent reasoning**: `llm_reasoning` text in a scrollable monospace box
5. **Timeline**: chronological list of `actions` with icons per type
   - `approval_requested` → clock icon, amber
   - `approved` → checkmark, green
   - `denied` → X, red
   - `remediation` → wrench, blue
   - `verification` → shield, green/red
6. **Chat link**: "View conversation" → navigates to `/chat/:incidentId`

**DiagnosisPanel.tsx:**

```tsx
export function DiagnosisPanel({ diagnosis }: { diagnosis: Diagnosis }) {
  const confidencePercent = Math.round(diagnosis.confidence * 100)
  const barColor = confidencePercent >= 80 ? 'bg-green-500' :
                   confidencePercent >= 50 ? 'bg-amber-500' : 'bg-red-500'
  return (
    <div className="bg-slate-50 rounded p-3">
      <p className="text-sm">{diagnosis.summary}</p>
      <div className="mt-2 flex items-center gap-2">
        <div className="flex-1 bg-slate-200 rounded h-1.5">
          <div className={`h-1.5 rounded ${barColor}`} style={{ width: `${confidencePercent}%` }} />
        </div>
        <span className="text-xs text-slate-500">{confidencePercent}% confidence</span>
      </div>
      {diagnosis.matched_playbook && (
        <p className="text-xs text-slate-500 mt-1">Playbook: {diagnosis.matched_playbook}</p>
      )}
    </div>
  )
}
```

## Test Criteria

```bash
cd /Users/dattaikhe/LLM/AutoOpsAI/frontend

npm run build
# Expected: no TypeScript errors, build succeeds

# Manual verification (backend must be running):
npm run dev
# → http://localhost:5173/health — service cards visible, colored correctly
# → http://localhost:5173/incidents — incident table with filter bar
# → click an incident → detail panel slides in with diagnosis + timeline
# → severity badges colored correctly (blue/amber/red)
# → WebSocket badge in header shows "connected" (green dot)
```

## Dependencies

- Step 25 (frontend scaffold, api client, WebSocket hook, Zustand store)
- Step 23 (backend incidents + status endpoints)
- Step 21 (WebSocket event stream)
