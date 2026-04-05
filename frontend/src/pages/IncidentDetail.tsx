import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, CheckCircle2, XCircle, Search, ArrowUpCircle } from 'lucide-react';
import type { Incident } from '../types';
import * as api from '../api';
import { useApp } from '../store';
import SeverityBadge from '../components/SeverityBadge';
import StatusBadge from '../components/StatusBadge';
import { formatTime } from '../utils';

export default function IncidentDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { addToast, refresh } = useApp();
  const [incident, setIncident] = useState<Incident | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    api.getIncident(id)
      .then(setIncident)
      .catch(err => setError(err.message))
      .finally(() => setLoading(false));
  }, [id]);

  const handleDecision = async (decision: 'approve' | 'deny' | 'investigate') => {
    if (!id) return;
    try {
      await api.approvalDecision(id, decision);
      addToast(`Incident ${decision}d`, 'success');
      refresh();
      // Reload detail
      const updated = await api.getIncident(id);
      setIncident(updated);
    } catch (err) {
      addToast(`Action failed: ${err instanceof Error ? err.message : 'Unknown'}`, 'error');
    }
  };

  const handleEscalate = async () => {
    if (!id) return;
    try {
      await api.escalateIncident(id);
      addToast('Incident escalated', 'success');
      refresh();
      const updated = await api.getIncident(id);
      setIncident(updated);
    } catch (err) {
      addToast(`Escalation failed: ${err instanceof Error ? err.message : 'Unknown'}`, 'error');
    }
  };

  if (loading) return <div className="muted">Loading incident…</div>;
  if (error) return <div className="error-text">Error: {error}</div>;
  if (!incident) return <div className="muted">Incident not found</div>;

  const inc = incident;

  return (
    <div>
      <div className="page-header">
        <button className="btn btn-sm btn-ghost" onClick={() => navigate('/incidents')}>
          <ArrowLeft size={16} /> Back
        </button>
        <h2>{inc.title}</h2>
      </div>

      <div className="detail-grid">
        {/* Main column */}
        <div>
          {/* Info */}
          <div className="detail-section">
            <h4>Incident Info</h4>
            <div className="detail-fields-grid">
              <Field label="ID" value={inc.incident_id} />
              <Field label="Service" value={inc.service_name} />
              <Field label="Severity"><SeverityBadge severity={inc.severity} /></Field>
              <Field label="Status"><StatusBadge status={inc.status} /></Field>
              <Field label="Anomaly Type" value={inc.anomaly_type || '—'} />
              <Field label="Metric" value={inc.metric || '—'} />
              <Field label="Value" value={inc.current_value != null ? String(inc.current_value) : '—'} />
              <Field label="Threshold" value={inc.threshold != null ? String(inc.threshold) : '—'} />
              <Field label="Detected" value={formatTime(inc.detected_at)} />
              <Field label="Resolved" value={inc.resolved_at ? formatTime(inc.resolved_at) : '—'} />
            </div>
          </div>

          {/* Evidence */}
          <div className="detail-section">
            <h4>Evidence</h4>
            <pre className="evidence-block">{inc.evidence || 'None'}</pre>
          </div>

          {/* Diagnosis */}
          {inc.diagnosis && (
            <div className="detail-section">
              <h4>Diagnosis</h4>
              <Field label="Summary" value={inc.diagnosis.summary} />
              <Field label="Explanation" value={inc.diagnosis.explanation} />
              <Field label="Confidence" value={`${((inc.diagnosis.confidence || 0) * 100).toFixed(0)}%`} />
              <Field label="Root Cause" value={inc.diagnosis.root_cause || '—'} />
              <Field label="Playbook" value={inc.diagnosis.playbook_id || 'None (novel issue)'} />
            </div>
          )}

          {/* Proposed Actions */}
          {inc.proposed_actions && inc.proposed_actions.length > 0 && (
            <div className="detail-section">
              <h4>Proposed Actions</h4>
              <ul className="actions-list">
                {inc.proposed_actions.map((a, idx) => (
                  <li key={idx}>
                    {a.description || a.action_type} → <strong>{a.target}</strong>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Action Results */}
          {inc.action_results && inc.action_results.length > 0 && (
            <div className="detail-section">
              <h4>Action Results</h4>
              {inc.action_results.map((r, idx) => (
                <div key={idx} className="action-result">
                  <span className={r.success ? 'result-success' : 'result-failure'}>
                    {r.success ? '✓' : '✕'}
                  </span>
                  <span className="mono small">{r.action_id}</span>
                  {r.output && <pre className="result-output">{r.output}</pre>}
                  {r.error && <pre className="result-error">{r.error}</pre>}
                </div>
              ))}
            </div>
          )}

          {/* Chat history */}
          {inc.chat && inc.chat.length > 0 && (
            <div className="detail-section">
              <h4>Conversation</h4>
              {inc.chat.map((m, idx) => (
                <div key={idx} className={`chat-msg ${m.role}`}>
                  <div className="chat-bubble">{m.content}</div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Sidebar column */}
        <div>
          {/* Timeline */}
          <div className="detail-section">
            <h4>Timeline</h4>
            {inc.timeline && inc.timeline.length > 0 ? (
              <ul className="timeline-list">
                {inc.timeline.map((t, idx) => (
                  <li key={idx}>
                    <div className="tl-time">{formatTime(t.timestamp)}</div>
                    <div className="tl-event">{t.event}</div>
                    {t.detail && <div className="tl-detail">{t.detail}</div>}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">No timeline events</p>
            )}
          </div>

          {/* Quick Actions */}
          <div className="detail-section">
            <h4>Quick Actions</h4>
            <div className="quick-actions">
              {inc.status === 'awaiting_approval' && (
                <>
                  <button className="btn btn-success" onClick={() => handleDecision('approve')}>
                    <CheckCircle2 size={16} /> Approve
                  </button>
                  <button className="btn btn-danger" onClick={() => handleDecision('deny')}>
                    <XCircle size={16} /> Deny
                  </button>
                  <button className="btn btn-secondary" onClick={() => handleDecision('investigate')}>
                    <Search size={16} /> Investigate
                  </button>
                </>
              )}
              {!['resolved', 'failed', 'escalated', 'denied'].includes(inc.status) && (
                <button className="btn btn-warning" onClick={handleEscalate}>
                  <ArrowUpCircle size={16} /> Escalate
                </button>
              )}
            </div>
          </div>

          {/* Approval Info */}
          {inc.approval && (
            <div className="detail-section">
              <h4>Approval</h4>
              <Field label="Decision" value={inc.approval.decision || 'Pending'} />
              <Field label="By" value={inc.approval.approved_by || '—'} />
              <Field label="At" value={inc.approval.decided_at ? formatTime(inc.approval.decided_at) : '—'} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Field({ label, value, children }: { label: string; value?: string; children?: React.ReactNode }) {
  return (
    <div className="detail-field">
      <div className="df-label">{label}</div>
      <div className="df-value">{children || value}</div>
    </div>
  );
}
