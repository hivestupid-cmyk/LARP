"""
main.py — AOTR Bot entry point.

IMPORT ORDER IS CRITICAL:
    ultralytics (and its torch/CUDA DLLs) MUST be imported before PyQt6.
    Importing PyQt6 first causes a DLL loader conflict on Windows that
    crashes the CUDA runtime. bot.engine imports ultralytics transitively,
    so we import it first.

Hotkeys:
    alt+1 — Toggle bot on/off (starts/stops BotEngine thread)
    alt+2 — Graceful shutdown (stops engine + exits Qt event loop)
"""

import logging
import os
import sys
import importlib
import time

# Suppress Qt Warnings (DPI, PaintEngine, etc.)
os.environ["QT_LOGGING_RULES"] = "*.warning=false;qt.qpa.window.warning=false"


from bot.engine import BotEngine      # pulls in ultralytics → torch → CUDA DLLs

# ── Step 2: PyQt6 (safe now that CUDA DLLs are loaded) ──────────────────────
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QObject, pyqtSignal
# ── Step 3: everything else ──────────────────────────────────────────────────
import keyboard
from bot.config import config
from bot.overlay import OverlayWindow
from bot.settings_gui import SettingsWindow
from bot.reconnect import RobloxReconnectWatchdog
from bot.discord_bot import DiscordBot

import sys
print("Bot running Python from:", sys.executable)
# ---------------------------------------------------------------------------
# Logging setupss qe 
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.FileHandler("bot.log", mode="w", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("main")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    logger.info("Bot is ready.")

    start_key:  str = config.get("bot", "start_hotkey",  "f1")
    pause_key:  str = config.get("bot", "pause_hotkey",  "f2")
    stop_key:   str = config.get("bot", "stop_hotkey",   "f3")

    # ── Qt application ──────────────────────────────────────────────────────
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False) # Don't exit when settings window closes

    class HotkeySignals(QObject):
        start_sig = pyqtSignal()
        pause_sig = pyqtSignal()
        exit_sig = pyqtSignal()
        reload_sig = pyqtSignal()

    hotkey_signals = HotkeySignals()

    # ── Settings & Bot Lifecycle ───────────────────────────────────────────
    settings = SettingsWindow()
    overlay: OverlayWindow | None = None
    engine: BotEngine | None = None
    reconnect_watchdog: RobloxReconnectWatchdog = RobloxReconnectWatchdog()
    
    # Phase 1520: Initialize Discord Bot early (when GUI opens)
    discord_bot_instance = DiscordBot(config)

    def on_start() -> None:
        nonlocal engine
        # Case 1: Engine hasn't been created yet (First run)
        if not engine:
            logger.info(f"[{start_key}] Bot not initialized. Starting engine now...")
            if discord_bot_instance:
                discord_bot_instance.send_notification(f"🔘 **{start_key.upper()} button pressed**: Initializing & **STARTING** Bot", edit_category="system_log")
            start_bot()
            if engine:
                engine.start()
            return

        # Case 2: Engine exists, resume its running state
        is_running = engine.isRunning()
        if not is_running:
            logger.info(f"[{start_key}] Bot is STOPPED/PAUSED. Proceeding to **RESUME/START**.")
            if discord_bot_instance:
                discord_bot_instance.send_notification(f"🔘 **{start_key.upper()} button pressed**: Proceeding to **RESUME/START** Bot", edit_category="system_log")
            
            reconnect_watchdog.resume()
            config.reload()
            engine.start()
            settings.hide()
            if overlay:
                overlay.show()

    def on_pause() -> None:
        nonlocal engine
        if not engine: return
        is_running = engine.isRunning()
        if is_running:
            logger.info(f"[{pause_key}] Bot is RUNNING. Proceeding to **PAUSE**.")
            if discord_bot_instance:
                discord_bot_instance.send_notification(f"🔘 **{pause_key.upper()} button pressed**: Proceeding to **PAUSE** Bot", edit_category="system_log")
            
            engine.stop_engine()
            reconnect_watchdog.pause()
            if overlay: overlay.hide()
            settings.refresh_config_view()
            settings.show()
            settings.raise_()
            settings.activateWindow()

    def on_exit() -> None:
        nonlocal engine
        logger.info(f"[{stop_key}] Bot EXIT triggered. Stopping engine instantly...")
        if engine and engine.isRunning():
            engine.stop_engine()
        reconnect_watchdog.stop()
        
        if discord_bot_instance:
            discord_bot_instance.send_notification(f"🛑 **{stop_key.upper()} button pressed**: Proceeding to **STOP/EXIT** Bot", edit_category="system_log")
            if hasattr(discord_bot_instance, "send_reward_session_ended"):
                discord_bot_instance.send_reward_session_ended()
            
            # Phase 2702: Clear emergency messages on Stop
            if hasattr(discord_bot_instance, "clear_emergency_messages_sync"):
                discord_bot_instance.clear_emergency_messages_sync()
            elif hasattr(discord_bot_instance, "clear_emergency_messages"):
                discord_bot_instance.clear_emergency_messages()
                time.sleep(1.5)
            
        os.system(f"taskkill /f /pid {os.getpid()}")
        os._exit(0)

    # Register hotkeys immediately so they work throughout the app lifetime
    try:
        hotkey_signals.start_sig.connect(on_start)
        hotkey_signals.pause_sig.connect(on_pause)
        hotkey_signals.exit_sig.connect(on_exit)
        keyboard.add_hotkey(start_key, lambda: hotkey_signals.start_sig.emit())
        keyboard.add_hotkey(pause_key, lambda: hotkey_signals.pause_sig.emit())
        keyboard.add_hotkey(stop_key,  lambda: hotkey_signals.exit_sig.emit())
        logger.info(f"Hotkeys Registered: {start_key}=Start, {pause_key}=Pause, {stop_key}=Exit")
    except Exception as e:
        logger.error(f"Failed to register hotkeys. Root access may be required: {e}")

    def start_bot() -> None:
        nonlocal overlay, engine
        if engine: 
            # If the engine already exists
            if not engine.isRunning():
                config.reload()
                logger.info("Settings Saved. Bot remains STOPPED until toggled.")
                if overlay:
                    if config.get("bot", "show_overlay", True):
                        overlay.show()
                    else:
                        overlay.hide()
            return
            
        logger.info("Initializing Bot components (Settings confirmed)...")
        
        # Phase 2709: Automated AI Model Downloader
        import bot.download_model
        if not bot.download_model.ensure_model_exists():
            logger.critical("Failed to download AI Model! The bot cannot start.")
            return
        
        # Initialize components
        overlay = OverlayWindow()
        # Always show overlay window — show_overlay only gates boxes/labels inside paintEvent.
        # FOV circle and IPM trajectory line have their own independent toggles.
        overlay.show()

        engine = BotEngine(parent=app, watchdog=reconnect_watchdog)
        engine.detections_ready.connect(overlay.update_detections)
        
        # Phase 1520: Link the early-started Discord bot to the new brain
        if discord_bot_instance:
            discord_bot_instance.set_brain(engine._brain)
        
        # Phase 48B: Start the Auto-Reconnect Watchdog as a daemon thread
        reconnect_watchdog.resume()
        if not reconnect_watchdog._is_running:
            reconnect_watchdog.start()
        logger.info("[Main] Auto-Reconnect Watchdog active.")

        logger.info(f"Bot components ready. Press {start_key} to Start, {pause_key} to Pause.")

    def on_reload_scripts() -> None:
        """Phase 1001: Hot-Reload core modules without restart."""
        nonlocal engine, overlay
        logger.info("[Main] Reloading bot scripts...")
        
        # 1. Stop engine cleanly (destroy old instance completely to avoid Enum ghosting)
        if engine:
            if engine.isRunning():
                engine.stop_engine()
                # Wait for thread to finish cleanly
                engine.wait()
            engine = None
        
        try:
            import bot.config
            import bot.screen
            import bot.detector
            import bot.controller
            import bot.in_game_macro
            import bot.brain
            import bot.engine
            
            importlib.reload(bot.config)
            importlib.reload(bot.screen)
            importlib.reload(bot.detector)
            importlib.reload(bot.controller)
            importlib.reload(bot.in_game_macro)
            importlib.reload(bot.brain)
            importlib.reload(bot.engine)
            
            # Re-initialize the internal references
            from bot.engine import BotEngine
            global config
            from bot.config import config
            
            logger.info("[Main] Scripts reloaded successfully. Re-initializing engine...")
            
            # 3. Force rebuild engine on next 'Start'
            # (The start_bot function below will handle creating the new BotEngine instance)
            
        except Exception as e:
            logger.error(f"[Main] Hot-Reload FAILED: {e}")

    # Phase 1533: Connect settings signals to Discord Notifications
    settings.saved.connect(lambda: discord_bot_instance.send_notification("💾 **Settings saved** (GUI Button)", edit_category="system_log"))
    settings.reloaded.connect(lambda: discord_bot_instance.send_notification("♻️ **Reload script pressed**: Hot-Reloading modules...", edit_category="system_log"))
    settings.started.connect(lambda: discord_bot_instance.send_notification("📁 **Menu closed**: Settings applied & Saved", edit_category="system_log"))

    # Connect settings logic
    settings.started.connect(start_bot)
    settings.reloaded.connect(on_reload_scripts)
    # Phase 1534: Bind Discord bot callbacks to Main Thread UI Signals
    if discord_bot_instance:
        hotkey_signals.reload_sig.connect(on_reload_scripts)
        discord_bot_instance.pause_callback = lambda: hotkey_signals.pause_sig.emit()
        discord_bot_instance.reload_callback = lambda: hotkey_signals.reload_sig.emit()

    settings.show()

    # ── Qt event loop — blocks until app.quit() is called ───────────────────
    sys.exit(app.exec())

 
if __name__ == "__main__":
    main()
