"""
StatusBadge - A status indicator component

Used to show execution states: running, success, error, cancelled, idle.
"""

from enum import Enum
from typing import Optional
from PyQt6.QtWidgets import QLabel, QWidget, QHBoxLayout
from PyQt6.QtCore import Qt, QTimer, pyqtProperty

from src.design_system.tokens import get_colors, get_state_colors, SPACING, RADIUS, TYPOGRAPHY

try:
    import qtawesome as qta
    HAS_QTAWESOME = True
except ImportError:
    HAS_QTAWESOME = False


class BadgeState(Enum):
    """Possible states for a badge"""
    IDLE = "idle"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    CANCELLED = "cancelled"
    WARNING = "warning"
    INFO = "info"


class StatusBadge(QLabel):
    """
    A badge that shows status with optional animation.
    
    Args:
        text: Initial text to display
        state: Initial state
        animated: Whether to animate running state
        parent: Parent widget
    """
    
    def __init__(
        self,
        text: str = "",
        state: BadgeState = BadgeState.IDLE,
        animated: bool = True,
        parent: QWidget = None
    ):
        super().__init__(text, parent)
        
        self._state = state
        self._animated = animated
        self._animation_phase = 0
        
        # Animation timer
        self._animation_timer = QTimer(self)
        self._animation_timer.timeout.connect(self._animate)
        
        # Set alignment
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Apply initial style
        self._apply_style()
    
    def _apply_style(self):
        """Apply style based on current state"""
        colors = get_colors()
        state_colors = get_state_colors()
        
        state_styles = {
            BadgeState.IDLE: {
                "bg": "transparent",
                "fg": colors.text_tertiary,
                "border": "none",
            },
            BadgeState.RUNNING: {
                "bg": state_colors.running_bg,
                "fg": state_colors.running_text,
                "border": f"1px solid {state_colors.running}",
            },
            BadgeState.SUCCESS: {
                "bg": colors.success,
                "fg": colors.text_inverse,
                "border": "none",
            },
            BadgeState.ERROR: {
                "bg": colors.danger,
                "fg": colors.text_inverse,
                "border": "none",
            },
            BadgeState.CANCELLED: {
                "bg": colors.warning,
                "fg": colors.text_inverse,
                "border": "none",
            },
            BadgeState.WARNING: {
                "bg": colors.warning,
                "fg": colors.text_inverse,
                "border": "none",
            },
            BadgeState.INFO: {
                "bg": colors.info,
                "fg": colors.text_inverse,
                "border": "none",
            },
        }
        
        s = state_styles.get(self._state, state_styles[BadgeState.IDLE])
        
        self.setStyleSheet(f"""
            QLabel {{
                background-color: {s["bg"]};
                color: {s["fg"]};
                border: {s["border"]};
                border-radius: {RADIUS.radius_sm}px;
                padding: {SPACING.space_1}px {SPACING.space_2}px;
                font-size: {TYPOGRAPHY.text_xs}px;
                font-weight: {TYPOGRAPHY.font_medium};
            }}
        """)
    
    def _animate(self):
        """Animation tick for running state"""
        self._animation_phase = (self._animation_phase + 1) % 4
        
        # Pulsing dots animation
        dots = "." * self._animation_phase
        base_text = self.text().rstrip(".")
        self.setText(f"{base_text}{dots}")
    
    def set_state(self, state: BadgeState, text: str = None):
        """Set the badge state and optionally text"""
        self._state = state
        
        if text is not None:
            self.setText(text)
        
        self._apply_style()
        
        # Handle animation
        if state == BadgeState.RUNNING and self._animated:
            self._animation_timer.start(300)
        else:
            self._animation_timer.stop()
    
    def set_running(self, text: str = "Running"):
        """Convenience method to set running state"""
        self.set_state(BadgeState.RUNNING, text)
    
    def set_success(self, text: str = "Success"):
        """Convenience method to set success state"""
        self.set_state(BadgeState.SUCCESS, text)
    
    def set_error(self, text: str = "Error"):
        """Convenience method to set error state"""
        self.set_state(BadgeState.ERROR, text)
    
    def set_cancelled(self, text: str = "Cancelled"):
        """Convenience method to set cancelled state"""
        self.set_state(BadgeState.CANCELLED, text)
    
    def set_idle(self, text: str = ""):
        """Convenience method to clear/idle state"""
        self.set_state(BadgeState.IDLE, text)
    
    def clear(self):
        """Clear the badge"""
        self.set_idle("")
    
    @property
    def state(self) -> BadgeState:
        """Get current state"""
        return self._state


class ExecutionStatusBadge(StatusBadge):
    """
    Specialized badge for code execution status.
    
    Shows icons alongside text when qtawesome is available.
    """
    
    def __init__(self, parent: QWidget = None):
        super().__init__(parent=parent)
        self._show_icons = HAS_QTAWESOME
    
    def set_running(self, text: str = "Running"):
        """Show running state with spinner"""
        if self._show_icons:
            # Could add spinner animation here
            pass
        super().set_running(text)
    
    def set_success(self, text: str = None):
        """Show success state"""
        display_text = text or "Done"
        super().set_success(display_text)
    
    def set_error(self, text: str = None):
        """Show error state"""
        display_text = text or "Error"
        super().set_error(display_text)
    
    def set_rows(self, count: int):
        """Show success with row count"""
        text = f"{count:,} rows"
        super().set_success(text)


class ConnectionStatusBadge(StatusBadge):
    """Specialized badge for connection status"""
    
    def __init__(self, parent: QWidget = None):
        super().__init__(parent=parent)
    
    def set_connected(self, name: str = "Connected"):
        """Show connected state"""
        colors = get_colors()
        state_colors = get_state_colors()
        
        self.setText(name)
        self.setStyleSheet(f"""
            QLabel {{
                background-color: transparent;
                color: {state_colors.connected};
                border: none;
                padding: {SPACING.space_1}px {SPACING.space_2}px;
                font-size: {TYPOGRAPHY.text_xs}px;
                font-weight: {TYPOGRAPHY.font_semibold};
            }}
        """)
        self._state = BadgeState.SUCCESS
    
    def set_disconnected(self, text: str = "Disconnected"):
        """Show disconnected state"""
        state_colors = get_state_colors()
        
        self.setText(text)
        self.setStyleSheet(f"""
            QLabel {{
                background-color: transparent;
                color: {state_colors.disconnected};
                border: none;
                padding: {SPACING.space_1}px {SPACING.space_2}px;
                font-size: {TYPOGRAPHY.text_xs}px;
                font-weight: {TYPOGRAPHY.font_medium};
            }}
        """)
        self._state = BadgeState.ERROR
    
    def set_connecting(self, text: str = "Connecting"):
        """Show connecting state"""
        self.set_state(BadgeState.RUNNING, text)
