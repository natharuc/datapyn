import base64

import pytest

from src.services.copilot.copilot_attachments import (
    AttachmentValidationError,
    build_sdk_attachments,
    normalize_attachment,
    validate_attachments_for_model,
)
from src.services.copilot.copilot_models import infer_supports_vision, model_supports_vision


PNG_1X1 = base64.b64encode(
    bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000a49444154789c6300010000050001000d0a2db40000000049454e44ae426082"
    )
).decode("ascii")


class TestCopilotAttachments:
    def test_normalize_attachment_accepts_data_url(self):
        item = normalize_attachment({
            "name": "shot.png",
            "mimeType": "image/png",
            "data": f"data:image/png;base64,{PNG_1X1}",
        })
        assert item["mimeType"] == "image/png"
        assert item["data"] == PNG_1X1
        assert item["size"] > 0

    def test_build_sdk_attachments_uses_blob_type(self):
        item = normalize_attachment({
            "name": "shot.png",
            "mimeType": "image/png",
            "data": PNG_1X1,
        })
        sdk_items = build_sdk_attachments([item])
        assert sdk_items == [{
            "type": "blob",
            "data": PNG_1X1,
            "mimeType": "image/png",
            "displayName": "shot.png",
        }]

    def test_validate_attachments_rejects_non_vision_model(self):
        models = [{"id": "o3-mini", "name": "o3-mini", "supports_vision": False}]
        item = normalize_attachment({
            "name": "shot.png",
            "mimeType": "image/png",
            "data": PNG_1X1,
        })
        with pytest.raises(AttachmentValidationError):
            validate_attachments_for_model([item], models, "o3-mini")

    def test_validate_attachments_accepts_vision_model(self):
        models = [{"id": "gpt-4o", "name": "GPT-4o", "supports_vision": True}]
        item = normalize_attachment({
            "name": "shot.png",
            "mimeType": "image/png",
            "data": PNG_1X1,
        })
        validated = validate_attachments_for_model([item], models, "gpt-4o")
        assert len(validated) == 1

    def test_attachment_limits_ignore_sdk_single_image_cap(self):
        from src.services.copilot.copilot_attachments import attachment_limits_for_model

        models = [{"id": "gpt-4o", "supports_vision": True, "max_prompt_images": 1}]
        limits = attachment_limits_for_model(models, "gpt-4o")
        assert limits["max_attachments"] >= 4

    def test_infer_supports_vision_for_common_models(self):
        assert infer_supports_vision("gpt-4o") is True
        assert infer_supports_vision("claude-sonnet-4") is True
        assert model_supports_vision([{"id": "gpt-4o", "supports_vision": True}], "gpt-4o") is True
