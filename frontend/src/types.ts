// API types matching backend models

export interface HealthCheck {
  status: 'healthy' | 'degraded';
  components: {
    ollama: boolean;
    database: boolean;
    provider: string;
    websocket_clients: number;
    prometheus?: boolean;
    loki?: boolean;
  };
}

export interface ServiceStatus {
  name: string;
  state: 'running' | 'stopped' | 'error' | 'restarting' | 'unknown';
  image?: string;
  ports?: string[];
}

export interface StatusResponse {
  services: Record<string, ServiceStatus>;
}

export interface Incident {
  incident_id: string;
  title: string;
  service_name: string;
  severity: 'HIGH' | 'MEDIUM' | 'LOW';
  status: string;
  anomaly_type?: string;
  metric?: string;
  current_value?: number;
  threshold?: number;
  detected_at: string;
  resolved_at?: string;
  evidence?: string;
  diagnosis?: {
    summary: string;
    explanation: string;
    confidence: number;
    root_cause?: string;
    playbook_id?: string;
  };
  proposed_actions?: Action[];
  action_results?: ActionResult[];
  chat?: ChatMessage[];
  timeline?: TimelineEvent[];
  approval?: {
    decision?: string;
    approved_by?: string;
    decided_at?: string;
  };
}

export interface Action {
  action_type: string;
  target: string;
  description?: string;
}

export interface ActionResult {
  action_id: string;
  success: boolean;
  output?: string;
  error?: string;
}

export interface ChatMessage {
  role: 'user' | 'agent' | 'system';
  content: string;
  timestamp?: string;
  metadata?: Record<string, unknown>;
}

export interface TimelineEvent {
  timestamp: string;
  event: string;
  detail?: string;
}

export interface ApprovalRequest {
  type: string;
  incident_id: string;
  title: string;
  service_name: string;
  severity: 'HIGH' | 'MEDIUM' | 'LOW';
  severity_color: string;
  detected_at: string;
  diagnosis: {
    summary: string;
    explanation: string;
    confidence: number;
    root_cause: string | null;
  };
  proposed_actions?: Action[];
  rollback_plan?: string;
  timeout_seconds?: number | null;
  status: string;
  actions_available: boolean;
}

export interface Playbook {
  id: string;
  name: string;
  severity: string;
  provider: string;
  detection_type: string;
  tags?: string[];
  description?: string;
  actions?: Action[];
}

export interface WSEvent {
  event_type: string;
  data: Record<string, unknown>;
  timestamp: string;
}

export interface AgentConfig {
  [key: string]: string | number | boolean;
}
