"""Real offline chart files and native/browser PNG precision validation."""

import base64
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys

import pandas as pd
from PIL import Image
import polars as pl
import pytest

from datapyn_runtime.data_tools import dispatch
from datapyn_runtime.kernel import ResultStore


@pytest.fixture
def chart():
    namespace = {"df": pd.DataFrame({"group": ["a", "b", "a"], "value": [1.2, 2.3, 3.4]})}
    store = ResultStore(pd, pl)
    return namespace, store, {"variable_name": "df", "config": {"type": "bar", "x_column": "group", "y_columns": ["value"], "title": "Análise", "show_data_labels": True}}


def test_html_is_self_contained_with_local_plotly_and_font(chart, tmp_path):
    namespace, store, params = chart
    path = tmp_path / "chart.html"
    response = dispatch("result.chart_export", {**params, "path": str(path)}, namespace, store)
    html = path.read_text(encoding="utf-8")
    assert "plotly.js" in html
    assert "Plotly.newPlot" in html
    assert "data:font/ttf;base64," in html
    assert "<script src=" not in html
    assert "Análise" in html or "An\\u00e1lise" in html
    assert response["renderer"] == "plotly-inline"
    assert response["point_count"] == 2
    assert response["bytes"] == path.stat().st_size


def test_json_preserves_the_rendered_figure_and_styles(chart, tmp_path):
    namespace, store, params = chart
    path = tmp_path / "chart.json"
    config = {**params["config"], "bar_opacity": 27, "label_color": "#123456", "label_decimals": 3,
              "show_axis_line": True, "axis_color": "#234567", "grid_color": "#345678"}
    dispatch("result.chart_export", {**params, "config": config, "path": str(path)}, namespace, store)
    response = json.loads(path.read_text(encoding="utf-8"))
    trace = response["figure"]["data"][0]
    assert trace["opacity"] == 0.27
    assert trace["text"] == ["4.600", "2.300"]
    assert trace["textfont"]["color"] == "#123456"
    assert response["figure"]["layout"]["xaxis"]["showline"]
    assert response["figure"]["layout"]["xaxis"]["gridcolor"] == "#345678"
    assert response["figure"]["layout"]["font"]["family"].startswith("Segoe UI, Roboto")
    assert response["figure"]["layout"]["font"]["size"] == 12
    assert response["figure"]["layout"]["title"]["font"]["size"] == 16
    assert response["figure"]["layout"]["margin"] == {"l": 56, "r": 24, "t": 56, "b": 72}
    assert response["figure"]["layout"]["xaxis"]["tickfont"]["size"] == 11
    assert trace["textposition"] == "outside"


def test_keep_zero_and_drop_null_modes_preserve_legacy_chart_options(tmp_path):
    namespace = {"df": pd.DataFrame({"group": ["a", "b", "c"], "first": [1, None, 3], "second": [None, 2, 4]})}
    store = ResultStore(pd, pl)
    config = {"x_column": "group", "y_columns": ["first", "second"], "aggregation": "mean"}
    figures = {mode: dispatch("result.chart", {"variable_name": "df", "config": {**config, "nulls": mode}}, namespace, store)
               for mode in ["keep", "zero", "drop"]}
    assert figures["keep"]["figure"]["data"][0]["y"] == [1, None, 3]
    assert figures["zero"]["figure"]["data"][0]["y"] == [1, 0, 3]
    assert figures["drop"]["point_count"] == 1


@pytest.mark.parametrize("kind", ["bar", "line", "scatter", "area", "pie"])
def test_mcp_png_renders_all_types_headlessly(chart, tmp_path, kind):
    namespace, store, params = chart
    path = tmp_path / f"chart-{kind}.png"
    response = dispatch("result.chart_export", {**params, "config": {**params["config"], "type": kind}, "path": str(path), "width": 700, "height": 400}, namespace, store)
    with Image.open(path) as image:
        assert image.format == "PNG"
        assert image.size == (700, 400)
    assert response["renderer"] == "matplotlib-agg"
    assert response["bytes"] > 1000


def test_native_ui_png_writes_exact_plotly_image_bytes(chart, tmp_path):
    namespace, store, params = chart
    image = Image.new("RGB", (20, 10), "red")
    output = BytesIO()
    image.save(output, format="PNG")
    payload = output.getvalue()
    path = tmp_path / "browser.png"
    response = dispatch("result.chart_export", {**params, "path": str(path), "image_data": "data:image/png;base64," + base64.b64encode(payload).decode()}, namespace, store)
    assert path.read_bytes() == payload
    assert response["renderer"] == "plotly-browser"


@pytest.mark.parametrize("extension", ["jpg", "jpeg"])
def test_mcp_jpeg_is_rgb_and_preserves_dimensions_and_paper_color(chart, tmp_path, extension):
    namespace, store, params = chart
    path = tmp_path / f"chart.{extension}"
    response = dispatch("result.chart_export", {**params, "config": {**params["config"], "background_color": "#e0d0c0"},
                        "path": str(path), "width": 600, "height": 350}, namespace, store)
    with Image.open(path) as image:
        assert image.format == "JPEG" and image.mode == "RGB"
        assert image.size == (600, 350)
        assert all(abs(value - expected) <= 2 for value, expected in zip(image.getpixel((0, 0)), (224, 208, 192)))
    assert response["format"] == extension
    assert response["renderer"] == "matplotlib-agg"


def test_browser_jpeg_flattens_transparent_png_against_selected_background(chart, tmp_path):
    namespace, store, params = chart
    image = Image.new("RGBA", (20, 10), (255, 0, 0, 0))
    for x in range(8, 16):
        for y in range(2, 10):
            image.putpixel((x, y), (20, 180, 40, 255))
    output = BytesIO()
    image.save(output, format="PNG")
    path = tmp_path / "browser.jpeg"
    response = dispatch("result.chart_export", {**params, "path": str(path), "format": "jpg",
                        "config": {**params["config"], "background_color": "#ffffff"},
                        "image_data": "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()}, namespace, store)
    with Image.open(path) as saved:
        assert saved.size == image.size and saved.mode == "RGB"
        assert all(value >= 250 for value in saved.getpixel((0, 0)))
        assert all(abs(value - expected) <= 14 for value, expected in zip(saved.getpixel((10, 5)), (20, 180, 40)))
    assert response["renderer"] == "plotly-browser"


def test_invalid_jpeg_source_never_truncates_existing_destination(chart, tmp_path):
    namespace, store, params = chart
    path = tmp_path / "existing.jpg"
    path.write_bytes(b"original")
    with pytest.raises(ValueError):
        dispatch("result.chart_export", {**params, "path": str(path), "image_data": "data:image/png;base64,bad!!"}, namespace, store)
    assert path.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("image_data", ["data:text/html;base64,PHNjcmlwdD4=", "data:image/png;base64,bad!!", "data:image/png;base64,aGVsbG8="])
def test_invalid_png_never_truncates_existing_destination(chart, tmp_path, image_data):
    namespace, store, params = chart
    path = tmp_path / "existing.png"
    path.write_bytes(b"original")
    with pytest.raises(ValueError):
        dispatch("result.chart_export", {**params, "path": str(path), "image_data": image_data}, namespace, store)
    assert path.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [path]


def test_agg_chart_export_never_imports_qt_in_a_fresh_interpreter(tmp_path):
    source = Path(__file__).resolve().parents[1] / "source"
    script = """
import sys
import pandas as pd,polars as pl
from datapyn_runtime.kernel import ResultStore
from datapyn_runtime.data_tools import dispatch
dispatch('result.chart_export',{'variable_name':'df','config':{'x_column':'x','y_columns':['y']},'path':sys.argv[1]},{'df':pd.DataFrame({'x':['a'],'y':[1]})},ResultStore(pd,pl))
assert not any(name.startswith(('PyQt','PySide')) for name in sys.modules)
"""
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path / "fresh.png")], env={**os.environ, "PYTHONPATH": str(source)}, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
