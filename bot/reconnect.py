"""
bot/reconnect.py - AOTR Bot Auto-Reconnect Module
==================================================
Adapted from: f:\\AI macro aotr\\Auto Reconnect roblox\\reconnect.py

Runs as a lightweight daemon thread alongside the main bot.
No UI. No extra dependencies beyond the standard library.

Responsibilities:
- Monitor the latest Roblox log file for disconnect keywords.
- When a disconnect is detected, re-launch Roblox via protocol URL.
- Reset and wait for the next session log automatically.

Usage:
    from bot.reconnect import RobloxReconnectWatchdog
    watchdog = RobloxReconnectWatchdog()
    watchdog.start()  # Starts a daemon thread
    # ...
    watchdog.stop()
"""

import os
import glob
import re
import time
import threading
import logging
import subprocess
import csv
import psutil
import pygetwindow as gw
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

ROBLOX_LOG_DIR = os.path.expandvars(r"%LOCALAPPDATA%\Roblox\logs")

DISCONNECT_KEYWORDS = list({
    "Error Code: 277": "Error 277 (Lost Connection)",
    "Error Code: 279": "Error 279 (Connection Failed)",
    "Error Code: 268": "Error 268 (Unexpected Client Behavior)",
    "Error Code: 267": "Error 267 (Kicked by Script)",
    "Error Code: 273": "Error 273 (Same Account Launched)",
    "Error Code: 524": "Error 524 (Not Authorized)",
    "Error Code: 529": "Error 529 (Technical Difficulties)",
    "Error Code: 610": "Error 610 (No Authenticated User)",
    "Error Code: 274": "Error 274 (Server Shut Down)",
    "Error Code: 278": "Error 278 (Disconnected from Server)",
    "Error Code: 280": "Error 280 (Version Mismatch)",
    "Connection attempt failed": "Connection attempt failed",
    "Lost connection": "Lost connection",
    "Disconnected - Websocket closed": "Websocket closed",
    "Teleport Failed": "Teleport Failed",
    "Unexpected client behavior": "Unexpected client behavior / Crash",
    "Kicked": "Kicked from server",
    "Security Timeout": "Security Timeout"
}.keys())

REASON_MAP = {
    "Error Code: 277": "Error 277 (Lost Connection)",
    "Error Code: 279": "Error 279 (Connection Failed)",
    "Error Code: 268": "Error 268 (Unexpected Client Behavior)",
    "Error Code: 267": "Error 267 (Kicked by Script)",
    "Error Code: 273": "Error 273 (Same Account Launched)",
    "Error Code: 524": "Error 524 (Not Authorized)",
    "Error Code: 529": "Error 529 (Technical Difficulties)",
    "Error Code: 610": "Error 610 (No Authenticated User)",
    "Error Code: 274": "Error 274 (Server Shut Down)",
    "Error Code: 278": "Error 278 (Disconnected from Server)",
    "Error Code: 280": "Error 280 (Version Mismatch)",
    "Connection attempt failed": "Connection attempt failed",
    "Lost connection": "Lost connection",
    "Disconnected - Websocket closed": "Websocket closed",
    "Teleport Failed": "Teleport Failed",
    "Unexpected client behavior": "Unexpected client behavior / Crash",
    "Kicked": "Kicked from server",
    "Security Timeout": "Security Timeout"
}

PLACE_ID_PATTERN = re.compile(
    r"placeId[:,]\s*(\d+)|PlaceId[:=]\s*(\d+)|placeId=(\d+)",
    re.IGNORECASE
)

DEFAULT_PLACE_ID = "13379208636"  # AOTR PlaceId Fallback (Phase 52)

_global_watchdog = None

class RobloxReconnectWatchdog:
    """
    Background daemon that monitors Roblox logs and auto-reconnects.
    Compatible with the bot's threading model (daemon thread, no blocking).
    """

    def __init__(self):
        global _global_watchdog
        _global_watchdog = self
        self._is_running = False
        self._is_paused = False
        self._thread: threading.Thread | None = None
        self.current_place_id: str | None = DEFAULT_PLACE_ID
        self.latest_log_file: str | None = None
        self.start_time = datetime.now(timezone.utc)
        
        # V9.0: Immortal Attributes
        self.reconnect_timestamps = [] # To handle Anti-Loop (max 3 in 15m)
        self.last_launch_attempt_t = 0.0 # To handle Post-Launch Verification
        self.last_process_seen_t = time.time() # For process monitoring
        self.last_reconnect_t = 0.0 # Cooldown to avoid multi-open
        _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.history_csv_path = os.path.join(_ROOT, "logs", "reconnect_history.csv")
        
        # Ensure logs directory exists
        _logs_dir = os.path.join(_ROOT, "logs")
        if not os.path.exists(_logs_dir):
            os.makedirs(_logs_dir)
        
        # Brain reference for state signalling (set by BotEngine after init)
        self.brain = None

    # ── Public API ──────────────────────────────────────────────────────────

    def start(self):
        """Start the watchdog as a daemon thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("[Watchdog] Already running, ignoring start().")
            return

        self._is_running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True, name="ReconnectWatchdog")
        self._thread.start()
        logger.info("[Watchdog] Auto-Reconnect Watchdog started.")

    def stop(self):
        """Signal the watchdog to stop."""
        self._is_running = False
        logger.info("[Watchdog] Auto-Reconnect Watchdog stopped.")
        
    def pause(self):
        """Temporarily suspend active window/health checks (e.g., when bot is paused)."""
        self._is_paused = True
        logger.info("[Watchdog] Auto-Reconnect Watchdog paused.")
        
    def resume(self):
        """Resume active window/health checks."""
        self._is_paused = False
        logger.info("[Watchdog] Auto-Reconnect Watchdog resumed.")

    # ── Internal ────────────────────────────────────────────────────────────

    def _get_latest_log(self) -> str | None:
        """Returns the path to the most recently created Roblox log file."""
        try:
            log_files = glob.glob(os.path.join(ROBLOX_LOG_DIR, "*.log"))
            if not log_files:
                return None
            return max(log_files, key=os.path.getctime)
        except Exception as e:
            logger.error("[Watchdog] Error finding log file: %s", e)
            return None

    def ensure_roblox_ready(self):
        """
        Synchronous check to ensure Roblox is running and focused.
        Called on bot startup.
        """
        from bot.config import config
        wconfig = config.get("window_management", {})
        proc_name = wconfig.get("process_name", "RobloxPlayerBeta.exe")
        
        logger.info("[Watchdog] Performing pre-flight Roblox check...")
        
        # 1. Check if running and visible (Phase 1735: Instant Zombie Check)
        is_running = any(proc.info['name'] == proc_name for proc in psutil.process_iter(['name']))
        has_visible_window = any(w.title == "Roblox" and w.visible for w in gw.getWindowsWithTitle('Roblox'))
        
        if not is_running or not has_visible_window:
            reason = "Process missing on startup" if not is_running else "Zombie process on startup"
            logger.warning(f"[Watchdog] {reason}. Attempting to launch/restart...")
            self._reconnect(reason=reason)
            # Wait for window
            for _ in range(30):
                if any(proc.info['name'] == proc_name for proc in psutil.process_iter(['name'])):
                    # Final check: is the window actually visible now?
                    if any(w.title == "Roblox" and w.visible for w in gw.getWindowsWithTitle('Roblox')):
                        logger.info("[Watchdog] Roblox launched and visible.")
                        time.sleep(1.0)
                        break
                time.sleep(0.5)
        
        # 2. Check focus (Phase 1766: Robust Win32 Focus)
        import ctypes
        hwnd = ctypes.windll.user32.FindWindowW(None, "Roblox")
        if hwnd:
            self._force_focus(hwnd)
            time.sleep(0.5)
        else:
            logger.warning("[Watchdog] Roblox window NOT found via FindWindowW.")

    def _force_focus(self, hwnd):
        """Forcefully bring window to foreground and maximize it."""
        import ctypes
        now = time.time()
        # Phase 1881: Add cooldown to avoid spam if SetForegroundWindow is blocked
        if hasattr(self, "_last_focus_t") and now - self._last_focus_t < 2.5:
            return

        foreground_hwnd = ctypes.windll.user32.GetForegroundWindow()
        if hwnd != foreground_hwnd:
            logger.info("[Watchdog] Focusing and Maximizing Roblox window (HWND:%s)...", hwnd)
            self._last_focus_t = now
            # SW_MAXIMIZE = 3
            ctypes.windll.user32.ShowWindow(hwnd, 3)
            # Alt-key trick to bypass SetForegroundWindow restrictions
            ctypes.windll.user32.keybd_event(0x12, 0, 0, 0) # Alt down
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            ctypes.windll.user32.keybd_event(0x12, 0, 2, 0) # Alt up

    def _check_window_health(self):
        """Proactive health check for the Roblox process and window focus."""
        if getattr(self, "_is_paused", False):
            return
            
        import time
        now = time.time()
        
        # Phase 2705: Throttle process checks to once every 2 seconds to eliminate CPU/psutil lag
        if hasattr(self, "_last_process_check") and now - self._last_process_check < 2.0:
            return
        self._last_process_check = now
            
        from bot.config import config
        wconfig = config.get("window_management", {})
        if not wconfig.get("enable_process_monitor", True):
            return

        proc_name = wconfig.get("process_name", "RobloxPlayerBeta.exe")
        is_alive = False
        
        # 1. Process Check (Heavy: ~50-100ms)
        import psutil
        for proc in psutil.process_iter(['name']):
            if proc.info['name'] == proc_name:
                is_alive = True
                break
        
        # 2. Window Check (Phase 1723: Detect Zombie/Invisible Process)
        # If window is closed but process remains, we treat it as missing
        has_visible_window = any(w.title == "Roblox" and w.visible for w in gw.getWindowsWithTitle('Roblox'))
        
        if is_alive and has_visible_window:
            self.last_process_seen_t = time.time()
            
            # 2. Focus Check (Only if process is alive)
            if wconfig.get("enable_auto_focus", True):
                import ctypes
                hwnd = ctypes.windll.user32.FindWindowW(None, "Roblox")
                if hwnd:
                    self._force_focus(hwnd)
                else:
                    logger.debug("[Watchdog] Focus check failed: FindWindowW could not find Roblox.")
        else:
            # Process is missing!
            elapsed_missing = time.time() - self.last_process_seen_t
            delay_sec = wconfig.get("process_missing_timeout_seconds", 20)
            
            if elapsed_missing > delay_sec:
                logger.error("[Watchdog] HEALTH FAILED: Roblox process missing for %ds. Triggering Reconnect.", int(elapsed_missing))
                self._reconnect(reason="Process Missing")
                self.last_process_seen_t = time.time() # Reset to avoid spam if relaunch fails

    def _reconnect(self, reason: str = "Unknown"):
        """Re-launch Roblox using the last known PlaceId (V9.0 Immortal Mode)"""
        if not self.current_place_id:
            logger.warning("[Watchdog] No PlaceId found yet. Cannot reconnect.")
            return

        # 1. Anti-Loop Protection (3 attempts / 15 mins)
        now_ts = time.time()
        # Clean up old timestamps (> 15 mins)
        self.reconnect_timestamps = [t for t in self.reconnect_timestamps if now_ts - t < 900]
        
        if len(self.reconnect_timestamps) >= 3:
            logger.critical("[Watchdog] ANTI-LOOP ACTIVE! 3 reconnects within 15 mins. Cooling down for 5 mins...")
            time.sleep(300) # Wait 5 minutes
            self.reconnect_timestamps = [] # Reset after cooldown
            return

        # 0. Cooldown Check (Avoid double-trigger from same log burst)
        if now_ts - self.last_reconnect_t < 60:
            logger.debug("[Watchdog] Reconnect suppressed (Cooldown active: %ds remaining)", int(60 - (now_ts - self.last_reconnect_t)))
            return

        logger.warning("[Watchdog] IMMORTAL RECONNECT TRIGGERED. Reason: %s", reason)
        self.last_reconnect_t = now_ts

        # 2. Force-Kill Process (Clean State)
        try:
            logger.info("[Watchdog] Hard Killing Roblox processes...")
            
            # Phase 2704: Aggressive kill via psutil first
            import psutil
            for proc in psutil.process_iter(['name']):
                if proc.info['name'] == "RobloxPlayerBeta.exe":
                    try:
                        proc.kill()
                    except psutil.NoSuchProcess:
                        pass
            
            # Fallback sweeping with taskkill
            subprocess.run(["taskkill", "/F", "/IM", "RobloxPlayerBeta.exe", "/T"], 
                           capture_output=True, check=False)
        except Exception as kill_err:
             logger.error("[Watchdog] Process kill failed (non-critical): %s", kill_err)

        # 3. Clean-state Delay (V9.0 Requirement)
        time.sleep(5)

        # 4. Smart Logging (CSV History)
        try:
            file_exists = os.path.isfile(self.history_csv_path)
            with open(self.history_csv_path, mode="a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(["Timestamp", "PlaceId", "Reason"])
                writer.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), self.current_place_id, reason])
        except Exception as log_err:
             logger.error("[Watchdog] CSV log failed: %s", log_err)

        # 4.5. Wait for Internet Connection (Crucial for Wi-Fi Drops)
        logger.info("[Watchdog] Checking internet connection before relaunching...")
        while True:
            try:
                import socket
                socket.create_connection(("8.8.8.8", 53), timeout=3).close()
                logger.info("[Watchdog] Internet connection verified.")
                break
            except OSError:
                logger.warning("[Watchdog] No internet connection. Waiting 5 seconds before retrying...")
                time.sleep(5)

        # 5. Relaunch (Protocol URL)
        try:
            url = f"roblox://placeId={self.current_place_id}/"
            os.startfile(url)
            logger.info("[Watchdog] Relaunch command sent: %s", url)
            self.last_launch_attempt_t = time.time() # For Verification check
            self.reconnect_timestamps.append(now_ts)
            
            # Masuk ke state RECOVERY setelah restart
            if self.brain:
                try:
                    from bot.brain import BotState
                    self.brain._change_state(BotState.RECOVERY)
                except Exception as ex:
                    logger.error(f"[Watchdog] Failed to set RECOVERY state: {ex}")
                    
        except Exception as e:
            logger.error("[Watchdog] Failed to send reconnect command: %s", e)

        # Reset session tracking
        self.current_place_id = DEFAULT_PLACE_ID

    def check_log_for_disconnect(self, lookback_seconds: float = 600.0) -> str | None:
        """
        Phase 2604: One-shot log scan called by Brain during stuck state.
        Reads latest Roblox log from start (not tail) and looks for
        disconnect keywords that occurred in the last `lookback_seconds`.

        Returns:
            Error description if disconnect is found, None if clean.
        """
        log_path = self._get_latest_log()
        if not log_path:
            logger.warning("[Watchdog] check_log_for_disconnect: No Roblox log found.")
            return None

        now_utc = datetime.now(timezone.utc)
        cutoff = now_utc - timedelta(seconds=lookback_seconds)

        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            for line in reversed(lines):  # Scan from end for speed
                for kw in DISCONNECT_KEYWORDS:
                    if kw.lower() in line.lower():
                        ts_match = re.search(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", line)
                        if ts_match:
                            try:
                                log_ts = datetime.strptime(
                                    ts_match.group(1), "%Y-%m-%dT%H:%M:%S"
                                ).replace(tzinfo=timezone.utc)
                                if log_ts >= cutoff:
                                    reason = REASON_MAP.get(kw, kw)
                                    logger.warning(
                                        "[Watchdog] Stuck-state scan found disconnect: '%s' (%s)",
                                        reason, ts_match.group(1)
                                    )
                                    return reason
                            except Exception:
                                pass
                        else:
                            # No timestamp, assume new (safety)
                            reason = REASON_MAP.get(kw, kw)
                            logger.warning(
                                "[Watchdog] Stuck-state scan found disconnect (no TS): '%s'", reason
                            )
                            return reason
        except Exception as e:
            logger.error("[Watchdog] check_log_for_disconnect error: %s", e)

        return None  # Clean log, no disconnect

    def _tail_file(self, filepath: str, seek_to_end: bool = True):
        """Continuously reads from the log file, watching for disconnect events."""
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                if seek_to_end:
                    # Normal case: skip old lines to avoid re-reading past errors
                    f.seek(0, os.SEEK_END)
                    logger.info("[Watchdog] Tailing log (Skipped to end): %s", os.path.basename(filepath))
                else:
                    # Fresh new log after reconnect: read from beginning to catch early errors (e.g. 529)
                    logger.info("[Watchdog] Tailing log (Reading from START for fresh session): %s", os.path.basename(filepath))

                while self._is_running and self.latest_log_file == filepath:
                    line = f.readline()
                    if not line:
                        # IMPORTANT: Clear Python's EOF internal buffer flag so it sees new writes
                        f.seek(0, os.SEEK_CUR)
                        
                        self._check_window_health()
                        time.sleep(0.25)
                        
                        # Fix: Check if a newer log file was created (e.g. after a restart)
                        current_latest = self._get_latest_log()
                        if current_latest and current_latest != filepath:
                            logger.info("[Watchdog] Newer log file detected during tail! Breaking tail loop to attach.")
                            break
                        
                        continue

                    # 1. Capture PlaceId for reconnect URL
                    if not self.current_place_id:
                        match = PLACE_ID_PATTERN.search(line)
                        if match:
                            for group in match.groups():
                                if group:
                                    self.current_place_id = group
                                    logger.info("[Watchdog] Session PlaceId captured: %s", self.current_place_id)
                                    break

                    # 2. Check for disconnect keywords
                    for kw in DISCONNECT_KEYWORDS:
                        if kw.lower() in line.lower():
                            logger.warning("[Watchdog] Valid Disconnect found live in log: '%s'", line.strip())
                            human_reason = REASON_MAP.get(kw, kw)
                            if self.brain:
                                self.brain.notify_disconnected(reason=f"{human_reason}")
                            self._reconnect(reason=human_reason)
                            return # Exits _tail_file, allows monitor loop to reset

        except FileNotFoundError:
            logger.warning("[Watchdog] Log file was deleted or moved: %s", filepath)
            self.latest_log_file = None
        except Exception as e:
            logger.error("[Watchdog] Error reading log file: %s", e)

    def _monitor_loop(self):
        """Main loop: checks for new log files and starts tailing them."""
        logger.info("[Watchdog] Monitoring Roblox logs at: %s", ROBLOX_LOG_DIR)

        while self._is_running:
            # 1. Post-Launch Verification (V9.0)
            # If we attempted a launch but no NEW log file has appeared after 60s
            if self.last_launch_attempt_t > 0:
                elapsed = time.time() - self.last_launch_attempt_t
                if elapsed > 60:
                    latest_on_disk = self._get_latest_log()
                    # If the latest on disk is still None or the one we already had (which was reset to None in _reconnect)
                    # wait, self.latest_log_file is set to None in _reconnect.
                    # So if latest_on_disk is same as some 'old' log or something?
                    # Let's just check if self.latest_log_file is still None.
                    if self.latest_log_file is None:
                        logger.error("[Watchdog] VERIFICATION FAILED. No new log after 60s. Retrying launch...")
                        self._reconnect("Launch Verification Failure")
                    else:
                        # Verification success handled by the log detection below
                        self.last_launch_attempt_t = 0

            new_log = self._get_latest_log()

            if new_log and new_log != self.latest_log_file:
                self.latest_log_file = new_log
                self.current_place_id = DEFAULT_PLACE_ID
                logger.info("[Watchdog] New log file detected: %s", os.path.basename(new_log))
                # Clear verification state because a new log appeared!
                self.last_launch_attempt_t = 0
                self._tail_file(new_log, seek_to_end=False)  # Read from start so early errors like 529 aren't missed
            else:
                # Run health check periodically between log polls
                self._check_window_health()
                time.sleep(1)  # Poll for new log files every 1s (reduced for faster focus check)
