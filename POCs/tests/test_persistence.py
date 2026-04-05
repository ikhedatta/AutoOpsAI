"""Tests for the MongoDB persistence layer."""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone


class TestPersistenceHealthCheck:
    """Test persistence module initialization."""

    def test_health_check_when_unavailable(self):
        from pymongo.errors import ConnectionFailure
        from POCs import persistence
        old_client = persistence._client
        try:
            mock_client = MagicMock()
            mock_client.admin.command.side_effect = ConnectionFailure("Connection refused")
            persistence._client = mock_client
            assert persistence.health_check() is False
        finally:
            persistence._client = old_client

    def test_get_db_returns_database(self):
        with patch("POCs.persistence.get_client") as mock_client:
            mock_db = MagicMock()
            mock_client.return_value.__getitem__ = MagicMock(return_value=mock_db)
            from POCs.persistence import get_db
            db = get_db()
            assert db is not None

    def test_close_clears_client(self):
        from POCs import persistence
        persistence._client = MagicMock()
        persistence.close()
        assert persistence._client is None


class TestPersistenceCRUD:
    """Test CRUD helpers with mocked MongoDB."""

    def test_save_incident(self):
        with patch("POCs.persistence.incidents_collection") as mock_coll:
            from POCs.persistence import save_incident
            save_incident({"incident_id": "INC-001", "status": "resolved"})
            mock_coll.return_value.replace_one.assert_called_once()

    def test_save_incident_handles_failure(self):
        with patch("POCs.persistence.incidents_collection") as mock_coll:
            mock_coll.return_value.replace_one.side_effect = Exception("Write failed")
            from POCs.persistence import save_incident
            # Should not raise
            save_incident({"incident_id": "INC-001"})

    def test_find_similar_incidents(self):
        with patch("POCs.persistence.incidents_collection") as mock_coll:
            mock_cursor = MagicMock()
            mock_cursor.sort.return_value.limit.return_value = [{"incident_id": "INC-001"}]
            mock_coll.return_value.find.return_value = mock_cursor
            from POCs.persistence import find_similar_incidents
            results = find_similar_incidents("High CPU")
            assert len(results) == 1

    def test_append_audit_entry(self):
        with patch("POCs.persistence.audit_collection") as mock_coll:
            from POCs.persistence import append_audit_entry
            append_audit_entry({"incident_id": "INC-001", "action": "detected"})
            mock_coll.return_value.insert_one.assert_called_once()

    def test_save_conversation(self):
        with patch("POCs.persistence.conversations_collection") as mock_coll:
            from POCs.persistence import save_conversation
            save_conversation("conv-123", [{"role": "user", "content": "hello"}])
            mock_coll.return_value.replace_one.assert_called_once()

    def test_load_conversation_found(self):
        with patch("POCs.persistence.conversations_collection") as mock_coll:
            mock_coll.return_value.find_one.return_value = {
                "conversation_id": "conv-123",
                "messages": [{"role": "user", "content": "hello"}],
            }
            from POCs.persistence import load_conversation
            msgs = load_conversation("conv-123")
            assert len(msgs) == 1

    def test_load_conversation_not_found(self):
        with patch("POCs.persistence.conversations_collection") as mock_coll:
            mock_coll.return_value.find_one.return_value = None
            from POCs.persistence import load_conversation
            msgs = load_conversation("nonexistent")
            assert msgs == []

    def test_get_playbook_stats_empty(self):
        with patch("POCs.persistence.incidents_collection") as mock_coll:
            mock_coll.return_value.aggregate.return_value = []
            from POCs.persistence import get_playbook_stats
            stats = get_playbook_stats("pb1")
            assert stats["usage_count"] == 0
