import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { RefreshCw } from 'lucide-react';
import { useApp } from '../store';
import SeverityBadge from '../components/SeverityBadge';
import StatusBadge from '../components/StatusBadge';
import { formatTime } from '../utils';
import * as api from '../api';

export default function Incidents() {
  const { incidents, addToast, refresh } = useApp();
  const navigate = useNavigate();
  const [filterStatus, setFilterStatus] = useState('');
  const [filterSeverity, setFilterSeverity] = useState('');

  let list = incidents;
  if (filterStatus) list = list.filter(i => i.status === filterStatus);
  if (filterSeverity) list = list.filter(i => i.severity === filterSeverity);

  const TERMINAL = ['resolved', 'failed', 'escalated', 'denied'];

  const handleEscalate = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    try {
      await api.escalateIncident(id);
      addToast('Incident escalated', 'success');
      refresh();
    } catch (err) {
      addToast(`Escalation failed: ${err instanceof Error ? err.message : 'Unknown'}`, 'error');
    }
  };

  const handleApprove = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    try {
      await api.approvalDecision(id, 'approve');
      addToast('Incident approved — analyzing logs...', 'success');
      await refresh();
      navigate(`/incidents/${id}`);
    } catch (err) {
      addToast(`Approval failed: ${err instanceof Error ? err.message : 'Unknown'}`, 'error');
    }
  };

  const handleDeny = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    try {
      await api.approvalDecision(id, 'deny');
      addToast('Incident denied', 'success');
      refresh();
    } catch (err) {
      addToast(`Deny failed: ${err instanceof Error ? err.message : 'Unknown'}`, 'error');
    }
  };

  return (
    <div>
      <div className="page-header">
        <h2>Incidents</h2>
        <div className="filters">
          <select value={filterStatus} onChange={e => setFilterStatus(e.target.value)}>
            <option value="">All Statuses</option>
            <option value="detecting">Detecting</option>
            <option value="diagnosing">Diagnosing</option>
            <option value="awaiting_approval">Awaiting Approval</option>
            <option value="approved">Approved</option>
            <option value="executing">Executing</option>
            <option value="resolved">Resolved</option>
            <option value="failed">Failed</option>
            <option value="escalated">Escalated</option>
          </select>
          <select value={filterSeverity} onChange={e => setFilterSeverity(e.target.value)}>
            <option value="">All Severities</option>
            <option value="HIGH">High</option>
            <option value="MEDIUM">Medium</option>
            <option value="LOW">Low</option>
          </select>
          <button className="btn btn-sm btn-secondary" onClick={() => refresh()}>
            <RefreshCw size={14} /> Refresh
          </button>
        </div>
      </div>

      <table className="data-table">
        <thead>
          <tr>
            <th>Severity</th>
            <th>Title</th>
            <th>Service</th>
            <th>Status</th>
            <th>Detected</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {list.length === 0 ? (
            <tr>
              <td colSpan={6} className="muted">
                No incidents match filters
              </td>
            </tr>
          ) : (
            list.map(i => (
              <tr key={i.incident_id} className="clickable-row" onClick={() => navigate(`/incidents/${i.incident_id}`)}>
                <td><SeverityBadge severity={i.severity} /></td>
                <td className="accent-link">{i.title}</td>
                <td>{i.service_name}</td>
                <td><StatusBadge status={i.status} /></td>
                <td className="mono small">{formatTime(i.detected_at)}</td>
                <td className="actions-cell" onClick={e => e.stopPropagation()}>
                  {!TERMINAL.includes(i.status) && (
                    <>
                      <button
                        className="btn btn-sm btn-success"
                        title="Approve this incident"
                        onClick={e => handleApprove(e, i.incident_id)}
                      >
                        Approve
                      </button>
                      <button
                        className="btn btn-sm btn-danger"
                        title="Deny this incident"
                        onClick={e => handleDeny(e, i.incident_id)}
                      >
                        Deny
                      </button>
                      <button
                        className="btn btn-sm btn-warning"
                        title="Escalate this incident"
                        onClick={e => handleEscalate(e, i.incident_id)}
                      >
                        Escalate
                      </button>
                    </>
                  )}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
