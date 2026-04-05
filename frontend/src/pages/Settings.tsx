import { useEffect, useState } from 'react';
import type { AgentConfig } from '../types';
import * as api from '../api';
import { useApp } from '../store';

export default function SettingsPage() {
  const { addToast } = useApp();
  const [config, setConfig] = useState<AgentConfig | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getAgentConfig()
      .then(setConfig)
      .catch(err => addToast(`Failed to load config: ${err instanceof Error ? err.message : 'Unknown'}`, 'error'))
      .finally(() => setLoading(false));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div>
      <h2>Agent Configuration</h2>
      {loading ? (
        <p className="muted">Loading configuration…</p>
      ) : !config ? (
        <p className="muted">Failed to load</p>
      ) : (
        <div className="config-grid">
          {Object.entries(config).map(([key, value]) => (
            <div key={key} className="config-item">
              <div className="cfg-key">{key.replace(/_/g, ' ')}</div>
              <div className="cfg-val">{String(value)}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
