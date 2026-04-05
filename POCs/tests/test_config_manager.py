"""Tests for the configuration state management POC."""

from POCs.configuration_state_poc.config_manager import ConfigManager


class TestConfigManager:
    """Test hierarchical config loading."""

    def setup_method(self):
        self.manager = ConfigManager(config_dir="nonexistent_dir")

    def test_default_config_loaded(self):
        config = self.manager.get_config("production")
        assert config is not None

    def test_approval_policy_present(self):
        config = self.manager.get_config("production")
        assert hasattr(config, "approval_policy")

    def test_default_has_low_risk_no_approval(self):
        defaults = ConfigManager.DEFAULT_CONFIG
        assert defaults["approval_policy"]["LOW"]["requires_approval"] is False

    def test_default_has_high_risk_approval(self):
        defaults = ConfigManager.DEFAULT_CONFIG
        assert defaults["approval_policy"]["HIGH"]["requires_approval"] is True

    def test_default_timeout_values(self):
        defaults = ConfigManager.DEFAULT_CONFIG
        assert defaults["approval_policy"]["MEDIUM"]["timeout_seconds"] == 300
