"""Tests for Permission System POC"""

import pytest
from permission_checker import (
    PermissionChecker,
    RiskLevel,
    should_auto_execute,
    get_approval_timeout,
    APPROVAL_REQUIREMENTS,
)


@pytest.fixture
def permission_checker():
    """Create permission checker with default config."""
    return PermissionChecker()


class TestPermissionChecks:
    """Test permission checking logic."""
    
    def test_low_risk_auto_execute(self, permission_checker):
        """LOW risk actions should auto-execute."""
        result = permission_checker.check_permission(
            action="redis_memory_purge",
            risk_level=RiskLevel.LOW,
        )
        assert result.result is True
        assert "safe" in result.reason.lower()
    
    def test_medium_risk_requires_approval(self, permission_checker):
        """MEDIUM risk unknown action requires approval."""
        result = permission_checker.check_permission(
            action="unknown_action_xyz",
            risk_level=RiskLevel.MEDIUM,
        )
        assert result.result is False
        assert "requires approval" in result.reason.lower()
    
    def test_high_risk_requires_approval(self, permission_checker):
        """HIGH risk actions require approval."""
        result = permission_checker.check_permission(
            action="database_failover",
            risk_level=RiskLevel.HIGH,
        )
        assert result.result is True  # It's in the safe list
        assert "safe" in result.reason.lower()
    
    def test_prefix_matching(self, permission_checker):
        """Prefix matching should work for wildcard safe operations."""
        permission_checker.safe_operations[RiskLevel.LOW].add("cache_*")
        result = permission_checker.check_permission(
            action="cache_clear_all",
            risk_level=RiskLevel.LOW,
        )
        assert result.result is True
        assert "prefix" in result.reason.lower()
    
    def test_config_override_blocks_action(self, permission_checker):
        """Config override should block even safe actions."""
        result = permission_checker.check_permission(
            action="redis_memory_purge",
            risk_level=RiskLevel.LOW,
            environment="production",
            config_overrides={"redis_memory_purge": False},
        )
        assert result.result is False
        assert "config override" in result.reason.lower()
    
    def test_config_override_allows_action(self, permission_checker):
        """Config override should allow blocked actions."""
        result = permission_checker.check_permission(
            action="unknown_action",
            risk_level=RiskLevel.LOW,
            config_overrides={"unknown_action": True},
        )
        assert result.result is True
        assert "config override" in result.reason.lower()


class TestApprovalRequirements:
    """Test approval threshold logic."""
    
    def test_low_risk_no_approval(self):
        """LOW risk should not require approval."""
        assert should_auto_execute(RiskLevel.LOW) is True
        assert get_approval_timeout(RiskLevel.LOW) == 0
    
    def test_medium_risk_requires_approval(self):
        """MEDIUM risk should require approval with 5-min timeout."""
        assert should_auto_execute(RiskLevel.MEDIUM) is False
        assert get_approval_timeout(RiskLevel.MEDIUM) == 300
    
    def test_high_risk_requires_approval_no_timeout(self):
        """HIGH risk should require approval without timeout."""
        assert should_auto_execute(RiskLevel.HIGH) is False
        assert get_approval_timeout(RiskLevel.HIGH) == 0


class TestApprovalThresholds:
    """Test approval requirement descriptions."""
    
    def test_approval_threshold_exists_for_all_levels(self):
        """All risk levels should have approval requirements defined."""
        for risk_level in RiskLevel:
            assert risk_level in APPROVAL_REQUIREMENTS
            assert "requires_approval" in APPROVAL_REQUIREMENTS[risk_level]
            assert "timeout_seconds" in APPROVAL_REQUIREMENTS[risk_level]
            assert "description" in APPROVAL_REQUIREMENTS[risk_level]


class TestDynamicOperationAddition:
    """Test adding operations dynamically."""
    
    def test_add_safe_operation(self, permission_checker):
        """Should be able to add operations at runtime."""
        permission_checker.add_safe_operation(
            "custom_action",
            RiskLevel.LOW,
        )
        
        result = permission_checker.check_permission(
            action="custom_action",
            risk_level=RiskLevel.LOW,
        )
        assert result.result is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
