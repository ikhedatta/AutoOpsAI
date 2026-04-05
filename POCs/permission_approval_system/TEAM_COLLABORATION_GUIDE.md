# Team Collaboration Guidelines

This guide covers how teams should configure and use the **Permission & Approval System** across multiple team members, environments, and deployment stages.

## Overview

The permission & approval system is designed to work in team environments with:
- **Multiple users** with different permission levels
- **Multiple environments** (dev, staging, prod)
- **Role-based access control** (RBAC)
- **Audit trail** for compliance
- **Approval workflows** for critical operations

## Team Roles and Permissions

### Standard Team Roles

```
┌──────────────────────────────────────────────────────────┐
│ Team Member Hierarchy                                    │
├──────────────────────────────────────────────────────────┤
│                                                          │
│ Admin/Lead                                               │
│  ├─ View all tools                                       │
│  ├─ Execute all tools (with approval for high-risk)     │
│  ├─ Manage permissions for team                          │
│  ├─ Approve critical operations                          │
│  └─ Review audit logs                                    │
│                                                          │
│ DevOps Engineer                                          │
│  ├─ View dev/staging tools                              │
│  ├─ Execute low/medium risk operations                  │
│  ├─ Request high-risk approvals                         │
│  ├─ View own audit history                              │
│  └─ Cannot modify permissions                           │
│                                                          │
│ Developer                                                │
│  ├─ View read-only tools                                │
│  ├─ Execute read-only operations                        │
│  ├─ Cannot execute write operations                     │
│  └─ Request approvals for needed operations             │
│                                                          │
│ Intern/Junior                                            │
│  ├─ View read-only tools only                           │
│  ├─ Execute read-only operations                        │
│  └─ All other operations blocked                        │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

### Configuration Example

`~/.autoops/team_config.json`:

```json
{
  "team": "platform-devops",
  "team_members": {
    "alice@company.com": {
      "role": "admin",
      "level": 5,
      "permissions": "all",
      "environments": ["dev", "staging", "prod"],
      "can_approve": true
    },
    "bob@company.com": {
      "role": "devops-engineer",
      "level": 3,
      "permissions": "medium",
      "environments": ["dev", "staging"],
      "can_approve": false
    },
    "charlie@company.com": {
      "role": "developer",
      "level": 2,
      "permissions": "low",
      "environments": ["dev"],
      "can_approve": false
    },
    "diana@company.com": {
      "role": "intern",
      "level": 1,
      "permissions": "readonly",
      "environments": ["dev"],
      "can_approve": false
    }
  },
  "approval_rules": {
    "high_risk": {
      "requires_approval": true,
      "min_approvers": 2,
      "allowed_approvers": ["alice@company.com"],
      "timeout_seconds": 600
    },
    "medium_risk": {
      "requires_approval": true,
      "min_approvers": 1,
      "allowed_approvers": ["alice@company.com", "bob@company.com"],
      "timeout_seconds": 300
    },
    "low_risk": {
      "requires_approval": false
    }
  }
}
```

## Setup for New Team

### Step 1: Initialize Team Configuration

```bash
mkdir -p ~/.autoops
cp team_config.json ~/.autoops/
```

### Step 2: Create Per-User Permission Files

For each team member:

```bash
# Admin user - full access
cat > ~/.autoops/alice_permissions.json << 'EOF'
{
  "user": "alice@company.com",
  "role": "admin",
  "safe_tools": ["docker_list_containers", "docker_list_images", "mongodb_status"],
  "allowlist": "all",
  "blocklist": [],
  "grants": {
    "docker_restart_container": ["prod_incident_response"],
    "mongodb_backup": ["maintenance_window"]
  },
  "deny_categories": []
}
EOF

# DevOps user - medium access
cat > ~/.autoops/bob_permissions.json << 'EOF'
{
  "user": "bob@company.com",
  "role": "devops-engineer",
  "safe_tools": ["docker_list_containers", "docker_list_images", "mongodb_status"],
  "allowlist": ["docker_stop_container", "docker_start_container"],
  "blocklist": ["docker_remove_image", "mongodb_delete"],
  "grants": {},
  "deny_categories": ["production_delete"]
}
EOF

# Developer - read-only access
cat > ~/.autoops/charlie_permissions.json << 'EOF'
{
  "user": "charlie@company.com",
  "role": "developer",
  "safe_tools": ["docker_list_containers", "docker_list_images", "mongodb_status"],
  "allowlist": [],
  "blocklist": "all_except_safe",
  "grants": {},
  "deny_categories": ["write", "delete", "restart"]
}
EOF
```

### Step 3: Verify Team Setup

```bash
# Check team permissions
uv run python << 'EOF'
from permission_approval_system import PermissionManager, get_registry

registry = get_registry()

users = ["alice@company.com", "bob@company.com", "charlie@company.com"]

for user in users:
    pm = PermissionManager(registry, Path(f'~/.autoops/{user.split("@")[0]}_permissions.json'))
    print(f"\n{user} can access:")
    
    for tool in registry.all_tools():
        result = pm.check_permission(tool.name, user)
        if result.allowed:
            print(f"  ✅ {tool.name} (risk: {tool.risk_level.value})")
        else:
            print(f"  ❌ {tool.name} (reason: {result.reason})")
EOF
```

## Environment-Based Permissions

### Configuration

`~/.autoops/environment_config.json`:

```json
{
  "environments": {
    "dev": {
      "risk_multiplier": 0.5,
      "auto_approve": true,
      "approval_timeout": 60,
      "allowed_roles": ["admin", "devops-engineer", "developer", "intern"],
      "audit_level": "info"
    },
    "staging": {
      "risk_multiplier": 1.0,
      "auto_approve": false,
      "approval_timeout": 300,
      "allowed_roles": ["admin", "devops-engineer"],
      "audit_level": "warning"
    },
    "production": {
      "risk_multiplier": 2.0,
      "auto_approve": false,
      "approval_timeout": 600,
      "allowed_roles": ["admin"],
      "audit_level": "critical",
      "requires_change_ticket": true,
      "requires_runbook": true
    }
  }
}
```

### Usage

```python
from permission_approval_system import PermissionManager, get_registry
import json

# Load environment config
with open('~/.autoops/environment_config.json') as f:
    env_config = json.load(f)

# Check if user can execute in environment
def can_execute_in_env(user_role: str, tool: str, environment: str) -> bool:
    env = env_config['environments'][environment]
    
    # Check if role is allowed
    if user_role not in env['allowed_roles']:
        return False
    
    # Check tool permissions
    registry = get_registry()
    tool_obj = registry.get(tool)
    
    if tool_obj.risk_level.value == 'high_risk' and environment == 'production':
        # Requires special approval
        return user_role == 'admin'
    
    return True

# Example
print(can_execute_in_env("devops-engineer", "docker_restart_container", "staging"))  # True
print(can_execute_in_env("devops-engineer", "docker_restart_container", "production"))  # False
```

## Shared Team Workflows

### Daily Standup - Permissions Check

```python
"""
Daily script to validate team permissions are correctly configured.
"""

import json
from pathlib import Path
from permission_approval_system import get_registry, PermissionManager

def audit_team_permissions():
    """Check that all team members have correct permissions."""
    
    with open(Path.home() / '.autoops' / 'team_config.json') as f:
        team_config = json.load(f)
    
    registry = get_registry()
    
    print("🔍 Team Permissions Audit")
    print("=" * 50)
    
    for user, user_config in team_config['team_members'].items():
        pm = PermissionManager(
            registry,
            Path.home() / '.autoops' / f"{user.split('@')[0]}_permissions.json"
        )
        
        # Count accessible tools
        accessible = sum(
            1 for tool in registry.all_tools()
            if pm.check_permission(tool.name, user).allowed
        )
        
        print(f"\n👤 {user}")
        print(f"   Role: {user_config['role']}")
        print(f"   Environments: {', '.join(user_config['environments'])}")
        print(f"   Accessible Tools: {accessible}/{len(registry.all_tools())}")
        
        # Highlight any missing standard tools
        standard_tools = ['docker_list_containers', 'mongodb_status']
        missing = [
            tool for tool in standard_tools
            if not pm.check_permission(tool, user).allowed
        ]
        
        if missing:
            print(f"   ⚠️  Missing Standard Tools: {', '.join(missing)}")

if __name__ == '__main__':
    audit_team_permissions()
```

### On-Call Rotation

```python
"""
On-call rotation permissions - grant temporary elevated access.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from permission_approval_system import PermissionManager, get_registry

class OnCallManager:
    """Manage temporary elevated permissions for on-call engineers."""
    
    def __init__(self, config_file: Path):
        self.config_file = config_file
        self.registry = get_registry()
    
    def promote_to_oncall(self, user: str, duration_hours: int = 24):
        """Temporarily elevate user permissions for on-call duty."""
        
        with open(self.config_file) as f:
            config = json.load(f)
        
        # Grant high-risk tools
        config['grants'] = {
            'docker_restart_container': [f'oncall_until_{datetime.now() + timedelta(hours=duration_hours)}'],
            'mongodb_backup': [f'oncall_until_{datetime.now() + timedelta(hours=duration_hours)}'],
        }
        
        with open(self.config_file, 'w') as f:
            json.dump(config, f, indent=2)
        
        print(f"✅ {user} promoted to on-call for {duration_hours} hours")
        print(f"   Elevated tools: docker_restart_container, mongodb_backup")
    
    def demote_from_oncall(self, user: str):
        """Remove temporary elevated permissions."""
        
        with open(self.config_file) as f:
            config = json.load(f)
        
        # Clear grants
        config['grants'] = {}
        
        with open(self.config_file, 'w') as f:
            json.dump(config, f, indent=2)
        
        print(f"✅ {user} demoted from on-call")
        print(f"   Temporary permissions revoked")

# Usage
oncall_mgr = OnCallManager(Path.home() / '.autoops' / 'bob_permissions.json')
oncall_mgr.promote_to_oncall('bob@company.com', duration_hours=24)  # Start shift
# ... do on-call work ...
oncall_mgr.demote_from_oncall('bob@company.com')  # End shift
```

### Cross-Team Approvals

```python
"""
Handle approvals that require cross-team coordination.
"""

from permission_approval_system import ApprovalWorkflow, ApprovalRequest

class CrossTeamApproval:
    """Manage approvals requiring multiple teams."""
    
    def __init__(self):
        self.workflow = ApprovalWorkflow(interactive=False)
        self.teams = {
            'platform': ['alice@company.com', 'bob@company.com'],
            'security': ['security-lead@company.com'],
            'product': ['product-owner@company.com'],
        }
    
    async def request_cross_team_approval(
        self,
        tool_name: str,
        affected_teams: list[str],
        reason: str,
        parameters: dict,
    ) -> bool:
        """Request approval from multiple teams."""
        
        print(f"\n🔄 Cross-Team Approval Request")
        print(f"   Tool: {tool_name}")
        print(f"   Affected Teams: {', '.join(affected_teams)}")
        print(f"   Reason: {reason}")
        
        approvals = {}
        for team in affected_teams:
            approvers = self.teams.get(team, [])
            print(f"\n   Requesting approval from {team}:")
            
            for approver in approvers:
                # Request from each approver
                approved = await self._get_approval(approver, tool_name, reason)
                approvals[f"{team}:{approver}"] = approved
        
        # Check if all required teams approved
        teams_approved = {}
        for key, approved in approvals.items():
            team = key.split(':')[0]
            teams_approved[team] = teams_approved.get(team, True) and approved
        
        all_approved = all(teams_approved.values())
        
        print(f"\n   Result: {'✅ APPROVED' if all_approved else '❌ REJECTED'}")
        for team, approved in teams_approved.items():
            print(f"   {team}: {'✅' if approved else '❌'}")
        
        return all_approved

# Usage
cross_team = CrossTeamApproval()
await cross_team.request_cross_team_approval(
    tool_name='mongodb_backup',
    affected_teams=['platform', 'product'],
    reason='Full database backup before major schema migration',
    parameters={'backup_name': 'pre_migration_2024_01'},
)
```

## Team Communication

### Permission Change Notification

```bash
#!/bin/bash
# notify_permission_change.sh

USER=$1
OLD_ROLE=$2
NEW_ROLE=$3

# Send notification
cat << EOF | mail -s "Permission Update: $USER" $USER
Permission Update Notification

User: $USER
Previous Role: $OLD_ROLE
New Role: $NEW_ROLE
Date: $(date)

Your tool access has been updated. For details, contact your team lead.

Tools You Can Access:
- Read-only tools: Enabled
- Low-risk operations: Check with your manager
- High-risk operations: Requires approval from admin

Questions? Contact: devops-admin@company.com
EOF

echo "✅ Notification sent to $USER"
```

### Weekly Audit Report

```python
"""
Generate weekly permissions and approval audit report for team.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from permission_approval_system import AuditLogger

def generate_weekly_report():
    """Generate weekly team audit report."""
    
    logger = AuditLogger()
    
    # Get events from past 7 days
    week_ago = datetime.now() - timedelta(days=7)
    
    report = {
        'period': f"Last 7 days ({week_ago.date()} to {datetime.now().date()})",
        'summary': {
            'total_operations': 0,
            'approvals_requested': 0,
            'approvals_granted': 0,
            'approvals_denied': 0,
            'permission_denied': 0,
        },
        'by_user': {},
        'by_tool': {},
        'high_risk_operations': [],
    }
    
    # Process audit events
    for event in logger.get_report()['events']:
        event_time = datetime.fromisoformat(event['timestamp'])
        
        if event_time < week_ago:
            continue
        
        # Update summary
        if event['event_type'] == 'permission_check':
            if event['allowed']:
                report['summary']['total_operations'] += 1
            else:
                report['summary']['permission_denied'] += 1
        
        elif event['event_type'] == 'approval_requested':
            report['summary']['approvals_requested'] += 1
        
        elif event['event_type'] == 'approval_decided':
            if event['approved']:
                report['summary']['approvals_granted'] += 1
            else:
                report['summary']['approvals_denied'] += 1
        
        # Track by user
        user = event.get('user_id', 'unknown')
        if user not in report['by_user']:
            report['by_user'][user] = {
                'operations': 0,
                'approvals': 0,
            }
        
        if event['event_type'] == 'tool_executed':
            report['by_user'][user]['operations'] += 1
        
        # Track by tool
        tool = event.get('tool_name', 'unknown')
        if tool not in report['by_tool']:
            report['by_tool'][tool] = 0
        report['by_tool'][tool] += 1
        
        # Highlight high-risk operations
        if event.get('risk_level') == 'high_risk':
            report['high_risk_operations'].append({
                'tool': event.get('tool_name'),
                'user': event.get('user_id'),
                'time': event.get('timestamp'),
                'status': 'approved' if event.get('approved') else 'denied',
            })
    
    # Output report
    print("\n📊 Weekly Team Audit Report")
    print("=" * 60)
    print(f"Period: {report['period']}")
    print(f"\nSummary:")
    print(f"  Total Operations: {report['summary']['total_operations']}")
    print(f"  Approvals Requested: {report['summary']['approvals_requested']}")
    print(f"  Approvals Granted: {report['summary']['approvals_granted']}")
    print(f"  Approvals Denied: {report['summary']['approvals_denied']}")
    print(f"  Permission Denied: {report['summary']['permission_denied']}")
    
    print(f"\nHigh-Risk Operations:")
    for op in report['high_risk_operations']:
        status_emoji = '✅' if op['status'] == 'approved' else '❌'
        print(f"  {status_emoji} {op['tool']} by {op['user']} at {op['time']}")
    
    return report

if __name__ == '__main__':
    generate_weekly_report()
```

## Best Practices

### ✅ DO

- ✅ Review team permissions quarterly
- ✅ Use roles consistently across team
- ✅ Document why grants/blocks exist
- ✅ Audit approval decisions regularly
- ✅ Rotate on-call permissions
- ✅ Update permissions when team members join/leave
- ✅ Test permissions before production deployment
- ✅ Keep audit logs for compliance

### ❌ DON'T

- ❌ Grant blanket "admin" access to all team members
- ❌ Share user permission files
- ❌ Leave high-risk tools unprotected
- ❌ Forget to revoke permissions on team member departure
- ❌ Approve requests without understanding impact
- ❌ Skip approval workflows for "just this once"
- ❌ Delete audit logs
- ❌ Hard-code permissions in code

## Checklists

### New Team Member Onboarding

- [ ] Create user in team_config.json
- [ ] Generate permission file based on role
- [ ] Test permissions with dry-run
- [ ] Add to appropriate approval groups
- [ ] Review with team lead
- [ ] Document in team runbook
- [ ] Schedule onboarding meeting

### Team Member Departure

- [ ] Backup their approval history
- [ ] Remove from team_config.json
- [ ] Delete permission files
- [ ] Revoke any active grants
- [ ] Review recent approval decisions
- [ ] Handoff on-call duties if applicable
- [ ] Archive audit logs

### Quarterly Permissions Review

- [ ] Review each team member's permissions
- [ ] Check for unused access
- [ ] Update roles based on current responsibilities
- [ ] Remove outdated grants
- [ ] Test approval workflows
- [ ] Review audit logs for anomalies
- [ ] Update documentation
- [ ] Communicate changes to team

---

**Status:** ✅ Ready for team collaboration
**Audit Compliance:** ✅ Supported
**Multi-User Setup:** ✅ Complete
