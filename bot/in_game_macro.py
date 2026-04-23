import time
import threading
import logging
import math
import os
import ctypes
import json
from typing import List, TYPE_CHECKING
if TYPE_CHECKING:
    from bot.detector import Detection

import pydirectinput
import keyboard
import numpy as np

# Phase 2517: High-Performance Pydirectinput Config
# Setting PAUSE to 0.0 is critical for AOTR to avoid 100ms delays between 
# every key press (Q, E, Space), which previously caused desync.
pydirectinput.PAUSE = 0.0
pydirectinput.FAILSAFE = False

logger = logging.getLogger(__name__)

# Kalman filter tracker for 2D constant-velocity motion.
# State: [x, y, vx, vy], Measurement: z=[x, y]
class KalmanTracker:
    def __init__(self, x0: float, y0: float, process_var: float = 5.0):
        from bot.config import config
        measurement_var = float(config.get("aim_assist", "measurement_var", 15.0))
        
        self.x = np.array([[float(x0)], [float(y0)], [0.0], [0.0]], dtype=float) 
        self.P = np.diag([measurement_var, measurement_var, 500.0, 500.0]).astype(float) 
        self.H = np.array([[1.0, 0.0, 0.0, 0.0],
                           [0.0, 1.0, 0.0, 0.0]], dtype=float) 
        self.R = np.eye(2, dtype=float) * float(measurement_var) 
        self.F = np.eye(4, dtype=float) 
        self._process_var = float(process_var)
        self._I = np.eye(4, dtype=float)
        self.max_velocity = 2500.0 
        
        # MAIN FIX: Dampening factor (0.90 - 0.98). 
        self.dampening = 0.95 

    def _compute_Q(self, dt: float) -> np.ndarray:
        # Clamp dt for process noise calculation. If allowed to spike during FPS drops,
        # dt^4 exponent will explode and make Kalman overconfident in chaotic predictions.
        dt_q = max(0.016, min(float(dt), 0.033))
        dt2 = dt_q * dt_q
        dt3 = dt2 * dt_q
        dt4 = dt3 * dt_q
        q = self._process_var

        return q * np.array([
            [dt4 / 4.0, 0.0, dt3 / 2.0, 0.0],
            [0.0, dt4 / 4.0, 0.0, dt3 / 2.0],
            [dt3 / 2.0, 0.0, dt2, 0.0],
            [0.0, dt3 / 2.0, 0.0, dt2],
        ], dtype=float)

    def predict(self, dt_override: float = None):
        if dt_override is not None:
            self.F[0, 2] = dt_override
            self.F[1, 3] = dt_override
            
        x_pred = self.F @ self.x
        
        # Pseudo-dampening (does not change internal state)
        vx_pred = max(-self.max_velocity, min(self.max_velocity, float(x_pred[2, 0]) * self.dampening))
        vy_pred = max(-self.max_velocity, min(self.max_velocity, float(x_pred[3, 0]) * self.dampening))
        
        return float(x_pred[0, 0]), float(x_pred[1, 0]), vx_pred, vy_pred

    def predict_and_advance(self, dt: float):
        dt = max(float(dt), 1e-4)
        self.F[0, 2] = dt
        self.F[1, 3] = dt
        
        self.x = self.F @ self.x
        time_scaled_dampening = self.dampening ** (dt / 0.016) if self.dampening < 1.0 else 1.0
        self.x[2, 0] = max(-self.max_velocity, min(self.max_velocity, self.x[2, 0] * time_scaled_dampening))
        self.x[3, 0] = max(-self.max_velocity, min(self.max_velocity, self.x[3, 0] * time_scaled_dampening))
        
        Q = self._compute_Q(dt)
        self.P = self.F @ self.P @ self.F.T + Q
        
        return float(self.x[0, 0]), float(self.x[1, 0]), float(self.x[2, 0]), float(self.x[3, 0])

    def update(self, z, dt: float) -> None:
        z = np.array(z, dtype=float).reshape(2, 1)
        dt = max(float(dt), 1e-4)

        self.F[0, 2] = dt
        self.F[1, 3] = dt
        Q = self._compute_Q(dt)

        x_pred = self.F @ self.x
        time_scaled_dampening = self.dampening ** (dt / 0.016) if self.dampening < 1.0 else 1.0
        x_pred[2, 0] *= time_scaled_dampening
        x_pred[3, 0] *= time_scaled_dampening
        P_pred = self.F @ self.P @ self.F.T + Q

        y = z - (self.H @ x_pred) 
        S = (self.H @ P_pred @ self.H.T) + self.R 
        
        try:
            # Pseudo-inverse to be more resilient against Singular Matrix Error
            K = P_pred @ self.H.T @ np.linalg.pinv(S) 
        except np.linalg.LinAlgError:
            K = np.zeros((4, 2))

        self.x = x_pred + (K @ y)
        self.P = (self._I - (K @ self.H)) @ P_pred

# Windows Mouse Constants
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800

# SendInput structures
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long),
                ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.c_size_t)] # Use c_size_t for ULONG_PTR

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort),
                ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.c_size_t)]

class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", ctypes.c_ulong),
                ("wParamL", ctypes.c_short),
                ("wParamH", ctypes.c_ushort)]

class INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT),
                ("ki", KEYBDINPUT),
                ("hi", HARDWAREINPUT)]

class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong),
                ("iu", INPUT_UNION)]

# ── Win32 Input Helpers ───────────────────────────────────────────────────────

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

def get_mouse_pos():
    pt = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y

def send_mouse_input(flags, dx=0, dy=0, data=0):
    """Send a Win32 mouse event via SendInput. Logs on failure."""
    ii_ = INPUT_UNION()
    ii_.mi = MOUSEINPUT(dx, dy, data, flags, 0, 0)
    command = INPUT(0, ii_)  # 0 = INPUT_MOUSE
    res = ctypes.windll.user32.SendInput(1, ctypes.pointer(command), ctypes.sizeof(command))
    if res == 0:
        logger.error(f"[Macro] SendInput Failed: {ctypes.GetLastError()}")

class InGameMacro:
    def __init__(self, controller=None):
        self.controller = controller
        self._thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.Lock()
        
        # Static Macro State
        self._commands = [] # Unified command list with timestamps
        self._latest_detections = [] 
        self.dist_yellow, self.dist_white = -1.0, -1.0
        
        # Playback Sync
        self._playback_last_x = 0
        self._playback_last_y = 0
        
        # V8.6: AI Aim Assist (Prediction + Persistence)
        self._aim_assist_active = False
        self._ctrl_hits = 0
        self._annie_centroid = None # (x, y) current
        self._annie_velocity = (0.0, 0.0) # (vx, vy) in px/s
        self._last_annie_pos = None
        self.kalman = None
        self._last_annie_t = 0.0
        
        # V9.0: Dynamic Lead Time (replaces hardcoded 110ms)
        # Adapts prediction to actual detection latency instead of assuming fixed FPS.
        self._base_lead_time = 0.03  # 30ms: base Win32 input pipeline delay
        self._avg_dt = 0.016         # Initial assumption: 60 FPS (16ms per frame)
        
        self._screen_w, self._screen_h = 2560, 1440 # V8.9: Dynamic res support
        self.is_static_phase = False # ROI Gating Flag
        
        # Phase 2503: Internal State Initialization (Prevents AttributeError)
        self._annie_first_seen_t = 0.0
        self._annie_bbox_height = 0.0
        self._annie_label = ""
        self._hallucination_streak = 0
        self._lkp_centroid = None
        self._lkp_label = ""
        self._lkp_t = 0.0
        
        # Phase 2602: Titan Gate — hold fire when titan is not detected
        self._titan_count = 0          # Number of titans detected in current frame
        self._titan_gate_skipped = False   # Flag: last leftdown skipped
        self._titan_gate_zero_since = 0.0  # Timestamp when titan first disappeared (for 4s fallback)
        
        # V4.2: Dynamic path from config
        # Use config key, fallback to empty string (no crash if path doesn't exist on other PCs)
        from bot.config import config
        macro_path = config.get("bot", "macro_file", "")
        
        # Phase 2708: Auto-Fallback to custom_macro.json if not set in GUI
        if not macro_path and os.path.exists("custom_macro.json"):
            logger.info("[Macro] 'macro_file' config is empty, but 'custom_macro.json' found! Auto-loading it.")
            macro_path = "custom_macro.json"

        if macro_path:
            self._load_macro(macro_path)
        else:
            logger.info("[Macro] No static macro loaded. Booting directly to Dynamic Combat Engine.")

    def set_screen_res(self, w: int, h: int) -> None:
        """Updates internal resolution for delta calculations (V8.9)."""
        self._screen_w, self._screen_h = w, h

    def update_annie_target(self, detection: 'Detection') -> None:
        """Called by Brain to supply real-time Annie coordinates with velocity tracking."""
        now = time.perf_counter()
        dt = now - self._last_annie_t

        # V9.0: Smooth DT using Exponential Moving Average (80/20 ratio)
        if 0 < dt < 0.2:
            self._avg_dt = (self._avg_dt * 0.8) + (dt * 0.2)

        x_screen = float(detection.x_screen)
        y_screen = float(detection.y_screen)
        curr_pos = (int(x_screen), int(y_screen))
        self._annie_bbox_height = float(detection.h_screen)
        self._annie_label = detection.label.lower().replace(" ", "_")

        # ── Anti-Hallucination Filter ──────────────────────────────────────────
        from bot.config import config
        max_det_speed = config.get("aim_assist", "max_detection_speed_px_s", 2500)
        if self._last_annie_pos is not None and dt > 0 and dt < 1.0:
            implied_speed = math.hypot(
                x_screen - self._last_annie_pos[0],
                y_screen - self._last_annie_pos[1]
            ) / dt
            if implied_speed > max_det_speed:
                streak = getattr(self, "_hallucination_streak", 0) + 1
                self._hallucination_streak = streak
                if streak < 3:
                    logger.debug(f"[Macro] Anti-Hallucination: rejected detection (speed {implied_speed:.0f} px/s > {max_det_speed}). Streak: {streak}")
                    return
                logger.debug(f"[Macro] Anti-Hallucination: 3+ consecutive fast detections, accepting as real movement.")
            else:
                self._hallucination_streak = 0
        # ──────────────────────────────────────────────────────────────────────

        if self.kalman is not None and (now - self._last_annie_t) > 0.3:
            logger.debug(f"[Macro] Kalman reset after {now - self._last_annie_t:.2f}s dead reckoning — re-locking to Annie.")
            self.kalman = KalmanTracker(x_screen, y_screen)
            pred_x, pred_y = x_screen, y_screen
            vx, vy = 0.0, 0.0
            self._annie_velocity = (0.0, 0.0)
            self._annie_centroid = (int(x_screen), int(y_screen))
            self._lkp_centroid   = self._annie_centroid
            self._lkp_label      = self._annie_label
            self._lkp_t          = now
            self._last_annie_pos = curr_pos
            self._last_annie_t   = now
            return

        # Kalman Filter integration
        if self.kalman is None:
            self.kalman = KalmanTracker(x_screen, y_screen)
            pred_x, pred_y = x_screen, y_screen
            vx, vy = 0.0, 0.0
            self._annie_velocity = (vx, vy)
        else:
            kalman_enabled = config.get("aim_assist", "kalman_enabled", True)
            if kalman_enabled:
                # IMPORTANT: dt must be passed to update()
                dt_safe = max(float(dt), 1e-4)

                # Dampening: can be toggled from config
                dampening_enabled = config.get("aim_assist", "dampening_enabled", True)
                self.kalman.dampening = 0.95 if dampening_enabled else 1.0

                self.kalman.update([x_screen, y_screen], dt_safe)

                # predict() no longer needs dt parameter because it is set in update()
                pred_x, pred_y, vx, vy = self.kalman.predict()
                self._annie_velocity = (float(vx), float(vy))
            else:
                # Kalman OFF: use raw YOLO coordinate directly, without smoothing
                pred_x, pred_y = x_screen, y_screen
                vx, vy = 0.0, 0.0
                self._annie_velocity = (0.0, 0.0)
                # Reset Kalman state so it's ready when re-enabled
                self.kalman = None

        self._last_annie_pos = curr_pos
        self._last_annie_t = now
        
        if not hasattr(self, "_annie_first_seen_t"):
            self._annie_first_seen_t = 0.0

        if self._annie_centroid is None:
            if self._annie_first_seen_t == 0.0:
                self._annie_first_seen_t = now
        
        if (now - self._annie_first_seen_t) >= 0.02:
            self._annie_centroid = (int(pred_x), int(pred_y))
            self._lkp_centroid = self._annie_centroid
            self._lkp_label    = getattr(self, "_annie_label", "")
            self._lkp_t        = now

    def reset_memory(self) -> None:
        """Resets macro state to prevent stale triggers."""
        self._ctrl_hits = 0
        self._aim_assist_active = False
        self._annie_centroid = None
        self._annie_velocity = (0.0, 0.0)
        self._last_annie_pos = None
        self.kalman = None
        self._last_annie_t = 0.0
        self._annie_first_seen_t = 0.0
        self._annie_bbox_height = 0.0
        self._annie_label = ""
        self._hallucination_streak = 0  # Anti-hallucination consecutive reject counter
        # Last Known Position (LKP) memory — persists through brief target loss
        self._lkp_centroid = None   # Last confirmed (cx, cy) of Annie
        self._lkp_label    = ""     # Label at time of LKP
        self._lkp_t        = 0.0    # Timestamp when LKP was last updated

    def _load_macro(self, path: str) -> None:
        """Parses the macro file (MCR or JSON) into machine-readable tuples."""
        try:
            filename, ext = os.path.splitext(path)
            ext = ext.lower()

            if ext == '.mcr':
                self._load_mcr(path)
            elif ext == '.json':
                self._load_json(path)
            else:
                logger.error(f"[Macro] Unsupported file format: {ext}")
        except Exception as e:
            logger.error(f"[Macro] Critical Error loading macro: {e}")

    def _load_json(self, filename):
        try:
            with open(filename, 'r') as f:
                data = json.load(f)
            # Data should be a list of dicts: {"t": 0.0, "type": "mouse", "x": 1280, "y": 720}
            
            # Phase 2144: The God Project Hybrid Approach - REMOVED Slicing
            # We now use the FULL macro sequence to ensure approach completes correctly.
            # ─────────────────────────────────────────────────────────────────────
            
            
            # Phase 2416: Extend Q+E hold duration in approach macro
            # Original hold: 0.64s (3.175 -> 3.823s). We push keyUp events later by hold_bonus.
            from bot.config import config
            hold_bonus = config.get("combat_engine", "approach_qe_hold_bonus", 1.0)
            if hold_bonus > 0:
                # Find first Q/E keyUp timestamps
                first_qe_up = min(
                    (e['t'] for e in data if e.get('type') == 'key' 
                     and e.get('key') in ('q', 'e') 
                     and e.get('event', '').lower().replace('key','') == 'up'),
                    default=None
                )
                if first_qe_up is not None:
                    # Push ALL events that come AFTER the first Q/E up by hold_bonus seconds
                    data = [
                        {**e, 't': e['t'] + hold_bonus} if e['t'] >= first_qe_up else e
                        for e in data
                    ]
                    logger.info(f"[Macro] Q+E hold extended by {hold_bonus}s (keyUp shifted from t={first_qe_up:.3f}s)")
            
            # Phase 2510: Static Macro Duration Cutoff
            # Only load commands within the approach window. Commands beyond this
            # time limit are ignored — Dynamic Combat AI handles the rest.
            max_duration = config.get("combat_engine", "static_macro_max_duration", 25.0)
            if max_duration <= 0:
                logger.info("[Macro] Loading ALL commands (max_duration is set to 0/infinite).")
            else:
                logger.info(f"[Macro] Loading commands up to t={max_duration}s (approach window only).")
            
            self._commands = []
            for entry in data:
                t = entry.get("t", 0.0)
                if max_duration > 0 and t > max_duration:
                    break  # Data is ordered by time, safe to break early
                ctype = entry.get("type")
                if ctype == "mouse":
                    # (type, timestamp, action, x, y)
                    self._commands.append(('mouse', t, 'move', entry['x'], entry['y']))
                elif ctype == "click":
                    evt = entry['event'].lower().replace("key", "") # Normalize 'keydown' or 'down' -> 'down'
                    self._commands.append(('mouse', t, entry['button'] + evt, 0, 0))
                elif ctype == "key":
                    evt = entry['event'].lower().replace("key", "")
                    self._commands.append(('key', t, evt, entry['key'], 0))
                elif ctype == "wheel":
                    # (type, timestamp, action, delta)
                    self._commands.append(('mouse', t, 'wheel', 0, entry['delta']))
            
            if max_duration <= 0:
                logger.info(f"[Macro] Loaded {len(self._commands)} commands from JSON (infinite/no cutoff).")
            else:
                logger.info(f"[Macro] Loaded {len(self._commands)} commands from JSON (cutoff at t={max_duration}s).")
        except Exception as e:
            logger.error(f"[Macro] JSON Load Error: {e}")

    def _load_mcr(self, filename):
        # ... (Existing MCR loader, but converted to timestamps for unified playback)
        # Actually, let's keep it simple: if MCR, convert it to a dummy timestamped list
        try:
            with open(filename, 'r') as f:
                lines = f.readlines()
            
            current_t = 0.0
            self._commands = []
            for line in lines:
                line = line.strip()
                if not line: continue
                parts = [p.strip() for p in line.split(':')]
                
                cmd_type = parts[0].upper()
                if cmd_type == 'DELAY':
                    if len(parts) > 1:
                        current_t += int(parts[1]) / 1000.0
                elif cmd_type == 'KEYBOARD':
                    if len(parts) > 3:
                        key = self._map_key(parts[1])
                        event = parts[2].lower().replace("key", "") # 'keydown' -> 'down'
                        self._commands.append(('key', current_t, event, key, 0))
                elif cmd_type == 'MOUSE':
                    if len(parts) > 4:
                        # Mouse : X : Y : Action : V1
                        x, y = int(parts[1]), int(parts[2])
                        action = parts[3].lower()
                        v1 = int(parts[4]) if len(parts) > 4 else 0 # V1 is wheel delta for 'wheel' action
                        
                        if action == 'move':
                            self._commands.append(('mouse', current_t, 'move', x, y))
                        elif action == 'leftdown':
                            self._commands.append(('mouse', current_t, 'leftdown', 0, 0))
                        elif action == 'leftup':
                            self._commands.append(('mouse', current_t, 'leftup', 0, 0))
                        elif action == 'wheel':
                            self._commands.append(('mouse', current_t, 'wheel', 0, v1))
            
            logger.info(f"[Macro] Partially converted MCR to {len(self._commands)} timestamped ops.")
        except Exception as e:
            logger.error(f"[Macro] MCR Load Error: {e}")

    def _map_key(self, mcr_key: str) -> str:
        mapping = {
            'ControlLeft': 'ctrl', 'ShiftLeft': 'shift', 'Space': 'space',
            'W': 'w', 'A': 'a', 'S': 's', 'D': 'd', 'Q': 'q', 'E': 'e',
            'R': 'r', 'G': 'g', 'C': 'c'
        }
        return mapping.get(mcr_key, mcr_key.lower())

    def reset_memory(self) -> None:
        """Resets macro state to prevent stale triggers."""
        self._ctrl_hits = 0
        self._aim_assist_active = False
        self._annie_centroid = None
        self._annie_velocity = (0.0, 0.0)
        self._last_annie_pos = None
        self.kalman = None
        self._last_annie_t = 0.0
        self._annie_first_seen_t = 0.0
        self._annie_bbox_height = 0.0

    def check_detonation_range(self, radius: float = 20.0) -> bool:
        """Compatibility dummy."""
        return False

    def update_detections(self, detections: list, distances: tuple) -> None:
        self._latest_detections = detections
        self.dist_yellow, self.dist_white = distances
        # Phase 2602: Update titan count for Titan Gate
        prev_count = self._titan_count
        self._titan_count = sum(
            1 for d in detections
            if d.label.lower().replace(" ", "_") == "titan"
        )
        # Phase 2602 + 2606: Update absent timer untuk fallback gate
        if self._titan_count > 0:
            # Titan detected — reset absent timer
            self._titan_gate_zero_since = 0.0
        else:
            # Titan lost — start absent timer if not already running
            if self._titan_gate_zero_since == 0.0:
                self._titan_gate_zero_since = time.perf_counter()

    def start(self) -> None:
        if self._running: return
        
        # Phase 2501: Fresh Macro Reload
        # Ensure we are using the latest macro file from config before starting playback.
        from bot.config import config
        macro_path = config.get("bot", "macro_file", "")
        if macro_path:
            self._load_macro(macro_path)
            
        self._running = True
        logger.info("[Macro] Starting High-Precision Static Playback...")
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self._running: return
        self._running = False
        self._release_all_keys()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.2)
        logger.info("[Macro] Playback Stopped.")

    def _release_all_keys(self) -> None:
        """Release all possible held keys using BOTH input APIs to prevent stuck keys."""
        keys_to_release = ['w', 'a', 's', 'd', 'q', 'e', 'shift', 'ctrl', 'space', 'r', 'g', 'c']
        for k in keys_to_release:
            try: pydirectinput.keyUp(k)
            except: pass
            try: keyboard.release(k)
            except: pass
        
        # Phase 2516: Explicit Mouse Release
        # Ensures no stuck mouse buttons during transitions or stops.
        try: pydirectinput.mouseUp(button='left')
        except: pass

    def _precise_sleep(self, ms: int) -> None:
        """Sub-millisecond precision sleep loop."""
        target = time.perf_counter() + (ms / 1000.0)
        while self._running and time.perf_counter() < target:
            # Only sleep if we have significant time left (>2ms)
            if target - time.perf_counter() > 0.002:
                time.sleep(0.0005)

    def _process_aimbot(self) -> None:
        """Isolated aimbot logic that can be run continuously."""
        if not self._aim_assist_active: return
        
        from bot.config import config
        memory_dur = config.get("combat_engine", "aim_memory_duration", 4.0)
        
        # Determine active target: live centroid OR Last Known Position fallback
        aim_centroid = self._annie_centroid
        aim_label    = getattr(self, "_annie_label", "")
        
        if aim_centroid is None:
            # Live target lost — try Last Known Position
            lkp = getattr(self, "_lkp_centroid", None)
            lkp_age = time.perf_counter() - getattr(self, "_lkp_t", 0.0)
            if lkp is not None and lkp_age < memory_dur:
                aim_centroid = lkp
                aim_label    = getattr(self, "_lkp_label", "")
                # (No log spam — this runs at 100Hz)
        
        if aim_centroid:
            now_aim_tick = time.perf_counter()
            # Throttle aim adjustment to ~100Hz (0.01s) to prevent loop spam & flicking
            if now_aim_tick - getattr(self, "_last_aim_tick", 0.0) > 0.01:
                self._last_aim_tick = now_aim_tick
                
                cx, cy = aim_centroid
                vx, vy = self._annie_velocity
                
                # V9.0: Dynamic Lead Time — adapts to real detection latency
                lead_enabled = config.get("aim_assist", "lead_prediction_enabled", True)
                if lead_enabled:
                    # Predicts 1 frame into the future using smoothed EMA frame time.
                    # Multiplier lowered from 2.0 to 1.0 to prevent overshoot when FPS drops.
                    # Caps at 0.15s (150ms) to prevent runaway prediction during extreme lag.
                    dynamic_lead = self._base_lead_time + (self._avg_dt * 1.0)
                    dynamic_lead = min(dynamic_lead, 0.15)
                    # Project target position using Dynamic Lead prediction
                    px = int(cx + vx * dynamic_lead)
                    py = int(cy + vy * dynamic_lead)
                else:
                    # Lead OFF: aim directly at centroid, no future extrapolation
                    px, py = cx, cy
                
                # Global Offsets
                px += config.get("aim_assist", "global_offset_x", 0)
                py += config.get("aim_assist", "global_offset_y", 0)

                # Phase 2311: Y-Offset for Annie Mark
                if aim_label == "annie_mark":
                     y_offset = config.get("combat_engine", "annie_mark_y_offset", 40)
                     py += y_offset
                
                # FIX: Use game/config resolution, NOT SystemMetrics!
                center_x = self._screen_w // 2
                center_y = self._screen_h // 2
                
                fov_radius = config.get("aim_assist", "fov_radius", 150)
                p_gain = config.get("aim_assist", "p_gain", 0.4)
                max_delta = config.get("aim_assist", "max_delta", 15)
                
                # FOV FIX: Calculate distance based on ORIGINAL point (cx, cy), not prediction.
                # So bot does not release target when prediction point jumps out of bounds.
                dist_to_center_raw = math.hypot(cx - center_x, cy - center_y)
                
                if dist_to_center_raw <= fov_radius:
                    # Get current physical cursor position so aim doesn't float endlessly
                    mx, my = get_mouse_pos()
                    
                    # Calculate pull from CURSOR position to PREDICTED point
                    raw_dx = (px - mx) * p_gain
                    raw_dy = (py - my) * p_gain
                    
                    # Clamp maximum speed per frame
                    dx = max(-max_delta, min(max_delta, int(raw_dx)))
                    dy = max(-max_delta, min(max_delta, int(raw_dy)))
                    
                    # Predict cursor landing point on screen after adding dx and dy
                    next_mx = mx + dx
                    next_my = my + dy
                    
                    # Calculate distance from cursor landing point to screen center
                    dist_next_to_center = math.hypot(next_mx - center_x, next_my - center_y)
                    
                    # ABSOLUTE PROTECTION: If cursor landing exceeds red FOV limit
                    if dist_next_to_center > fov_radius:
                        # Calculate collision angle using Arc Tangent trigonometry
                        angle = math.atan2(next_my - center_y, next_mx - center_x)
                        
                        # Force landing coordinates to be exactly on the circle edge
                        safe_mx = center_x + int(math.cos(angle) * fov_radius)
                        safe_my = center_y + int(math.sin(angle) * fov_radius)
                        
                        # Recalculate safe dx and dy values so it doesn't cross the line
                        dx = safe_mx - mx
                        dy = safe_my - my
                        
                    if abs(dx) > 0 or abs(dy) > 0:
                        send_mouse_input(MOUSEEVENTF_MOVE, dx, dy)
                
                # Keep playback state in sync if required
    def _run_dynamic_combat(self) -> None:
        """Phase 2: Airborne Pendulum Combat Engine (Timing calibrated from macro recording)"""
        try:
            logger.info("[Macro] Phase 2: Airborne Pendulum Engine Started!")
            from bot.config import config
            
            # Release leftovers from static phase
            self._release_all_keys()
            
            # Phase 2507: Transit Buffer
            # Wait for macro momentum (dash back) to settle before starting first AI cycle.
            logger.info("[Macro] Transit Buffer: Settling macro momentum (0.8s)...")
            time.sleep(0.8)
            
            assault_count = 0
            
            while self._running:
                assault_count += 1
                # Sync: Ensure mouse is UP before starting a new cycle
                pydirectinput.mouseUp(button='left')
                
                self._process_aimbot()
                # --- PHASE 1: ASSAULT & ENGAGE (Hold Q + E + Space continuously) ---
                self._aim_assist_active = True
                
                # Initial Space Boost maneuver (Phase 2506)
                pydirectinput.keyDown('space')
                self._precise_sleep(40) # Quick tap duration (but stay held!)
                
                # Phase 2511: Hybrid IPM (Depth + Trajectory Turn Penalty)
                use_ipm     = config.get("combat_engine", "use_hybrid_ipm", False)
                K           = config.get("combat_engine", "ipm_k", 120.0)
                C           = config.get("combat_engine", "ipm_c", 0.2)
                clamp_min   = config.get("combat_engine", "ipm_clamp_min", 0.3)
                clamp_max   = config.get("combat_engine", "ipm_clamp_max", 2.0)
                turn_factor = config.get("combat_engine", "ipm_turn_factor", 0.0005)

                h_bbox = self._annie_bbox_height

                # Trajectory distance: screen 2D distance from FOV center to Annie centroid
                cx_screen, cy_screen = self._screen_w // 2, self._screen_h // 2
                if self._annie_centroid:
                    traj_dist = math.hypot(
                        self._annie_centroid[0] - cx_screen,
                        self._annie_centroid[1] - cy_screen
                    )
                else:
                    traj_dist = 0.0

                if h_bbox > 0 and use_ipm:
                    turn_penalty = traj_dist * turn_factor
                    assault_dur  = (K / h_bbox) + C + turn_penalty
                    
                    # ADAPTIVE LAG COMPENSATION (Prevents bot from "falling short" during FPS drops)
                    # When game lags (FPS drops), Roblox physics slows down, distance traveled per-second decreases.
                    enable_lag_comp = config.get("combat_engine", "enable_lag_compensation", True)
                    fps_ratio = self._avg_dt / 0.0166 # 0.0166 = 60fps
                    if enable_lag_comp and fps_ratio > 1.15: # If FPS is below ~50
                        max_mult = config.get("combat_engine", "lag_comp_max_mult", 1.3)
                        lag_multiplier = min(max_mult, fps_ratio ** 0.5) # Scale proportionally
                        assault_dur *= lag_multiplier
                        logger.info(f"[Macro] Lag detected ({(1/self._avg_dt):.0f} FPS). Assault duration increased by +{(lag_multiplier-1)*100:.1f}%")

                    # Phase 2512: Clamp to realistic limits
                    if assault_dur < clamp_min: assault_dur = clamp_min
                    if assault_dur > clamp_max: assault_dur = clamp_max
                    logger.info(f"[Macro] HYBRID IPM: bbox_h={h_bbox:.1f}px traj={traj_dist:.0f}px turn+={turn_penalty:.3f}s → t_hold={assault_dur:.2f}s")
                else:
                    # FALLBACK: Static Duration (Phase 2410)
                    assault_dur = config.get("combat_engine", "assault_duration", 1.5)
                    if use_ipm:
                        logger.warning(f"[Macro] No bbox data, fallback {assault_dur:.2f}s")
                    else:
                        logger.info(f"[Macro] STATIC MODE: Using {assault_dur:.2f}s duration.")
                
                # Phase 2600: First Hit Override Control
                if assault_count == 1:
                    first_dur = config.get("combat_engine", "assault_duration_first", assault_dur)
                    if first_dur > 0:
                        logger.info(f"[Macro] OVERRIDE: Applying First Assault Duration: {first_dur}s")
                        assault_dur = first_dur
                
                # Snapshot timestamp immediately before engagement (precise timing)
                now = time.perf_counter()
                assault_end = now + assault_dur
                logger.info(f"[Macro] DYNAMIC: Engaging Target (Flight for {assault_dur:.2f}s)...")
                logger.info(f"[Macro] TIMER: Assault START.")
                
                pydirectinput.keyDown('q', _pause=False)
                pydirectinput.keyDown('e', _pause=False)
                pydirectinput.keyDown('space', _pause=False)
                
                # Phase 2515: Sequential Initial Click ("Almost Simultaneous") - ASYNC FIX
                use_init_click = config.get("combat_engine", "use_assault_click", False)
                init_click_delay = config.get("combat_engine", "assault_key_click_delay", 0.1)
                
                # Hold for assault_duration while running aimbot
                last_heartbeat = now
                click_sent = not use_init_click # If disabled, treat as already "sent"
                
                while self._running and time.perf_counter() < assault_end:
                    if not click_sent and (time.perf_counter() - now) >= init_click_delay:
                        actual_delay = time.perf_counter() - now
                        logger.info(f"[Macro] TIMER: Sequential Click SENT at {actual_delay:.3f}s (Async 50ms Tap).")
                        
                        # Create a small function to tap separately from the aimbot loop
                        # SAFETY FIX: Click duration increased to be dynamic so Roblox doesn't 'miss' clicks during lag
                        enable_lag_comp = config.get("combat_engine", "enable_lag_compensation", True)
                        base_click_s = config.get("combat_engine", "base_click_duration_ms", 70) / 1000.0
                        safe_click_dur = max(base_click_s, self._avg_dt * 1.5) if enable_lag_comp else base_click_s
                        
                        def async_tap(dur=safe_click_dur):
                            pydirectinput.mouseDown(button='left')
                            time.sleep(dur) 
                            pydirectinput.mouseUp(button='left')
                            
                        # Run tap in background thread so aimbot continues smoothly!
                        threading.Thread(target=async_tap, daemon=True).start()
                        click_sent = True

                    self._process_aimbot()
                    self._precise_sleep(5)  # 5ms precision loop
                    
                    # Phase 2509: Heartbeat log every 0.5s to verify hold is active
                    if time.perf_counter() - last_heartbeat > 0.5:
                        logger.info(f"[Macro] TIMER: STILL HOLDING... (Time left: {max(0, assault_end - time.perf_counter()):.1f}s)")
                        last_heartbeat = time.perf_counter()
                
                logger.info(f"[Macro] TIMER: Assault END.")
                
                if not self._running: break
                # Release all approach keys
                pydirectinput.keyUp('space')
                pydirectinput.keyUp('q')
                pydirectinput.keyUp('e')
                # Removed pydirectinput.keyUp('w', _pause=False) to match keyDown change
                
                # --- PHASE 2: EXECUTE (Fire Thunder Spear) ---
                logger.info("[Macro] DYNAMIC: Landing Shot! Firing Thunder Spears.")
                pydirectinput.mouseDown(button='left')
                # SAFETY FIX: Hold click increased according to frame rate so it isn't lost during lag spikes.
                enable_lag_comp = config.get("combat_engine", "enable_lag_compensation", True)
                base_click_ms = config.get("combat_engine", "base_click_duration_ms", 70)
                safe_shot_dur = max(base_click_ms, int(self._avg_dt * 1000 * 1.5)) if enable_lag_comp else base_click_ms
                self._precise_sleep(safe_shot_dur)
                pydirectinput.mouseUp(button='left')
                self._precise_sleep(50) # Phase 2505: Animation buffer reduced from 200ms
                
                if not self._running: break
                
                # --- PHASE 3: EVADE (Double S Dash - Optimized for Aggression) ---
                logger.info("[Macro] DYNAMIC: SNAP LOOK DOWN & EVADE.")
                self._aim_assist_active = False
                
                # Phase 2506: Automated Look-Down Reset before Dodge
                # Reduced from 800px: gentler angle keeps bot at manageable height
                send_mouse_input(MOUSEEVENTF_MOVE, 0, 300)
                self._precise_sleep(30)
                
                # SAFETY FIX: Keyboard tap duration increased so it isn't skipped (merged frames) by the game during lag.
                enable_lag_comp = config.get("combat_engine", "enable_lag_compensation", True)
                base_click_ms = config.get("combat_engine", "base_click_duration_ms", 70)
                safe_tap = max(base_click_ms, int(self._avg_dt * 1000 * 1.5)) if enable_lag_comp else base_click_ms
                safe_gap = max(base_click_ms, int(self._avg_dt * 1000 * 1.5)) if enable_lag_comp else base_click_ms
                
                pydirectinput.keyDown('s', _pause=False)
                self._precise_sleep(safe_tap)
                pydirectinput.keyUp('s', _pause=False)
                self._precise_sleep(safe_gap)
                pydirectinput.keyDown('s', _pause=False)
                self._precise_sleep(safe_tap)
                pydirectinput.keyUp('s', _pause=False)
                
                # --- PHASE 4: COOLDOWN (float in air, keep aimbot ON for smooth re-engagement) ---
                # Aimbot stays active: cursor tracks Annie while airborne so next assault starts on-target.
                self._aim_assist_active = True
                
                # Refresh cooldown timing from config live
                cooldown_dur = config.get("combat_engine", "cooldown_duration", 1.2)
                cooldown_end = time.perf_counter() + cooldown_dur
                while self._running and time.perf_counter() < cooldown_end:
                    self._process_aimbot()
                    self._precise_sleep(5)  # 5ms precision loop
        except Exception as e:
            logger.error(f"[Macro] Dynamic Combat Error: {e}")
        finally:
            self._release_all_keys()
            self._aim_assist_active = False
            logger.info("[Macro] Dynamic Combat Engine Stopped.")

    def _run_loop(self) -> None:
        """High-Performance Relative Playback Engine & Aimbot Runner."""
        from bot.config import config
        self.is_static_phase = True # Block ROI during startup and approach
        
        # Phase 2415: Startup Delay
        # After cutscene skip, game still has fade-in/loading animation.
        # Wait before firing any inputs to ensure the game world is ready.
        startup_delay = config.get("combat_engine", "startup_delay", 2.0)
        logger.info(f"[Macro] Startup delay: {startup_delay}s (waiting for game fade-in)...")
        delay_end = time.perf_counter() + startup_delay
        while self._running and time.perf_counter() < delay_end:
            time.sleep(0.05)
        if not self._running:
            return
        
        # If no commands are loaded, just run purely as Dynamic Combat
        if not self._commands:
            logger.info("[Macro] No static macro loaded. Booting directly to Dynamic Combat Engine.")
            self.is_static_phase = False
            self._run_dynamic_combat()
            return

        playback_start = time.perf_counter()
        first_mouse = next((c for c in self._commands if c[0] == 'mouse' and c[2] == 'move'), None)
        
        self._ctrl_hits = 0
        self._aim_assist_active = False
        self._last_shot_fired_t = playback_start # Initialize shot tracker for Titan Gate
        
        if first_mouse:
            self._playback_last_x, self._playback_last_y = first_mouse[3], first_mouse[4]
        else:
            self._playback_last_x, self._playback_last_y = 0, 0
        
        for cmd in self._commands:
            if not self._running: break
            
            ctype, target_t = cmd[0], cmd[1]
            
            # Active Wait state (runs aimbot while waiting for next command time)
            while self._running and (time.perf_counter() - playback_start) < target_t:
                self._process_aimbot()
                time.sleep(0.0005)
            
            if not self._running: break
            
            if ctype == 'key':
                event, keyname = cmd[2], cmd[3]
                mapped_key = self._map_key(keyname)
                if event == 'down': 
                    if mapped_key == 'ctrl':
                        self._ctrl_hits += 1
                        
                        # Phase 2502: Safe Aim Activation Window
                        # Only allow aimbot to activate if we have passed the safe time.
                        # This prevents early macro dashes from triggering aimbot during cutscene skip.
                        elapsed_time = time.perf_counter() - playback_start
                        safe_time = config.get("combat_engine", "safe_aim_activation_time", 2.5)
                        
                        if self._ctrl_hits >= 2 and elapsed_time > safe_time:
                            if not self._aim_assist_active:
                                logger.info(f"[Macro] Safe Time ({elapsed_time:.1f}s > {safe_time}s) reached & CTRL hit. AI AIM ASSIST ACTIVE.")
                                self._aim_assist_active = True
                        elif self._ctrl_hits >= 2:
                            logger.debug(f"[Macro] Blocked early Aimbot activation (Time: {elapsed_time:.1f}s < {safe_time}s)")
                    pydirectinput.keyDown(mapped_key, _pause=False)
                elif event == 'up':
                    pydirectinput.keyUp(mapped_key, _pause=False)
                    
            elif ctype == 'mouse':
                # Suppress recorded rigid mouse movements if AI is actively tracking Annie
                if self._aim_assist_active and self._annie_centroid:
                    if cmd[2] == 'move':
                        continue
                        
                action, x, y_or_delta = cmd[2], cmd[3], cmd[4]
                
                if action == 'move':
                    raw_dx, raw_dy = x - self._playback_last_x, y_or_delta - self._playback_last_y
                    MAX_DELTA = 30
                    dx = max(-MAX_DELTA, min(MAX_DELTA, int(raw_dx)))
                    dy = max(-MAX_DELTA, min(MAX_DELTA, int(raw_dy)))
                    
                    if dx != 0 or dy != 0:
                        send_mouse_input(MOUSEEVENTF_MOVE, dx, dy)
                    
                    self._playback_last_x, self._playback_last_y = x, y_or_delta
                elif action == 'leftdown':
                    # Phase 2602 + 2606: Titan Gate (Non-blocking).
                    # titan >= 1 -> shoot directly.
                    # titan == 0 -> SKIP shot, EXCEPT if it's been 10 seconds since LAST shot.
                    TITAN_GATE_MAX_WAIT = 10.0
                    time_since_last_shot = time.perf_counter() - getattr(self, "_last_shot_fired_t", 0.0)
                    
                    if self._titan_count == 0:
                        if time_since_last_shot < TITAN_GATE_MAX_WAIT:
                            self._titan_gate_skipped = True
                            logger.debug(f"[TitanGate] SKIP shot - titan=0 (10s limit not reached: {time_since_last_shot:.1f}s)")
                            continue
                        else:
                            logger.info(f"[TitanGate] BLIND SHOT - titan=0 but it's been {time_since_last_shot:.1f}s since last shot!")
                            
                    # Shot allowed (because titan is visible, OR it's been 10 seconds)
                    self._titan_gate_skipped = False
                    self._last_shot_fired_t = time.perf_counter() # Reset timer BECAUSE shot was fired!
                    send_mouse_input(MOUSEEVENTF_LEFTDOWN)
                elif action == 'leftup':
                    if getattr(self, "_titan_gate_skipped", False):
                        self._titan_gate_skipped = False
                        logger.debug("[TitanGate] SKIP leftup (matching leftdown was skipped).")
                        continue
                    send_mouse_input(MOUSEEVENTF_LEFTUP)
                elif action == 'rightdown':
                    send_mouse_input(MOUSEEVENTF_RIGHTDOWN)
                elif action == 'rightup':
                    send_mouse_input(MOUSEEVENTF_RIGHTUP)
                elif action == 'wheel':
                     send_mouse_input(MOUSEEVENTF_WHEEL, data=int(y_or_delta * 120))
            
        # Transition out of static macro and into dynamic combat
        if self._running:
            logger.info("[Macro] Static Arrival Phase complete. Switching to Dynamic Combat Engine.")
            self.is_static_phase = False # Unblock ROI for main combat
            self._run_dynamic_combat()
