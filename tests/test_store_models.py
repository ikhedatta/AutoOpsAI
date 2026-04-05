"""Tests for agent.store.models — Beanie document models.

Since Beanie Document subclasses require init_beanie() to be called before
instantiation (they check for motor_collection), we test the model structure
and metadata without creating instances.
"""

from __future__ import annotations

import pytest

from agent.models import IncidentStatus, Severity
from agent.store.models import (
    ALL_DOCUMENTS,
    ApprovalDoc,
    AuditLogDoc,
    ChatMessageDoc,
    IncidentDoc,
)


class TestIncidentDoc:
    def test_collection_name(self):
        assert IncidentDoc.Settings.name == "incidents"

    def test_has_expected_fields(self):
        fields = IncidentDoc.model_fields
        assert "incident_id" in fields
        assert "title" in fields
        assert "service_name" in fields
        assert "severity" in fields
        assert "status" in fields
        assert "detected_at" in fields
        assert "resolved_at" in fields
        assert "timeline" in fields
        assert "proposed_actions" in fields

    def test_status_default(self):
        fields = IncidentDoc.model_fields
        assert fields["status"].default == IncidentStatus.DETECTING.value

    def test_optional_fields(self):
        fields = IncidentDoc.model_fields
        assert fields["resolved_at"].default is None
        assert fields["root_cause"].default is None
        assert fields["rollback_plan"].default is None


class TestApprovalDoc:
    def test_collection_name(self):
        assert ApprovalDoc.Settings.name == "approvals"

    def test_has_expected_fields(self):
        fields = ApprovalDoc.model_fields
        assert "incident_id" in fields
        assert "severity" in fields
        assert "title" in fields
        assert "decision" in fields
        assert "decided_by" in fields
        assert "timeout_seconds" in fields

    def test_decision_default_none(self):
        fields = ApprovalDoc.model_fields
        assert fields["decision"].default is None
        assert fields["decided_by"].default is None


class TestAuditLogDoc:
    def test_collection_name(self):
        assert AuditLogDoc.Settings.name == "audit_log"

    def test_has_expected_fields(self):
        fields = AuditLogDoc.model_fields
        assert "action" in fields
        assert "resource_type" in fields
        assert "resource_id" in fields
        assert "user_id" in fields
        assert "detail" in fields
        assert "timestamp" in fields


class TestChatMessageDoc:
    def test_collection_name(self):
        assert ChatMessageDoc.Settings.name == "chat_messages"

    def test_has_expected_fields(self):
        fields = ChatMessageDoc.model_fields
        assert "incident_id" in fields
        assert "role" in fields
        assert "content" in fields
        assert "metadata" in fields
        assert "timestamp" in fields


class TestAllDocuments:
    def test_contains_all_models(self):
        assert IncidentDoc in ALL_DOCUMENTS
        assert ApprovalDoc in ALL_DOCUMENTS
        assert AuditLogDoc in ALL_DOCUMENTS
        assert ChatMessageDoc in ALL_DOCUMENTS
        assert len(ALL_DOCUMENTS) == 4
