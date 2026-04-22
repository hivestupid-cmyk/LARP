import threading
import time
import math
import random
import logging
import ctypes
import pydirectinput
from bot.config import config

logger = logging.getLogger(__name__)

# Win32 Constants
MOUSEEVENTF_MOVE = 0x0001

class Controller:
    """
    Handles hardware-level mouse and keyboard simulation.
    Uses Win32 API for high-performance low-latency mouse movement.
    UI Clicks are executed in a background thread to prevent blocking the Brain/Overlay.
    """
    def __init__(self):
        pydirectinput.FAILSAFE = False
        pydirectinput.PAUSE = 0
        self.is_busy = False # True if a background click/move is in progress

        # Screen dimensions
        self.screen_width = config.get("screen", "width", 2560)
        self.screen_height = config.get("screen", "height", 1440)
        
        # Shift Lock Calibration (2K Screen)
        # Center X is 1280, but Shift Lock Crosshair is at Y:711
        self.center_x = 1280
        self.center_y = 711

        # Speed multiplier (Phase 118)
        self.bot_speed = config.get("bot", "bot_speed", 1.0)
        
        # Sensitivity multiplier
        self.sensitivity = config.get("bot", "sensitivity", 0.8) * self.bot_speed

        # Hook hold state tracking
        self._hook_left_held = False
        self._hook_right_held = False

        logger.info("[Controller] Initialized (Win32 API) at %dx%d", self.screen_width, self.screen_height)

    # ── Mouse ────────────────────────────────────────────────────────────

    def move_mouse_relative(self, dx: int, dy: int, humanize: bool = True):
        """Moves mouse relative using Win32 API for sub-millisecond latency.
        Adds subtle Gaussian noise to mimic human micro-tremors (anti-cheat bypass).
        """
        if dx == 0 and dy == 0:
            return
        
        # Ensure we move at least 1 unit if delta is non-zero (fix for slow micro-aiming)
        def scale_and_clamp(val):
            scaled = val * self.sensitivity
            if val > 0: return max(1, int(scaled))
            if val < 0: return min(-1, int(scaled))
            return 0

        final_dx = scale_and_clamp(dx)
        final_dy = scale_and_clamp(dy)
        
        if humanize and (abs(final_dx) > 5 or abs(final_dy) > 5):
            # Add a small noise ±1px to mimic hand tremor
            final_dx += int(random.gauss(0, 0.5))
            final_dy += int(random.gauss(0, 0.5))
        
        ctypes.windll.user32.mouse_event(
            MOUSEEVENTF_MOVE,
            final_dx,
            final_dy,
            0, 0
        )

    def aim_at(self, target_x: int, target_y: int, smooth: bool = True):
        """Dynamic Smoothing: Factor increases as target gets closer (more responsive at close range).
        Max delta capped per-frame so Roblox always registers the input.
        """
        dx = target_x - self.center_x
        dy = target_y - self.center_y
        
        if smooth:
            dist = math.hypot(dx, dy)
            # Dynamic factor: 0.20 (far) → 0.45 (close) for high-speed AI response
            if dist > 300:
                factor = 0.20
            elif dist < 100:
                factor = 0.45
            else:
                # Linearly interpolate between 0.10 and 0.25 based on distance
                t = (300 - dist) / 200  # 0 at 300px, 1 at 100px
                factor = 0.10 + t * 0.15
            
            move_x = int(dx * factor)
            move_y = int(dy * factor)

            # Cap movement per frame for smoothness
            max_delta_px = 120
            move_x = max(-max_delta_px, min(max_delta_px, move_x))
            move_y = max(-max_delta_px, min(max_delta_px, move_y))
            self.move_mouse_relative(move_x, move_y)
        else:
            # Snap instantly (still relative but with high cap)
            self.snap_aim_at(target_x, target_y)

    def snap_aim_at(self, target_x: int, target_y: int):
        """Instant snap movement for combat firing. No smoothing, high speed cap."""
        dx = int((target_x - self.center_x) * 1.0) # Full distance
        dy = int((target_y - self.center_y) * 1.0)
        
        # High cap for snap (allows nearly instant 90-degree turns)
        max_snap = 1200 
        move_x = max(-max_snap, min(max_snap, dx))
        move_y = max(-max_snap, min(max_snap, dy))
        
        self.move_mouse_relative(move_x, move_y, humanize=False)

    def click_at(self, x: int, y: int):
        """Non-blocking absolute move + click (UI). Starts a background thread."""
        if self.is_busy:
            return
        threading.Thread(target=self._click_at_threaded, args=(x, y), daemon=True).start()

    def move_to(self, x: int, y: int):
        """Non-blocking absolute move (UI). Starts a background thread."""
        if self.is_busy:
            return
        threading.Thread(target=self._move_to_threaded_internal, args=(x, y), daemon=True).start()

    def _smooth_move_to(self, x: int, y: int, duration: float = 0.5, steps: int = 30):
        """
        Custom smooth move via ctypes (Win32 mouse_event relative moves).
        pydirectinput's moveTo(duration=...) is IGNORED by the base library,
        so we implement our own incremental move here.
        """
        import ctypes
        # Get current mouse position
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        
        pt = POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        start_x, start_y = pt.x, pt.y

        step_delay = duration / steps
        for i in range(1, steps + 1):
            t = i / steps
            # Ease-in-out curve for natural feel
            t_smooth = t * t * (3 - 2 * t)
            cur_x = int(start_x + (x - start_x) * t_smooth)
            cur_y = int(start_y + (y - start_y) * t_smooth)
            pydirectinput.moveTo(cur_x, cur_y)
            # Phase 113: Fallback 1: SetCursorPos
            ctypes.windll.user32.SetCursorPos(cur_x, cur_y)
            # Phase 113: Fallback 2: MOUSEEVENTF_ABSOLUTE (Normalized 0-65535)
            nx = int(cur_x * 65535 / self.screen_width)
            ny = int(cur_y * 65535 / self.screen_height)
            ctypes.windll.user32.mouse_event(0x8001, nx, ny, 0, 0) # ABSOLUTE | MOVE
            time.sleep(step_delay)

    def _click_at_threaded(self, x: int, y: int):
        self.is_busy = True
        try:
            # Step 0: Calculate distance-based duration for reliable travel
            class POINT(ctypes.Structure):
                _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
            pt = POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
            dist = math.hypot(x - pt.x, y - pt.y)
            
            # Base 0.1s + 0.1s per 500 pixels (Max ~0.6s for 2K screen)
            move_duration = (0.1 + (dist / 500) * 0.1) / self.bot_speed
            settle_sleep = 0.1 / self.bot_speed

            # Step 1: Smooth gradual move
            logger.info(f"[Controller] UI Click target: {x}, {y} (Dist: {int(dist)}px, Dur: {move_duration:.2f}s)")
            self._smooth_move_to(x, y, duration=move_duration, steps=20)
            
            # Step 2: Instant "Confirmation" snap
            pydirectinput.moveTo(int(x), int(y)) 
            ctypes.windll.user32.SetCursorPos(int(x), int(y))
            
            # Step 3: Wait for game engine and cursor to settle
            time.sleep(settle_sleep) 
            
            # Step 4: Perform the actual click
            self._click_internal("LMB")
        finally:
            self.is_busy = False

    def _move_to_threaded_internal(self, x: int, y: int):
        self.is_busy = True
        try:
            move_duration = 0.05 / self.bot_speed
            settle_sleep = 0.05 / self.bot_speed
            self._smooth_move_to(x, y, duration=move_duration, steps=15)
            pydirectinput.moveTo(int(x), int(y)) 
            time.sleep(settle_sleep) 
        finally:
            self.is_busy = False

    def click(self, button: str = "LMB"):
        """Non-blocking single click (Combat/UI). Starts a background thread."""
        if self.is_busy: return
        threading.Thread(target=self._click_threaded, args=(button,), daemon=True).start()

    def _click_threaded(self, button: str):
        self.is_busy = True
        try:
            self._click_internal(button)
        finally:
            self.is_busy = False

    def _click_internal(self, button: str):
        """The actual blocking click logic, called only from background threads."""
        btn = 'left' if button == "LMB" else 'right'
        # Add a tiny human-like random jit before clicking (10-30ms)
        time.sleep(random.uniform(0.01, 0.03))
        pydirectinput.mouseDown(button=btn)
        time.sleep(0.02) # V4.28: Super Fast Hold
        pydirectinput.mouseUp(button=btn)

    # ── ODM Hooks (Sustained Hold) ───────────────────────────────────────

    def hold_hook_left(self):
        """Hold Q — sustained pull towards anchor on the left."""
        if not self._hook_left_held:
            pydirectinput.keyDown('q')
            self._hook_left_held = True
            logger.debug("[Controller] Hook LEFT held.")

    def release_hook_left(self):
        """Release Q."""
        if self._hook_left_held:
            pydirectinput.keyUp('q')
            self._hook_left_held = False
            logger.debug("[Controller] Hook LEFT released.")

    def hold_hook_right(self):
        """Hold E — sustained pull towards anchor on the right."""
        if not self._hook_right_held:
            pydirectinput.keyDown('e')
            self._hook_right_held = True
            logger.debug("[Controller] Hook RIGHT held.")

    def release_hook_right(self):
        """Release E."""
        if self._hook_right_held:
            pydirectinput.keyUp('e')
            self._hook_right_held = False
            logger.debug("[Controller] Hook RIGHT released.")

    def hold_dual_hooks(self):
        """Hold both Q and E simultaneously for maximum pull."""
        self.hold_hook_left()
        self.hold_hook_right()

    def release_all_hooks(self):
        """Release both hooks."""
        self.release_hook_left()
        self.release_hook_right()

    # ── Combat Actions ───────────────────────────────────────────────────

    def fire_thunder_spear(self):
        """Fire Thunder Spear (LMB) as an explicit tap to prevent 'holding' errors."""
        pydirectinput.mouseDown(button='left')
        time.sleep(0.03)  # 30ms hold to ensure game reads it as a true click
        pydirectinput.mouseUp(button='left')

    def dash(self):
        """Dash Forward = double-tap space. 15ms gap so Roblox reads both presses."""
        pydirectinput.press('space')
        time.sleep(0.015)
        pydirectinput.press('space')

    def dash_backward(self):
        """Dash Backward = double-tap S."""
        pydirectinput.press('s')
        time.sleep(0.015)
        pydirectinput.press('s')

    def dash_left(self):
        """Dash Left = double-tap A."""
        pydirectinput.press('a')
        time.sleep(0.015)
        pydirectinput.press('a')

    def dash_right(self):
        """Dash Right = double-tap D."""
        pydirectinput.press('d')
        time.sleep(0.015)
        pydirectinput.press('d')

    # ── Boost (Space Hold) ───────────────────────────────────────────────

    def boost(self):
        pydirectinput.press('space')

    def hold_boost(self):
        pydirectinput.keyDown('space')

    def release_boost(self):
        pydirectinput.keyUp('space')

    def scroll_at(self, x: int, y: int, amount: int):
        """Non-blocking absolute move + scroll. Starts a background thread."""
        if self.is_busy: return
        threading.Thread(target=self._scroll_at_threaded, args=(x, y, amount), daemon=True).start()

    def _scroll_at_threaded(self, x: int, y: int, amount: int):
        self.is_busy = True
        try:
            # Re-use the move duration/settle logic from move_to
            move_duration = 0.2 / self.bot_speed
            self._smooth_move_to(x, y, duration=move_duration, steps=15)
            pydirectinput.moveTo(int(x), int(y))
            time.sleep(0.1)
            self.scroll(amount)
        finally:
            self.is_busy = False

    def scroll(self, amount: int):
        """Scrolls the mouse wheel. Positive = Up, Negative = Down.
        Standard scroll tick is ±120 per notch.
        """
        logger.debug("[Controller] Scrolling mouse wheel: %d", amount)
        # MOUSEEVENTF_WHEEL = 0x0800
        ctypes.windll.user32.mouse_event(0x0800, 0, 0, int(amount), 0)

    def zoom_out(self):
        """Scrolls down using Win32 API to zoom out the camera (DirectInput compatible)."""
        logger.info("[Controller] Zooming out camera.")
        self.scroll(-1000)

    def enable_shiftlock(self):
        """Taps Left Ctrl to enable shiftlock."""
        logger.info("[Controller] Enabling Shiftlock (Ctrl).")
        pydirectinput.press('ctrl')

    # ── Generic Key Helpers ──────────────────────────────────────────────

    def hold_key(self, key_name: str):
        pydirectinput.keyDown(key_name.lower())

    def release_key(self, key_name: str):
        pydirectinput.keyUp(key_name.lower())
