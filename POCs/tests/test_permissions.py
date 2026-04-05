"""Tests for the permission system POC."""

from POCs.permission_system_poc.permission_checker import (
    PermissionChecker,
    RiskLevel,
    PermissionResult,
)


class TestPermissionChecker:
    """Test tiered permission checking logic."""

    def setup_method(self):
        # Uses defaults since config file won't exist
        self.checker = PermissionChecker(config_file="nonexistent.yaml")

    def test_low_risk_action_auto_executes(self):
        result = self.checker.check_permission(
            action="redis_memory_purge",
            risk_level=RiskLevel.LOW,
        )
        assert result.result is True

    def test_medium_risk_requires_approval(self):
        result = self.checker.check_permission(
            action="docker_restart_stateless_services",
            risk_level=RiskLevel.MEDIUM,
        )
        assert result.result is True  # It's in the whitelist

    def test_high_risk_action_requires_approval(self):
        result = self.checker.check_permission(
            action="database_failover",
            risk_level=RiskLevel.HIGH,
        )
        assert result.result is True  # In HIGH whitelist

    def test_unknown_action_denied(self):
        result = self.checker.check_permission(
            action="drop_production_database",
            risk_level=RiskLevel.HIGH,
        )
        assert result.result is False

    def test_prefix_matching(self):
        # "docker_restart_stateless_services" should match prefix "docker_restart_"
        result = self.checker.check_permission(
            action="docker_restart_stateless_services",
            risk_level=RiskLevel.MEDIUM,
        )
        assert result.result is True

    def test_low_risk_actions_are_populated(self):
        assert len(self.checker.safe_operations[RiskLevel.LOW]) > 0

    def test_all_risk_levels_have_operations(self):
        for level in RiskLevel:
            assert isinstance(self.checker.safe_operations[level], set)
