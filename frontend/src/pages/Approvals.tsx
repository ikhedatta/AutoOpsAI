import { CheckCircle2, XCircle, Search } from 'lucide-react';
import { useApp } from '../store';
import SeverityBadge from '../components/SeverityBadge';
import { formatTime } from '../utils';
import * as api from '../api';

export default function Approvals() {
  const { approvals, addToast, refresh } = useApp();

  const handleDecision = async (id: string, decision: 'approve' | 'deny' | 'investigate') => {
    try {
      await api.approvalDecision(id, decision);
      addToast(`${decision === 'approve' ? 'Approved' : decision === 'deny' ? 'Denied' : 'Investigating'}`, 'success');
      refresh();
    } catch (err) {
      addToast(`Action failed: ${err instanceof Error ? err.message : 'Unknown'}`, 'error');
    }
  };

  return (
    <div>
      <h2>Pending Approvals</h2>
      {approvals.length === 0 ? (
        <p className="muted">No pending approvals</p>
      ) : (
        <div className="approvals-list">
          {approvals.map(a => (
            <div key={a.incident_id} className={`approval-card sev-${a.severity.toLowerCase()}-border`}>
              <div className="approval-header">
                <SeverityBadge severity={a.severity} />
                <span className="approval-title">{a.title}</span>
                <span className="mono small dim">{formatTime(a.detected_at)}</span>
              </div>
              <p className="approval-summary">{a.diagnosis.summary}</p>
              {a.diagnosis.root_cause && (
                <p className="approval-root-cause">Root cause: {a.diagnosis.root_cause}</p>
              )}
              {a.proposed_actions && a.proposed_actions.length > 0 && (
                <>
                  <strong className="approval-actions-label">Proposed Actions:</strong>
                  <ul className="approval-actions-list">
                    {a.proposed_actions.map((act, idx) => (
                      <li key={idx}>{act.description || `${act.action_type} → ${act.target}`}</li>
                    ))}
                  </ul>
                </>
              )}
              {a.rollback_plan && (
                <div className="approval-rollback">Rollback: {a.rollback_plan}</div>
              )}
              <div className="approval-buttons">
                <button className="btn btn-sm btn-success" onClick={() => handleDecision(a.incident_id, 'approve')}>
                  <CheckCircle2 size={14} /> Approve
                </button>
                <button className="btn btn-sm btn-danger" onClick={() => handleDecision(a.incident_id, 'deny')}>
                  <XCircle size={14} /> Deny
                </button>
                <button className="btn btn-sm btn-secondary" onClick={() => handleDecision(a.incident_id, 'investigate')}>
                  <Search size={14} /> Investigate
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
