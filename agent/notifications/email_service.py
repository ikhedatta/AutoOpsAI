"""
Email notification service for escalations.

Uses SMTP to send email notifications when incidents are escalated.
"""

from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from agent.config import get_settings

logger = logging.getLogger(__name__)


async def send_escalation_email(
    incident_id: str,
    title: str,
    service_name: str,
    severity: str,
    detail: str = "",
    recipients: Optional[list[str]] = None,
) -> bool:
    """
    Send an escalation email notification.

    Args:
        incident_id: The incident ID
        title: Incident title
        service_name: Affected service
        severity: Incident severity (HIGH, MEDIUM, LOW)
        detail: Additional details
        recipients: Override recipients (uses config if not provided)

    Returns:
        True if email sent successfully, False otherwise
    """
    settings = get_settings()

    # Check if SMTP is configured
    if not settings.smtp_host:
        logger.warning("SMTP not configured - skipping escalation email")
        return False

    # Get recipients
    if recipients is None:
        if not settings.escalation_recipients:
            logger.warning("No escalation recipients configured")
            return False
        recipients = [e.strip() for e in settings.escalation_recipients.split(",") if e.strip()]

    if not recipients:
        logger.warning("No recipients for escalation email")
        return False

    # Build email
    from_email = settings.smtp_from_email or settings.smtp_user
    subject = f"🚨 ESCALATED: [{severity}] {title} - {service_name}"

    html_body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; background-color: #1a1a2e; color: #eaeaea; padding: 20px;">
        <div style="max-width: 600px; margin: 0 auto; background: #16213e; padding: 20px; border-radius: 8px;">
            <h2 style="color: #e94560; margin-top: 0;">🚨 Incident Escalated</h2>
            
            <table style="width: 100%; border-collapse: collapse;">
                <tr>
                    <td style="padding: 10px; border-bottom: 1px solid #333; color: #888;">Incident ID</td>
                    <td style="padding: 10px; border-bottom: 1px solid #333; font-family: monospace;">{incident_id}</td>
                </tr>
                <tr>
                    <td style="padding: 10px; border-bottom: 1px solid #333; color: #888;">Title</td>
                    <td style="padding: 10px; border-bottom: 1px solid #333;"><strong>{title}</strong></td>
                </tr>
                <tr>
                    <td style="padding: 10px; border-bottom: 1px solid #333; color: #888;">Service</td>
                    <td style="padding: 10px; border-bottom: 1px solid #333;">{service_name}</td>
                </tr>
                <tr>
                    <td style="padding: 10px; border-bottom: 1px solid #333; color: #888;">Severity</td>
                    <td style="padding: 10px; border-bottom: 1px solid #333;">
                        <span style="background: {'#e94560' if severity == 'HIGH' else '#f9a825' if severity == 'MEDIUM' else '#4caf50'}; 
                                     color: white; padding: 2px 8px; border-radius: 4px; font-weight: bold;">
                            {severity}
                        </span>
                    </td>
                </tr>
                <tr>
                    <td style="padding: 10px; color: #888;">Details</td>
                    <td style="padding: 10px;">{detail or 'Manually escalated by operator'}</td>
                </tr>
            </table>
            
            <p style="margin-top: 20px; color: #888; font-size: 12px;">
                This incident requires immediate attention. Please review and take appropriate action.
            </p>
        </div>
    </body>
    </html>
    """

    text_body = f"""
INCIDENT ESCALATED

Incident ID: {incident_id}
Title: {title}
Service: {service_name}
Severity: {severity}
Details: {detail or 'Manually escalated by operator'}

This incident requires immediate attention. Please review and take appropriate action.
    """

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_email
        msg["To"] = ", ".join(recipients)

        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        # Send email
        if settings.smtp_use_tls:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port)
            server.starttls()
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port)

        if settings.smtp_user and settings.smtp_password:
            server.login(settings.smtp_user, settings.smtp_password)

        server.sendmail(from_email, recipients, msg.as_string())
        server.quit()

        logger.info(f"Escalation email sent for incident {incident_id} to {recipients}")
        return True

    except Exception as e:
        logger.error(f"Failed to send escalation email: {e}")
        return False


async def send_new_incident_email(
    incident_id: str,
    title: str,
    service_name: str,
    severity: str,
    evidence: str = "",
    recipients: list[str] | None = None,
) -> bool:
    """Send an email notification whenever a new incident is created."""
    settings = get_settings()

    if not settings.smtp_host:
        logger.warning("SMTP not configured — skipping new-incident email")
        return False

    if recipients is None:
        # prefer dedicated incident list, fall back to escalation list
        raw = settings.incident_recipients or settings.escalation_recipients
        if not raw:
            logger.warning("No recipients configured for new-incident email")
            return False
        recipients = [e.strip() for e in raw.split(",") if e.strip()]

    if not recipients:
        logger.warning("No recipients for new-incident email")
        return False

    from_email = settings.smtp_from_email or "autoops@emerson.com"
    severity_color = {"HIGH": "#e94560", "MEDIUM": "#f9a825", "LOW": "#4caf50"}.get(severity, "#888")
    subject = f"[AutoOpsAI] New Incident [{severity}] — {title}"

    html_body = f"""
<html>
<body style="font-family: Arial, sans-serif; background-color: #0f0f23; color: #eaeaea; padding: 20px;">
  <div style="max-width: 620px; margin: 0 auto; background: #1a1a2e; padding: 24px;
              border-radius: 8px; border-top: 4px solid {severity_color};">
    <h2 style="color: {severity_color}; margin-top: 0;">&#x26A0;&#xFE0F; New Incident Detected</h2>

    <table style="width:100%; border-collapse:collapse; margin-bottom:16px;">
      <tr>
        <td style="padding:10px 8px; border-bottom:1px solid #2e2e4e; color:#888; width:140px;">Incident ID</td>
        <td style="padding:10px 8px; border-bottom:1px solid #2e2e4e; font-family:monospace;">{incident_id}</td>
      </tr>
      <tr>
        <td style="padding:10px 8px; border-bottom:1px solid #2e2e4e; color:#888;">Title</td>
        <td style="padding:10px 8px; border-bottom:1px solid #2e2e4e;"><strong>{title}</strong></td>
      </tr>
      <tr>
        <td style="padding:10px 8px; border-bottom:1px solid #2e2e4e; color:#888;">Service</td>
        <td style="padding:10px 8px; border-bottom:1px solid #2e2e4e;">{service_name}</td>
      </tr>
      <tr>
        <td style="padding:10px 8px; border-bottom:1px solid #2e2e4e; color:#888;">Severity</td>
        <td style="padding:10px 8px; border-bottom:1px solid #2e2e4e;">
          <span style="background:{severity_color}; color:#fff; padding:2px 10px;
                       border-radius:4px; font-weight:bold; font-size:13px;">{severity}</span>
        </td>
      </tr>
      <tr>
        <td style="padding:10px 8px; color:#888; vertical-align:top;">Evidence</td>
        <td style="padding:10px 8px; font-size:13px; color:#ccc;">{evidence or "No evidence captured"}</td>
      </tr>
    </table>

    <p style="margin:0; color:#888; font-size:12px;">
      This notification was sent by AutoOpsAI. Review and act on this incident in the AutoOpsAI dashboard.
    </p>
  </div>
</body>
</html>"""

    text_body = f"""NEW INCIDENT DETECTED — AutoOpsAI

Incident ID : {incident_id}
Title       : {title}
Service     : {service_name}
Severity    : {severity}
Evidence    : {evidence or "No evidence captured"}

Review and act on this incident in the AutoOpsAI dashboard.
"""

    try:
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        import smtplib

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_email
        msg["To"] = ", ".join(recipients)
        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        server = smtplib.SMTP(settings.smtp_host, settings.smtp_port)
        if settings.smtp_use_tls:
            server.starttls()
        if settings.smtp_user and settings.smtp_password:
            server.login(settings.smtp_user, settings.smtp_password)

        server.sendmail(from_email, recipients, msg.as_string())
        server.quit()
        logger.info("New-incident email sent for %s to %s", incident_id, recipients)
        return True

    except Exception as exc:
        logger.error("Failed to send new-incident email for %s: %s", incident_id, exc)
        return False
