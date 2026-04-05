const severityStyles: Record<string, string> = {
  HIGH: 'sev sev-high',
  MEDIUM: 'sev sev-medium',
  LOW: 'sev sev-low',
};

export default function SeverityBadge({ severity }: { severity: string }) {
  return <span className={severityStyles[severity] || 'sev'}>{severity}</span>;
}
