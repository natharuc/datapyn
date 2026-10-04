"""Encode retained PNG output for portable image exports."""

from io import BytesIO


def image_bytes(png, export_format):
    if export_format == "png":
        return png
    if export_format not in {"jpg", "jpeg"}:
        raise ValueError("Choose PNG or JPEG for an image")
    from PIL import Image
    with Image.open(BytesIO(png)) as decoded:
        if decoded.width * decoded.height > 40_000_000:
            raise ValueError("Images support at most 40 million pixels")
        rgba = decoded.convert("RGBA")
        # JPEG has no alpha channel. A white paper background preserves the
        # appearance of transparent Matplotlib output without resizing it.
        image = Image.new("RGB", rgba.size, "white")
        image.paste(rgba, mask=rgba.getchannel("A"))
        output = BytesIO()
        image.save(output, format="JPEG", quality=95, subsampling=0, optimize=True)
        return output.getvalue()
