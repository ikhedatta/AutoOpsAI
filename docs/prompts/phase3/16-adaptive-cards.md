# [Step 16] — Adaptive Card Builder

## Context

Steps 01-15 are complete. The following exist:
- `agent/models.py` — `RiskLevel`, `Action`, `Diagnosis`
- `agent/store/documents.py` — `IncidentDocument`, `ApprovalDocument`
- `agent/approval/__init__.py` — package exists

## Objective

Produce JSON template files for each MS Teams Adaptive Card type and a `CardBuilder` class that renders them from incident data. No external card-building library — templates are JSON files, values are substituted via string replacement.

## Files to Create

- `agent/approval/teams_cards/approval_medium.json` — MEDIUM risk approval request card template.
- `agent/approval/teams_cards/approval_high.json` — HIGH risk approval request card template.
- `agent/approval/teams_cards/resolved.json` — Resolution card (replaces approval card on resolution).
- `agent/approval/teams_cards/auto_resolved.json` — Compact notification for LOW risk auto-resolutions.
- `agent/approval/teams_cards/investigation_reply.json` — Detailed investigation response card.
- `agent/approval/card_builder.py` — `CardBuilder` class.
- `tests/test_card_builder.py` — Tests asserting correct card structure.

## Files to Modify

None.

## Key Requirements

**Template format:** Templates are JSON files with `${variable_name}` placeholders. The `CardBuilder` replaces them with actual values using simple string replacement. All templates must be valid JSON when placeholders are filled.

**agent/approval/teams_cards/approval_medium.json:**
```json
{
  "type": "AdaptiveCard",
  "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
  "version": "1.4",
  "body": [
    {
      "type": "ColumnSet",
      "columns": [
        {
          "type": "Column",
          "width": "stretch",
          "items": [{"type": "TextBlock", "text": "AutoOps AI", "weight": "Bolder", "size": "Medium"}]
        },
        {
          "type": "Column",
          "width": "auto",
          "items": [{"type": "TextBlock", "text": "⚠ MEDIUM", "color": "Warning", "weight": "Bolder", "horizontalAlignment": "Right"}]
        }
      ]
    },
    {"type": "TextBlock", "text": "${title}", "size": "Large", "weight": "Bolder", "wrap": true},
    {"type": "TextBlock", "text": "${diagnosis}", "wrap": true, "spacing": "Medium"},
    {
      "type": "FactSet",
      "spacing": "Medium",
      "facts": [
        {"title": "Service", "value": "${service}"},
        {"title": "Detected", "value": "${detected_at}"},
        {"title": "Proposed Action", "value": "${proposed_action}"},
        {"title": "Timeout", "value": "Auto-deny in ${timeout_display}"}
      ]
    },
    {
      "type": "Container",
      "style": "emphasis",
      "spacing": "Medium",
      "items": [
        {"type": "TextBlock", "text": "Rollback Plan", "weight": "Bolder", "size": "Small"},
        {"type": "TextBlock", "text": "${rollback_plan}", "wrap": true, "size": "Small"}
      ]
    }
  ],
  "actions": [
    {"type": "Action.Submit", "title": "✅ Approve", "data": {"action": "approve", "incident_id": "${incident_id}"}, "style": "positive"},
    {"type": "Action.Submit", "title": "❌ Deny", "data": {"action": "deny", "incident_id": "${incident_id}"}, "style": "destructive"},
    {"type": "Action.Submit", "title": "🔍 Investigate More", "data": {"action": "investigate", "incident_id": "${incident_id}"}}
  ]
}
```

**agent/approval/teams_cards/approval_high.json:**
Same structure as approval_medium.json but:
- Severity badge text: `"🚨 HIGH"` with `"color": "Attention"`
- Replace the timeout fact with: `{"title": "Approval Required", "value": "Explicit approval required — this action will NOT auto-execute"}`
- Add a warning container above the facts:
  ```json
  {"type": "Container", "style": "attention", "items": [{"type": "TextBlock", "text": "⚠ HIGH RISK ACTION — Explicit human approval required before execution", "wrap": true, "weight": "Bolder"}]}
  ```

**agent/approval/teams_cards/resolved.json:**
```json
{
  "type": "AdaptiveCard",
  "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
  "version": "1.4",
  "body": [
    {
      "type": "ColumnSet",
      "columns": [
        {"type": "Column", "width": "stretch", "items": [{"type": "TextBlock", "text": "AutoOps AI — Resolved", "weight": "Bolder", "color": "Good"}]},
        {"type": "Column", "width": "auto", "items": [{"type": "TextBlock", "text": "✅ RESOLVED", "color": "Good", "weight": "Bolder"}]}
      ]
    },
    {"type": "TextBlock", "text": "${title}", "size": "Large", "weight": "Bolder", "wrap": true},
    {
      "type": "FactSet",
      "facts": [
        {"title": "Approved By", "value": "${approved_by}"},
        {"title": "Action Taken", "value": "${action_taken}"},
        {"title": "Verification", "value": "${verification_result}"},
        {"title": "Resolution Time", "value": "${resolution_time}"}
      ]
    }
  ]
}
```

**agent/approval/teams_cards/auto_resolved.json:**
Compact card — no action buttons:
```json
{
  "type": "AdaptiveCard",
  "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
  "version": "1.4",
  "body": [
    {"type": "TextBlock", "text": "AutoOps AI — Auto-Resolved", "weight": "Bolder", "color": "Good"},
    {"type": "TextBlock", "text": "${title}", "weight": "Bolder", "wrap": true},
    {"type": "TextBlock", "text": "Action taken: ${action_taken}", "wrap": true},
    {"type": "TextBlock", "text": "Outcome: ${outcome}", "wrap": true},
    {"type": "TextBlock", "text": "Resolved in ${resolution_time}", "isSubtle": true}
  ]
}
```

**agent/approval/teams_cards/investigation_reply.json:**
Reply card sent in-thread with detailed analysis:
```json
{
  "type": "AdaptiveCard",
  "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
  "version": "1.4",
  "body": [
    {"type": "TextBlock", "text": "Investigation Report", "weight": "Bolder", "size": "Large"},
    {"type": "TextBlock", "text": "Incident: ${title}", "weight": "Bolder"},
    {"type": "TextBlock", "text": "${llm_reasoning}", "wrap": true, "spacing": "Medium"},
    {
      "type": "Container",
      "style": "emphasis",
      "items": [
        {"type": "TextBlock", "text": "Recent Log Excerpts", "weight": "Bolder", "size": "Small"},
        {"type": "TextBlock", "text": "${log_excerpts}", "wrap": true, "size": "Small", "fontType": "Monospace"}
      ]
    }
  ],
  "actions": [
    {"type": "Action.Submit", "title": "✅ Approve After Review", "data": {"action": "approve", "incident_id": "${incident_id}"}, "style": "positive"},
    {"type": "Action.Submit", "title": "❌ Deny", "data": {"action": "deny", "incident_id": "${incident_id}"}, "style": "destructive"}
  ]
}
```

**agent/approval/card_builder.py:**

```python
class CardBuilder:
    def __init__(self, templates_dir: str = "agent/approval/teams_cards"):
        self.templates_dir = Path(templates_dir)
        self._templates: dict[str, str] = {}

    def _load_template(self, template_name: str) -> str:
        """Load and cache template JSON string."""

    def _render(self, template_name: str, variables: dict[str, str]) -> dict:
        """
        Load template, replace all ${key} placeholders with values from variables dict.
        Returns parsed dict (valid JSON).
        """

    def build_approval_card(self, incident: IncidentDocument, approval: ApprovalDocument) -> dict:
        """
        Build an approval request card.
        Uses approval_medium.json for MEDIUM risk, approval_high.json for HIGH risk.
        """

    def build_resolved_card(
        self,
        incident: IncidentDocument,
        approved_by: str,
        action_taken: str,
        verification_result: str,
    ) -> dict:
        """Build a resolution card to replace the approval card."""

    def build_auto_resolved_card(
        self, incident: IncidentDocument, action_taken: str, outcome: str
    ) -> dict:
        """Build a compact notification for LOW risk auto-resolutions."""

    def build_investigation_reply(
        self, incident: IncidentDocument, llm_reasoning: str, log_excerpts: str
    ) -> dict:
        """Build an investigation reply card."""
```

Template loading: load templates lazily on first use, cache in `self._templates`. Fail fast if template file not found (raise `FileNotFoundError`).

Variable substitution: iterate over the `variables` dict, replace `${key}` → `value` in the template string. Use `str.replace()`. All values in the variables dict must be strings. Truncate long strings: `diagnosis` max 500 chars, `log_excerpts` max 1000 chars.

**tests/test_card_builder.py:**

Required test cases:
1. `test_build_approval_card_medium` — `RiskLevel.MEDIUM` → correct template used, assert `"⚠ MEDIUM"` in JSON output.
2. `test_build_approval_card_high` — `RiskLevel.HIGH` → `"🚨 HIGH"` and `"HIGH RISK ACTION"` in output.
3. `test_build_resolved_card` — assert `"RESOLVED"` and `approved_by` value in output.
4. `test_build_auto_resolved_card` — assert `"Auto-Resolved"` in output.
5. `test_all_placeholders_replaced` — assert no `${` strings remain in rendered output for all card types.
6. `test_template_is_valid_json` — assert `build_approval_card()` returns a valid `dict` (not a string).
7. `test_missing_template_raises` — pass a bad templates_dir, assert `FileNotFoundError` on first render.

## Test Criteria

```bash
cd /Users/dattaikhe/LLM/AutoOpsAI
pytest tests/test_card_builder.py -v
# Expected: all 7 tests pass

# Verify all 5 template files exist and are valid JSON
python -c "
import json
from pathlib import Path
templates = [
    'agent/approval/teams_cards/approval_medium.json',
    'agent/approval/teams_cards/approval_high.json',
    'agent/approval/teams_cards/resolved.json',
    'agent/approval/teams_cards/auto_resolved.json',
    'agent/approval/teams_cards/investigation_reply.json',
]
for t in templates:
    data = json.loads(Path(t).read_text())
    assert data['type'] == 'AdaptiveCard', f'{t}: missing AdaptiveCard type'
    print(f'  {t} - valid JSON OK')
print('All 5 templates valid')
"
```

## Dependencies

- Step 01 (project setup)
- Step 02 (core models — `RiskLevel`)
- Step 08 (MongoDB documents — `IncidentDocument`, `ApprovalDocument`)
