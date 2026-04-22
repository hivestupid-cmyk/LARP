"""
bot/engine.py — QThread managing the main capture→detect→emit loop.

Why QThread?
    QThread integrates with the Qt event loop so signals/slots work correctly
    across threads. A plain daemon threading.Thread cannot emit Qt signals
    safely without additional marshalling.

Loop design:
    1. ScreenCapture.get_frame()       → 640×640 letterboxed BGR + mapping consts
    2. Detector.detect()               → List[Detection] in screen space
    3. Emit detections_ready(list)     → OverlayWindow picks up via QueuedConnection
    4. Sleep remainder of frame budget → maintains target FPS without busy-wait

Stop mechanism:
    _stop_flag is a threading.Event; setting it causes the while loop to exit
    cleanly after the current iteration. stop_engine() also calls screen.stop()
    to release the dxcam device.
"""

import logging
import time
import threading
import os

try:
    import psutil
except ImportError:
    psutil = None

from PyQt6.QtCore import QThread, pyqtSignal

from bot.config import config
from bot.screen import ScreenCapture
from bot.detector import Detector, Detection
from bot.controller import Controller
from bot.brain import BotBrain, BotState
from typing import List

logger = logging.getLogger(__name__)


class BotEngine(QThread):
    """
    QThread that runs the capture → detect → signal loop.

    Signals
    -------
    detections_ready(list)
        Emitted after every successful inference pass. The list contains
        Detection objects in screen-space coordinates.
    """

    detections_ready: pyqtSignal = pyqtSignal(list)  # list[Detection]
    
    def __init__(self, parent=None, watchdog=None):
        super().__init__(parent)
        self.watchdog = watchdog

        self.target_fps: int = config.get("bot", "target_fps", 60)
        self._frame_budget: float = 1.0 / self.target_fps
        self._stop_flag = threading.Event()

        # Action settings
        self.auto_attack: bool = config.get("bot", "auto_attack", True)

        # Lazy-initialised inside run() — must be created on the capture thread
        self._screen: ScreenCapture | None = None
        self._detector: Detector | None = None
        
        # Phase 1620: Initialized early so Discord Bot can link immediately
        self._controller = Controller()
        self._brain = BotBrain(self._controller, self._stop_flag)
        
        # Link brain to watchdog for state signalling (DISCONNECTED state)
        if watchdog:
            watchdog.brain = self._brain

    # ------------------------------------------------------------------
    # QThread entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Called automatically by Qt when start() is invoked."""
        # Phase 138: Lower process priority to give Game more CPU
        if psutil:
            try:
                p = psutil.Process(os.getpid())
                p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
                logger.info("[Engine] Process priority set to BELOW_NORMAL for system stability.")
            except Exception as e:
                logger.warning(f"[Engine] Could not set process priority: {e}")
        
        # Phase 1509: Pre-flight check (Process + Focus)
        if self.watchdog:
            self.watchdog.ensure_roblox_ready()

        logger.info("[Engine] Started — target FPS: %d", self.target_fps)
        self._stop_flag.clear()
        _overlay_frame_counter = 0  # Only emit overlay every Nth frame
        _config_reload_counter  = 0  # Reload config every N frames for hot-reload

        # Init capture + detector on this thread (Resources)
        self._screen   = ScreenCapture()
        self._detector = Detector()
        self._screen.start()

        while not self._stop_flag.is_set():
            t0 = time.perf_counter()
            
            # Phase 2701: Instant Focus Lock (Aggressive Window Pinning)
            if config.get("window_management", {}).get("enable_auto_focus", True):
                import ctypes
                user32 = ctypes.windll.user32
                hwnd = user32.FindWindowW(None, "Roblox")
                if hwnd and user32.GetForegroundWindow() != hwnd:
                    is_ingame = (self._brain and self._brain.state == BotState.IN_GAME)
                    if is_ingame:
                        user32.ShowWindow(hwnd, 9) # Restore
                    else:
                        user32.ShowWindow(hwnd, 3) # Maximize
                    user32.keybd_event(0x12, 0, 0, 0)
                    user32.SetForegroundWindow(hwnd)
                    user32.keybd_event(0x12, 0, 2, 0)

            # 1. Hot-reload config every ~5s (225 frames @ 45fps) for live settings like target_fps
            _config_reload_counter += 1
            if _config_reload_counter >= 225:
                _config_reload_counter = 0
                config.reload()
                new_fps = config.get("bot", "target_fps", self.target_fps)
                if new_fps != self.target_fps:
                    logger.info(f"[Engine] Hot-reload: target_fps {self.target_fps} → {new_fps}")
                    self.target_fps = new_fps
                    self._frame_budget = 1.0 / self.target_fps

            # 2. Capture (Non-blocking grab from ScreenCapture's async thread)
            frame_640, frame_raw, scale, pad_x, pad_y, win_x, win_y = self._screen.get_frame()
            if frame_640 is None:
                # Still waiting for first frame from background thread
                time.sleep(0.001)
                continue

            # ── Dynamic ROI ───────────────────────────────────────────────────────
            # When Annie's last-known position is fresh (<1.5s), slice a 640×640
            # crop from the raw frame centered on her. This gives YOLO 1:1 pixels
            # (no downscale) → 88% fewer pixels to process + better accuracy.
            #
            # IMPORTANT: Only use ROI during IN_GAME. In LOADING/CUTSCENE/MENU we
            # need FULL-SCREEN so UI buttons (cutscene_skip etc.) are always visible.
            # ─────────────────────────────────────────────────────────────────────
            roi_timeout  = config.get("aim_assist", "aim_memory_duration", 1.5)
            roi_size     = 640
            macro        = self._brain.in_game_macro
            lkp          = getattr(macro, "_lkp_centroid", None)
            lkp_t        = getattr(macro, "_lkp_t",        0.0)
            in_game      = self._brain.state == BotState.IN_GAME
            
            use_roi = (
                in_game
                and not getattr(macro, "is_static_phase", False)
                and lkp is not None
                and frame_raw is not None
                and (t0 - lkp_t) < roi_timeout
            )
            
            if use_roi:
                screen_w = config.get("screen", "width",  2560)
                screen_h = config.get("screen", "height", 1440)
                half = roi_size // 2
                
                # Clamp ROI so it never goes outside the raw frame
                rx1 = max(0, min(lkp[0] - half, screen_w - roi_size))
                ry1 = max(0, min(lkp[1] - half, screen_h - roi_size))
                
                # Zero-copy numpy slice — no memory allocated
                inf_frame  = frame_raw[ry1:ry1 + roi_size, rx1:rx1 + roi_size]
                roi_offset = (rx1 + win_x, ry1 + win_y)
                inf_scale, inf_pad_x, inf_pad_y = 1.0, 0, 0
            else:
                # Full window mode (letterboxed path)
                inf_frame  = frame_640
                roi_offset = (win_x, win_y)
                inf_scale, inf_pad_x, inf_pad_y = scale, pad_x, pad_y

            # --- MASSIVE CPU/RAM/GPU OPTIMIZATION ---
            # Per user request: only run AI scanning once the macro signals "double s" (Aim Assist = True)
            # This completely turns off YOLO during the ~15s static macro execution!
            is_static_phase   = getattr(macro, "is_static_phase", False)
            aim_assist_active = getattr(macro, "_aim_assist_active", False)
            
            if in_game and is_static_phase and not aim_assist_active:
                detections, distances = [], (-1.0, -1.0)
            else:
                # 3. Detect (returns screen-space Detection objects + distances)
                detections, distances = self._detector.detect(
                    inf_frame, inf_scale, inf_pad_x, inf_pad_y,
                    full_frame=frame_raw, roi_offset=roi_offset,
                )

            # 4. Action Logic (Passed to the Tactical Brain)
            self._brain.process_tick(detections, distances, frame=frame_raw)

            # 5. Emit to overlay every 2nd frame (halves Qt signal marshalling cost)
            _overlay_frame_counter += 1
            if _overlay_frame_counter % 2 == 0:
                self.detections_ready.emit(detections)

            # 6. FPS pacing — Hybrid Spin-Wait for microsecond precision
            lkp_label = getattr(macro, "_lkp_label", "") if in_game else ""
            target_fps_annie = config.get("bot", "target_fps_annie_mark", 0)
            
            if in_game and lkp_label == "annie_mark" and target_fps_annie > 0:
                active_frame_budget = 1.0 / target_fps_annie
            else:
                active_frame_budget = self._frame_budget

            target_time = t0 + active_frame_budget
            while time.perf_counter() < target_time:
                remaining = target_time - time.perf_counter()
                if remaining > 0.001:
                    time.sleep(0.001)
                else:
                    break


        # Cleanup
        if self._screen:
            self._screen.stop()
        if self._brain and hasattr(self._brain, 'in_game_macro'):
            self._brain.in_game_macro.stop()
        logger.info("[Engine] Stopped.")

    # ------------------------------------------------------------------
    # Control methods — safe to call from the main thread
    # ------------------------------------------------------------------

    def stop_engine(self) -> None:
        """Signal the loop to exit and wait for the thread to finish."""
        logger.info("[Engine] Stop requested.")
        self._stop_flag.set()
        # Wait up to 2 seconds for clean exit, otherwise force continue
        if not self.wait(2000):
            logger.warning("[Engine] Thread failed to stop within 2s. Forcing exit.")
        logger.info("[Engine] Thread joined.")

    def toggle(self) -> None:
        """Start or stop the engine depending on current state."""
        if self.isRunning():
            self.stop_engine()
        else:
            self.start()
