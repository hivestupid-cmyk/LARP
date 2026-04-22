"""
bot/overlay.py — PyQt6 transparent click-through overlay using QMainWindow.

Extreme DWM Optimisations applied to reduce GPU usage:
1. No Global Timer: We removed the 60 Hz QTimer. The screen only repaints
   when new detections arrive from the engine thread.
2. Dirty Rectangles: Instead of wiping the entire 2560x1440 screen every frame,
   we only `update(rect)` the exact bounding boxes of the old and new detections.
3. HW Accel Attributes: WA_PaintOnScreen completely bypasses backing stores.
4. No Static Crosshair: Drawing a crosshair forces the centre of the screen
   to repaint every frame, which hurts DWM performance. Removed.
"""

import logging
import math
from typing import List

from PyQt6.QtCore import Qt, QTimer, QRect, pyqtSignal, QObject
from PyQt6.QtGui import QPainter, QPen, QColor, QFont
from PyQt6.QtWidgets import QMainWindow, QWidget

from bot.config import config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Signals proxy — lets the engine thread safely update the main-thread widget
# ---------------------------------------------------------------------------

class _Signals(QObject):
    detections_ready = pyqtSignal(list)   # list[Detection]
    detections_cleared = pyqtSignal()


# ---------------------------------------------------------------------------
# Dirty Rect tracking — only repaint changing areas, not 2560x1440
# ---------------------------------------------------------------------------
def _get_det_rect(det) -> QRect:
    # Includes space for the text label above the box
    return QRect(
        det.x_screen - det.w_screen // 2 - 2,
        det.y_screen - det.h_screen // 2 - 20, # Extra top padding for text
        det.w_screen + 4,
        det.h_screen + 24
    )

# ---------------------------------------------------------------------------
# Canvas widget (all painting happens here)
# ---------------------------------------------------------------------------

class _OverlayCanvas(QWidget):
    """Transparent drawing surface mounted as the QMainWindow central widget."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._detections: List = []
        self._last_rects: List[QRect] = []
        self._active: bool = False

    # Called from main thread via signal
    def set_detections(self, detections: list) -> None:
        # Repaint old areas + Center Crosshair area
        for r in self._last_rects:
            self.update(r)
        
        # Always update center crosshair area + trajectory region
        cx, cy = self.width() // 2, self.height() // 2
        from bot.config import config
        if config.get("aim_assist", "show_fov_circle", True):
            fov = config.get("aim_assist", "fov_radius", 150)
            self.update(QRect(cx - fov - 5, cy - fov - 5, fov * 2 + 10, fov * 2 + 10))
        else:
            self.update(QRect(cx - 20, cy - 20, 40, 40))

        # Invalidate full trajectory bounding box (center→target) for any Annie det
        for d in (self._detections + detections):
            if "Annie" in getattr(d, "label", ""):
                tx, ty = getattr(d, "x_screen", cx), getattr(d, "y_screen", cy)
                self.update(QRect(
                    min(cx, tx) - 5, min(cy, ty) - 15,
                    abs(cx - tx) + 50, abs(cy - ty) + 30
                ))

        self._detections = detections
        self._last_rects = [_get_det_rect(d) for d in detections]
        self._active = bool(detections)

        # Repaint new areas
        for r in self._last_rects:
            self.update(r)

    def clear(self) -> None:
        for r in self._last_rects:
            self.update(r)
        
        # Always update center crosshair area
        cx, cy = self.width() // 2, self.height() // 2
        from bot.config import config
        if config.get("aim_assist", "show_fov_circle", True):
            fov = config.get("aim_assist", "fov_radius", 150)
            self.update(QRect(cx - fov - 5, cy - fov - 5, fov * 2 + 10, fov * 2 + 10))
        else:
            self.update(QRect(cx - 20, cy - 20, 40, 40))

        self._detections = []
        self._last_rects = []
        self._active = False

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)

        # Clear ONLY the regions that need repainting (from update events)
        painter.fillRect(event.region().boundingRect(), QColor(0, 0, 0, 0))

        # Disable anti-aliasing — measurable CPU/GPU saving
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        # ── Layer 1: Detection Boxes + Labels ─────────────────────────────
        # Gated by "Show Visual Overlay" setting
        if self._active and self._detections and config.get("bot", "show_overlay", True):
            font = QFont("Arial", 10, QFont.Weight.Bold)
            painter.setFont(font)

            for det in self._detections:
                # Colour by class type
                if "Titan" in det.label:
                    colour = QColor(255, 60, 60)   # Red
                elif "Annie" in det.label:
                    colour = QColor(60, 240, 255)  # Cyan
                elif any(k in det.label for k in ("Button", "Modifier", "Difficulty")):
                    colour = QColor(255, 240, 50)  # Yellow
                else:
                    colour = QColor(50, 255, 100)  # Green

                painter.setPen(QPen(colour, 2))

                # Bounding box (screen-space coords from detector)
                left = det.x_screen - det.w_screen // 2
                top  = det.y_screen - det.h_screen // 2
                rect = QRect(left, top, det.w_screen, det.h_screen)
                painter.drawRect(rect)

                # Label with matching background color (semi-transparent)
                text = f"{det.label}  {det.confidence:.2f}"
                fm   = painter.fontMetrics()
                tw   = fm.horizontalAdvance(text)
                th   = fm.height()
                bg   = QRect(left, top - th - 4, tw + 8, th + 4)

                bg_color = QColor(colour)
                bg_color.setAlpha(170)

                painter.fillRect(bg, bg_color)
                painter.setPen(QPen(QColor(0, 0, 0) if bg_color.lightness() > 128 else QColor(255, 255, 255)))
                painter.drawText(left + 4, top - 5, text)

        # ── Layer 2: IPM Trajectory Lines ────────────────────────────────
        # INDEPENDENT of show_overlay — gated only by show_ipm_line
        if self._active and self._detections and config.get("aim_assist", "show_ipm_line", True):
            tcx, tcy = self.width() // 2, self.height() // 2
            for det in self._detections:
                if "Annie" in det.label:
                    # Dashed red line from FOV center to target centroid
                    pen_traj = QPen(QColor(255, 50, 50, 200), 2)
                    pen_traj.setStyle(Qt.PenStyle.DashLine)
                    painter.setPen(pen_traj)
                    painter.drawLine(tcx, tcy, det.x_screen, det.y_screen)

                    # Pixel distance label at midpoint
                    screen_dist = int(math.hypot(tcx - det.x_screen, tcy - det.y_screen))
                    mid_x = (tcx + det.x_screen) // 2
                    mid_y = (tcy + det.y_screen) // 2

                    painter.fillRect(QRect(mid_x - 22, mid_y - 10, 44, 20), QColor(0, 0, 0, 160))
                    painter.setPen(QPen(QColor(255, 220, 0)))
                    painter.setFont(QFont("Arial", 8, QFont.Weight.Bold))
                    painter.drawText(mid_x - 18, mid_y + 4, f"{screen_dist}px")

        cx, cy = self.width() // 2, self.height() // 2

        # ── Layer 3: FOV Circle ────────────────────────────────────────────
        # INDEPENDENT of show_overlay — gated only by show_fov_circle
        if config.get("aim_assist", "show_fov_circle", True):
            fov_radius = config.get("aim_assist", "fov_radius", 150)

            pen = QPen(QColor(255, 0, 0, 100), 2)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)

            painter.drawEllipse(cx - fov_radius, cy - fov_radius, fov_radius * 2, fov_radius * 2)

        painter.end()


# ---------------------------------------------------------------------------
# Main overlay window
# ---------------------------------------------------------------------------

class OverlayWindow(QMainWindow):
    """
    Full-screen transparent, click-through overlay window.

    Call update_detections() from any thread — it is thread-safe via signals.
    """

    def __init__(self):
        super().__init__()

        screen_w: int = config.get("screen", "width",  2560)
        screen_h: int = config.get("screen", "height", 1440)
        fps: int      = config.get("bot",    "target_fps", 60)

        # ── Window flags ────────────────────────────────────────────────────
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint       |
            Qt.WindowType.FramelessWindowHint         |
            Qt.WindowType.Tool                        |
            Qt.WindowType.WindowTransparentForInput   |
            Qt.WindowType.BypassWindowManagerHint     # Bypass DWM — eliminates compositing lag
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_PaintOnScreen)  # HW acceleration

        self.setGeometry(0, 0, screen_w, screen_h)

        # ── Central canvas ──────────────────────────────────────────────────
        self._canvas = _OverlayCanvas()
        self._canvas.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setCentralWidget(self._canvas)

        # ── Signal bridge (thread-safe updates from engine QThread) ─────────
        self._signals = _Signals()
        self._signals.detections_ready.connect(
            self._canvas.set_detections, Qt.ConnectionType.QueuedConnection
        )
        self._signals.detections_cleared.connect(
            self._canvas.clear, Qt.ConnectionType.QueuedConnection
        )

        logger.info("Overlay aktif.")

    # ------------------------------------------------------------------
    # Public API — safe to call from any thread
    # ------------------------------------------------------------------

    def update_detections(self, detections: list) -> None:
        """Post new detections to the canvas (thread-safe)."""
        self._signals.detections_ready.emit(detections)

    def clear_detections(self) -> None:
        """Clear detections from the canvas (thread-safe)."""
        self._signals.detections_cleared.emit()
