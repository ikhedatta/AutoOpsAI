import { useEffect, useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import {
  LayoutDashboard,
  AlertTriangle,
  CheckCircle2,
  BookOpen,
  MessageSquare,
  Settings,
  Play,
  Square,
  Wifi,
  WifiOff,
  Activity,
  Cog,
} from 'lucide-react';
import { useApp } from '../store';
import ToastContainer from './ToastContainer';
import { formatClockTime } from '../utils';
import * as api from '../api';

export default function Layout() {
  const { health, wsConnected, incidents, approvals, toasts, removeToast, addToast } = useApp();
  const [clock, setClock] = useState(formatClockTime(new Date()));
  const [agentRunning, setAgentRunning] = useState(false);
  const [agentLoading, setAgentLoading] = useState(false);

  useEffect(() => {
    const id = setInterval(() => setClock(formatClockTime(new Date())), 1000);
    return () => clearInterval(id);
  }, []);

  const activeIncidents = incidents.filter(
    i => !['resolved', 'failed', 'denied', 'denied_timeout'].includes(i.status)
  ).length;
  const pendingApprovals = approvals.length;

  const toggleAgent = async () => {
    setAgentLoading(true);
    try {
      if (agentRunning) {
        await api.stopAgent();
        setAgentRunning(false);
        addToast('Agent stopped', 'info');
      } else {
        await api.startAgent();
        setAgentRunning(true);
        addToast('Agent started', 'success');
      }
    } catch (err) {
      addToast(`Agent error: ${err instanceof Error ? err.message : 'Unknown'}`, 'error');
    } finally {
      setAgentLoading(false);
    }
  };

  const healthStatus = health?.status || 'unknown';

  return (
    <div className="app">
      {/* Header */}
      <header className="header">
        <div className="header-left">
          <Cog size={22} className="logo-icon" />
          <span className="logo">AutoOps AI</span>
          <span className="version">v1.0.0</span>
        </div>
        <div className="header-center">
          <div className={`badge badge-${healthStatus}`}>
            <Activity size={12} />
            <span>{healthStatus === 'healthy' ? 'Healthy' : healthStatus === 'degraded' ? 'Degraded' : 'Connecting…'}</span>
          </div>
          <div className={`badge ${wsConnected ? 'badge-connected' : 'badge-unknown'}`}>
            {wsConnected ? <Wifi size={12} /> : <WifiOff size={12} />}
            <span>{wsConnected ? 'WS: live' : 'WS: disconnected'}</span>
          </div>
        </div>
        <div className="header-right">
          <span className="clock">{clock}</span>
        </div>
      </header>

      {/* Layout */}
      <div className="layout">
        {/* Sidebar */}
        <nav className="sidebar">
          <NavLink to="/" end className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <LayoutDashboard size={18} />
            <span>Overview</span>
          </NavLink>
          <NavLink to="/incidents" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <AlertTriangle size={18} />
            <span>Incidents</span>
            {activeIncidents > 0 && <span className="nav-badge">{activeIncidents}</span>}
          </NavLink>
          <NavLink to="/approvals" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <CheckCircle2 size={18} />
            <span>Approvals</span>
            {pendingApprovals > 0 && <span className="nav-badge">{pendingApprovals}</span>}
          </NavLink>
          <NavLink to="/playbooks" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <BookOpen size={18} />
            <span>Playbooks</span>
          </NavLink>
          <NavLink to="/chat" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <MessageSquare size={18} />
            <span>Chat</span>
          </NavLink>
          <NavLink to="/settings" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <Settings size={18} />
            <span>Settings</span>
          </NavLink>

          <div className="nav-spacer" />
        </nav>

        {/* Main content */}
        <main className="content">
          <Outlet />
        </main>
      </div>

      <ToastContainer toasts={toasts} onRemove={removeToast} />
    </div>
  );
}
