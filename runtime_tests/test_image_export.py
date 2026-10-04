import base64
from io import BytesIO
import json
from pathlib import Path

from PIL import Image
import pytest

from datapyn_runtime.rich_outputs import RichOutputs
from test_runtime import Client


@pytest.mark.parametrize("extension", ["png", "jpg", "jpeg"])
def test_rich_image_exports_real_format_without_resizing(tmp_path, extension):
    image = Image.new("RGBA", (32, 16), (255, 0, 0, 0))
    image.putpixel((0, 0), (0, 0, 255, 255))
    png = BytesIO()
    image.save(png, "PNG")
    capture = RichOutputs()
    assert capture.image(png.getvalue())
    output = capture.outputs[0]
    path = tmp_path / f"figura.{extension}"
    response = capture.write({"artifact_id": output["artifact_id"], "path": str(path), "format": extension})
    assert response["bytes"] == path.stat().st_size
    with Image.open(path) as decoded:
        assert decoded.size == (32, 16) and decoded.format == ("PNG" if extension == "png" else "JPEG")
        if extension != "png":
            assert decoded.mode == "RGB" and all(channel > 245 for channel in decoded.getpixel((25, 12)))
    assert capture.artifacts[output["artifact_id"]][0]["data"] == base64.b64encode(png.getvalue()).decode("ascii")


def test_failed_image_decode_preserves_destination(tmp_path):
    capture = RichOutputs()
    assert capture.image(b"\x89PNG\r\n\x1a\ninvalid")
    path = tmp_path / "figura.jpg"
    path.write_bytes(b"existing")
    with pytest.raises(Exception):
        capture.write({"artifact_id": capture.outputs[0]["artifact_id"], "path": str(path), "format": "jpg"})
    assert path.read_bytes() == b"existing" and not list(tmp_path.glob(".*.tmp"))


def test_runtime_artifact_write_infers_jpeg_and_plotly_json_without_explicit_format():
    client = Client()
    try:
        client.session()
        finished = client.execute("import matplotlib.pyplot as plt\nplt.plot([1,2], [3,4])\nplt.gcf()", "image-inference")
        assert finished["status"] == "succeeded", finished
        artifact = finished["rich_outputs"][0]
        directory = Path(client.state_directory.name)
        for suffix, expected in (("png", "PNG"), ("jpg", "JPEG"), ("JPEG", "JPEG")):
            path = directory / f"figure.{suffix}"
            response = client.request("result.artifact_write", {"session_id": "a", "artifact_id": artifact["artifact_id"], "path": str(path)})
            assert response["format"] == suffix.lower()
            with Image.open(path) as image:
                assert image.format == expected
        mismatch = directory / "mismatch.png"
        mismatch.write_bytes(b"preserve")
        response = client.response("result.artifact_write", {"session_id": "a", "artifact_id": artifact["artifact_id"], "path": str(mismatch), "format": "jpg"})
        assert "Choose a .jpg destination" in response["error"]["message"]
        assert mismatch.read_bytes() == b"preserve"
        unsupported = directory / "figure.gif"
        response = client.response("result.artifact_write", {"session_id": "a", "artifact_id": artifact["artifact_id"], "path": str(unsupported)})
        assert "Choose a .png destination" in response["error"]["message"]
        assert not unsupported.exists()
        finished = client.execute("import plotly.graph_objects as go\ngo.Figure(data=[go.Bar(x=['a'], y=[37])])", "plotly-inference")
        assert finished["status"] == "succeeded", finished
        artifact = finished["rich_outputs"][0]
        path = directory / "plotly.json"
        response = client.request("result.artifact_write", {"session_id": "a", "artifact_id": artifact["artifact_id"], "path": str(path)})
        assert response["format"] == "json" and json.loads(path.read_text())["data"][0]["y"] == [37]
    finally:
        client.close()
