import { useEffect, useState } from 'react';
import { RefreshCw, ChevronDown, ChevronRight } from 'lucide-react';
import type { Playbook } from '../types';
import * as api from '../api';
import { useApp } from '../store';
import SeverityBadge from '../components/SeverityBadge';

export default function Playbooks() {
  const { addToast } = useApp();
  const [playbooks, setPlaybooks] = useState<Playbook[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const load = async () => {
    setLoading(true);
    try {
      const data = await api.getPlaybooks();
      setPlaybooks(data);
    } catch (err) {
      addToast(`Failed to load playbooks: ${err instanceof Error ? err.message : 'Unknown'}`, 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleReload = async () => {
    try {
      await api.reloadPlaybooks();
      addToast('Playbooks reloaded', 'success');
      load();
    } catch (err) {
      addToast(`Reload failed: ${err instanceof Error ? err.message : 'Unknown'}`, 'error');
    }
  };

  const toggleExpand = async (id: string) => {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  return (
    <div>
      <div className="page-header">
        <h2>Playbooks</h2>
        <button className="btn btn-sm btn-secondary" onClick={handleReload}>
          <RefreshCw size={14} /> Reload
        </button>
      </div>

      {loading ? (
        <p className="muted">Loading playbooks…</p>
      ) : playbooks.length === 0 ? (
        <p className="muted">No playbooks loaded</p>
      ) : (
        <div className="playbook-grid">
          {playbooks.map(p => (
            <div key={p.id} className={`playbook-card ${expanded.has(p.id) ? 'expanded' : ''}`}>
              <div className="pb-name">{p.name}</div>
              <div className="pb-meta">
                <SeverityBadge severity={p.severity} />
                <span>{p.provider}</span>
                <span>{p.detection_type}</span>
              </div>
              {p.tags && p.tags.length > 0 && (
                <div className="pb-tags">
                  {p.tags.map(t => (
                    <span key={t} className="pb-tag">{t}</span>
                  ))}
                </div>
              )}
              <button className="pb-toggle" onClick={() => toggleExpand(p.id)}>
                {expanded.has(p.id) ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                {expanded.has(p.id) ? 'Hide details' : 'Show details'}
              </button>
              {expanded.has(p.id) && (
                <div className="pb-detail">
                  {p.description && <p>{p.description}</p>}
                  {p.actions && p.actions.length > 0 && (
                    <ul>
                      {p.actions.map((a, idx) => (
                        <li key={idx}>{a.description || `${a.action_type} → ${a.target}`}</li>
                      ))}
                    </ul>
                  )}
                  {!p.description && (!p.actions || p.actions.length === 0) && (
                    <p className="muted">No additional details</p>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
