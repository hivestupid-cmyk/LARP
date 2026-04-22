import logging
import time
import random
import threading
from enum import Enum, auto
from typing import List, Optional
from bot.detector import Detection
from bot.controller import Controller
from bot.config import config
from bot.in_game_macro import InGameMacro
from bot.ocr_utils import get_reward_ocr
from bot.discord_bot import DiscordBot

logger = logging.getLogger(__name__)

class BotState(Enum):
    MAIN_MENU = auto()
    LOADING = auto()           # Game transition screens
    CHAR_SELECT = auto()       # Character selection screen
    SELECTING_SETTINGS = auto()# Map/Objective/Difficulty setup
    LOBBY = auto()             # Post-creation lobby (Modifiers/Start)
    CUTSCENE = auto()
    IN_GAME = auto()
    DEAD = auto()
    DISCONNECTED = auto()      # Roblox disconnected screen
    RECOVERY = auto()          # Reconnecting/Restarting Roblox (Idle wait)

class BotBrain:
    """
    The "Persistence Mind" of the bot.
    Processes UI detections and manages match lifecycle (Lobby -> Play -> Restart).
    Combat is handled by external macros or user.
    """
    def __init__(self, controller: Controller, stop_flag: Optional[threading.Event] = None):
        self.controller = controller
        self.stop_flag = stop_flag
        self.state = BotState.MAIN_MENU
        
        # Timing & Throttling
        self.last_state_change = time.time()
        self.startup_time = time.time()
        self.last_ui_click: float = 0.0
        self.last_ui_seen: float = time.time()
        self.bot_speed = config.get("bot", "bot_speed", 1.0)
        self.ui_cooldown = 1.0 / self.bot_speed
        self.in_game_grace_period = 2.5 # Wait of nothing before In-Game        
        
        # Match/Lobby Persistence Flags
        self.objective_click_count = 0
        self.difficulty_click_count = 0
        self._phase_start_time = 0.0
        self._last_status_log = 0.0
        self._last_thinking_log = 0.0
        self._last_objective_seen_time = 0.0 # Phase 92: Objective memory
        self._first_lobby_indicator_time = 0.0 # Phase 93: Anti-hallucination
        self._first_setup_indicator_time = 0.0 # Phase 93: Anti-hallucination
        self._last_setup_indicator_time = 0.0  # Phase 108: Setup memory persistence
        self._first_dead_indicator_time = 0.0  # Phase 112: Secure DEAD state detection
        self._objective_menu_open_time = 0.0   # Phase 119: Temporal persistence for Objective Menu
        self.main_menu_click_count = 0        # Phase 121: Anti-loop for Main Menu
        
        # Non-blocking setup state
        self._last_deploy_action_time = 0.0
        self._deploy_settle_start_time = 0.0
        self._last_mod_menu_seen_time = 0.0 # Tracking persistence (flicker protection)
        self.session_start_clicked = False # Phase 116: Avoid START click spam
        self.last_start_click_time = 0.0
        self.waiting_for_loading = False # Phase 137: Retry -> Loading lock
        self._dead_action_cooldown = 0.0 # Phase 142: UI lock safety
        
        # Reactive Memory (Only for items that don't have visual persistent indicators)
        self.session_clicked_modifiers = set()
        self.session_modifiers_reset_done = False
        self.session_modifiers_scrolled = False
        self._cutscene_skip_done = False
        self._char_select_done = False
        self.session_objective_done = False
        self.difficulty_confirm_done = False
        self.session_deploy_step = 1
        self._main_play_done = False
        self._passed_transition_zone = False
        self.last_main_play_click = 0.0
        self._char_select_step = 1
        self._state_start_times = {}
        

        # Phase 2604: Stuck-State Watchdog
        self._stuck_watchdog_last_state = self.state   # State saat watchdog terakhir dicek
        self._stuck_watchdog_since = time.time()       # Kapan state sekarang dimulai
        self._stuck_watchdog_last_check = 0.0          # Throttle: jangan cek terlalu sering
        self._stuck_watchdog_triggered = False         # Guard: sudah trigger di state ini?
        # Phase 2605: IN_GAME timeout guard
        self._ingame_watchdog_triggered = False        # Guard: sudah trigger timeout IN_GAME ini?
        
        # Phase 130: In-Game Macro threading (Passed Controller for shared aiming logic)
        self.in_game_macro = InGameMacro(self.controller)
        
        # Session Stats (Discord Reporting)
        self.session_gold   = 0
        self.session_exp    = 0
        self.session_exp_bp = 0
        self.session_gems   = 0
        self.session_perks  = 0
        
        # Phase 1533: Last Mission Rewards (Discord !reward)
        self.last_gold   = 0
        self.last_exp    = 0
        self.last_exp_bp = 0
        self.last_gems   = 0
        self.last_perks  = 0
        
        self._latest_frame = None
        
        # Diagnostics
        self.eyes_only = config.get("bot", "eyes_only", False)
        
        # UI Priority (Labels used for state detection and interaction)
        self.UI_SCAN_CLASSES = {
            "annie", "nightmare_modifiers", "aberrant", "aberrant_difficulty", "annie_mark", 
            "back_button", "boring_modifiers", "character_stats", "checked_modifier", 
            "chronic_injuries_modifiers", "create_button", "cutscene_skip", "difficulty_title", 
            "dist_meter", "easy_difficulty", "fog_modifiers", "forest_title", "giant_forest_map", 
            "giant_forest_title", "glass_cannon_modifiers", "ground", "guard_objective", 
            "guard_objective_selected", "hard_difficulty", "injury_prone_modifiers", "leave_button", 
            "loading", "lobby_button_ui", "maps_objective_settings", "mission_button", 
            "mission_completed", "mission_failed", "modifier_button", "modifiers_button", 
            "next_difficulty_button", "no_perks_modifiers", "no_skills_modifiers", "no_talents_modifiers", 
            "normal_difficulty", "objective_button", "objective_ui", "oddball_modifiers", 
            "play_button_ui", "play_menu_utama_ui", "player", "previous_difficulty_button", 
            "retry_button", "select_char", "severe_difficulty", "simple_modifiers", "slot_a", 
            "slot_b", "slot_c", "start_button", "stats", "stats_title", "status_starting", 
            "thunder_spear", "time_trial_modifiers", "titan", "titan_mark", "trees", "uncheck_modifiers"
        }

        logger.info("[Brain] Initialized. Focusing on UI & Persistence. Eyes Only: %s", self.eyes_only)

    def process_tick(self, detections: List[Detection], distances: dict, frame = None):
        """
        Main logic entry point called every frame.
        """
        now = time.time()
        self._latest_frame = frame
        
        # Phase 2603: Live Detection Class Monitor (Global via process_tick)
        if now - getattr(self, "_last_det_log_discord", 0.0) >= 1.0:
            self._last_det_log_discord = now
            if hasattr(self, "discord_bot_instance") and self.discord_bot_instance:
                if detections:
                    label_counts: dict = {}
                    for d in detections:
                        lbl = d.label.lower().replace(" ", "_")
                        label_counts[lbl] = label_counts.get(lbl, 0) + 1
                    parts = []
                    for lbl, cnt in sorted(label_counts.items()):
                        parts.append(f"`{lbl}`({cnt})" if cnt > 1 else f"`{lbl}`")
                    det_str = ", ".join(parts)
                else:
                    det_str = "_none_"
                det_msg = f"👁️ **Current Detected Class:** {det_str}"
                self.discord_bot_instance.send_notification(det_msg, edit_category="detections")

        # 1. Update State based on UI Detections
        self._update_state(detections, frame)
        
        # 2. Robust UI/Game State Verification
        self.check_game_state(detections)

        # Phase 2604: Stuck-State Watchdog (cek tiap 10 detik, aktif jika non-IN_GAME)
        if now - getattr(self, "_stuck_watchdog_last_check", 0.0) >= 10.0:
            self._stuck_watchdog_last_check = now
            self._stuck_state_watchdog()

        # 3. Action Suppression for 'Eyes Only' mode
        if self.eyes_only:
            return

        # Phase 123: Physical Action Synchronization
        # If the physical controller is busy moving or clicking, PAUSE logic to avoid dropped clicks.
        if self.controller.is_busy:
            return
            

        # Phase 2411: Cross-State Cutscene Skip
        # Fire the cutscene handler immediately whenever the skip button is visible,
        # regardless of whether we are in LOADING or CUTSCENE state.
        # This eliminates the 0.2s persistence delay for LOADING -> CUTSCENE transition.
        if self.state not in [BotState.IN_GAME] and not getattr(self, "_cutscene_skip_done", False):
            if any(d.label.lower().replace(" ", "_") in ["cutscene_skip", "skip_button"] for d in detections):
                self._handle_cutscene(detections)
                return

        # 4. Execute        # Phase 125: Handle States
        if self.state == BotState.MAIN_MENU:
            self._handle_main_menu(detections)
        elif self.state == BotState.CHAR_SELECT:
            self._handle_char_select(detections)
        elif self.state == BotState.SELECTING_SETTINGS:
            self._handle_selecting_settings(detections)
        elif self.state == BotState.LOBBY:
            self._handle_lobby(detections)
        elif self.state == BotState.DEAD:
            self._handle_dead(detections)
        elif self.state == BotState.IN_GAME:
            self._handle_in_game(detections, distances)
        elif self.state == BotState.LOADING:
            self._handle_loading(detections)
        elif self.state == BotState.CUTSCENE:
            self._handle_cutscene(detections)
        elif self.state == BotState.DISCONNECTED:
            self._handle_disconnected()
        elif self.state == BotState.RECOVERY:
            self._handle_recovery()

    def _update_state(self, detections: List[Detection], frame=None):
        now = time.time()
        labels = [d.label.lower().replace(" ", "_") for d in detections]
        
        # Filter out gameplay objects to accurately determine if UI is visible
        NON_UI_LABELS = {"annie", "annie_mark", "titan", "titan_mark", "player", "trees", "thunder_spear", "ground", "dist_meter"}
        ui_labels = [l for l in labels if l not in NON_UI_LABELS]
        
        # Phase 61: Periodic status log
        if now - getattr(self, "_last_status_log", 0) > 5.0:
            self._last_status_log = now
            visible = ", ".join(ui_labels) if ui_labels else "NONE"
            if not ui_labels and any(l in NON_UI_LABELS for l in labels):
                visible = "[GAMEPLAY OBJECTS ONLY]"
            logger.info("[Brain] Thinking... State: %s | Visible UI: [%s]", self.state.name, visible)

        # Persistence Candidates
        candidate_state = None
        in_transition = (now - self.last_ui_click < 1.0) # Reduced to 1s to be snappy

        settings_indicators = ["create_button", "difficulty_title", 
                               "giant_forest_map", "map_selection", "objective_button", "objective_ui", 
                               "selecting_objective", "guard_objective_selected", "guard_objective", 
                               "back_button", "next_difficulty_button"]

        # 1. Determine Candidate State
        # strong_lobby: any modifier UI OR post-Create lobby indicators
        _strong_lobby_labels = {
            "modifiers_button", "modifier_button", "checked_modifier",
            "uncheck_modifiers", "leave_button", "start_button", "status_starting",
        }
        _weak_lobby_labels = {"giant_forest_title", "aberrant"}
        _has_strong_lobby = any(l.endswith("_modifiers") or l in _strong_lobby_labels for l in labels)
        # Weak labels only count if accompanied by a real anchor (leave/start)
        _has_anchor = any(l in {"leave_button", "start_button"} for l in labels)
        _has_weak_lobby = _has_anchor and any(l in _weak_lobby_labels for l in labels)
        strong_lobby = _has_strong_lobby or _has_weak_lobby
        
        # Phase 2145 (v2): Dedicated DISCONNECTED state
        # Triggered INSTANTLY by specific disconnect UI — no timer needed
        disconnect_labels = {"reconnect_button", "leave_disconnected", "disconnect_popup"}
        if any(l in disconnect_labels for l in labels):
            if self.state != BotState.DISCONNECTED:
                logger.critical("[Brain] DISCONNECT UI DETECTED! Switching to DISCONNECTED state.")
                self.disconnect_reason = "UI Popup Detected"
                self._change_state(BotState.DISCONNECTED)
            return  # Don't evaluate anything else this frame
        
        if "loading" in labels:
            candidate_state = BotState.LOADING
        elif ("cutscene_skip" in labels or "skip_button" in labels) and not getattr(self, "_cutscene_skip_done", False):
            candidate_state = BotState.CUTSCENE
        elif any(l in ["mission_failed", "mission_completed", "stats_title", "stats", "retry_button"] for l in labels):
            candidate_state = BotState.DEAD
            
            # Phase 1507: Real-Time OCR Reward Detection
            # Triggers on BOTH mission_completed and mission_failed:
            # rewards are based on titan kills regardless of mission outcome.
            mission_outcome = None
            if "mission_completed" in labels:
                mission_outcome = "completed"
            elif "mission_failed" in labels:
                mission_outcome = "failed"

            if mission_outcome and not getattr(self, "_results_stat_counted", False):
                # Guard: minimum 60s between reward sends — prevents double fire from
                # hallucination flickers (dead → in_game → dead within a second)
                now_t = time.time()
                if now_t - getattr(self, "_last_reward_sent_t", 0.0) < 60.0:
                    logger.warning("[Brain] Reward OCR skipped — too soon after last reward (hallucination state flicker).")
                    self._results_stat_counted = True  # Lock to prevent further attempts this session
                else:
                    logger.info(f"[Brain] Mission {mission_outcome} — attempting OCR for rewards...")
                    self._results_stat_counted = True
                    self._last_reward_sent_t = now_t
                    try:
                        ocr = get_reward_ocr()
                        ocr.reset_buffer()  # Fresh buffer each mission
                        # Returns (exp, gold, exp_bp, gems, perks)
                        e, g, ebp, gem, perks = ocr.extract_rewards(frame)

                        if g > 0 or e > 0 or ebp > 0 or gem > 0 or perks > 0:
                            # Accumulate session totals
                            self.session_gold   += g
                            self.session_exp    += e
                            self.session_exp_bp += ebp
                            self.session_gems   += gem
                            self.session_perks  += perks

                            # Store as 'Last Mission' snapshot
                            self.last_gold   = g
                            self.last_exp    = e
                            self.last_exp_bp = ebp
                            self.last_gems   = gem
                            self.last_perks  = perks

                            logger.info(
                                f"[Brain] OCR Success: +{e} Exp, +{g} Gold, +{ebp} ExpBP, "
                                f"+{gem} Gems, +{perks} Perks | "
                                f"Session → Exp:{self.session_exp}, G:{self.session_gold}, "
                                f"EP:{self.session_exp_bp}, Gem:{self.session_gems}, P:{self.session_perks}"
                            )

                            # Notify Discord
                            if hasattr(self, "discord_bot_instance") and self.discord_bot_instance:
                                icon       = "🏆" if mission_outcome == "completed" else "💀"
                                status_txt = "Mission Completed!" if mission_outcome == "completed" \
                                             else "Mission Failed (partial reward)"
                                msg = (
                                    f"{icon} **{status_txt}**\n"
                                    f"💰 Gold: `+{g:,}` (Total: `{self.session_gold:,}`)\n"
                                    f"⭐ Exp: `+{e:,}` (Total: `{self.session_exp:,}`)\n"
                                    f"📘 Exp BP: `+{ebp:,}` (Total: `{self.session_exp_bp:,}`)\n"
                                    f"💎 Gems: `+{gem:,}` (Total: `{self.session_gems:,}`)\n"
                                    f"🎖️ Perks: `+{perks}` (Total: `{self.session_perks}`)"
                                )
                                if hasattr(self.discord_bot_instance, "send_notification_with_image") and frame is not None:
                                    try:
                                        from bot.ocr_utils import crop_region
                                        regions = config.get("reward_regions", {}) or {}
                                        box = regions.get("reward_box", [847, 807, 912, 119])
                                        reward_crop = crop_region(frame, box)
                                        self.discord_bot_instance.send_notification_with_image(msg, reward_crop)
                                    except Exception as e:
                                        # Crop gagal — kirim dengan frame penuh (JANGAN double-call)
                                        logger.warning(f"[Discord] Crop reward box failed, sending full frame: {e}")
                                        self.discord_bot_instance.send_notification_with_image(msg, frame)
                                else:
                                    self.discord_bot_instance.send_notification(msg)
                        else:
                            # Zero = 0 titan kills (valid), not an OCR failure
                            logger.info("[Brain] OCR all zeros — likely 0 titan kills. No reward recorded.")

                    except Exception as ex:
                        logger.error(f"[Brain] Reward OCR failed: {ex}")
        elif strong_lobby:
            candidate_state = BotState.LOBBY
        elif any(l in ["character_stats", "select_char", "slot_c", "slot_b", "slot_a", "play_button_ui", "lobby_button_ui"] for l in labels):
            # play_button_ui = post char-select Play button; lobby_button_ui = server select button
            candidate_state = BotState.CHAR_SELECT
        elif any(l in settings_indicators for l in labels):
            candidate_state = BotState.SELECTING_SETTINGS
        elif any(l in ["aberrant", "severe", "hard", "normal", "easy"] for l in labels):
            # Weak lobby check (only if no deploy seen)
            candidate_state = BotState.LOBBY
        elif any(l in ["play_menu_utama_ui", "mission_button"] for l in labels):
            # play_menu_utama_ui = real Main Menu button; mission_button = mission list
            candidate_state = BotState.MAIN_MENU

        # 2. Persistence Logic (Phase 1897: Robust Transition Memory)
        persistence = config.get("state_persistence", 1.0)
        
        # Reactive Overrides: Jump out of LOADING or into CUTSCENE/IN_GAME faster
        if self.state == BotState.LOADING or candidate_state in [BotState.CUTSCENE, BotState.IN_GAME]:
            persistence = 0.2
        
        # Phase 2151: Anti-hallucination for all classes outside IN_GAME
        # If UI other than game objects appears during combat, it must be stable for 4 seconds
        if self.state == BotState.IN_GAME and candidate_state is not None:
            persistence = 4.0
        
        if candidate_state is not None and candidate_state != self.state:
            # New candidate or continuing candidate?
            if candidate_state == getattr(self, "_candidate_state", None):
                # Continuing: Check if held long enough
                if now - getattr(self, "_candidate_state_start", 0) > persistence:
                    short_labels = labels[:5]
                    logger.info(f"[Brain] UI: {short_labels} stable. Changing State: {self.state.name} -> {candidate_state.name} ({persistence}s)")
                    self._change_state(candidate_state)
                    self._candidate_state = None
                    self._candidate_state_start = 0
            else:
                # New candidate: Start timer
                self._candidate_state = candidate_state
                self._candidate_state_start = now
        elif candidate_state is None:
            # Phase 1897: Silence during transition. KEEP the current candidate timer running (don't reset).
            pass 
        else:
            # candidate_state == self.state: No change needed, clear trackers
            self._candidate_state = None
            self._candidate_state_start = 0

        # 3. Post-Transition Overrides (Immediate releases)
        if self.waiting_for_loading and candidate_state in [BotState.LOADING, BotState.CUTSCENE]:
             self.waiting_for_loading = False 
             logger.info("[Brain] Prison Release: Transition seen.")

        # Phase 1501: Removed auto-bridge. Let _update_state handle candidate detection.

        # Phase 2500: Explicit Cutscene Skip Timer (Fast-path)
        # If we clicked skip, wait exactly 1.5s for the fade-out, then FORCE In-Game.
        if getattr(self, "_cutscene_skip_done", False) and self.state != BotState.IN_GAME:
            if now - self.last_ui_click > 1.5:
                if getattr(self, "_can_enter_ingame", False):
                    logger.info("[Brain] Cutscene skip fade-out completed (1.5s). Forcing IN_GAME.")
                    self._change_state(BotState.IN_GAME)
                else:
                    logger.warning("[Brain] Cutscene skipped, but ignoring IN_GAME transition because it hasn't passed LOADING/DISCONNECT state.")
                self._cutscene_skip_done = False  # Reset flag

        # Phase 1502: Implicit In-Game logic (Once everything is gone)
        # NEW RULE (Strict IN_GAME Gating):
        # Transition to IN_GAME is strictly forbidden UNLESS cutscene_skip button has been pressed (Phase 2500)
        # if candidate_state is None and not ui_labels and self.state not in [BotState.MAIN_MENU, BotState.IN_GAME]:
             # Standard Fallback: Wait 4.0s of complete UI silence to drop into game
             # if (now - self.last_ui_seen > 4.0) and getattr(self, "_passed_transition_zone", False):
             #    logger.info(f"[Brain] UI Cleared & Transition Zone passed (4.0s Silence). Entering IN_GAME.")
             #    self._change_state(BotState.IN_GAME)
        
        if ui_labels:
             self.last_ui_seen = now

    def _change_state(self, new_state: BotState):
        if self.state != new_state:
            logger.info("[Brain] State Change: %s -> %s", self.state.name, new_state.name)
            
            # Phase 2707: Dynamic Window Resizing (Save Resources)
            try:
                import ctypes
                hwnd = ctypes.windll.user32.FindWindowW(None, "Roblox")
                if hwnd:
                    if new_state == BotState.IN_GAME:
                        logger.info("[Brain] Entering IN_GAME: Ensuring Roblox Window is Maximized to maintain AI Model accuracy.")
                        ctypes.windll.user32.ShowWindow(hwnd, 3) # SW_MAXIMIZE
                    elif self.state == BotState.IN_GAME:
                        logger.info("[Brain] Exiting IN_GAME: Window remains intact.")
            except Exception as e:
                logger.error(f"[Brain] Failed to resize window: {e}")
            
            # Notify Discord on State Change
            if hasattr(self, "discord_bot_instance") and self.discord_bot_instance:
                if new_state == BotState.DISCONNECTED:
                    admin_id = self.discord_bot_instance.admin_id
                    ping = f"<@{admin_id}>" if admin_id else ""
                    reason_msg = getattr(self, "disconnect_reason", "Unknown Code")
                    if hasattr(self.discord_bot_instance, "send_emergency_notification"):
                        self.discord_bot_instance.send_emergency_notification(f"🔌 {ping} **CRITICAL WARNING: ROBLOX DISCONNECTED!**\n**Reason:** `{reason_msg}`")
                    else:
                        self.discord_bot_instance.send_notification(f"🔌 {ping} **CRITICAL WARNING: ROBLOX DISCONNECTED!**\n**Reason:** `{reason_msg}`")
                else:
                    self.discord_bot_instance.send_notification(f"🔄 **Current Bot State:** `{new_state.name}`", edit_category="state")
            
            if new_state in [BotState.LOADING, BotState.SELECTING_SETTINGS, BotState.CUTSCENE]:
                self._passed_transition_zone = True
                logger.debug("[Brain] Transition Zone Activated.")
                
            # Gate logic for exclusive IN_GAME progression
            if new_state in [BotState.LOADING, BotState.DISCONNECTED, BotState.MAIN_MENU, BotState.RECOVERY]:
                self._can_enter_ingame = True

            # Phase 130: Automatically handle in-game macro state
            if new_state == BotState.IN_GAME:
                self._can_enter_ingame = False
                self.in_game_macro.start()
                self._in_game_start_time = time.time()  # Dedicated stopwatch anchor
            elif self.state == BotState.IN_GAME:
                self.in_game_macro.stop()
                self._in_game_start_time = 0.0  # Reset when leaving IN_GAME
            
            # Reset flags for fresh match setup
            if new_state in [BotState.MAIN_MENU, BotState.CHAR_SELECT, BotState.DEAD, BotState.RECOVERY]:
                self.reset_session_flags(reason=f"{new_state.name}_ENTRY")
                self._cutscene_skip_done = False
                logger.info(f"[Brain] Session flags reset for {new_state.name} entry.")
            elif new_state == BotState.SELECTING_SETTINGS and self.session_deploy_step == 1:
                self.reset_session_flags(reason="SELECTING_SETTINGS_COLD_ENTRY")
                logger.info("[Brain] Session flags reset for fresh SETTINGS entry.")

            self.state = new_state
            self.last_state_change = time.time()
            self._lobby_stuck_reset_done = False
            
            # Phase 2604: Reset stuck-watchdog setiap state change
            self._stuck_watchdog_since = time.time()
            self._stuck_watchdog_triggered = False
            self._stuck_watchdog_last_state = new_state
            # Phase 2605: Reset IN_GAME timeout guard saat keluar dari IN_GAME
            if self.state == BotState.IN_GAME:
                self._ingame_watchdog_triggered = False

    def reset_session_flags(self, reason="General", preserve_modifiers=False,
                            preserve_ocr_count=False):
        """
        Resets all flags used for match setup navigation.

        Args:
            preserve_ocr_count: When True, keeps _results_stat_counted=True so
                                OCR does NOT re-fire after a retry click while
                                still on the same result screen.
        """
        logger.debug(f"[Brain] Flag Reset Triggered: {reason}")
        self.session_deploy_step = 1
        self.objective_click_count = 0
        self.difficulty_click_count = 0
        self._last_objective_seen_time = 0.0
        self._first_lobby_indicator_time = 0.0
        self._first_setup_indicator_time = 0.0  # Phase 801
        
        if not preserve_modifiers:
            self.session_clicked_modifiers = set()
            
        self.session_modifiers_reset_done = False
        self.session_modifiers_scrolled = False
        self._cutscene_skip_done = False
        self._main_play_done = False
        self._mission_click_count = 0
        self.session_modifiers_exit_clicked = False
        self.session_start_clicked = False
        self._passed_transition_zone = False  # Gate Reset

        # Only reset OCR flag when truly starting a new match.
        # preserve_ocr_count=True prevents double-counting on retry clicks.
        if not preserve_ocr_count:
            self._results_stat_counted = False
        
        # Phase 501: Clear Macro Memory on session reset
        self.in_game_macro.reset_memory()
        
        # Phase 1533: Reset 'Last Mission' rewards when starting new run
        self.last_gold = 0
        self.last_exp = 0
        self.last_gems = 0
        
        # Phase 2160: Reset Character Selection sequence
        self._char_select_step = 1

    def _handle_in_game(self, detections: List[Detection], distances: tuple[float, float]):
        """
        Passive waiting state. The bot does nothing during the match
        except pass the real-time AI vision over to the Python macro
        to allow for Auto-Aim and tracking.
        """
        # Phase 131: Feed vision to the macro thread
        self.in_game_macro.update_detections(detections, distances)
        
        # Phase 1699a: Stopwatch State Update (1s interval, zero OCR overhead)
        now = time.time()
        if now - getattr(self, "_last_state_timer_update", 0.0) >= 1.0:
            self._last_state_timer_update = now
            if hasattr(self, "discord_bot_instance") and self.discord_bot_instance:
                start_t = getattr(self, "_in_game_start_time", 0.0)
                elapsed = int(now - start_t) if start_t > 0 else 0
                mins, secs = divmod(elapsed, 60)
                timer_str = f"{mins:02d}:{secs:02d}"
                state_msg = f"🔄 **Current Bot State:** `IN_GAME` ⏱️ `[{timer_str}]`"
                self.discord_bot_instance.send_notification(state_msg, edit_category="state")
        
        # Phase 1699b: Live Ronde Tracker (1s interval - includes OCR + image)
        if now - getattr(self, "_last_ronde_update", 0.0) >= 1.0:
            self._last_ronde_update = now
            
            if getattr(self, "_latest_frame", None) is not None:
                frame = self._latest_frame
                # Use actual dynamic dimensions of the frame (handles dynamic window resizing perfectly)
                screen_w = frame.shape[1]
                screen_h = frame.shape[0]
                
                # Scale coordinates down from original reference 1920x1080
                scale_x = screen_w / 1920.0
                scale_y = screen_h / 1080.0
                
                # User's target roi: x=1, y=130, w=288, h=192
                cx = max(0, int(1 * scale_x))
                cy = max(0, int(130 * scale_y))
                cw = min(screen_w - cx, int(288 * scale_x))
                ch = min(screen_h - cy, int(192 * scale_y))
                
                if cy+ch <= frame.shape[0] and cx+cw <= frame.shape[1]:
                    ronde_crop = frame[cy:cy+ch, cx:cx+cw]
                    
                    if hasattr(self, "discord_bot_instance") and self.discord_bot_instance:
                        msg = "⏱️ **Live Ronde Info** *(Screenshot Crop)*"
                        self.discord_bot_instance.send_notification(msg, edit_category="ronde", frame=ronde_crop)
        
        # Phase 1942: Extract Annie detection for Aim Assist
        # Prioritize 'annie_mark' since it is consistently visible UI, reducing aimbot jitter/delay
        annie_det = next((d for d in detections if d.label.lower().replace(" ", "_") == "annie_mark"), None)
        if not annie_det:
            annie_det = next((d for d in detections if d.label.lower().replace(" ", "_") == "annie"), None)
        if annie_det:
            self.in_game_macro.update_annie_target(annie_det)
        else:
            # Phase 2420: Dead Reckoning (Inertial Tracking)
            # Annie not visible this frame — don't reset, instead extrapolate position
            # by running a pure Kalman predict step using last known velocity.
            macro = self.in_game_macro
            macro._annie_first_seen_t = 0.0  # Reset persistence (need fresh detect to re-lock)
            
            if macro.kalman is not None and macro._lkp_t > 0:
                from bot.config import config
                memory_dur = config.get("combat_engine", "aim_memory_duration", 4.0)
                dead_reckoning_enabled = config.get("aim_assist", "dead_reckoning_enabled", True)
                lkp_age = time.perf_counter() - macro._lkp_t
                
                if dead_reckoning_enabled and lkp_age < memory_dur:
                    # Dead reckoning: extrapolate using velocity from last known state
                    dt = time.perf_counter() - macro._last_annie_t
                    dt = max(dt, 1e-4)
                    pred_x, pred_y, vx, vy = macro.kalman.predict_and_advance(dt)
                    macro._annie_velocity = (float(vx), float(vy))
                    macro._annie_centroid = (int(pred_x), int(pred_y))
                else:
                    # Dead Reckoning OFF or memory expired — stop aiming immediately
                    macro._annie_centroid = None
            else:
                macro._annie_centroid = None

    def _stuck_state_watchdog(self):
        """
        Phase 2604 + 2605: Stuck-State & In-Game Timeout Watchdog.

        IN_GAME (Phase 2605):
          - If IN_GAME > 4 minutes (240s) → game stuck → force-restart Roblox.
          - No need to scan log (normal game max ~3 mins).

        Other states (Phase 2604, excluding DISCONNECTED):
          - If stuck > 60 seconds:
            1. Scan Roblox log for disconnect.
            2. If log is clean -> force-restart Roblox.

        All emergency messages tag Discord admin for immediate notification.
        """
        INGAME_TIMEOUT  = 240.0   # 4 minutes — game is stuck if longer than this
        STUCK_THRESHOLD = 60.0    # 60 detik untuk state non-IN_GAME
        now = time.time()

        # ── Helper: Ambil admin ping sekali di awal ────────────────────────────
        ping = ""
        if hasattr(self, "discord_bot_instance") and self.discord_bot_instance:
            admin_id = getattr(self.discord_bot_instance, "admin_id", "")
            if admin_id:
                ping = f"<@{admin_id}> "

        # ── Phase 2605 + 2608: IN_GAME Timeout & Periodic Log Scan ───────────
        if self.state == BotState.IN_GAME:
            ingame_dur = now - getattr(self, "_in_game_start_time", now)

            # Phase 2608: Scan log every 2 seconds during IN_GAME to detect
            # Error 279 (and other errors) in real-time without waiting 4 mins.
            # Only reading text file - no effect on gameplay.
            LOG_SCAN_INTERVAL = 2.0
            last_scan = getattr(self, "_ingame_log_scan_at", 0.0)
            if now - last_scan >= LOG_SCAN_INTERVAL:
                self._ingame_log_scan_at = now
                try:
                    from bot.reconnect import _global_watchdog
                    if _global_watchdog:
                        disc_reason = _global_watchdog.check_log_for_disconnect(
                            lookback_seconds=300.0  # Naikkan dari 60s ke 300s untuk tangkap error lebih luas
                        )
                        if disc_reason:
                            logger.warning(
                                "[StuckWatchdog] IN_GAME log scan: disconnect '%s'. Reconnecting immediately.",
                                disc_reason
                            )
                            if hasattr(self, "discord_bot_instance") and self.discord_bot_instance:
                                self.discord_bot_instance.send_notification(
                                    f"\U0001f534 {ping}**Error Detected!** "
                                    f"`{disc_reason}` found during IN_GAME. "
                                    f"Auto-reconnecting..."
                                )
                            self.notify_disconnected(reason=f"IN_GAME log scan: {disc_reason}")
                            return
                except Exception as e:
                    logger.debug("[StuckWatchdog] IN_GAME log scan error: %s", e)

            if ingame_dur >= INGAME_TIMEOUT:
                if not getattr(self, "_ingame_watchdog_triggered", False):
                    self._ingame_watchdog_triggered = True
                    logger.critical(
                        "[StuckWatchdog] IN_GAME timeout! %.0f seconds (>%.0fs). Force-restart Roblox.",
                        ingame_dur, INGAME_TIMEOUT
                    )
                    if hasattr(self, "discord_bot_instance") and self.discord_bot_instance:
                        mins = int(ingame_dur) // 60
                        secs = int(ingame_dur) % 60
                        if hasattr(self.discord_bot_instance, "send_emergency_notification"):
                            self.discord_bot_instance.send_emergency_notification(
                                f"\u23f0 {ping}**IN_GAME Timeout!** Game has been running for `{mins}m {secs}s` "
                                f"(limit: 4 mins). Game stuck \u2014 Force-restart Roblox..."
                            )
                        else:
                            self.discord_bot_instance.send_notification(
                                f"\u23f0 {ping}**IN_GAME Timeout!** Game has been running for `{mins}m {secs}s` "
                                f"(limit: 4 mins). Game stuck \u2014 Force-restart Roblox..."
                            )
                    try:
                        from bot.reconnect import _global_watchdog
                        if _global_watchdog:
                            _global_watchdog._reconnect(
                                reason=f"IN_GAME timeout ({int(ingame_dur)}s > {int(INGAME_TIMEOUT)}s)"
                            )
                        else:
                            import subprocess
                            logger.warning("[StuckWatchdog] Watchdog N/A. Fallback taskkill.")
                            subprocess.run(
                                ["taskkill", "/F", "/IM", "RobloxPlayerBeta.exe", "/T"],
                                capture_output=True, check=False
                            )
                    except Exception as e:
                        logger.error("[StuckWatchdog] IN_GAME force-restart error: %s", e)
            else:
                # Belum timeout, reset guard agar bisa trigger kalau nanti kembali ke IN_GAME
                self._ingame_watchdog_triggered = False
            # Jangan proses logika non-IN_GAME di bawah
            self._stuck_watchdog_since = now
            self._stuck_watchdog_triggered = False
            return

        # ── Kecualikan DISCONNECTED ────────────────────────────────────────────
        if self.state == BotState.DISCONNECTED:
            self._stuck_watchdog_since = now
            self._stuck_watchdog_triggered = False
            return
            
        # ── Timer khusus RECOVERY ────────────────────────────────────────────
        if self.state == BotState.RECOVERY:
            stuck_dur = now - self._stuck_watchdog_since
            # Allow up to 120 seconds for Roblox booting
            if stuck_dur > 120.0 and not getattr(self, "_stuck_watchdog_triggered", False):
                self._stuck_watchdog_triggered = True
                logger.critical("[StuckWatchdog] Roblox startup failed in RECOVERY (120s). Force restarting...")
                try:
                    from bot.reconnect import _global_watchdog
                    if _global_watchdog:
                        _global_watchdog._reconnect(reason="RECOVERY Stuck Drop")
                except Exception as e:
                    logger.error(e)
            return

        # ── Phase 2604: Non-IN_GAME Stuck Check ───────────────────────────────
        stuck_dur = now - self._stuck_watchdog_since

        if stuck_dur < STUCK_THRESHOLD:
            return

        if getattr(self, "_stuck_watchdog_triggered", False):
            return

        # ── STUCK TERDETEKSI ──────────────────────────────────────────────────
        logger.critical(
            "[StuckWatchdog] State '%s' stuck %.0fs! Memulai recovery...",
            self.state.name, stuck_dur
        )
        if hasattr(self, "discord_bot_instance") and self.discord_bot_instance:
            if hasattr(self.discord_bot_instance, "send_emergency_notification"):
                self.discord_bot_instance.send_emergency_notification(
                    f"\u26a0\ufe0f {ping}**STUCK STATE!** State `{self.state.name}` has been "
                    f"`{int(stuck_dur)}s` without changes. Recovery starting..."
                )
            else:
                self.discord_bot_instance.send_notification(
                    f"\u26a0\ufe0f {ping}**STUCK STATE!** State `{self.state.name}` has been "
                    f"`{int(stuck_dur)}s` without changes. Recovery starting..."
                )

        self._stuck_watchdog_triggered = True

        # ── Langkah 1: Cek log Roblox untuk disconnect ────────────────────────
        try:
            from bot.reconnect import _global_watchdog
            if _global_watchdog:
                disc_reason = _global_watchdog.check_log_for_disconnect(lookback_seconds=600)
                if disc_reason:
                    logger.warning(
                        "[StuckWatchdog] Disconnect found in log: '%s'. notify_disconnected().",
                        disc_reason
                    )
                    if hasattr(self, "discord_bot_instance") and self.discord_bot_instance:
                        if hasattr(self.discord_bot_instance, "send_emergency_notification"):
                            self.discord_bot_instance.send_emergency_notification(
                                f"\U0001f50d {ping}**Log scan**: Disconnect found (`{disc_reason}`). "
                                f"Auto-reconnecting..."
                            )
                        else:
                            self.discord_bot_instance.send_notification(
                                f"\U0001f50d {ping}**Log scan**: Disconnect found (`{disc_reason}`). "
                                f"Auto-reconnecting..."
                            )
                    self.notify_disconnected(reason=f"StuckWatchdog: {disc_reason}")
                    return
        except Exception as e:
            logger.error("[StuckWatchdog] Error scan log: %s", e)

        # ── Langkah 2: Log bersih tapi stuck → force-restart Roblox ──────────
        logger.critical(
            "[StuckWatchdog] Clean log. Force-restart Roblox (state: %s, stuck: %ds).",
            self.state.name, int(stuck_dur)
        )
        if hasattr(self, "discord_bot_instance") and self.discord_bot_instance:
            if hasattr(self.discord_bot_instance, "send_emergency_notification"):
                self.discord_bot_instance.send_emergency_notification(
                    f"\U0001f534 {ping}**Clean log but stuck!** "
                    f"Force-restart Roblox (endtask + relaunch)..."
                )
            else:
                self.discord_bot_instance.send_notification(
                    f"\U0001f534 {ping}**Clean log but stuck!** "
                    f"Force-restart Roblox (endtask + relaunch)..."
                )
        try:
            from bot.reconnect import _global_watchdog
            if _global_watchdog:
                _global_watchdog._reconnect(
                    reason=f"StuckWatchdog force-restart ({self.state.name} {int(stuck_dur)}s)"
                )
            else:
                import subprocess
                logger.warning("[StuckWatchdog] Watchdog N/A. Fallback taskkill.")
                subprocess.run(
                    ["taskkill", "/F", "/IM", "RobloxPlayerBeta.exe", "/T"],
                    capture_output=True, check=False
                )
        except Exception as e:
            logger.error("[StuckWatchdog] Force-restart error: %s", e)

    def _handle_loading(self, detections: List[Detection]):
        """Resting state during game transitions."""
        if time.time() - getattr(self, "_last_status_log", 0) > 10.0:
            self._last_status_log = time.time()
            logger.info("[Loading] AI is resting during loading screen...")
        pass

    def _handle_recovery(self):
        """Idle state where the bot waits passively after triggering a Roblox restart."""
        if time.time() - getattr(self, "_last_status_log", 0) > 10.0:
            self._last_status_log = time.time()
            logger.info("[Recovery] AI is waiting for Roblox to finish restarting and UI to appear...")
        pass

    def _handle_disconnected(self):
        """Handler for the DISCONNECTED state — triggers auto-reconnect."""
        now = time.time()
        cooldown = 30.0
        last_attempt = getattr(self, "_last_reconnect_attempt", 0.0)
        if now - last_attempt < cooldown:
            return

        logger.critical("[Brain] DISCONNECTED state active. Attempting auto-reconnect...")
        self._last_reconnect_attempt = now
        try:
            from bot.reconnect import _global_watchdog
            if _global_watchdog:
                _global_watchdog._reconnect(reason="Disconnected State (UI/Log)")
            else:
                logger.error("[Brain] Reconnect watchdog not available!")
        except Exception as e:
            logger.error(f"[Brain] Reconnect call failed: {e}")

    def notify_disconnected(self, reason: str = "Log Watchdog"):
        """Public method: allows reconnect.py to signal a disconnect to the brain."""
        if self.state != BotState.DISCONNECTED:
            logger.critical(f"[Brain] notify_disconnected() called by '{reason}'. Switching state.")
            self.disconnect_reason = reason
            self._change_state(BotState.DISCONNECTED)


    def check_game_state(self, detections: List[Detection]):
        """Robust UI detection for edge cases."""
        # This method can be used for secondary verifications if needed.
        # Global state overrides have been moved to _update_state for better priority management.
        pass


    def _handle_dead(self, detections: List[Detection]):
        """Wait for Results UI and click Retry or Lobby."""
        def _do_retry_click(tx, ty):
            import pydirectinput
            try:
                pydirectinput.press('win')
                time.sleep(0.05)
                pydirectinput.press('win')
                time.sleep(0.15)
            except Exception as e:
                logger.error(f"[DEAD] Failed to press win key: {e}")
            self.controller.click_at(tx, ty)

        if time.time() - self.last_state_change < 2.0:
            return
            
        if time.time() - self.last_ui_click < self.ui_cooldown:
            return

        # Phase 137: "Prison" mode: Wait for loading after retry
        if self.waiting_for_loading:
            # Phase 142: Safety Switch. If 5 seconds pass without Loading/Cutscene, break prison.
            if time.time() > getattr(self, "_dead_action_cooldown", 0.0):
                logger.warning("[DEAD] Safety Switch: Loading not seen for 5s. Re-enabling buttons.")
                self.waiting_for_loading = False
            else:
                return

        # Phase 129: Wait after a retry click to respect game countdown
        if time.time() < getattr(self, "_dead_action_cooldown", 0.0):
            return

        # Phase 141: Absolute Focus on Retry
        retry_target = next((d for d in detections if d.label.lower().replace(" ", "_") == "retry_button"), None)
        
        # Phase 601: Compound UI Detection
        labels = [d.label.lower() for d in detections]
        has_compound = all(any(x in l for l in labels) for x in ["class", "modifier button", "leave button"])
        
        if retry_target or has_compound:
            coords = config.get("coordinates", {})
            if retry_target:
                logger.info("[DEAD] AI Detected retry_button, focusing ONLY on this.")
                rx, ry = coords.get("retry_game", [1543, 1103])
                self.controller.scroll(-1000)
                time.sleep(0.05)
                _do_retry_click(rx, ry)
            else:
                logger.info("[DEAD] Compound UI detected. Re-trying match.")
                coords = config.get("coordinates", {})
                rx, ry = coords.get("retry_game", [1543, 1103])
                self.controller.scroll(-1000)
                time.sleep(0.05)
                _do_retry_click(rx, ry)

            self.last_ui_click = time.time()
            self.waiting_for_loading = True
            self._dead_action_cooldown = time.time() + 5.0
            
            # Phase 801: Reset logic on Retry click.
            # preserve_ocr_count=True → keeps _results_stat_counted=True so OCR
            # does not re-fire whilst still on the same result screen.
            self.reset_session_flags(preserve_ocr_count=True)
            self.in_game_macro.reset_memory()
            return

        # Phase 1495: Restrict to Retry button ONLY
        target_btns = ["retry_button"]
        for btn_label in target_btns:
            target = next((d for d in detections if d.label.lower().replace(" ", "_") == btn_label), None)
            if target:
                logger.info("[DEAD] AI Detected %s, proceeding.", btn_label)
                self.controller.scroll(-1000)
                time.sleep(0.05)
                _do_retry_click(target.x_screen, target.y_screen)
                self.last_ui_click = time.time()
                return

        # Phase 1530: Stalled State Fallback
        # If we've been in DEAD state for too long (>3s) without action, blind-click the center
        # V1.2: Only trigger fallback AFTER OCR has finished (or if it's been >10s)
        time_since_dead = time.time() - self.last_state_change
        if time_since_dead > 3.0:
            ocr_done = getattr(self, "_results_stat_counted", False)
            if not ocr_done and time_since_dead < 10.0:
                return # Wait for OCR to finish before blind-clicking
                
            if time.time() - getattr(self, "_last_blind_retry", 0) > 2.0:
                logger.warning("[DEAD] Bot STUCK in result screen! Attempting blind-click on Retry Coords.")
                coords = config.get("coordinates", {})
                rx, ry = coords.get("retry_game", [1543, 1103])
                self.controller.scroll(-1000)
                time.sleep(0.05)
                _do_retry_click(rx, ry)
                self._last_blind_retry = time.time()
                
                # Reset session for the next match, but keep OCR flag locked
                # so blind-clicks don't cause duplicate reward counting.
                self.reset_session_flags(preserve_ocr_count=True)
                self.in_game_macro.reset_memory()
                self.last_ui_click = time.time()
                return




    def _handle_loading(self, detections: List[Detection]):
        # Passive state: Bot is waiting for screen/server transitions
        if random.random() < 0.05: # Occasional log
             logger.info("[Loading] Waiting for screen transition...")
        return

    def _handle_main_menu(self, detections: List[Detection]):
        if time.time() - self.last_ui_click < self.ui_cooldown:
            return

        coords = config.get("coordinates", {})
        labels = [d.label.lower().replace(" ", "_") for d in detections]
        
        # Step 1: Handle Main Play Button
        if not getattr(self, "_main_play_done", False):
            main_play = next((d for d in detections if d.label.lower().replace(" ", "_") == "play_menu_utama_ui"), None)
            # visual check or fallback after 3s
            if main_play or (time.time() - self.last_state_change > 3.0):
                logger.info("[Main-Menu] Step 1: Clicking Main Play Button.")
                px, py = coords.get("main_menu_play", [2217, 1182])
                if main_play: px, py = main_play.x_screen, main_play.y_screen
                self.controller.click_at(px, py)
                self._main_play_done = True
                self.last_main_play_click = time.time()
                self.last_ui_click = time.time()
                self._mission_click_count = 0 # Reset counter for Step 2
            return
            
        # Step 2: Handle Mission Button
        mission_btn = next((d for d in detections if d.label.lower().replace(" ", "_") == "mission_button"), None)
        # Visual check or fallback after 2s of Step 1 completion
        if mission_btn or (time.time() - self.last_main_play_click > 2.0):
            # Limit to 3 clicks per session to avoid infinite loop if game is stuck
            click_count = getattr(self, "_mission_click_count", 0)
            if click_count < 3:
                logger.info(f"[Main-Menu] Step 2: Clicking Mission Button (Attempt {click_count+1}).")
                mx, my = coords.get("main_menu_mission", [313, 1179])
                if mission_btn: mx, my = mission_btn.x_screen, mission_btn.y_screen
                self.controller.click_at(mx, my)
                self._mission_click_count = click_count + 1
                self.last_ui_click = time.time()
                
                # Phase 2058: Blind transition to Settings menu
                if self._mission_click_count >= 1:
                    logger.info("[Main-Menu] Blindly transitioning to Settings menu...")
                    self._change_state(BotState.SELECTING_SETTINGS)
            else:
                # If we clicked 3 times and still in Main Menu after 10s, reset to Step 1
                if time.time() - self.last_ui_click > 10.0:
                    logger.warning("[Main-Menu] Stuck at Step 2 for 10s. Resetting to Step 1.")
                    self._main_play_done = False
                    self._mission_click_count = 0
            return

    def _handle_char_select(self, detections: List[Detection]):
        """3-step sequence: select slot → click play_button_ui → click lobby_button_ui.
        
        Step inference is driven by VISIBLE UI LABELS, not just an internal counter.
        This prevents the bot from getting stuck clicking slot_a when the screen has
        already advanced to play_button_ui or lobby_button_ui.
        """
        coords = config.get("coordinates", {})
        strategy = config.get("strategy", {})
        if time.time() - self.last_ui_click < self.ui_cooldown:
            return

        labels = [d.label.lower().replace(" ", "_") for d in detections]

        # --- Visual-First Step Inference ---
        # Priority: lobby_button_ui (step 3) > play_button_ui (step 2) > slot/select_char (step 1)
        if "lobby_button_ui" in labels:
            # Step 1 & 2 are already done — we can see the lobby button, click it now.
            inferred_step = 3
        elif "play_button_ui" in labels:
            # Slot already selected — play button is visible, click it.
            inferred_step = 2
        elif any(l in labels for l in ["slot_a", "slot_b", "slot_c", "select_char", "character_stats"]):
            # Still on character selection screen — need to pick the slot.
            inferred_step = 1
        else:
            # No relevant UI visible yet, wait.
            logger.debug("[Char-Select] No relevant UI detected. Waiting...")
            return

        # Override internal counter with visual reality
        if inferred_step != getattr(self, "_char_select_step", 1):
            logger.info(f"[Char-Select] Visual override: step counter was {self._char_select_step}, but UI says Step {inferred_step}. Correcting.")
            self._char_select_step = inferred_step

        step = self._char_select_step

        # Step 1: Select the character slot
        if step == 1:
            slot_name = strategy.get("character_slot", "slot_a").lower().replace(" ", "_")
            sx, sy = coords.get(slot_name, [0, 0])
            if sx > 0:
                logger.info(f"[Char-Select] Step 1/3: Clicking character slot '{slot_name}'.")
                self.controller.click_at(sx, sy)
            else:
                logger.warning(f"[Char-Select] Missing coords for '{slot_name}', using default click.")
                sx, sy = coords.get("select_char_play", [1275, 806])
                self.controller.click_at(sx, sy)
            self._char_select_step = 2
            self.last_ui_click = time.time()

        # Step 2: Click play_button_ui once it appears
        elif step == 2:
            px, py = coords.get("select_char_play", [1275, 806])
            logger.info("[Char-Select] Step 2/3: Clicking play_button_ui.")
            self.controller.click_at(px, py)
            self._char_select_step = 3
            self.last_ui_click = time.time()

        # Step 3: Click lobby_button_ui to trigger server loading
        elif step == 3:
            lx, ly = coords.get("lobby_button_ui", [997, 780])
            logger.info("[Char-Select] Step 3/3: Clicking lobby_button_ui → Triggering Loading.")
            self.controller.click_at(lx, ly)
            self._char_select_step = 1  # reset for next run
            self.last_ui_click = time.time()


    def _handle_selecting_settings(self, detections: List[Detection]):
        # Phase 1816: Patience after clicking Start (Step 8)
        if time.time() - getattr(self, "_last_step8_time", 0) < 1.5:
            return

        if time.time() - self.last_ui_click < self.ui_cooldown:
            return

        labels = [d.label.lower().replace(" ", "_") for d in detections]
        coords = config.get("coordinates", {})
        strategy = config.get("strategy", {})

        # -- STEP 1: WAIT FOR NEW SERVER & SELECT MAP --
        if self.session_deploy_step == 1:
            # Phase 2034: Check for generic elements if map assets haven't loaded yet
            has_map_ui = any(l in ["giant_forest_map", "map_selection", "objective_button", "create_button", "next_difficulty_button"] for l in labels)
            if has_map_ui or (time.time() - self.last_state_change > 4.0):
                logger.info("[Settings] Step 1/7: Choosing Giant Forest Map (New Server).")

                mx, my = coords.get("map_giant_forest", [1735, 1068])
                self.controller.click_at(mx, my)
                self.session_deploy_step = 2
                self.last_ui_click = time.time()
            return

        # -- STEP 2: OPEN OBJECTIVE MENU --
        if self.session_deploy_step == 2:
            obj_btn = next((d for d in detections if d.label.lower().replace(" ", "_") == "objective_button"), None)
            if obj_btn or (time.time() - self.last_ui_click > 4.0):
                logger.info("[Settings] Step 2/6: Opening Objective Menu.")
                ox, oy = coords.get("objective_button", [1062, 1125])
                self.controller.click_at(ox, oy)
                self.session_deploy_step = 3
                self.last_ui_click = time.time()
            return

        # -- STEP 3: SELECT GUARD --
        if self.session_deploy_step == 3:
            # guard_objective_selected = replaces the old 'selecting_objective' class (no longer in model)
            # It appears ONLY when the objective submenu is open (unlike giant_forest_map which is permanent)
            is_obj_menu = "guard_objective_selected" in labels or "back_button" in labels
            if is_obj_menu:
                logger.info("[Settings] Step 3/6: Selecting Guard Objective.")
                gx, gy = coords.get("objective_guard", [1062, 746])
                self.controller.click_at(gx, gy)
                self.session_deploy_step = 4
                self.last_ui_click = time.time()
            elif time.time() - self.last_ui_click > 2.0:
                # Objective menu likely open but not detected — click guard coord blindly
                logger.warning("[Settings] Step 3/6: Menu not detected (2s). Blind-clicking Guard coord.")
                gx, gy = coords.get("objective_guard", [1062, 746])
                self.controller.click_at(gx, gy)
                self.session_deploy_step = 4
                self.last_ui_click = time.time()
            return

        # -- STEP 4: CLICK BACK --
        if self.session_deploy_step == 4:
            is_obj_menu = "guard_objective_selected" in labels or "back_button" in labels
            if is_obj_menu or time.time() - self.last_ui_click > 1.2:
                logger.info("[Settings] Step 4/7: Clicking Back from Objective.")
                bx, by = coords.get("objective_back", [1051, 1124])
                self.controller.click_at(bx, by)
                self.session_deploy_step = 5
                self.last_ui_click = time.time()
            return

        # -- STEP 5: SET DIFFICULTY --
        if self.session_deploy_step == 5:
            target_diff = strategy.get("difficulty", "Aberrant").lower()
            diff_map = {"easy": 0, "normal": 1, "hard": 2, "severe": 3, "aberrant": 4}
            target_clicks = diff_map.get(target_diff, 4)
            
            if self.difficulty_click_count < target_clicks:
                logger.info(f"[Settings] Step 5/7: Difficulty Formula ({self.difficulty_click_count}/{target_clicks}). Clicking Next.")
                dx, dy = coords.get("difficulty_next", [1432, 611])
                self.controller.click_at(dx, dy)
                self.difficulty_click_count += 1
                self.last_ui_click = time.time()
            else:
                logger.info("[Settings] Step 5/7: Difficulty complete. Moving to Step 6.")
                self.session_deploy_step = 6
                self.last_ui_click = time.time()
            return

        # -- STEP 6: CLICK CREATE BUTTON --
        if self.session_deploy_step == 6:
            create_btn = next((d for d in detections if d.label.lower().replace(" ", "_") == "create_button"), None)
            if create_btn or (time.time() - self.last_ui_click > 2.0):
                logger.info("[Settings] Step 6/6: Clicking Create Server Button — waiting for LOADING.")
                # Always use hardcoded coord — AI-detected position is unreliable here
                cx, cy = coords.get("start_create", [1286, 1124])
                self.controller.click_at(cx, cy)
                # Stay on step 6 — state machine will transition to LOADING when screen changes
                self.last_ui_click = time.time()
            return

    def _handle_lobby(self, detections: List[Detection]):
        now = time.time()
        # Phase 1621: Exit immediately if start button was already click to avoid loops during fade
        if getattr(self, "session_start_clicked", False):
            if now - self.last_ui_click > 5.0 and now - self.last_state_change < 60.0:
                logger.debug("[Lobby] Action blocked: session_start_clicked is True.")
            return 

        if now - self.last_ui_click < self.ui_cooldown:
            return

        # Phase 1679: Stuck Recovery - if in Lobby for 4s without action, reset once
        if now - self.last_state_change > 4.0 and not getattr(self, "session_start_clicked", False):
            if not getattr(self, "_lobby_stuck_reset_done", False):
                logger.warning("[Lobby] Stuck for 4s without action. Forcing Flag Reset (preserving clicked mods).")
                self.reset_session_flags(reason="Lobby_Stuck", preserve_modifiers=True)
                self._lobby_stuck_reset_done = True
                return

        labels = [d.label.lower().replace(" ", "_") for d in detections]
        coords = config.get("coordinates", {})
        strategy = config.get("strategy", {})
        target_mods = [m.lower().replace(" ", "_") for m in strategy.get("modifiers", [])]

        if not target_mods:
            # No modifiers needed, just start
            start_btn = next((d for d in detections if d.label.lower().replace(" ", "_") == "start_button"), None)
            if start_btn:
                logger.info("[Lobby] No modifiers. Starting Match.")
                sx, sy = coords.get("start_create", [1280, 1150])
                self.controller.click_at(sx, sy)
                self.session_start_clicked = True
                self.last_ui_click = now
            return

        # Phase 1506: Mod Menu Visibility with Persistence
        # We consider the menu open if we see markers OR if we recently saw them (persistence)
        is_mod_menu_open = any(l.endswith("_modifiers") for l in labels if l != "modifiers_button") or \
                           any(l in ["back_button", "checked_modifier", "difficulty_title"] for l in labels)
        
        if is_mod_menu_open:
            self._last_mod_menu_seen_time = now
        elif now - getattr(self, "_last_mod_menu_seen_time", 0) < 1.5: 
            is_mod_menu_open = True 
        
        # --- EXECUTION LOGIC ---
        all_target_clicked = all(m in self.session_clicked_modifiers for m in target_mods)

        if is_mod_menu_open:
            # --- MENU IS OPEN (Select or Exit) ---
            
            # 1. Safety Reset (Scroll Up 10000) - Only once
            if not self.session_modifiers_reset_done:
                first_mod = target_mods[0]
                mx, my = coords.get(f"modifier_{first_mod}", [853, 671])
                logger.info(f"[Lobby] Safety Reset: Scrolling UP 10000.")
                self.controller.scroll_at(mx, my, 10000)
                self.session_modifiers_reset_done = True
                self.last_ui_click = now
                return

            # 2. Sequential Selection (Batch 1 -> Batch 2)
            batch1 = ["no_perks", "no_skills", "no_talents", "nightmare", "oddball"]
            for m in batch1:
                if m in target_mods and m not in self.session_clicked_modifiers:
                    mx, my = coords.get(f"modifier_{m}", [0, 0])
                    is_already_checked = any(d.label.lower().replace(" ", "_") in ["checked_modifier", "checked"] and 
                                            abs(d.x_screen - mx) < 500 and abs(d.y_screen - my) < 40 
                                            for d in detections)
                    if is_already_checked:
                        self.session_clicked_modifiers.add(m)
                        continue
                    logger.info(f"[Lobby] Selecting {m}.")
                    self.controller.click_at(mx, my)
                    self.session_clicked_modifiers.add(m)
                    self.last_ui_click = now
                    return

            # Batch 2
            if all(m in self.session_clicked_modifiers for m in [x for x in batch1 if x in target_mods]):
                needed_batch2 = [m for m in target_mods if m in ["injury_prone", "chronic_injuries", "fog", "glass_cannon", "time_trial"]]
                if needed_batch2 and not self.session_modifiers_scrolled:
                    scroll_amt = config.get("bot", "modifier_scroll_amount", -590)
                    logger.info(f"[Lobby] Batch 1 done. Scrolling for Batch 2 (Amt: {scroll_amt}).")
                    self.controller.scroll(scroll_amt)
                    self.session_modifiers_scrolled = True
                    self.last_ui_click = now
                    return

                for m in needed_batch2:
                    if m not in self.session_clicked_modifiers:
                        mx, my = coords.get(f"modifier_{m}", [0, 0])
                        is_already_checked = any(d.label.lower().replace(" ", "_") in ["checked_modifier", "checked"] and 
                                                abs(d.x_screen - mx) < 500 and abs(d.y_screen - my) < 40 
                                                for d in detections)
                        if is_already_checked:
                            self.session_clicked_modifiers.add(m)
                            continue
                        logger.info(f"[Lobby] Selecting {m} (Batch 2).")
                        self.controller.click_at(mx, my)
                        self.session_clicked_modifiers.add(m)
                        self.last_ui_click = now
                        return

            # 3. Exit Menu
            if all_target_clicked:
                if not getattr(self, "session_modifiers_exit_clicked", False):
                    logger.info("[Lobby] All selected. Exiting Menu.")
                    bx, by = coords.get("modifier_back", [1277, 1122])
                    self.controller.click_at(bx, by)
                    self.session_modifiers_exit_clicked = True
                    self._last_exit_click_time = now
                    self.last_ui_click = now
                elif now - getattr(self, "_last_exit_click_time", 0) > 8.0:
                    self.session_modifiers_exit_clicked = False # Retry
                return
        else:
            # --- MENU IS CLOSED (Open or Start) ---
            if not all_target_clicked:
                logger.info("[Lobby] Opening Modifiers menu.")
                mx, my = coords.get("modifiers_button", [1275, 1121])
                self.controller.click_at(mx, my)
                self.last_ui_click = now
            else:
                # IMPORTANT: Final check for Start button
                start_btn = next((d for d in detections if d.label.lower().replace(" ", "_") == "start_button"), None)
                if start_btn or (now - getattr(self, "_last_exit_click_time", 0) > 2.0):
                    logger.info("[Lobby] Final Step: Clicking Start Game.")
                    sx, sy = coords.get("start_create", [1280, 1150])
                    if start_btn: sx, sy = start_btn.x_screen, start_btn.y_screen
                    self.controller.click_at(sx, sy)
                    self.session_start_clicked = True
                    self.last_ui_click = now

    def _handle_cutscene(self, detections: List[Detection]):
        if getattr(self, "_cutscene_skip_done", False):
            return
        
        skip_btn = next((d for d in detections if d.label.lower().replace(" ", "_") in ["cutscene_skip", "skip_button"]), None)
        if skip_btn:
            logger.info("[Cutscene] Skip button clicked. Waiting for cutscene to fade...")
            self.controller.click_at(skip_btn.x_screen, skip_btn.y_screen)
            self._cutscene_skip_done = True
            self.last_ui_click = time.time()
            # We DONT change state to IN_GAME instantly to allow the screen to fade.
            # _update_state() will naturally transition to IN_GAME after 1s of UI silence.

    def _handle_loading(self, detections: List[Detection]):
        # Loading is passive, just wait for transition
        # Phase 1917: Enhanced log to see transition activity
        if time.time() - getattr(self, "_last_loading_log", 0) > 2.0:
            logger.info("[Loading] Waiting for screen transition...")
            self._last_loading_log = time.time()

    def _is_ui_visible(self, detections: Optional[List[Detection]]) -> bool:
        if not detections: return False
        UI_KEYWORDS = ["Button", "Ui", "Title", "Map", "Modifier", "Objective", "Char"]
        for d in detections:
            if any(kw in d.label for kw in UI_KEYWORDS) or d.label in self.UI_SCAN_CLASSES:
                return True
        return False

    def _parse_highest_char_stat(self, detections: List[Detection], slots: List[Detection]) -> Optional[Detection]:
        char_stats = [d for d in detections if d.label == "Character Stats"]
        if not char_stats or not slots: return None
        best_slot, highest_val = None, -1
        for slot in slots:
            closest_stat = min(char_stats, key=lambda c: (c.x_screen - slot.x_screen)**2 + (c.y_screen - slot.y_screen)**2)
            digits = [d for d in detections if d.label.isdigit() and \
                     (closest_stat.x_screen - closest_stat.w_screen/2 <= d.x_screen <= closest_stat.x_screen + closest_stat.w_screen/2) and \
                     (closest_stat.y_screen - closest_stat.h_screen/2 <= d.y_screen <= closest_stat.y_screen + closest_stat.h_screen/2)]
            if digits:
                digits.sort(key=lambda d: d.x_screen)
                try:
                    val = int("".join([d.label for d in digits]))
                    if val > highest_val: highest_val, best_slot = val, slot
                except ValueError: pass
        return best_slot
