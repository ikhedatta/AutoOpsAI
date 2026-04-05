const statusLabels: Record<string, string> = {
  detecting: 'Detecting',
  diagnosing: 'Diagnosing',
  awaiting_approval: 'Awaiting Approval',
  approved: 'Approved',
  executing: 'Executing',
  resolved: 'Resolved',
  failed: 'Failed',
  escalated: 'Escalated',
  denied: 'Denied',
  denied_timeout: 'Timed Out',
  verifying: 'Verifying',
};

export default function StatusBadge({ status }: { status: string }) {
  const label = statusLabels[status] || status;
  return <span className={`status-badge status-${status}`}>{label}</span>;
}
