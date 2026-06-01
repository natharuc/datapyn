"""Tests for Copilot SDK compatibility patches."""

from datetime import datetime, timezone


class TestCopilotSdkCompat:
    def test_is_runtime_update_error_detects_model_billing(self):
        from src.services.copilot.copilot_sdk_compat import is_runtime_update_error

        assert is_runtime_update_error("Missing required field 'multiplier' in ModelBilling")

    def test_is_runtime_update_error_detects_iso_timestamp_ping(self):
        from src.services.copilot.copilot_sdk_compat import is_runtime_update_error

        assert is_runtime_update_error(
            "invalid literal for int() with base 10: '2026-06-01T12:21:59.542Z'"
        )

    def test_coerce_sdk_timestamp_accepts_epoch_ms(self):
        from src.services.copilot.copilot_sdk_compat import coerce_sdk_timestamp

        assert coerce_sdk_timestamp(1710000000123) == 1710000000123

    def test_coerce_sdk_timestamp_accepts_iso_string(self):
        from src.services.copilot.copilot_sdk_compat import coerce_sdk_timestamp

        value = coerce_sdk_timestamp("2026-06-01T12:21:59.542Z")
        expected = int(datetime(2026, 6, 1, 12, 21, 59, 542000, tzinfo=timezone.utc).timestamp() * 1000)
        assert value == expected

    def test_apply_sdk_compat_patch_allows_missing_multiplier(self):
        from src.services.copilot.copilot_sdk_compat import apply_sdk_compat_patches

        apply_sdk_compat_patches()
        from copilot.client import ModelBilling

        billing = ModelBilling.from_dict({})
        assert billing.multiplier == 1.0

    def test_apply_sdk_compat_patch_preserves_existing_multiplier(self):
        from src.services.copilot.copilot_sdk_compat import apply_sdk_compat_patches

        apply_sdk_compat_patches()
        from copilot.client import ModelBilling

        billing = ModelBilling.from_dict({"multiplier": 2.5})
        assert billing.multiplier == 2.5

    def test_apply_sdk_compat_patch_accepts_iso_ping_timestamp(self):
        from src.services.copilot.copilot_sdk_compat import apply_sdk_compat_patches

        apply_sdk_compat_patches()
        from copilot.client import PingResponse

        response = PingResponse.from_dict({
            "message": "pong: datapyn",
            "timestamp": "2026-06-01T12:21:59.542Z",
            "protocolVersion": 2,
        })
        assert response.message == "pong: datapyn"
        assert response.protocolVersion == 2
        assert isinstance(response.timestamp, int)
        assert response.timestamp > 0
