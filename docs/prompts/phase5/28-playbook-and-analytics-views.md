# [Step 28] — Playbook & Analytics Views

## Context

Steps 25-27 are complete. The following exist:
- `frontend/src/api/client.ts` — `api.listPlaybooks`, `api.getPlaybook`, `api.createPlaybook`, `api.updatePlaybook`, `api.deletePlaybook`
- `frontend/src/types/api.ts` — `PlaybookSummary`
- `frontend/src/pages/PlaybooksPage.tsx` — placeholder
- `frontend/src/pages/AnalyticsPage.tsx` — placeholder

## Objective

Implement the Playbook Manager and Analytics views. Playbooks: browsable list, YAML viewer, create/edit/delete. Analytics: MTTR trend, incident severity breakdown, resolution rate charts using Recharts.

## Files to Modify

- `frontend/src/pages/PlaybooksPage.tsx` — Full implementation.
- `frontend/src/pages/AnalyticsPage.tsx` — Full implementation.

## Files to Create

```
frontend/src/components/
├── playbooks/
│   ├── PlaybookList.tsx         ← Searchable list of playbooks
│   ├── PlaybookDetail.tsx       ← Rendered playbook view
│   └── PlaybookEditor.tsx       ← YAML textarea + save/delete
└── analytics/
    ├── MTTRChart.tsx             ← Line chart: avg resolution time over time
    ├── SeverityPieChart.tsx      ← Pie chart: incidents by severity
    ├── ResolutionRateBar.tsx     ← Bar chart: auto-resolved vs human-approved
    └── StatCard.tsx              ← Single metric card (total incidents, avg MTTR, etc.)
```

## Key Requirements

**PlaybooksPage.tsx:**

```tsx
export function PlaybooksPage() {
  const [search, setSearch] = useState('')
  const [severityFilter, setSeverityFilter] = useState('')
  const [selected, setSelected] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [showCreate, setShowCreate] = useState(false)

  const { data, refetch } = useQuery({
    queryKey: ['playbooks', { severity: severityFilter }],
    queryFn: () => api.listPlaybooks({ severity: severityFilter }),
  })

  const filtered = (data?.playbooks ?? []).filter((p) =>
    p.name.toLowerCase().includes(search.toLowerCase()) ||
    p.id.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div className="p-6 flex gap-6 h-full">
      {/* Left: list */}
      <div className="w-80 flex-shrink-0">
        <div className="flex items-center justify-between mb-3">
          <h1 className="text-xl font-bold">Playbooks</h1>
          <button onClick={() => setShowCreate(true)}
                  className="text-xs bg-blue-600 text-white px-2 py-1 rounded">+ New</button>
        </div>
        <input
          className="w-full border rounded px-2 py-1 text-sm mb-2"
          placeholder="Search playbooks..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select className="w-full border rounded px-2 py-1 text-sm mb-3"
                value={severityFilter} onChange={(e) => setSeverityFilter(e.target.value)}>
          <option value="">All severities</option>
          <option value="LOW">LOW</option>
          <option value="MEDIUM">MEDIUM</option>
          <option value="HIGH">HIGH</option>
        </select>
        <PlaybookList playbooks={filtered} selectedId={selected}
                      onSelect={(id) => { setSelected(id); setEditing(false) }} />
      </div>

      {/* Right: detail or editor */}
      <div className="flex-1">
        {showCreate && (
          <PlaybookEditor mode="create" onSave={() => { setShowCreate(false); refetch() }}
                          onCancel={() => setShowCreate(false)} />
        )}
        {selected && !showCreate && !editing && (
          <PlaybookDetail playbookId={selected}
                          onEdit={() => setEditing(true)}
                          onDelete={() => { setSelected(null); refetch() }} />
        )}
        {selected && editing && (
          <PlaybookEditor mode="edit" playbookId={selected}
                          onSave={() => { setEditing(false); refetch() }}
                          onCancel={() => setEditing(false)} />
        )}
        {!selected && !showCreate && (
          <EmptyState icon="book-open" message="Select a playbook to view details" />
        )}
      </div>
    </div>
  )
}
```

**PlaybookList.tsx:**

Vertical list of playbook entries. Each item shows: name, severity badge, detection type chip (container_health / metric_threshold / log_pattern). Highlight selected item.

**PlaybookDetail.tsx:**

Fetch full playbook via `api.getPlaybook(id)`. Display:
- Title, severity badge, provider scope
- **Detection**: type + condition summary (human-readable, not raw YAML)
- **Remediation steps**: numbered list of `{action}: {target} — {params}`
- **Rollback**: description + steps
- **Tags**: small pill chips
- Edit button (top right) → triggers `onEdit`
- Delete button (danger, with confirmation dialog) → calls `api.deletePlaybook`, then `onDelete`

**PlaybookEditor.tsx:**

```tsx
// Simple YAML editor — textarea with monospace font, no syntax highlighting library required
// For create: blank template pre-filled with minimal valid playbook structure
// For edit: fetches existing playbook as JSON, converts to YAML string for display

const BLANK_TEMPLATE = `id: new_playbook
name: "New Playbook"
severity: MEDIUM
detection:
  type: container_health
  conditions:
    - service_name: "service-name"
      state: stopped
remediation:
  steps:
    - action: restart_service
      target: "service-name"
rollback:
  description: "Manual rollback"
  steps: []
`

export function PlaybookEditor({ mode, playbookId, onSave, onCancel }: EditorProps) {
  const [yaml, setYaml] = useState(BLANK_TEMPLATE)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // For edit mode, fetch and convert to YAML string
  // ... (use js-yaml library: add "js-yaml" to package.json)

  const handleSave = async () => {
    setSaving(true)
    setError(null)
    try {
      // Parse YAML → validate → POST or PUT
      const parsed = jsYaml.load(yaml) as Record<string, unknown>
      if (mode === 'create') {
        await api.createPlaybook(parsed)
      } else {
        await api.updatePlaybook(playbookId!, parsed)
      }
      onSave()
    } catch (e: any) {
      setError(e.message || 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <h2 className="font-bold">{mode === 'create' ? 'New Playbook' : 'Edit Playbook'}</h2>
        <div className="flex gap-2">
          <button onClick={onCancel} className="text-sm text-slate-600">Cancel</button>
          <button onClick={handleSave} disabled={saving}
                  className="text-sm bg-blue-600 text-white px-3 py-1 rounded">
            {saving ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>
      <textarea
        className="w-full h-96 font-mono text-sm border rounded p-3"
        value={yaml}
        onChange={(e) => setYaml(e.target.value)}
        spellCheck={false}
      />
      {error && <p className="text-red-600 text-sm mt-2">{error}</p>}
    </div>
  )
}
```

Add `js-yaml` and `@types/js-yaml` to package.json.

**AnalyticsPage.tsx:**

```tsx
export function AnalyticsPage() {
  const { data: allIncidents } = useQuery({
    queryKey: ['incidents-all'],
    queryFn: () => api.listIncidents({ limit: 200 }),
    refetchInterval: 60_000,
  })

  const incidents = allIncidents?.incidents ?? []

  // Derived metrics
  const resolved = incidents.filter((i) => i.status === 'resolved')
  const avgMTTR = resolved.length > 0
    ? resolved.reduce((sum, i) => sum + (i.resolution_time_seconds ?? 0), 0) / resolved.length
    : 0
  const autoResolved = resolved.filter((i) => i.auto_resolved).length
  const humanApproved = resolved.filter((i) => !i.auto_resolved).length

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold mb-6">Analytics</h1>

      {/* Summary stat cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <StatCard label="Total Incidents" value={incidents.length} />
        <StatCard label="Resolved" value={resolved.length} />
        <StatCard label="Avg MTTR" value={formatDuration(avgMTTR)} />
        <StatCard label="Auto-Resolved" value={`${autoResolved} / ${resolved.length}`} />
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="bg-white rounded-lg border p-4">
          <h2 className="font-semibold mb-3">By Severity</h2>
          <SeverityPieChart incidents={incidents} />
        </div>
        <div className="bg-white rounded-lg border p-4">
          <h2 className="font-semibold mb-3">Resolution Rate</h2>
          <ResolutionRateBar autoResolved={autoResolved} humanApproved={humanApproved}
                             escalated={incidents.filter(i => i.status === 'escalated').length} />
        </div>
        <div className="bg-white rounded-lg border p-4 col-span-1 lg:col-span-1">
          <h2 className="font-semibold mb-3">MTTR Trend</h2>
          <MTTRChart incidents={resolved} />
        </div>
      </div>
    </div>
  )
}
```

**StatCard.tsx:**

Large number + label, optional trend arrow (up/down). Simple white card with border.

**SeverityPieChart.tsx:**

```tsx
import { PieChart, Pie, Cell, Legend, Tooltip } from 'recharts'

const COLORS: Record<string, string> = { LOW: '#3b82f6', MEDIUM: '#f59e0b', HIGH: '#ef4444' }

export function SeverityPieChart({ incidents }: { incidents: Incident[] }) {
  const counts = incidents.reduce((acc, i) => {
    acc[i.severity] = (acc[i.severity] ?? 0) + 1
    return acc
  }, {} as Record<string, number>)

  const data = Object.entries(counts).map(([name, value]) => ({ name, value }))

  if (data.length === 0) return <EmptyState message="No data yet" />

  return (
    <PieChart width={200} height={200}>
      <Pie data={data} cx={100} cy={100} outerRadius={80} dataKey="value" label>
        {data.map((entry) => <Cell key={entry.name} fill={COLORS[entry.name] ?? '#8884d8'} />)}
      </Pie>
      <Tooltip />
      <Legend />
    </PieChart>
  )
}
```

**ResolutionRateBar.tsx:**

Horizontal stacked bar: auto-resolved (blue) / human-approved (green) / escalated (red). Use Recharts `BarChart` with a single stacked bar.

**MTTRChart.tsx:**

Line chart: X-axis = date (last 30 days, bucketed by day), Y-axis = avg resolution time in seconds. Use Recharts `LineChart`. Group `resolved` incidents by day, compute average MTTR per day. Show empty state if fewer than 2 data points.

```tsx
function groupByDay(incidents: Incident[]) {
  const byDay: Record<string, number[]> = {}
  for (const i of incidents) {
    if (!i.resolution_time_seconds || !i.resolved_at) continue
    const day = i.resolved_at.slice(0, 10)   // "2026-03-31"
    byDay[day] = byDay[day] ?? []
    byDay[day].push(i.resolution_time_seconds)
  }
  return Object.entries(byDay)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, times]) => ({
      date,
      avgMTTR: Math.round(times.reduce((s, t) => s + t, 0) / times.length),
    }))
}
```

**`frontend/package.json` additions:**
Add `js-yaml` and `@types/js-yaml` to dependencies.

## Test Criteria

```bash
cd /Users/dattaikhe/LLM/AutoOpsAI/frontend

npm install
# js-yaml installs without errors

npm run build
# No TypeScript errors

npm run dev
# → http://localhost:5173/playbooks
#   - Playbook list shows all loaded playbooks
#   - Severity filter works
#   - Click playbook → detail panel shows detection + remediation + rollback
#   - "New" button → editor with blank YAML template
#   - Edit existing → YAML pre-populated, Save works
#   - Delete with confirmation → playbook removed from list

# → http://localhost:5173/analytics
#   - Stat cards show correct counts (even if 0)
#   - Severity pie chart renders (or empty state)
#   - Resolution rate bar renders
#   - MTTR line chart renders (or empty state if < 2 data points)
```

**Phase 5 exit criteria:** All 4 views functional. Real-time WebSocket updates working in Health and Approvals views. Playbook CRUD operational. Analytics charts render with live data.

## Dependencies

- Step 25 (frontend scaffold, api client, Zustand)
- Step 26 (shared components: SeverityBadge, EmptyState, LoadingSpinner)
- Step 23 (playbooks API, incidents API)
