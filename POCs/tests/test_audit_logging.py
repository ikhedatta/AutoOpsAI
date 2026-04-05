"""Tests for the audit logging POC."""

import json
import os
import pytest
from datetime import datetime

from POCs.audit_logging_poc.audit_log import (
    AuditLogger,
    AuditAction,
    AuditLogEntry,
    ErrorCategory,
    categorize_error,
)


class TestAuditLogger:
    """Test audit log capture and querying."""

    def setup_method(self):
        self.logger = AuditLogger(log_file=None, use_db=False)

    @pytest.mark.asyncio
    async def test_log_entry(self):
        await self.logger.log(
            incident_id="INC-001",
            action=AuditAction.INCIDENT_DETECTED,
            user_id="system",
            details={"symptom": "High CPU"},
        )
        assert len(self.logger.entries) == 1
        assert self.logger.entries[0].action == AuditAction.INCIDENT_DETECTED

    @pytest.mark.asyncio
    async def test_log_with_error(self):
        await self.logger.log(
            incident_id="INC-001",
            action=AuditAction.ACTION_FAILED,
            user_id="system",
            details={"step": "docker_restart"},
            error="Container not found",
            error_category=ErrorCategory.INFRASTRUCTURE_ERROR,
            severity="ERROR",
        )
        entry = self.logger.entries[0]
        assert entry.error == "Container not found"
        assert entry.error_category == ErrorCategory.INFRASTRUCTURE_ERROR
        assert entry.severity == "ERROR"

    @pytest.mark.asyncio
    async def test_incident_trail(self):
        for action in [AuditAction.INCIDENT_DETECTED, AuditAction.PLAYBOOK_MATCHED, AuditAction.RESOLVED]:
            await self.logger.log(
                incident_id="INC-001",
                action=action,
                user_id="system",
                details={},
            )
        await self.logger.log(
            incident_id="INC-002",
            action=AuditAction.INCIDENT_DETECTED,
            user_id="system",
            details={},
        )
        trail = self.logger.get_incident_trail("INC-001")
        assert len(trail) == 3

    @pytest.mark.asyncio
    async def test_stats(self):
        await self.logger.log(incident_id="INC-001", action=AuditAction.INCIDENT_DETECTED,
                              user_id="system", details={})
        await self.logger.log(incident_id="INC-001", action=AuditAction.RESOLVED,
                              user_id="system", details={})
        stats = self.logger.get_stats()
        assert stats.total_entries == 2
        assert stats.by_action["incident_detected"] == 1
        assert stats.by_action["resolved"] == 1

    @pytest.mark.asyncio
    async def test_file_persistence(self, tmp_path):
        log_file = str(tmp_path / "audit.log")
        file_logger = AuditLogger(log_file=log_file, use_db=False)
        await file_logger.log(
            incident_id="INC-001",
            action=AuditAction.INCIDENT_DETECTED,
            user_id="system",
            details={"test": True},
        )
        assert os.path.exists(log_file)
        with open(log_file) as f:
            line = f.readline()
        data = json.loads(line)
        assert data["incident_id"] == "INC-001"

    @pytest.mark.asyncio
    async def test_export_for_compliance(self, tmp_path):
        await self.logger.log(incident_id="INC-001", action=AuditAction.RESOLVED,
                              user_id="system", details={})
        export_file = str(tmp_path / "export.json")
        self.logger.export_for_compliance(export_file)
        with open(export_file) as f:
            data = json.load(f)
        assert data["total_entries"] == 1

    def test_entry_serialization(self):
        entry = AuditLogEntry(
            timestamp=datetime(2026, 4, 5, 12, 0),
            incident_id="INC-001",
            action=AuditAction.INCIDENT_DETECTED,
            user_id="system",
            session_id="sess-123",
            details={"key": "value"},
        )
        json_str = entry.to_json()
        data = json.loads(json_str)
        assert data["incident_id"] == "INC-001"
        assert data["action"] == "incident_detected"

        d = entry.to_dict()
        assert d["session_id"] == "sess-123"


class TestErrorCategorization:
    def test_playbook_not_found(self):
        assert categorize_error("Playbook not found for this incident") == ErrorCategory.PLAYBOOK_NOT_FOUND

    def test_permission_denied(self):
        assert categorize_error("Permission denied for this action") == ErrorCategory.INSUFFICIENT_PERMISSIONS

    def test_timeout(self):
        assert categorize_error("Operation timeout after 60s") == ErrorCategory.APPROVAL_TIMEOUT

    def test_llm_error(self):
        assert categorize_error("LLM inference failed") == ErrorCategory.LLM_INFERENCE_ERROR

    def test_remediation_context(self):
        assert categorize_error("Step failed", {"action_type": "remediation"}) == ErrorCategory.REMEDIATION_FAILED

    def test_unknown(self):
        assert categorize_error("Something unexpected") == ErrorCategory.UNKNOWN
