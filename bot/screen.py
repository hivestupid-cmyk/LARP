"""
bot/screen.py — Zero-latency screen capture with manual letterboxing.

Why manual letterboxing?
    If we let YOLO resize the raw 2560x1440 frame internally, the exact padding
    offsets are hidden inside the model pipeline and we cannot unmap bounding boxes
    back to screen coordinates accurately.

    By doing it ourselves we know EXACTLY:
        scale  = 640 / max(screen_w, screen_h)
        pad_x  = (640 - scaled_w) // 2
        pad_y  = (640 - scaled_h) // 2

    These are then returned alongside every frame so detector.py can do the
    inverse transform correctly.

Letterbox math for 2560x1440 → 640x640:
    scale    = 640 / 2560          = 0.25
    scaled_w = round(2560 * 0.25) = 640
    scaled_h = round(1440 * 0.25) = 360
    pad_x    = (640 - 640) / 2    = 0
    pad_y    = (640 - 360) / 2    = 140   ← 140 px black top + bottom
"""

import logging
import numpy as np
import cv2
import dxcam
import threading
import time

from bot.config import config

logger = logging.getLogger(__name__)


class ScreenCapture:
    """
    Captures the full 2560×1440 display via dxcam (DXGI — zero GPU readback latency)
    and returns a 640×640 letterboxed BGR frame alongside the mapping constants
    needed to unproject detections back into screen space.
    """

    TARGET_SIZE: int = 640

    def __init__(self):
        self.screen_w: int = config.get("screen", "width", 2560)
        self.screen_h: int = config.get("screen", "height", 1440)
        self.target_fps: int = config.get("bot", "target_fps", 60)
        self.brightness_boost: float = config.get("screen", "brightness_multiplier", 1.0) # Phase 111

        # Pre-compute letterbox constants (immutable for this screen resolution)
        self.scale: float = self.TARGET_SIZE / max(self.screen_w, self.screen_h)
        self.scaled_w: int = round(self.screen_w * self.scale)
        self.scaled_h: int = round(self.screen_h * self.scale)
        self.pad_x: int = (self.TARGET_SIZE - self.scaled_w) // 2
        self.pad_y: int = (self.TARGET_SIZE - self.scaled_h) // 2

        # Pre-allocate TWO canvases for double-buffering (avoids processed.copy() each frame)
        # While one canvas is being read by the engine, the capture loop writes into the other.
        self._canvas_a = np.zeros((self.TARGET_SIZE, self.TARGET_SIZE, 3), dtype=np.uint8)
        self._canvas_b = np.zeros((self.TARGET_SIZE, self.TARGET_SIZE, 3), dtype=np.uint8)
        self._active_canvas = self._canvas_a  # canvas currently exposed to engine
        self._write_canvas  = self._canvas_b  # canvas being written to by capture loop

        self._cam = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._latest_data: tuple[np.ndarray | None, np.ndarray | None, float, int, int, int, int] = (None, None, self.scale, self.pad_x, self.pad_y, 0, 0)
        
        # Phase 111/118: Darkness persistence tracking
        self._dark_start: float = 0.0
        self._last_dark_log: float = 0.0

        logger.info(
            f"ScreenCapture init | {self.screen_w}x{self.screen_h} → "
            f"640x640 | scale={self.scale:.4f} "
            f"pad_x={self.pad_x} pad_y={self.pad_y}"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """
        Create and start the dxcam instance.
        Must be called from the thread that will call get_frame().
        """
        if self._cam is not None:
            return  # Already running

        try:
            # Phase 109: Fix dxcam method call (get_available_devices -> device_info)
            import dxcam
            try:
                devices = dxcam.device_info()
                logger.info(f"[Screen] DXCAM available devices: {devices}")
            except:
                logger.info("[Screen] DXCAM device_info not available/failed. Using default.")

            target_monitor = config.get("screen", "monitor_index", 0)
            self._cam = dxcam.create(device_idx=target_monitor, output_color="BGR")
            self._cam.start(target_fps=self.target_fps, video_mode=True)
            
            self._running = True
            self._thread = threading.Thread(target=self._capture_loop, daemon=True)
            self._thread.start()
            
            logger.info(f"dxcam started on Monitor {target_monitor} at target {self.target_fps} FPS [Async Mode]")
        except Exception as exc:
            logger.error(f"Failed to start dxcam: {exc}")
            self._cam = None

    def get_frame(self) -> tuple[np.ndarray | None, np.ndarray | None, float, int, int, int, int]:
        """
        Thread-safe grab of the latest processed frame from the background thread.
        Non-blocking.
        Returns: (processed_640, raw_frame, scale, pad_x, pad_y, win_x, win_y)
        """
        with self._lock:
            return self._latest_data

    def _capture_loop(self) -> None:
        """Background thread loop: capture -> crop to window -> resize -> slice into canvas."""
        import ctypes
        import cv2
        import numpy as np
        
        class RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        
        while self._running and self._cam:
            try:
                raw = self._cam.get_latest_frame()
                if raw is not None:
                    # Phase 2708: Dynamically slice to actual active Roblox Window frame
                    hwnd = ctypes.windll.user32.FindWindowW(None, "Roblox")
                    win_x, win_y = 0, 0
                    if hwnd:
                        try:
                            rect = RECT()
                            ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(rect))
                            
                            pt_lt = POINT(rect.left, rect.top)
                            pt_rb = POINT(rect.right, rect.bottom)
                            
                            ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(pt_lt))
                            ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(pt_rb))
                            
                            raw_h, raw_w = raw.shape[:2]
                            l_px = max(0, min(pt_lt.x, raw_w))
                            r_px = max(0, min(pt_rb.x, raw_w))
                            t_px = max(0, min(pt_lt.y, raw_h))
                            b_px = max(0, min(pt_rb.y, raw_h))
                            if r_px > l_px and b_px > t_px:
                                raw = raw[t_px:b_px, l_px:r_px]
                                win_x, win_y = l_px, t_px
                        except Exception:
                            pass

                    # Dynamically calculate letterbox mapping for the current window size
                    raw_h, raw_w = raw.shape[:2]
                    scale = self.TARGET_SIZE / max(raw_w, raw_h)
                    scaled_w = round(raw_w * scale)
                    scaled_h = round(raw_h * scale)
                    pad_x = (self.TARGET_SIZE - scaled_w) // 2
                    pad_y = (self.TARGET_SIZE - scaled_h) // 2
                    
                    processed = cv2.resize(raw, (scaled_w, scaled_h), interpolation=cv2.INTER_AREA)

                    # Swap canvases (zero-copy double-buffer)
                    self._write_canvas.fill(0)
                    self._write_canvas[pad_y : pad_y + scaled_h, pad_x : pad_x + scaled_w] = processed
                    with self._lock:
                        # Swap: expose the freshly-written canvas, recycle the old one
                        self._active_canvas, self._write_canvas = self._write_canvas, self._active_canvas
                        self._latest_data = (self._active_canvas, raw, scale, pad_x, pad_y, win_x, win_y)
                
                # Tiny sleep to yield thread and stay near target FPS
                # budget 1/60 = 16ms, we don't need to spin-wait here as dxcam
                # handles its own internal timing.
                time.sleep(0.001)
            except Exception as exc:
                logger.error(f"Async Capture Error: {exc}")
                time.sleep(0.1)

    def stop(self) -> None:
        """Stop dxcam and background thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

        if self._cam is not None:
            try:
                self._cam.stop()
                self._cam.release()
            except Exception as exc:
                logger.warning(f"dxcam stop error: {exc}")
            finally:
                self._cam = None
            logger.info("dxcam stopped.")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _letterbox(self, img: np.ndarray) -> np.ndarray:
        """
        Resize img to (scaled_w, scaled_h). Canvas writing is done in the
        capture loop via double-buffer — this method just returns the resized slice.
        """
        # INTER_AREA: Correct algorithm for downscaling.
        # INTER_NEAREST is fast but destroys thin UI text/edges via aliasing,
        # causing small buttons (retry, start, modifiers) to vanish at 640px.
        return cv2.resize(
            img,
            (self.scaled_w, self.scaled_h),
            interpolation=cv2.INTER_AREA,
        )
