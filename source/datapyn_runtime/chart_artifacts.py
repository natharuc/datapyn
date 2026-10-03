"""Atomic chart files; Plotly in the UI and headless Agg for MCP image exports."""

from __future__ import annotations

import base64
from io import BytesIO
import json
from pathlib import Path

from .data_tools import _destination, _integer, atomic_destination, build_chart

MAX_IMAGE_BYTES = 32 * 1024 * 1024


def _png_data(value):
    prefix = "data:image/png;base64,"
    if not isinstance(value, str) or not value.startswith(prefix):
        raise ValueError("Provide a PNG image data URL")
    if len(value) > MAX_IMAGE_BYTES * 4 // 3 + 100:
        raise ValueError("Chart images may contain at most 32 MiB")
    try:
        image = base64.b64decode(value[len(prefix):], validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError("Invalid PNG image encoding") from error
    if not image.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("The image is not a PNG")
    from PIL import Image
    try:
        with Image.open(BytesIO(image)) as decoded:
            if decoded.format != "PNG" or decoded.width * decoded.height > 40_000_000:
                raise ValueError("Chart images support at most 40 million pixels")
            decoded.verify()
    except Exception as error:
        raise ValueError("Invalid or oversized PNG image") from error
    return image


def _jpeg_data(png, background):
    """Flatten transparency onto the configured paper color, without resizing."""
    from PIL import Image, ImageColor
    with Image.open(BytesIO(png)) as decoded:
        if decoded.width * decoded.height > 40_000_000:
            raise ValueError("Chart images support at most 40 million pixels")
        rgba = decoded.convert("RGBA")
        image = Image.new("RGB", rgba.size, ImageColor.getrgb(background))
        image.paste(rgba, mask=rgba.getchannel("A"))
        output = BytesIO()
        image.save(output, format="JPEG", quality=95, subsampling=0, optimize=True)
        return output.getvalue()


def _offline_html(response):
    import plotly.graph_objects as go
    figure = go.Figure(response["figure"])
    content = figure.to_html(include_plotlyjs=True, full_html=True, div_id="datapyn-chart",
                             config={"responsive": True, "scrollZoom": True, "displaylogo": False,
                                     "modeBarButtonsToRemove": ["lasso2d", "select2d"]})
    background = response["figure"]["layout"]["paper_bgcolor"]
    font_path = Path(__file__).resolve().parents[1] / "src" / "assets" / "fonts" / "Ubuntu-Regular.ttf"
    font = ""
    if font_path.is_file() and font_path.stat().st_size <= 512 * 1024:
        font = "@font-face{font-family:Ubuntu;src:url(data:font/ttf;base64," + base64.b64encode(font_path.read_bytes()).decode("ascii") + ") format('truetype');font-weight:400;font-display:swap;}"
    style = "<meta name='viewport' content='width=device-width,initial-scale=1'><style>" + font + f"html,body{{margin:0;background:{background};height:100%;font-family:Ubuntu,sans-serif}}#datapyn-chart{{min-height:500px;height:100vh!important}}" + "</style>"
    return content.replace("<head>", "<head>" + style, 1).encode("utf-8")


def _agg_png(response, width, height):
    """Render bounded Plotly traces without a GUI, browser, or Qt backend."""
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    import numpy as np

    config, layout = response["config"], response["figure"]["layout"]
    background, color = layout["paper_bgcolor"], layout["font"]["color"]
    figure = Figure(figsize=(width / 100, height / 100), dpi=100, facecolor=background, layout="constrained")
    FigureCanvasAgg(figure)
    axes = figure.add_subplot(111, facecolor=background)
    traces = response["figure"]["data"]
    kind, stacked = config.get("type", "bar"), config.get("stacking") in {"stacked", "percent"}
    label_color = traces[0].get("textfont", {}).get("color") or color
    show_labels = bool(config.get("show_data_labels"))
    if kind == "pie":
        trace = traces[0]
        axes.pie(trace["values"], labels=trace["labels"], colors=trace["marker"]["colors"],
                 autopct="%1.1f%%" if show_labels else None, wedgeprops={"width": 0.58, "edgecolor": background},
                 textprops={"color": label_color})
    else:
        labels = list(traces[0].get("y" if config.get("horizontal") and kind == "bar" else "x", []))
        positions = np.arange(len(labels))
        previous_positive, previous_negative = np.zeros(len(labels)), np.zeros(len(labels))
        area_previous = np.zeros(len(labels))
        for index, trace in enumerate(traces):
            horizontal = kind == "bar" and bool(config.get("horizontal"))
            values = np.array([float(value) if value is not None else np.nan for value in trace["x" if horizontal else "y"]])
            name = trace.get("name", "")
            trace_color = trace.get("marker", {}).get("color") or trace.get("line", {}).get("color") or "#5b8def"
            if kind == "bar":
                bar_width = 0.8 if stacked else 0.8 / max(1, len(traces))
                offset = positions if stacked else positions - 0.4 + bar_width * (index + 0.5)
                bottom = np.where(values >= 0, previous_positive, previous_negative) if stacked else np.zeros(len(values))
                options = {"color": trace_color, "alpha": trace.get("opacity", 0.94), "label": name}
                bars = axes.barh(offset, values, height=bar_width, left=bottom, **options) if horizontal else axes.bar(offset, values, width=bar_width, bottom=bottom, **options)
                if stacked:
                    previous_positive += np.where(values >= 0, values, 0)
                    previous_negative += np.where(values < 0, values, 0)
                if show_labels:
                    axes.bar_label(bars, labels=trace.get("text"), color=label_color, fontsize=9, padding=3)
            elif kind == "area":
                top = area_previous + values if stacked else values
                axes.fill_between(positions, area_previous if stacked else 0, top, color=trace_color,
                                  alpha=max(0.05, min(0.9, float(config.get("area_opacity", 20)) / 100)), label=name)
                axes.plot(positions, top, color=trace_color, linewidth=trace.get("line", {}).get("width", 2))
                area_previous = top if stacked else area_previous
            elif kind == "scatter":
                axes.scatter(positions, values, color=trace_color, s=trace.get("marker", {}).get("size", 5) ** 2, label=name)
            else:
                line = trace.get("line", {})
                axes.plot(positions, values, color=trace_color, label=name,
                          linestyle={"dash": "--", "dot": ":", "dashdot": "-."}.get(line.get("dash"), "-") if config.get("show_line", True) else "None",
                          linewidth=line.get("width", 2), marker="o" if config.get("show_markers", True) or not config.get("show_line", True) else None,
                          markersize=trace.get("marker", {}).get("size", 5))
            if show_labels and kind != "bar":
                for x, y, text in zip(positions, values, trace.get("text") or []):
                    axes.annotate(text, (x, y), xytext=(0, 5), textcoords="offset points", ha="center", color=label_color, fontsize=9)
        # Keep a static image readable while retaining every data point.
        stride = max(1, (len(labels) + 23) // 24)
        visible = positions[::stride]
        visible_labels = labels[::stride]
        if config.get("horizontal") and kind == "bar":
            axes.set_yticks(visible, visible_labels)
        else:
            axes.set_xticks(visible, visible_labels, rotation=35 if len(labels) > 8 else 0, ha="right" if len(labels) > 8 else "center")
        if config.get("show_grid", True):
            axes.grid(True, color=layout["xaxis"]["gridcolor"], alpha=0.6)
        else:
            axes.grid(False)
        axes.set_axisbelow(True)
        if config.get("show_legend", True) and any(trace.get("name") for trace in traces):
            legend = axes.legend(facecolor=background, edgecolor="none", loc="best")
            for item in legend.get_texts():
                item.set_color(color)
        axes.set_xlabel(layout["xaxis"]["title"]["text"], color=color)
        axes.set_ylabel(layout["yaxis"]["title"]["text"], color=color)
    axes.set_title(layout.get("title", {}).get("text", ""), color=color, loc="left", pad=16)
    axes.tick_params(colors=color)
    for spine in axes.spines.values():
        spine.set_visible(bool(config.get("show_axis_line", False)))
        spine.set_color(layout.get("xaxis", {}).get("linecolor", color))
    output = BytesIO()
    font_path = Path(__file__).resolve().parents[1] / "src" / "assets" / "fonts" / "Ubuntu-Regular.ttf"
    if font_path.is_file():
        from matplotlib.font_manager import FontProperties
        from matplotlib.text import Text
        for item in figure.findobj(Text):
            item.set_fontproperties(FontProperties(fname=str(font_path), size=item.get_fontsize()))
    figure.savefig(output, format="png", facecolor=background, dpi=100)
    figure.clear()
    return output.getvalue()


def export_chart(params, namespace, store):
    path = _destination(params)
    format_name = params.get("format") or path.suffix.lstrip(".").lower()
    if format_name not in {"html", "png", "jpg", "jpeg", "json"}:
        raise ValueError("Export a chart as HTML, PNG, JPEG, or JSON")
    extensions = {".jpg", ".jpeg"} if format_name in {"jpg", "jpeg"} else {"." + format_name}
    if path.suffix.lower() not in extensions:
        raise ValueError(f"Choose a .{format_name} destination")
    response = build_chart(params, namespace, store)
    if format_name == "html":
        artifact, renderer = _offline_html(response), "plotly-inline"
    elif format_name == "json":
        artifact, renderer = json.dumps(response, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8"), "plotly-json"
    elif params.get("image_data") is not None:
        artifact, renderer = _png_data(params["image_data"]), "plotly-browser"
    else:
        width = _integer(params.get("width", 1400), "width", 400, 4000)
        height = _integer(params.get("height", 850), "height", 300, 4000)
        artifact, renderer = _agg_png(response, width, height), "matplotlib-agg"
    if format_name in {"jpg", "jpeg"}:
        artifact = _jpeg_data(artifact, response["figure"]["layout"]["paper_bgcolor"])
    with atomic_destination(path) as temporary:
        temporary.write_bytes(artifact)
    return {"path": str(path), "bytes": len(artifact), "format": format_name, "renderer": renderer,
            "source_rows": response["source_rows"], "point_count": response["point_count"]}
