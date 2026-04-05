import { createContext, useContext, useCallback, useRef, useEffect, useState, type ReactNode } from 'react';
import type { HealthCheck, StatusResponse, Incident, ApprovalRequest, WSEvent } from './types';
import * as api from './api';

// ---- Toast system ----
export type ToastType = 'success' | 'error' | 'warning' | 'info';
interface Toast {
  id: number;
  message: string;
  type: ToastType;
}

// ---- Chat messages ----
export interface ChatMsg {
  id: number;
  role: 'user' | 'agent' | 'system';
  content: string;
  timestamp: Date;
  responseTimeMs?: number;
}

// ---- Global state ----
interface AppState {
  health: HealthCheck | null;
  services: Record<string, import('./types').ServiceStatus>;
  incidents: Incident[];
  approvals: ApprovalRequest[];
  events: WSEvent[];
  wsConnected: boolean;
  agentRunning: boolean;
  toasts: Toast[];
  chatMessages: ChatMsg[];
  addChatMessage: (role: ChatMsg['role'], content: string, responseTimeMs?: number) => number;
  updateChatMessage: (id: number, updater: (prev: ChatMsg) => Partial<ChatMsg>) => void;
  addToast: (message: string, type?: ToastType) => void;
  removeToast: (id: number) => void;
  refresh: () => Promise<void>;
}

const AppContext = createContext<AppState | null>(null);

export function useApp() {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error('useApp must be used inside AppProvider');
  return ctx;
}

const MAX_EVENTS = 100;
const POLL_MS = 8000;
let toastIdCounter = 0;

export function AppProvider({ children }: { children: ReactNode }) {
  const [health, setHealth] = useState<HealthCheck | null>(null);
  const [services, setServices] = useState<Record<string, import('./types').ServiceStatus>>({});
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([]);
  const [events, setEvents] = useState<WSEvent[]>([]);
  const [wsConnected, setWsConnected] = useState(false);
  const [agentRunning, setAgentRunning] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [chatMessages, setChatMessages] = useState<ChatMsg[]>([
    { id: 0, role: 'agent', content: "Hello! I'm your AutoOps AI assistant. Ask me about system health, incidents, or anything DevOps-related.", timestamp: new Date() },
  ]);
  const wsRef = useRef<WebSocket | null>(null);
  const pollRef = useRef<number>(0);
  const chatIdRef = useRef(1);

  const addToast = useCallback((message: string, type: ToastType = 'info') => {
    const id = ++toastIdCounter;
    setToasts(prev => [...prev, { id, message, type }]);
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 4000);
  }, []);

  const removeToast = useCallback((id: number) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  }, []);

  const addChatMessage = useCallback((role: ChatMsg['role'], content: string, responseTimeMs?: number) => {
    const id = chatIdRef.current++;
    setChatMessages(prev => [...prev, { id, role, content, timestamp: new Date(), responseTimeMs }]);
    return id;
  }, []);

  const updateChatMessage = useCallback((id: number, updater: (prev: ChatMsg) => Partial<ChatMsg>) => {
    setChatMessages(prev => prev.map(m => m.id === id ? { ...m, ...updater(m) } : m));
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [h, s, inc, app] = await Promise.all([
        api.getHealth(),
        api.getStatus(),
        api.getIncidents(),
        api.getPendingApprovals(),
      ]);
      setHealth(h);
      setServices(s.services || {});
      setIncidents(inc);
      setApprovals(app);
      setAgentRunning(true);
    } catch {
      // partial failure is ok
    }
  }, []);

  // WebSocket
  useEffect(() => {
    let cancelled = false;
    let ws: WebSocket;

    function connect() {
      if (cancelled) return;
      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
      ws = new WebSocket(`${proto}://${window.location.host}/api/v1/ws/events`);

      ws.onopen = () => {
        if (!cancelled) setWsConnected(true);
      };

      ws.onmessage = (msg) => {
        try {
          const evt: WSEvent = JSON.parse(msg.data);
          setEvents(prev => {
            const next = [evt, ...prev];
            return next.length > MAX_EVENTS ? next.slice(0, MAX_EVENTS) : next;
          });

          // Toast for important events
          const d = evt.data || {};
          const toastMap: Record<string, { type: ToastType; msg: string }> = {
            incident_detected: { type: 'warning', msg: `New incident: ${d.title || d.service || ''}` },
            approval_requested: { type: 'warning', msg: `Approval needed: ${String(d.incident_id || '').slice(0, 8)}` },
            incident_resolved: { type: 'success', msg: `Incident resolved: ${String(d.incident_id || '').slice(0, 8)}` },
            incident_failed: { type: 'error', msg: `Incident failed: ${d.reason || ''}` },
          };
          const t = toastMap[evt.event_type];
          if (t) addToast(t.msg, t.type);

          // Push important WS events into chat as system notifications
          const chatEventMap: Record<string, string> = {
            incident_detected: `🚨 New incident: **${d.severity || ''} — ${d.title || d.service || ''}**`,
            metric_anomaly: `📊 Metric anomaly: **${d.service || ''}** ${d.metric || ''} = ${d.value ?? ''} (threshold: ${d.threshold ?? ''})`,
            approval_requested: `⏳ Approval requested for incident \`${String(d.incident_id || '').slice(0, 8)}\` — ${((d.proposed_actions as unknown[]) || []).length} proposed actions`,
            incident_resolved: `✅ Incident \`${String(d.incident_id || '').slice(0, 8)}\` resolved (${d.duration_seconds || '?'}s)`,
            incident_failed: `❌ Incident failed: ${d.reason || 'unknown'}`,
            service_status_changed: `🔄 Service **${d.service || ''}**: ${d.old_state || '?'} → ${d.new_state || '?'}`,
          };
          const chatMsg = chatEventMap[evt.event_type];
          if (chatMsg) {
            addChatMessage('system', chatMsg);
          }

          // Re-poll on incident/approval events
          if (evt.event_type.startsWith('incident_') || evt.event_type.startsWith('approval_')) {
            refresh();
          }
        } catch {
          // ignore non-JSON
        }
      };

      ws.onclose = () => {
        if (!cancelled) {
          setWsConnected(false);
          setTimeout(connect, 3000);
        }
      };

      ws.onerror = () => {
        if (!cancelled) setWsConnected(false);
      };

      wsRef.current = ws;
    }

    connect();

    return () => {
      cancelled = true;
      ws?.close();
    };
  }, [addToast, addChatMessage, refresh]);

  // Polling
  useEffect(() => {
    refresh();
    pollRef.current = window.setInterval(refresh, POLL_MS);
    return () => clearInterval(pollRef.current);
  }, [refresh]);

  return (
    <AppContext.Provider
      value={{
        health,
        services,
        incidents,
        approvals,
        events,
        wsConnected,
        agentRunning,
        toasts,
        chatMessages,
        addChatMessage,
        updateChatMessage,
        addToast,
        removeToast,
        refresh,
      }}
    >
      {children}
    </AppContext.Provider>
  );
}
