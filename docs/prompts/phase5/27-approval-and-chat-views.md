# [Step 27] — Approval & Chat Views

## Context

Steps 25-26 are complete. The following exist:
- `frontend/src/api/client.ts` — `api.getPendingApprovals`, `api.approveIncident`, `api.denyIncident`, `api.investigateIncident`, `api.getChatLog`, `api.sendChatMessage`
- `frontend/src/types/api.ts` — `PendingApproval`, `ChatMessage`, `WSEvent`
- `frontend/src/store/index.ts` — `pendingApprovals`, `setPendingApprovals`
- `frontend/src/pages/ApprovalPage.tsx` — placeholder
- `frontend/src/pages/ChatPage.tsx` — placeholder

## Objective

Implement the Approval Queue and Agent Chat views. The approval view renders interactive approval cards with Approve/Deny/Investigate buttons, risk badges, timeout countdowns, and real-time updates via WebSocket. The chat view renders the agent conversation log with approval cards rendered inline as interactive UI blocks.

## Files to Modify

- `frontend/src/pages/ApprovalPage.tsx` — Full implementation.
- `frontend/src/pages/ChatPage.tsx` — Full implementation.

## Files to Create

```
frontend/src/components/
├── approval/
│   ├── ApprovalCard.tsx        ← Full approval card with action buttons
│   ├── ApprovalCardResolved.tsx ← Resolved/denied card (no buttons)
│   ├── RiskBadge.tsx            ← Risk level badge (LOW/MEDIUM/HIGH)
│   └── TimeoutCountdown.tsx     ← Countdown timer for MEDIUM risk
└── chat/
    ├── ChatWindow.tsx           ← Scrollable message history
    ├── ChatBubble.tsx           ← Agent or human message bubble
    ├── InlineApprovalCard.tsx   ← Approval card rendered inside chat
    └── ChatInput.tsx            ← Message input bar with send button
```

## Key Requirements

**ApprovalPage.tsx:**

```tsx
export function ApprovalPage() {
  const { data, isLoading, refetch } = useQuery({
    queryKey: ['pending-approvals'],
    queryFn: api.getPendingApprovals,
    refetchInterval: 15_000,
  })

  // WebSocket: when approval_requested arrives, immediately refetch
  const lastEvent = useAppStore((s) => s.lastEvent)
  useEffect(() => {
    if (lastEvent?.type === 'approval_requested' ||
        lastEvent?.type === 'approval_decision' ||
        lastEvent?.type === 'incident_resolved') {
      refetch()
    }
  }, [lastEvent, refetch])

  const pending = data?.pending ?? []

  return (
    <div className="p-6 max-w-3xl mx-auto">
      <h1 className="text-2xl font-bold mb-6">Approval Queue</h1>
      {isLoading && <LoadingSpinner />}
      {pending.length === 0 && !isLoading && (
        <EmptyState icon="check-circle" message="No pending approvals" />
      )}
      <div className="space-y-4">
        {pending.map((approval) => (
          <ApprovalCard key={approval.incident_id} approval={approval} onAction={refetch} />
        ))}
      </div>
    </div>
  )
}
```

**ApprovalCard.tsx:**

The core UI element. Renders the same information as the Teams Adaptive Card but as a React component.

```tsx
interface Props {
  approval: PendingApproval
  onAction: () => void            // called after approve/deny/investigate
  embedded?: boolean              // true when rendered inside ChatWindow
}

export function ApprovalCard({ approval, onAction, embedded = false }: Props) {
  const [loading, setLoading] = useState<'approve' | 'deny' | 'investigate' | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handleApprove = async () => {
    setLoading('approve')
    try {
      await api.approveIncident(approval.incident_id, 'dashboard-user')
      onAction()
    } catch { setError('Approval failed') }
    finally { setLoading(null) }
  }

  const handleDeny = async () => {
    setLoading('deny')
    try {
      await api.denyIncident(approval.incident_id, 'dashboard-user')
      onAction()
    } catch { setError('Denial failed') }
    finally { setLoading(null) }
  }

  const handleInvestigate = async () => {
    setLoading('investigate')
    try {
      await api.investigateIncident(approval.incident_id)
      onAction()
    } catch { setError('Request failed') }
    finally { setLoading(null) }
  }

  return (
    <div className={`rounded-lg border-2 ${riskBorderColor(approval.severity)} bg-white shadow-sm`}>
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b">
        <div>
          <RiskBadge severity={approval.severity} />
          <h3 className="font-semibold mt-1">{approval.title}</h3>
        </div>
        {approval.timeout_at && (
          <TimeoutCountdown targetTime={approval.timeout_at} />
        )}
      </div>

      {/* Body */}
      <div className="p-4 space-y-3">
        <FactRow label="Proposed Action" value={approval.proposed_action} />
        {approval.rollback_plan && (
          <FactRow label="Rollback Plan" value={approval.rollback_plan} />
        )}
        <FactRow label="Requested" value={formatRelativeTime(approval.requested_at)} />
        {approval.severity === 'MEDIUM' && (
          <p className="text-xs text-amber-700 bg-amber-50 rounded p-2">
            This action will auto-deny if not approved within 5 minutes.
          </p>
        )}
        {approval.severity === 'HIGH' && (
          <p className="text-xs text-red-700 bg-red-50 rounded p-2">
            Explicit approval required — this action will not auto-execute.
          </p>
        )}
        {error && <p className="text-xs text-red-600">{error}</p>}
      </div>

      {/* Action buttons */}
      <div className="flex gap-2 p-4 border-t bg-slate-50">
        <button
          onClick={handleApprove}
          disabled={loading !== null}
          className="flex-1 bg-green-600 text-white rounded px-3 py-2 text-sm font-medium hover:bg-green-700 disabled:opacity-50"
        >
          {loading === 'approve' ? 'Approving...' : 'Approve'}
        </button>
        <button
          onClick={handleDeny}
          disabled={loading !== null}
          className="flex-1 bg-red-600 text-white rounded px-3 py-2 text-sm font-medium hover:bg-red-700 disabled:opacity-50"
        >
          {loading === 'deny' ? 'Denying...' : 'Deny'}
        </button>
        <button
          onClick={handleInvestigate}
          disabled={loading !== null}
          className="flex-1 bg-slate-600 text-white rounded px-3 py-2 text-sm font-medium hover:bg-slate-700 disabled:opacity-50"
        >
          {loading === 'investigate' ? '...' : 'Investigate'}
        </button>
      </div>
    </div>
  )
}
```

**RiskBadge.tsx:**
```tsx
const riskColors: Record<Severity, string> = {
  LOW: 'bg-blue-100 text-blue-800 border-blue-200',
  MEDIUM: 'bg-amber-100 text-amber-800 border-amber-200',
  HIGH: 'bg-red-100 text-red-800 border-red-200',
}
export function RiskBadge({ severity }: { severity: Severity }) {
  return (
    <span className={`px-2 py-0.5 text-xs font-bold rounded border ${riskColors[severity]}`}>
      {severity} RISK
    </span>
  )
}
```

**TimeoutCountdown.tsx:**

Displays a live countdown ("4:32 remaining"). Turns red below 60 seconds.
Updates every second via `setInterval`. When time reaches 0, shows "Timed out".

```tsx
export function TimeoutCountdown({ targetTime }: { targetTime: string }) {
  const [secondsLeft, setSecondsLeft] = useState(() =>
    Math.max(0, Math.floor((new Date(targetTime).getTime() - Date.now()) / 1000))
  )

  useEffect(() => {
    if (secondsLeft <= 0) return
    const id = setInterval(() => setSecondsLeft((s) => Math.max(0, s - 1)), 1000)
    return () => clearInterval(id)
  }, [secondsLeft])

  if (secondsLeft <= 0) return <span className="text-xs text-slate-500">Timed out</span>

  const mins = Math.floor(secondsLeft / 60)
  const secs = secondsLeft % 60
  const color = secondsLeft < 60 ? 'text-red-600 font-bold' : 'text-amber-700'
  return <span className={`text-sm tabular-nums ${color}`}>{mins}:{String(secs).padStart(2, '0')}</span>
}
```

**ChatPage.tsx:**

```tsx
export function ChatPage() {
  const { incidentId } = useParams()
  const [message, setMessage] = useState('')
  const [sending, setSending] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  const { data } = useQuery({
    queryKey: ['chat', incidentId],
    queryFn: () => incidentId ? api.getChatLog(incidentId) : null,
    enabled: !!incidentId,
    refetchInterval: 10_000,
  })

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [data?.messages])

  const handleSend = async () => {
    if (!message.trim()) return
    setSending(true)
    try {
      await api.sendChatMessage(message)
      setMessage('')
    } finally { setSending(false) }
  }

  if (!incidentId) {
    return (
      <div className="p-6">
        <h1 className="text-2xl font-bold mb-4">Agent Chat</h1>
        <p className="text-slate-500">Select an incident to view its conversation, or ask the agent about current system state below.</p>
        <ChatInput value={message} onChange={setMessage} onSend={handleSend} disabled={sending} />
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full p-6">
      <h1 className="text-xl font-bold mb-4">Incident Chat — {incidentId}</h1>
      <ChatWindow messages={data?.messages ?? []} />
      <div ref={bottomRef} />
      <ChatInput value={message} onChange={setMessage} onSend={handleSend} disabled={sending} />
    </div>
  )
}
```

**ChatWindow.tsx:**

Scrollable container rendering `ChatBubble` for each message. Messages with `type="approval_card"` render `InlineApprovalCard` instead of a bubble.

**ChatBubble.tsx:**

- Agent messages: left-aligned, slate background, robot icon
- Human messages: right-aligned, blue background
- Timestamp shown as relative time ("2 minutes ago")

**InlineApprovalCard.tsx:**

Renders the approval card inline inside the chat stream. Same data as `ApprovalCard` but compact (no border, smaller padding). When the card's `approval.incident_id` appears in the pending approvals list, shows Approve/Deny/Investigate buttons. When resolved/denied, renders `ApprovalCardResolved` (outcome badge + approver name).

**ChatInput.tsx:**

```tsx
export function ChatInput({ value, onChange, onSend, disabled }: ChatInputProps) {
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      onSend()
    }
  }
  return (
    <div className="flex gap-2 mt-4">
      <textarea
        className="flex-1 border rounded px-3 py-2 text-sm resize-none"
        rows={2}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Ask the agent about current system state..."
        disabled={disabled}
      />
      <button
        onClick={onSend}
        disabled={disabled || !value.trim()}
        className="bg-blue-600 text-white px-4 rounded hover:bg-blue-700 disabled:opacity-50"
      >
        Send
      </button>
    </div>
  )
}
```

## Test Criteria

```bash
cd /Users/dattaikhe/LLM/AutoOpsAI/frontend

npm run build
# Expected: no TypeScript errors

npm run dev
# → http://localhost:5173/approvals
#   - Empty state shown when no pending approvals
#   - When backend has a pending approval: card visible with correct title,
#     risk badge, proposed action, and three buttons
#   - MEDIUM risk card shows countdown timer
#   - Clicking Approve: button shows "Approving...", card disappears after success

# → http://localhost:5173/chat/inc_XXXXX (with a valid incident ID)
#   - Agent messages shown left-aligned
#   - Human actions (approve/deny) shown right-aligned
#   - approval_card messages rendered as inline card (not as text bubble)
#   - Auto-scrolls to bottom

# WebSocket integration:
#   - When a new incident is detected: approval card appears in /approvals
#     without manual refresh (via WebSocket approval_requested event)
```

## Dependencies

- Step 25 (frontend scaffold, api client, Zustand store, WebSocket hook)
- Step 26 (SeverityBadge, StatusBadge, shared layout components)
- Step 23 (approval endpoints, chat endpoints)
