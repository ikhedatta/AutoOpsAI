import {
  Server,
  AlertTriangle,
  Clock,
  Database,
  Cpu,
  Users,
} from 'lucide-react';
import { useApp } from '../store';
import { formatTime } from '../utils';
import SeverityBadge from '../components/SeverityBadge';
import StatusBadge from '../components/StatusBadge';
import { useNavigate } from 'react-router-dom';

export default function Overview() {
  const { health, services, incidents, approvals, events } = useApp();
  const navigate = useNavigate();

  const svcList = Object.values(services);
  const svcCount = svcList.length;
  const runningCount = svcList.filter(s => s.state === 'running').length;
  const activeIncidents = incidents.filter(
    i => !['resolved', 'failed', 'denied', 'denied_timeout'].includes(i.status)
  ).length;

  return (
    <div className="page-overview">
      <h2>System Overview</h2>

      {/* Stat cards */}
      <div className="card-grid">
        <StatCard
          icon={<Server size={20} />}
          label="Services"
          value={svcCount > 0 ? `${runningCount}/${svcCount}` : '—'}
          sub={svcCount > 0 ? 'running' : 'Provider degraded'}
          color={runningCount === svcCount ? 'var(--green)' : 'var(--yellow)'}
        />
        <StatCard
          icon={<AlertTriangle size={20} />}
          label="Active Incidents"
          value={String(activeIncidents)}
          sub={`${incidents.length} total`}
          color={activeIncidents ? 'var(--red)' : 'var(--green)'}
        />
        <StatCard
          icon={<Clock size={20} />}
          label="Pending Approvals"
          value={String(approvals.length)}
          sub="awaiting decision"
          color={approvals.length ? 'var(--yellow)' : 'var(--green)'}
        />
        <StatCard
          icon={<Cpu size={20} />}
          label="Ollama"
          value={health?.components.ollama ? 'Online' : 'Offline'}
          sub={`${health?.components.provider || 'unknown'} provider`}
          color={health?.components.ollama ? 'var(--green)' : 'var(--red)'}
        />
        <StatCard
          icon={<Database size={20} />}
          label="Database"
          value={health?.components.database ? 'Connected' : 'Down'}
          sub="MongoDB"
          color={health?.components.database ? 'var(--green)' : 'var(--red)'}
        />
        <StatCard
          icon={<Users size={20} />}
          label="WS Clients"
          value={String(health?.components.websocket_clients ?? 0)}
          sub="connected"
          color="var(--accent)"
        />
      </div>

      {/* Two columns: services + recent incidents */}
      <div className="section-row">
        <div className="section-col">
          <h3>Services</h3>
          {svcList.length === 0 ? (
            <p className="muted">No services discovered</p>
          ) : (
            <div className="services-grid">
              {svcList.map(s => (
                <div key={s.name} className="service-card">
                  <span className={`svc-dot ${s.state}`} />
                  <span className="svc-name">{s.name}</span>
                  <span className="svc-state">{s.state}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="section-col">
          <h3>Recent Incidents</h3>
          {incidents.length === 0 ? (
            <p className="muted">No incidents recorded</p>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Sev</th>
                  <th>Title</th>
                  <th>Status</th>
                  <th>Time</th>
                </tr>
              </thead>
              <tbody>
                {incidents.slice(0, 8).map(i => (
                  <tr
                    key={i.incident_id}
                    className="clickable-row"
                    onClick={() => navigate(`/incidents/${i.incident_id}`)}
                  >
                    <td><SeverityBadge severity={i.severity} /></td>
                    <td>{i.title}</td>
                    <td><StatusBadge status={i.status} /></td>
                    <td className="mono small">{formatTime(i.detected_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Live event feed */}
      <div className="section-row">
        <div className="section-col wide">
          <h3>Live Event Feed</h3>
          <div className="event-feed">
            {events.length === 0 ? (
              <p className="muted">Waiting for events…</p>
            ) : (
              events.slice(0, 50).map((e, idx) => {
                const time = new Date(e.timestamp).toLocaleTimeString([], {
                  hour: '2-digit',
                  minute: '2-digit',
                  second: '2-digit',
                });
                return (
                  <div key={idx} className="event-item">
                    <span className="event-time">{time}</span>
                    <span className="event-type">{e.event_type}</span>
                    <span className="event-detail">{summarizeEvent(e)}</span>
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function StatCard({
  icon,
  label,
  value,
  sub,
  color,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  sub: string;
  color: string;
}) {
  return (
    <div className="stat-card">
      <div className="stat-header">
        <span className="stat-icon">{icon}</span>
        <span className="stat-label">{label}</span>
      </div>
      <div className="stat-value" style={{ color }}>
        {value}
      </div>
      <div className="stat-sub">{sub}</div>
    </div>
  );
}

function summarizeEvent(e: import('../types').WSEvent): string {
  const d = e.data || {};
  switch (e.event_type) {
    case 'incident_detected':
      return `${d.severity} — ${d.title || d.service}`;
    case 'incident_diagnosing':
      return `Confidence: ${(((d.confidence as number) || 0) * 100).toFixed(0)}%`;
    case 'approval_requested':
      return `${d.severity} — ${((d.proposed_actions as unknown[]) || []).length} actions`;
    case 'incident_approved':
      return `by ${d.approved_by}`;
    case 'incident_denied':
      return `by ${d.denied_by}: ${d.reason || ''}`;
    case 'incident_executing':
      return `${d.action_count} action(s)`;
    case 'incident_resolved':
      return `duration: ${d.duration_seconds}s`;
    case 'incident_failed':
      return String(d.reason || '');
    case 'service_status_changed':
      return `${d.service}: ${d.old_state} → ${d.new_state}`;
    case 'metric_anomaly':
      return `${d.service} ${d.metric}: ${d.value} (threshold: ${d.threshold})`;
    default:
      return JSON.stringify(d).slice(0, 120);
  }
}
