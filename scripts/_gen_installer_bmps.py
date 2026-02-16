"""Generate installer BMPs with DataPyn logo (24-bit BMP for WiX)."""
import sys
import os

# Add source to path for logo access
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QImage, QPainter, QColor, QFont, QPen
from PyQt6.QtSvg import QSvgRenderer
from PIL import Image

app = QApplication(sys.argv)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
svg_path = os.path.join(ROOT_DIR, 'source', 'src', 'assets', 'datapyn_logo.svg')

renderer = QSvgRenderer(svg_path)
assert renderer.isValid(), f"Failed to load SVG: {svg_path}"

# =============================================
# DIALOG BMP (493x312) - 24-bit
# Left panel (0-163px) = logo + text
# Right panel (164-493) = wizard text (WiX)
# =============================================
dialog = QImage(493, 312, QImage.Format.Format_ARGB32)
dialog.fill(QColor(255, 255, 255))
p = QPainter(dialog)
p.setRenderHint(QPainter.RenderHint.Antialiasing)
p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

# Left panel background
p.fillRect(0, 0, 164, 312, QColor(240, 244, 250))

# Render SVG logo centered in left panel
logo_size = 110
logo_x = (164 - logo_size) / 2
logo_y = 50
renderer.render(p, QRectF(logo_x, logo_y, logo_size, logo_size))

# Text 'DataPyn' below logo
p.setPen(QColor(51, 105, 255))  # #3369FF same as logo
font_title = QFont('Segoe UI', 16)
font_title.setBold(True)
p.setFont(font_title)
p.drawText(0, 170, 164, 30, Qt.AlignmentFlag.AlignCenter, 'DataPyn')

# Subtitle
p.setPen(QColor(100, 100, 100))
font_sub = QFont('Segoe UI', 8)
p.setFont(font_sub)
p.drawText(0, 198, 164, 18, Qt.AlignmentFlag.AlignCenter, 'Data Analysis Tool')

# Separator line
p.setPen(QPen(QColor(210, 215, 225), 1))
p.drawLine(164, 0, 164, 312)
p.end()

# Convert QImage -> 24-bit BMP via Pillow
temp_dialog = os.path.join(SCRIPT_DIR, '_dialog_temp.png')
dialog_out = os.path.join(SCRIPT_DIR, 'installer_dialog.bmp')
dialog.save(temp_dialog, 'PNG')
img = Image.open(temp_dialog).convert('RGB')
img.save(dialog_out, 'BMP')
os.remove(temp_dialog)
print(f"Dialog BMP: {os.path.getsize(dialog_out)} bytes -> {dialog_out}")

# =============================================
# BANNER BMP (493x58) - 24-bit
# Left side = page titles (WiX)
# Right side = our logo + text
# =============================================
banner = QImage(493, 58, QImage.Format.Format_ARGB32)
banner.fill(QColor(255, 255, 255))
p2 = QPainter(banner)
p2.setRenderHint(QPainter.RenderHint.Antialiasing)
p2.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

# Logo on right side (leave enough margin so text is not clipped)
logo_bs = 36
logo_bx = 493 - 130
logo_by = (58 - logo_bs) / 2
renderer.render(p2, QRectF(logo_bx, logo_by, logo_bs, logo_bs))

# Text next to logo
p2.setPen(QColor(51, 105, 255))
font_banner = QFont('Segoe UI', 11)
font_banner.setBold(True)
p2.setFont(font_banner)
p2.drawText(int(logo_bx + logo_bs + 6), 0, 90, 58,
            Qt.AlignmentFlag.AlignVCenter, 'DataPyn')

# Bottom border
p2.setPen(QPen(QColor(210, 215, 225), 1))
p2.drawLine(0, 57, 493, 57)
p2.end()

# Convert QImage -> 24-bit BMP via Pillow
temp_banner = os.path.join(SCRIPT_DIR, '_banner_temp.png')
banner_out = os.path.join(SCRIPT_DIR, 'installer_banner.bmp')
banner.save(temp_banner, 'PNG')
img2 = Image.open(temp_banner).convert('RGB')
img2.save(banner_out, 'BMP')
os.remove(temp_banner)
print(f"Banner BMP: {os.path.getsize(banner_out)} bytes -> {banner_out}")

print("Done - 24-bit BMPs generated with DataPyn logo")
