import sys
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QRadioButton, QCheckBox, QPushButton, QButtonGroup,
    QFrame, QScrollArea, QFileDialog, QLineEdit, QTextEdit,
    QSlider, QDialog, QSpinBox, QDoubleSpinBox, QFormLayout
)
from PyQt6.QtCore import Qt, pyqtSignal, QFileSystemWatcher
from bot.config import config

class SettingsWindow(QWidget):
    # Signal emitted when user clicks "Save & Start"
    started = pyqtSignal()
    # Phase 1001: Signal emitted when user wants to hot-reload scripts
    reloaded = pyqtSignal()
    # Phase 1533: Signal emitted when settings are saved
    saved = pyqtSignal()
    
    # Custom signal for stopping the thread safely to update UI
    stop_enhance_signal = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle("AOTR Bot Settings")
        self.setFixedWidth(900)
        self.setFixedHeight(600)
        
        self.stop_enhance_signal.connect(self._stop_hotkey_triggered)
        # Modern Glassmorphism effect
        self.setWindowOpacity(0.96)
        
        # Premium Dark Mode / Gray Stylesheet
        self.setStyleSheet("""
            QWidget {
                background-color: #1A1A1A;
                color: #B0B0B0;
                font-family: 'Inter', 'Roboto', 'Segoe UI', sans-serif;
                font-size: 13px;
            }
            QTabWidget::pane {
                border: 1px solid #333333;
                background-color: #202020;
                border-radius: 6px;
            }
            QTabBar::tab {
                background: #151515;
                color: #888888;
                padding: 10px 15px;
                font-weight: bold;
                border: 1px solid #252525;
                border-bottom: none;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                min-width: 110px;
                margin-right: 4px;
            }
            QTabBar::scroller {
                width: 0px;
            }
            QTabBar::tab:selected {
                color: #FFFFFF;
                background: #202020;
                border: 1px solid #404040;
                border-bottom: 2px solid #555555;
            }
            QTabBar::tab:hover:!selected {
                background: #252525;
                color: #DDDDDD;
            }
            QFrame#Section {
                background-color: #252525;
                border: 1px solid #383838;
                border-radius: 8px;
                padding: 15px;
                margin: 5px;
            }
            QFrame#SubSection {
                background-color: #2A2A2A;
                border: 1px solid #444444;
                border-radius: 6px;
                padding: 10px;
                margin-top: 8px;
            }
            QLabel#Title {
                font-size: 20px;
                font-weight: bold;
                color: #E0E0E0;
                padding-left: 2px;
            }
            QLabel#SubTitle {
                font-size: 15px;
                font-weight: bold;
                color: #B0B0B0;
                margin-top: 5px;
                margin-bottom: 8px;
                padding-bottom: 4px;
                border-bottom: 1px solid #555555;
            }
            QLabel {
                background-color: transparent;
                color: #B0B0B0;
            }
            QRadioButton, QCheckBox {
                background-color: transparent;
                spacing: 10px;
                padding: 5px;
                color: #B0B0B0;
                font-weight: 500;
            }
            QCheckBox::indicator, QRadioButton::indicator {
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 2px solid #505050;
                background: #1E1E1E;
            }
            QRadioButton::indicator {
                border-radius: 9px;
            }
            QCheckBox::indicator:hover, QRadioButton::indicator:hover {
                border: 2px solid #777777;
            }
            QCheckBox::indicator:checked, QRadioButton::indicator:checked {
                background: #606060;
                border: 2px solid #888888;
            }
            QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
                background-color: #121212;
                color: #E0E0E0;
                border: 1px solid #444444;
                border-radius: 5px;
                padding: 6px 10px;
                selection-background-color: #555555;
            }
            QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
                border: 1px solid #777777;
                background-color: #181818;
            }
            QSpinBox::up-button, QSpinBox::down-button, 
            QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
                width: 0px;
                height: 0px;
                border: none;
                background: transparent;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: #1A1A1A;
                border: 1px solid #444444;
                selection-background-color: #333333;
                color: #B0B0B0;
            }
            QPushButton {
                background-color: #333333;
                color: #FFFFFF;
                border: 1px solid #555555;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #444444;
                border: 1px solid #777777;
            }
            QPushButton:pressed {
                background-color: #222222;
            }
            QPushButton#SaveBtn {
                background-color: #2D4A22; border: 1px solid #3E6B2E;
            }
            QPushButton#SaveBtn:hover { background-color: #3E6B2E; }
            QPushButton#ReloadBtn {
                background-color: #6B4210; border: 1px solid #8C5716;
            }
            QPushButton#ReloadBtn:hover { background-color: #8C5716; }
            QPushButton#StartBtn, QPushButton#HotkeyBtn {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2196F3, stop:1 #1565C0);
                border: 1px solid #0D47A1;
                color: #FFFFFF;
                padding: 10px;
                font-size: 13px;
                border-radius: 5px;
            }
            QPushButton#StartBtn:hover, QPushButton#HotkeyBtn:hover { 
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #42A5F5, stop:1 #1976D2);
                border: 1px solid #0D47A1;
            }
            QPushButton#StartBtn:pressed, QPushButton#HotkeyBtn:pressed { 
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0D47A1, stop:1 #0B3B70);
            }
            QScrollArea { border: none; background: transparent; }
            QScrollArea > QWidget > QWidget { background: transparent; }
            
            /* Custom Dark Scrollbar */
            QScrollBar:vertical {
                border: none;
                background: #1A1A1A;
                width: 8px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #444444;
                min-height: 30px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: #666666;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
        """)

        self.layout = QVBoxLayout()
        self.setLayout(self.layout)
        
        # --- Top Header Bar ---
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(10, 5, 10, 5)
        
        header_layout.addStretch() # Left stretch
        title_label = QLabel("L.A.R.P", objectName="Title")
        # Modernized title style: light gray, centered feel
        title_label.setStyleSheet("color: #B0B0B0; font-size: 18px; font-weight: bold; letter-spacing: 2px;")
        header_layout.addWidget(title_label)
        header_layout.addStretch() # Right stretch
        
        kill_btn = QPushButton("✕")
        kill_btn.setToolTip("Force Quit App")
        kill_btn.setFixedSize(30, 30)
        kill_btn.setStyleSheet("""
            QPushButton {
                background-color: #252525; 
                color: #CCCCCC; 
                font-weight: bold; 
                border-radius: 15px; 
                font-size: 14px;
                border: 1px solid #444444;
            }
            QPushButton:hover {
                background-color: #333333;
                color: #FFFFFF;
                border: 1px solid #666666;
            }
        """)
        kill_btn.clicked.connect(self.force_kill_script)
        header_layout.addWidget(kill_btn)
        
        self.layout.addLayout(header_layout)

        # --- QTabWidget Main Structure ---
        from PyQt6.QtWidgets import QTabWidget
        from PyQt6.QtGui import QIcon
        from PyQt6.QtCore import QSize
        import os
        
        self.tab_widget = QTabWidget()
        self.tab_widget.setIconSize(QSize(20, 20))
        
        # Fixed Path: Get icons relative to this script's location
        script_dir = os.path.dirname(os.path.abspath(__file__))
        icons_dir = os.path.join(script_dir, "..", "assets", "icons")

        def create_scrollable_tab(title, icon_name=None):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            content = QWidget()
            layout = QVBoxLayout(content)
            layout.setAlignment(Qt.AlignmentFlag.AlignTop)
            scroll.setWidget(content)
            
            icon = QIcon()
            if icon_name:
                icon_path = os.path.join(icons_dir, f"{icon_name}.png")
                if os.path.exists(icon_path):
                    icon = QIcon(icon_path)
            
            self.tab_widget.addTab(scroll, icon, title)
            return layout
        
        self.layout_combat = create_scrollable_tab("COMBAT", "combat")
        self.layout_setup = create_scrollable_tab("SETUP", "setup")
        self.layout_system = create_scrollable_tab("SYSTEM", "system")
        self.layout_info = create_scrollable_tab("INFO", "info")
        self.layout_tools = create_scrollable_tab("TOOLS", "tools")
        
        self.layout.addWidget(self.tab_widget)

        # --- Difficulty Section ---
        diff_frame = QFrame(objectName="Section")
        diff_layout = QVBoxLayout(diff_frame)
        diff_layout.addWidget(QLabel("DIFFICULTY", objectName="SubTitle"))
        
        self.diff_group = QButtonGroup(self)
        self.diff_btns = {}
        for d in ["Easy", "Normal", "Hard", "Severe", "Aberrant"]:
            btn = QRadioButton(d)
            self.diff_btns[d] = btn
            self.diff_group.addButton(btn)
            diff_layout.addWidget(btn)
            
        # Load default
        current_diff = config.get("strategy", "difficulty", "Normal")
        if current_diff in self.diff_btns:
            self.diff_btns[current_diff].setChecked(True)
        else:
            self.diff_btns["Normal"].setChecked(True)

        self.layout_setup.addWidget(diff_frame)

        # --- Modifiers Section (Scrollable) ---
        mod_frame = QFrame(objectName="Section")
        mod_layout = QVBoxLayout(mod_frame)
        mod_layout.addWidget(QLabel("MODIFIERS", objectName="SubTitle"))
        
        mod_scroll = QScrollArea()
        mod_scroll.setWidgetResizable(True)
        mod_content = QWidget()
        mod_content_layout = QVBoxLayout(mod_content)
        
        self.mod_checks = {}
        modifiers = [
            "No Perks", "No Skills", "No Talents", "Nightmare", "Oddball",
            "Injury Prone", "Chronic Injuries", "Fog", "Glass Cannon", 
            "Time Trial", "Boring", "Simple"
        ]
        
        saved_mods = config.get("strategy", "modifiers", [])
        for m in modifiers:
            cb = QCheckBox(m)
            self.mod_checks[m] = cb
            if m in saved_mods:
                cb.setChecked(True)
            mod_content_layout.addWidget(cb)
            
        mod_scroll.setWidget(mod_content)
        mod_layout.addWidget(mod_scroll)
        self.layout_setup.addWidget(mod_frame)

        # --- Objective Section ---
        obj_frame = QFrame(objectName="Section")
        obj_layout = QVBoxLayout(obj_frame)
        obj_layout.addWidget(QLabel("OBJECTIVE", objectName="SubTitle"))
        
        self.obj_group = QButtonGroup(self)
        self.obj_btns = {}
        for o in ["Guard"]: # Expandable
            btn = QRadioButton(o)
            self.obj_btns[o] = btn
            self.obj_group.addButton(btn)
            obj_layout.addWidget(btn)
        
        # Default
        current_obj = config.get("strategy", "objective", "Guard")
        if current_obj in self.obj_btns:
            self.obj_btns[current_obj].setChecked(True)
            
        self.layout_setup.addWidget(obj_frame)
            
        # --- Target Character Section ---
        char_frame = QFrame(objectName="Section")
        char_layout = QVBoxLayout(char_frame)
        char_layout.addWidget(QLabel("TARGET CHARACTER", objectName="SubTitle"))
        
        self.char_group = QButtonGroup(self)
        self.char_btns = {}
        # Changed the options to include the Auto stat feature
        for c in ["Auto (Highest Stats)", "Slot A", "Slot B", "Slot C"]:
            btn = QRadioButton(c)
            self.char_btns[c] = btn
            self.char_group.addButton(btn)
            char_layout.addWidget(btn)
            
        current_char = config.get("strategy", "character_slot", "Auto (Highest Stats)")
        if current_char in self.char_btns:
            self.char_btns[current_char].setChecked(True)
        else:
            self.char_btns["Auto (Highest Stats)"].setChecked(True)
            
        self.layout_setup.addWidget(char_frame)
        
        # --- Custom Model Section ---
        model_frame = QFrame(objectName="Section")
        model_layout = QVBoxLayout(model_frame)
        model_layout.addWidget(QLabel("CUSTOM YOLO MODEL", objectName="SubTitle"))
        
        saved_model = config.get("bot", "model_path", "")
        
        model_hlayout = QHBoxLayout()
        self.model_input = QLineEdit()
        self.model_input.setPlaceholderText("Auto (Latest Training Folder) or select .pt/.onnx/.engine")
        self.model_input.setText(saved_model)
        self.model_input
        
        browse_btn = QPushButton("Browse")
        browse_btn.setStyleSheet("background-color: #03DAC6; color: #000; padding: 5px; font-weight: bold; border-radius: 3px;")
        browse_btn.clicked.connect(self.browse_model)
        
        clear_btn = QPushButton("Clear")
        clear_btn.setStyleSheet("background-color: #CF6679; color: #000; padding: 5px; font-weight: bold; border-radius: 3px;")
        clear_btn.clicked.connect(self.model_input.clear)
        
        model_hlayout.addWidget(self.model_input)
        model_hlayout.addWidget(browse_btn)
        model_hlayout.addWidget(clear_btn)
        
        model_layout.addLayout(model_hlayout)
        self.layout_system.addWidget(model_frame)
        
        # --- Aim Assist Section ---
        aim_frame = QFrame(objectName="Section")
        aim_layout = QVBoxLayout(aim_frame)
        aim_layout.addWidget(QLabel("AIM ASSIST (FOV)", objectName="SubTitle"))
        
        # --- Visual Overlays ---
        aim_vis_group = QFrame(objectName="SubSection")
        aim_vis_layout = QVBoxLayout(aim_vis_group)
        aim_vis_layout.addWidget(QLabel("VISUAL OVERLAYS", objectName="SubTitle"))

        # FOV Circle Toggle
        self.show_fov_cb = QCheckBox("Show FOV Circle (Preview)")
        self.show_fov_cb.setChecked(config.get("aim_assist", "show_fov_circle", True))
        aim_vis_layout.addWidget(self.show_fov_cb)

        # IPM Trajectory Line Toggle
        self.show_ipm_line_cb = QCheckBox("Show IPM Trajectory Line (Center → Target)")
        self.show_ipm_line_cb.setChecked(config.get("aim_assist", "show_ipm_line", True))
        aim_vis_layout.addWidget(self.show_ipm_line_cb)
        
        aim_layout.addWidget(aim_vis_group)
        
        from PyQt6.QtWidgets import QSpinBox, QDoubleSpinBox
        
        # --- Core Aim Settings ---
        from PyQt6.QtWidgets import QFormLayout
        aim_core_group = QFrame(objectName="SubSection")
        aim_core_layout = QFormLayout(aim_core_group)
        aim_core_layout.addWidget(QLabel("CORE AIM SETTINGS", objectName="SubTitle"))

        # AI Confidence Score
        self.conf_spin = QDoubleSpinBox()
        self.conf_spin.setRange(0.05, 0.95)
        self.conf_spin.setSingleStep(0.05)
        self.conf_spin.setValue(config.get("detection", "confidence_threshold", 0.45))
        aim_core_layout.addRow("AI Confidence Score:", self.conf_spin)
        
        # FOV Radius
        self.fov_spin = QSpinBox()
        self.fov_spin.setRange(50, 800)
        self.fov_spin.setSingleStep(10)
        self.fov_spin.setValue(config.get("aim_assist", "fov_radius", 150))
        aim_core_layout.addRow("FOV Radius (px):", self.fov_spin)
        
        # P-Gain
        self.pgain_spin = QDoubleSpinBox()
        self.pgain_spin.setRange(0.01, 2.0)
        self.pgain_spin.setSingleStep(0.05)
        self.pgain_spin.setValue(config.get("aim_assist", "p_gain", 0.4))
        aim_core_layout.addRow("P-Gain (Sensitivity):", self.pgain_spin)
        
        # Max Delta
        self.maxd_spin = QSpinBox()
        self.maxd_spin.setRange(1, 100)
        self.maxd_spin.setValue(config.get("aim_assist", "max_delta", 15))
        aim_core_layout.addRow("Max Delta (Speed Cap):", self.maxd_spin)
        
        # Kalman Variance
        self.kalman_spin = QDoubleSpinBox()
        self.kalman_spin.setRange(1.0, 100.0)
        self.kalman_spin.setSingleStep(5.0)
        self.kalman_spin.setValue(config.get("aim_assist", "measurement_var", 20.0))
        aim_core_layout.addRow("Kalman Measurement Var:", self.kalman_spin)
        
        # Anti-Hallucination
        self.halluc_spin = QSpinBox()
        self.halluc_spin.setRange(500, 10000)
        self.halluc_spin.setSingleStep(100)
        self.halluc_spin.setValue(config.get("aim_assist", "max_detection_speed_px_s", 2500))
        aim_core_layout.addRow("Anti-Hallucination Speed (px/s):", self.halluc_spin)
        
        # Global Aim Offsets
        offsets_hlayout = QHBoxLayout()
        self.offset_x_spin = QSpinBox()
        self.offset_x_spin.setRange(-1000, 1000)
        self.offset_x_spin.setValue(config.get("aim_assist", "global_offset_x", 0))
        self.offset_y_spin = QSpinBox()
        self.offset_y_spin.setRange(-1000, 1000)
        self.offset_y_spin.setValue(config.get("aim_assist", "global_offset_y", 0))
        
        offsets_hlayout.addWidget(QLabel("X:"))
        offsets_hlayout.addWidget(self.offset_x_spin)
        offsets_hlayout.addWidget(QLabel(" Y:"))
        offsets_hlayout.addWidget(self.offset_y_spin)
        offsets_hlayout.addStretch()
        
        aim_core_layout.addRow("Global Aim Offset (px):", offsets_hlayout)
        aim_layout.addWidget(aim_core_group)

        # ── Prediction Feature Toggles ──────────────────────────────────────
        aim_pred_group = QFrame(objectName="SubSection")
        aim_pred_layout = QVBoxLayout(aim_pred_group)
        aim_pred_layout.addWidget(QLabel("PREDICTION FEATURES", objectName="SubTitle"))

        self.kalman_enabled_cb = QCheckBox("Enable Kalman Filter (Smooth tracking)")
        self.kalman_enabled_cb.setToolTip(
            "Enable Kalman Filter to track Annie's position.\n"
            "If disabled, the bot directly uses raw YOLO coordinates without smoothing."
        )
        self.kalman_enabled_cb.setChecked(config.get("aim_assist", "kalman_enabled", True))
        aim_pred_layout.addWidget(self.kalman_enabled_cb)

        self.dampening_enabled_cb = QCheckBox("Enable Velocity Dampening (Anti-overshoot)")
        self.dampening_enabled_cb.setToolTip(
            "Dampen prediction velocity per frame (0.95x per tick).\n"
            "If disabled, pendulum prediction might overshoot when the target stops suddenly."
        )
        self.dampening_enabled_cb.setChecked(config.get("aim_assist", "dampening_enabled", True))
        aim_pred_layout.addWidget(self.dampening_enabled_cb)

        self.dead_reckoning_enabled_cb = QCheckBox("Enable Dead Reckoning (Extrapolate when invisible)")
        self.dead_reckoning_enabled_cb.setToolTip(
            "When Annie is undetected, the bot predicts her position using the last known velocity.\n"
            "If disabled, the bot stops moving the cursor instantly when Annie leaves the frame."
        )
        self.dead_reckoning_enabled_cb.setChecked(config.get("aim_assist", "dead_reckoning_enabled", True))
        aim_pred_layout.addWidget(self.dead_reckoning_enabled_cb)

        self.lead_prediction_enabled_cb = QCheckBox("Enable Lead Prediction (Dynamic lead-time)")
        self.lead_prediction_enabled_cb.setToolTip(
            "The bot aims slightly AHEAD of Annie based on velocity + lag.\n"
            "If disabled, the bot aims directly at Annie's centroid without leading."
        )
        self.lead_prediction_enabled_cb.setChecked(config.get("aim_assist", "lead_prediction_enabled", True))
        aim_pred_layout.addWidget(self.lead_prediction_enabled_cb)
        
        aim_layout.addWidget(aim_pred_group)
        # ────────────────────────────────────────────────────────────────────

        self.layout_combat.addWidget(aim_frame)
        
        # --- Combat Engine Timing Section ---
        combat_frame = QFrame(objectName="Section")
        combat_layout = QVBoxLayout(combat_frame)
        combat_layout.addWidget(QLabel("COMBAT ENGINE TIMING", objectName="SubTitle"))
        
        from PyQt6.QtWidgets import QSpinBox, QDoubleSpinBox
        
        # -- Hybrid IPM --
        ipm_group = QFrame(objectName="SubSection")
        ipm_layout = QVBoxLayout(ipm_group)
        self.use_ipm_cb = QCheckBox("Use Hybrid IPM (Dynamic Duration)")
        self.use_ipm_cb.setChecked(config.get("combat_engine", "use_hybrid_ipm", False))
        ipm_layout.addWidget(self.use_ipm_cb)
        combat_layout.addWidget(ipm_group)

        # -- FPS Lag Compensation --
        lag_group = QFrame(objectName="SubSection")
        lag_layout = QFormLayout(lag_group)
        lag_layout.addWidget(QLabel("FPS LAG COMPENSATION", objectName="SubTitle"))
        
        self.lag_comp_cb = QCheckBox("Enable Lag Compensation")
        self.lag_comp_cb.setChecked(config.get("combat_engine", "enable_lag_compensation", True))
        lag_layout.addRow(self.lag_comp_cb)

        self.lag_mult_spin = QDoubleSpinBox()
        self.lag_mult_spin.setRange(1.0, 5.0)
        self.lag_mult_spin.setSingleStep(0.1)
        self.lag_mult_spin.setValue(config.get("combat_engine", "lag_comp_max_mult", 1.3))
        lag_layout.addRow("Max Lag Multiplier for Flight:", self.lag_mult_spin)

        self.base_click_ms_spin = QSpinBox()
        self.base_click_ms_spin.setRange(10, 500)
        self.base_click_ms_spin.setSingleStep(10)
        self.base_click_ms_spin.setValue(config.get("combat_engine", "base_click_duration_ms", 70))
        lag_layout.addRow("Base Click Duration (ms):", self.base_click_ms_spin)
        
        combat_layout.addWidget(lag_group)

        # -- Mid-Assault Click Sequence --
        seq_group = QFrame(objectName="SubSection")
        seq_layout = QFormLayout(seq_group)
        seq_layout.addWidget(QLabel("ASSAULT SEQUENCE", objectName="SubTitle"))
        
        self.use_assault_click_cb = QCheckBox("Enable Initial Click (Q+E+Space → Click)")
        self.use_assault_click_cb.setChecked(config.get("combat_engine", "use_assault_click", False))
        seq_layout.addRow(self.use_assault_click_cb)
        
        self.click_delay_spin = QSpinBox()
        self.click_delay_spin.setRange(0, 1000)
        self.click_delay_spin.setSingleStep(10)
        self.click_delay_spin.setValue(int(config.get("combat_engine", "assault_key_click_delay", 0.1) * 1000))
        seq_layout.addRow("Key-to-Click Delay (ms):", self.click_delay_spin)
        
        combat_layout.addWidget(seq_group)
        
        # --- NEW: Timing & Delays ---
        timing_group = QFrame(objectName="SubSection")
        timing_layout = QFormLayout(timing_group)
        timing_layout.addWidget(QLabel("TIMING & DELAYS", objectName="SubTitle"))

        # First Assault Duration (Static)
        self.assault_first_spin = QDoubleSpinBox()
        self.assault_first_spin.setRange(0.1, 8.0)
        self.assault_first_spin.setSingleStep(0.1)
        self.assault_first_spin.setValue(config.get("combat_engine", "assault_duration_first", 1.0))
        timing_layout.addRow("[FIRST HIT] Static Assault Duration (s):", self.assault_first_spin)

        # Assault Duration (Static)
        self.assault_spin = QDoubleSpinBox()
        self.assault_spin.setRange(0.1, 8.0)
        self.assault_spin.setSingleStep(0.1)
        self.assault_spin.setValue(config.get("combat_engine", "assault_duration", 1.5))
        timing_layout.addRow("[NEXT HITS] Static Assault Duration (s):", self.assault_spin)
        
        # Startup Delay
        self.startup_spin = QDoubleSpinBox()
        self.startup_spin.setRange(0.0, 10.0)
        self.startup_spin.setSingleStep(0.5)
        self.startup_spin.setDecimals(1)
        self.startup_spin.setValue(config.get("combat_engine", "startup_delay", 2.0))
        timing_layout.addRow("Startup Delay (seconds):", self.startup_spin)
        
        # Aim Memory Duration
        self.memory_spin = QDoubleSpinBox()
        self.memory_spin.setRange(0.5, 10.0)
        self.memory_spin.setSingleStep(0.5)
        self.memory_spin.setDecimals(1)
        self.memory_spin.setValue(config.get("combat_engine", "aim_memory_duration", 4.0))
        timing_layout.addRow("Aim Memory Duration (seconds):", self.memory_spin)
        
        combat_layout.addWidget(timing_group)
        
        # -- Approach Phase Settings --
        approach_group = QFrame(objectName="SubSection")
        approach_layout = QFormLayout(approach_group)
        approach_layout.addWidget(QLabel("APPROACH PHASE (STATIC MACRO)", objectName="SubTitle"))

        self.qe_hold_spin = QDoubleSpinBox()
        self.qe_hold_spin.setRange(0.0, 10.0)
        self.qe_hold_spin.setSingleStep(0.5)
        self.qe_hold_spin.setDecimals(1)
        self.qe_hold_spin.setValue(config.get("combat_engine", "approach_qe_hold_bonus", 1.0))
        approach_layout.addRow("Q+E Hold Bonus (seconds):", self.qe_hold_spin)

        self.static_dur_spin = QDoubleSpinBox()
        self.static_dur_spin.setRange(0.0, 999.0)
        self.static_dur_spin.setSingleStep(1.0)
        self.static_dur_spin.setDecimals(1)
        self.static_dur_spin.setValue(config.get("combat_engine", "static_macro_max_duration", 7.0))
        approach_layout.addRow("Total Approach Duration (s):", self.static_dur_spin)
        
        combat_layout.addWidget(approach_group)
        
        # -- Cooldowns & Offsets --
        off_group = QFrame(objectName="SubSection")
        off_layout = QFormLayout(off_group)
        off_layout.addWidget(QLabel("COOLDOWNS & OFFSETS", objectName="SubTitle"))

        self.cooldown_spin = QDoubleSpinBox()
        self.cooldown_spin.setRange(0.0, 5.0)
        self.cooldown_spin.setSingleStep(0.1)
        self.cooldown_spin.setDecimals(1)
        self.cooldown_spin.setValue(config.get("combat_engine", "cooldown_after_dash", 1.0))
        off_layout.addRow("Cooldown After Dash (s):", self.cooldown_spin)
        
        self.yoffset_spin = QSpinBox()
        self.yoffset_spin.setRange(0, 500)
        self.yoffset_spin.setSingleStep(10)
        self.yoffset_spin.setValue(config.get("combat_engine", "annie_mark_y_offset", 150))
        off_layout.addRow("Annie Mark Y Offset (px):", self.yoffset_spin)
        
        combat_layout.addWidget(off_group)
        
        self.layout_combat.addWidget(combat_frame)
        
        # --- Debug/Mode Section ---
        debug_frame = QFrame(objectName="Section")
        debug_layout = QVBoxLayout(debug_frame)
        debug_layout.addWidget(QLabel("DIAGNOSTICS", objectName="SubTitle"))
        
        # --- Toggles ---
        diag_tog_group = QFrame(objectName="SubSection")
        diag_tog_layout = QVBoxLayout(diag_tog_group)
        diag_tog_layout.addWidget(QLabel("TOGGLES", objectName="SubTitle"))

        self.eyes_only_cb = QCheckBox("Eyes Only Mode (No Actions)")
        self.eyes_only_cb.setChecked(config.get("bot", "eyes_only", False))
        diag_tog_layout.addWidget(self.eyes_only_cb)
        
        # Phase 125: Visual Overlay Toggle
        self.show_overlay_cb = QCheckBox("Show Visual Overlay (Boxes/Crosshair)")
        self.show_overlay_cb.setChecked(config.get("bot", "show_overlay", True))
        diag_tog_layout.addWidget(self.show_overlay_cb)

        # OCR Debug Mode
        self.ocr_debug_cb = QCheckBox("OCR Debug Mode (Save reward crop images)")
        self.ocr_debug_cb.setToolTip(
            "When active, upon mission completion the bot will save reward ROI crops\n"
            "to the 'debug_ocr/' folder (debug_reward_box_raw.png & debug_reward_box_proc.png).\n"
            "Use this to verify Gold/Exp/Gems OCR accuracy."
        )
        self.ocr_debug_cb.setChecked(config.get("reward_regions", "debug_mode", False))
        diag_tog_layout.addWidget(self.ocr_debug_cb)
        
        debug_layout.addWidget(diag_tog_group)

        # --- Global Settings ---
        diag_glob_group = QFrame(objectName="SubSection")
        diag_glob_layout = QFormLayout(diag_glob_group)
        diag_glob_layout.addWidget(QLabel("GLOBAL SETTINGS", objectName="SubTitle"))

        # Modifier Scroll Amount
        self.scroll_input = QLineEdit()
        self.scroll_input.setText(str(config.get("bot", "modifier_scroll_amount", -5500)))
        self.scroll_input.setFixedWidth(80)
        diag_glob_layout.addRow("Modifier Scroll Amount (Ticks):", self.scroll_input)

        # Brightness Booster
        self.bright_input = QLineEdit()
        self.bright_input.setText(str(config.get("screen", "brightness_multiplier", 1.0)))
        self.bright_input.setFixedWidth(80)
        diag_glob_layout.addRow("Brightness Booster (1.0 = Normal):", self.bright_input)
        
        # Bot Speed
        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(0.1, 20.0)
        self.speed_spin.setSingleStep(0.1)
        self.speed_spin.setValue(config.get("bot", "bot_speed", 1.0))
        diag_glob_layout.addRow("Bot Global Speed (Multiplier):", self.speed_spin)
        
        # Target FPS
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(10, 120)
        self.fps_spin.setSingleStep(5)
        self.fps_spin.setValue(config.get("bot", "target_fps", 45))
        diag_glob_layout.addRow("Target FPS (Global Capture):", self.fps_spin)

        # Annie Mark Target FPS
        self.fps_annie_spin = QSpinBox()
        self.fps_annie_spin.setRange(0, 120)
        self.fps_annie_spin.setSingleStep(5)
        self.fps_annie_spin.setValue(config.get("bot", "target_fps_annie_mark", 0))
        diag_glob_layout.addRow("Target FPS (Annie Mark):", self.fps_annie_spin)
        
        debug_layout.addWidget(diag_glob_group)
        debug_layout.addSpacing(10)
        
        self.layout_info.addWidget(debug_frame)
        
        # --- Discord Bot Section ---
        discord_frame = QFrame(objectName="Section")
        discord_layout = QVBoxLayout(discord_frame)
        discord_layout.addWidget(QLabel("DISCORD BOT", objectName="SubTitle"))
        
        # --- Discord Credentials ---
        discord_cred_group = QFrame(objectName="SubSection")
        discord_cred_layout = QVBoxLayout(discord_cred_group)
        discord_cred_layout.addWidget(QLabel("CREDENTIALS & WEBHOOKS", objectName="SubTitle"))

        self.discord_enabled_cb = QCheckBox("Enable Discord Bot")
        self.discord_enabled_cb.setChecked(config.get("discord_bot", "enabled", False))
        discord_cred_layout.addWidget(self.discord_enabled_cb)
        
        token_layout = QHBoxLayout()
        token_layout.addWidget(QLabel("Bot Token:"))
        self.discord_token_input = QLineEdit()
        self.discord_token_input.setEchoMode(QLineEdit.EchoMode.Password) # Privacy
        self.discord_token_input.setText(config.get("discord_bot", "token", ""))
        token_layout.addWidget(self.discord_token_input)
        discord_cred_layout.addLayout(token_layout)
        
        admin_layout = QHBoxLayout()
        admin_layout.addWidget(QLabel("Admin User ID:"))
        self.discord_admin_input = QLineEdit()
        self.discord_admin_input.setText(str(config.get("discord_bot", "admin_user_id", "")))
        admin_layout.addWidget(self.discord_admin_input)
        discord_cred_layout.addLayout(admin_layout)
        
        # Webhook URL field
        webhook_layout = QHBoxLayout()
        webhook_label = QLabel("Webhook URL:")
        webhook_label.setToolTip(
            "Discord Webhook URL for sending notifications (state, rounds, rewards).\n"
            "Create via: Channel Settings → Integrations → Webhooks → New Webhook → Copy URL"
        )
        webhook_layout.addWidget(webhook_label)
        self.discord_webhook_input = QLineEdit()
        self.discord_webhook_input.setEchoMode(QLineEdit.EchoMode.Password)  # Privacy
        self.discord_webhook_input.setPlaceholderText("https://discord.com/api/webhooks/...")
        self.discord_webhook_input.setText(config.get("discord_bot", "webhook_url", ""))
        webhook_layout.addWidget(self.discord_webhook_input)
        discord_cred_layout.addLayout(webhook_layout)
        
        # Reward Webhook URL field
        reward_webhook_layout = QHBoxLayout()
        reward_webhook_label = QLabel("Reward Webhook:")
        reward_webhook_label.setToolTip("Optional: Separate webhook exclusively for Boss Rewards")
        reward_webhook_layout.addWidget(reward_webhook_label)
        
        self.discord_reward_webhook_input = QLineEdit()
        self.discord_reward_webhook_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.discord_reward_webhook_input.setPlaceholderText("https://discord.com/api/webhooks/... (Optional)")
        self.discord_reward_webhook_input.setText(config.get("discord_bot", "reward_webhook_url", ""))
        reward_webhook_layout.addWidget(self.discord_reward_webhook_input)
        
        # --- Window Management Section ---
        win_frame = QFrame(objectName="Section")
        win_layout = QVBoxLayout(win_frame)
        win_layout.addWidget(QLabel("WINDOW MANAGEMENT", objectName="SubTitle"))
        
        self.win_proc_cb = QCheckBox("Enable Process Monitor (Auto-Relog)")
        self.win_proc_cb.setChecked(config.get("window_management", "enable_process_monitor", True))
        win_layout.addWidget(self.win_proc_cb)
        
        self.win_focus_cb = QCheckBox("Enable Auto-Focus Roblox")
        self.win_focus_cb.setChecked(config.get("window_management", "enable_auto_focus", True))
        win_layout.addWidget(self.win_focus_cb)
        
        reconnect_layout = QHBoxLayout()
        reconnect_layout.addWidget(QLabel("Relog after (min):"))
        self.reconnect_delay_input = QLineEdit()
        self.reconnect_delay_input.setText(str(config.get("window_management", "reconnect_delay_minutes", 2)))
        self.reconnect_delay_input
        self.reconnect_delay_input.setFixedWidth(50)
        reconnect_layout.addWidget(self.reconnect_delay_input)
        reconnect_layout.addStretch()
        win_layout.addLayout(reconnect_layout)
        
        from PyQt6.QtWidgets import QComboBox
        res_layout = QHBoxLayout()
        res_layout.addWidget(QLabel("Game Resolution:"))
        self.res_combo = QComboBox()
        self.res_combo.addItems(["1920x1080 (1080p)", "2560x1440 (2K)"])
        
        current_w = config.get("screen", "width", 1920)
        self.res_combo.setCurrentIndex(1 if current_w >= 2560 else 0)
        
        self.res_combo
        res_layout.addWidget(self.res_combo)
        res_layout.addStretch()
        win_layout.addLayout(res_layout)
        
        self.layout_system.addWidget(win_frame)

        # --- Raw Config Viewer Section --- # Phase 96
        config_frame = QFrame(objectName="Section")
        config_layout = QVBoxLayout(config_frame)
        
        config_header = QHBoxLayout()
        config_header.addWidget(QLabel("LIVE CONFIG.JSON VIEWER", objectName="SubTitle"))
        
        refresh_btn = QPushButton("Refresh from Disk")
        refresh_btn.clicked.connect(self.refresh_config_view)
        config_header.addWidget(refresh_btn)
        
        config_layout.addLayout(config_header)
        
        self.config_text = QTextEdit()
        self.config_text.setReadOnly(True)
        self.config_text.setFixedHeight(120)
        self.config_text.setStyleSheet("background-color: #121212; color: #B0B0B0; font-family: Consolas, monospace; font-size: 11px; padding: 5px; border: 1px solid #444444;")
        config_layout.addWidget(self.config_text)
        
        self.layout_info.addWidget(config_frame)

        # --- Version Label + Update Status (INFO tab footer) ---
        version_footer = QWidget()
        version_footer_layout = QHBoxLayout(version_footer)
        version_footer_layout.setContentsMargins(8, 4, 8, 4)
        
        from bot.updater import CURRENT_VERSION
        self.version_label = QLabel(f"L.A.R.P v{CURRENT_VERSION}")
        self.version_label.setStyleSheet("color: #555555; font-size: 11px;")
        
        self.update_status_label = QLabel("Checking for updates...")
        self.update_status_label.setStyleSheet("color: #555555; font-size: 11px;")
        
        version_footer_layout.addWidget(self.version_label)
        version_footer_layout.addStretch()
        version_footer_layout.addWidget(self.update_status_label)
        
        self.layout_info.addWidget(version_footer)
        self.layout_info.addStretch()

        # --- Tools Section ---
        tools_frame = QFrame(objectName="Section")
        tools_layout = QVBoxLayout(tools_frame)
        tools_layout.addWidget(QLabel("AUTO ENHANCE PERKS", objectName="SubTitle"))
        
        info_label = QLabel("Auto click: Auto Add (1754, 786) -> Enhance (1760, 988)")
        tools_layout.addWidget(info_label)
        
        self.enhance_btn = QPushButton("▶ Start Auto Enhance")
        self.enhance_btn.setStyleSheet("background-color: #1976D2; color: #fff; padding: 10px; font-weight: bold; border-radius: 5px;")
        self.enhance_btn.clicked.connect(self.toggle_auto_enhance)
        tools_layout.addWidget(self.enhance_btn)
        
        self.layout_tools.addWidget(tools_frame)
        
        self.auto_enhance_running = False

        # --- Fixed Bottom Control Area ---
        control_area = QFrame()
        control_area.setStyleSheet("background-color: #212121; border-top: 1px solid #333;")
        control_layout = QVBoxLayout(control_area)
        control_layout.setContentsMargins(5, 10, 5, 5)
        
        self.refresh_config_view() # Load initial view
        
        # Auto-refresh viewer when config.json changes on disk (e.g. manual edits)
        self._config_watcher = QFileSystemWatcher([config._path])
        self._config_watcher.fileChanged.connect(self._on_config_file_changed)
        
        # --- Kick off background update check ---
        from bot.updater import check_for_updates_async
        check_for_updates_async(self._on_update_check_result)

        # --- Actions ---
        action_layout = QHBoxLayout()
        
        hotkey_btn = QPushButton("HOTKEYS F1 Start    F2 Pause    F3 Stop")
        hotkey_btn.setObjectName("HotkeyBtn")
        hotkey_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        hotkey_btn.setToolTip("Use these keyboard keys to control the bot while running.")
        
        start_btn = QPushButton("SAVE AND START")
        start_btn.setObjectName("StartBtn")
        start_btn.setToolTip("Will save config and close this menu.")
        start_btn.clicked.connect(self.save_and_start)
        
        action_layout.addWidget(hotkey_btn)
        action_layout.addWidget(start_btn)
        
        control_layout.addLayout(action_layout)
        self.layout.addWidget(control_area)
        
        # --- Scroll Hijack Prevention ---
        from PyQt6.QtCore import QObject, QEvent
        from PyQt6.QtWidgets import QAbstractSpinBox, QComboBox
        
        class ScrollBlocker(QObject):
            def eventFilter(self, obj, event):
                if event.type() == QEvent.Type.Wheel:
                    # Ignore the wheel event on the input, allowing the parent scroll area to scroll
                    event.ignore()
                    return True
                return False
                
        self._scroll_blocker = ScrollBlocker(self)
        
        # Apply strict focus policy and block wheel events for all SpinBoxes and ComboBoxes
        for w in self.findChildren(QAbstractSpinBox):
            w.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            w.installEventFilter(self._scroll_blocker)
            
        for w in self.findChildren(QComboBox):
            w.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            w.installEventFilter(self._scroll_blocker)

    def _on_update_check_result(self, release: dict | None):
        """
        Called from background thread when update check completes.
        Uses Qt's thread-safe invokeMethod pattern via a stored lambda.
        """
        from PyQt6.QtCore import QMetaObject, Qt as QtCore_Qt
        # We need to update the UI from the main thread, so we use a timer trick
        if release:
            self._pending_update = release
            QMetaObject.invokeMethod(self, "_show_update_available", QtCore_Qt.ConnectionType.QueuedConnection)
        else:
            self._pending_update = None
            QMetaObject.invokeMethod(self, "_show_up_to_date", QtCore_Qt.ConnectionType.QueuedConnection)

    from PyQt6.QtCore import pyqtSlot

    @pyqtSlot()
    def _show_update_available(self):
        release = getattr(self, "_pending_update", None)
        if not release:
            return
        # Update the label in INFO tab footer
        self.update_status_label.setText("🔔 Update Available!")
        self.update_status_label.setStyleSheet("color: #FFA726; font-size: 11px; font-weight: bold;")
        # Show the update dialog
        dialog = UpdateDialog(release, self)
        dialog.exec()

    @pyqtSlot()
    def _show_up_to_date(self):
        self.update_status_label.setText("✔ Up to date")
        self.update_status_label.setStyleSheet("color: #4CAF50; font-size: 11px;")

    def browse_model(self):

        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select YOLO Model", "", "YOLO Models (*.pt *.onnx *.engine);;All Files (*)"
        )
        if file_path:
            self.model_input.setText(file_path)

    def _on_config_file_changed(self, path: str):
        """Called by QFileSystemWatcher when config.json is modified externally."""
        # Re-add the file to watcher (some editors like VS Code do delete+recreate on save)
        if path not in self._config_watcher.files():
            self._config_watcher.addPath(path)
        # Delay 150ms to allow the editor to finish writing the file before we read it
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(150, self.refresh_config_view)

    def refresh_config_view(self):
        import json
        config.reload()
        display_text = f"TARGET PATH: {config._path}\n\n{json.dumps(config._data, indent=2)}"
        self.config_text.setPlainText(display_text)

    def save_settings(self):
        # Gather data
        diff = self.diff_group.checkedButton().text()
        mods = [m for m, cb in self.mod_checks.items() if cb.isChecked()]
        obj = self.obj_group.checkedButton().text() if self.obj_group.checkedButton() else "Guard"
        char = self.char_group.checkedButton().text() if self.char_group.checkedButton() else "Auto (Highest Stats)"

        # Phase 96: Reload disk config first, so we don't erase manual edits to scroll_amount etc.
        config.reload()

        # Update config
        if "strategy" not in config._data:
            config._data["strategy"] = {}
        
        config._data["strategy"]["difficulty"] = diff
        config._data["strategy"]["modifiers"] = mods
        config._data["strategy"]["objective"] = obj
        config._data["strategy"]["character_slot"] = char
        
        if "bot" not in config._data:
            config._data["bot"] = {}
        config._data["bot"]["eyes_only"] = self.eyes_only_cb.isChecked()
        config._data["bot"]["show_overlay"] = self.show_overlay_cb.isChecked() # Phase +125 Fix
        config._data["bot"]["model_path"] = self.model_input.text().strip()
        try:
            config._data["bot"]["modifier_scroll_amount"] = int(self.scroll_input.text().strip())
        except ValueError:
            pass # Keep previous if invalid
            
        # Phase 111/118: Save Brightness & Speed
        if "screen" not in config._data:
            config._data["screen"] = {}
        try:
            config._data["screen"]["brightness_multiplier"] = float(self.bright_input.text().strip())
        except ValueError:
            pass
            
        config._data["bot"]["bot_speed"] = self.speed_spin.value()
        config._data["bot"]["target_fps"] = self.fps_spin.value()
        config._data["bot"]["target_fps_annie_mark"] = self.fps_annie_spin.value()
        
        # Detection Settings
        if "detection" not in config._data:
            config._data["detection"] = {}
        config._data["detection"]["confidence_threshold"] = float(self.conf_spin.value())
        
        # Aim Assist Settings
        if "aim_assist" not in config._data:
            config._data["aim_assist"] = {}
        config._data["aim_assist"]["show_fov_circle"] = self.show_fov_cb.isChecked()
        config._data["aim_assist"]["show_ipm_line"]   = self.show_ipm_line_cb.isChecked()
        config._data["aim_assist"]["fov_radius"] = self.fov_spin.value()
        config._data["aim_assist"]["p_gain"] = self.pgain_spin.value()
        config._data["aim_assist"]["max_delta"] = self.maxd_spin.value()
        config._data["aim_assist"]["measurement_var"] = self.kalman_spin.value()
        config._data["aim_assist"]["max_detection_speed_px_s"] = self.halluc_spin.value()
        config._data["aim_assist"]["global_offset_x"] = self.offset_x_spin.value()
        config._data["aim_assist"]["global_offset_y"] = self.offset_y_spin.value()
        # Prediction Feature Toggles
        config._data["aim_assist"]["kalman_enabled"]          = self.kalman_enabled_cb.isChecked()
        config._data["aim_assist"]["dampening_enabled"]       = self.dampening_enabled_cb.isChecked()
        config._data["aim_assist"]["dead_reckoning_enabled"]  = self.dead_reckoning_enabled_cb.isChecked()
        config._data["aim_assist"]["lead_prediction_enabled"] = self.lead_prediction_enabled_cb.isChecked()
        
        # Combat Engine Timing
        if "combat_engine" not in config._data:
            config._data["combat_engine"] = {}
        config._data["combat_engine"]["use_hybrid_ipm"] = self.use_ipm_cb.isChecked()
        config._data["combat_engine"]["enable_lag_compensation"] = self.lag_comp_cb.isChecked()
        config._data["combat_engine"]["lag_comp_max_mult"] = self.lag_mult_spin.value()
        config._data["combat_engine"]["base_click_duration_ms"] = self.base_click_ms_spin.value()
        config._data["combat_engine"]["use_assault_click"] = self.use_assault_click_cb.isChecked()
        config._data["combat_engine"]["assault_key_click_delay"] = float(self.click_delay_spin.value() / 1000.0)
        config._data["combat_engine"]["startup_delay"] = self.startup_spin.value()
        config._data["combat_engine"]["aim_memory_duration"] = self.memory_spin.value()
        config._data["combat_engine"]["approach_qe_hold_bonus"] = self.qe_hold_spin.value()
        config._data["combat_engine"]["static_macro_max_duration"] = self.static_dur_spin.value()
        config._data["combat_engine"]["assault_duration_first"] = self.assault_first_spin.value()
        config._data["combat_engine"]["assault_duration"] = self.assault_spin.value()
        config._data["combat_engine"]["cooldown_duration"] = self.cooldown_spin.value()
        config._data["combat_engine"]["annie_mark_y_offset"] = self.yoffset_spin.value()
        
        # OCR Debug Mode
        if "reward_regions" not in config._data:
            config._data["reward_regions"] = {}
        config._data["reward_regions"]["debug_mode"] = self.ocr_debug_cb.isChecked()

        # Discord Bot Settings
        if "discord_bot" not in config._data:
            config._data["discord_bot"] = {}
        config._data["discord_bot"]["enabled"] = self.discord_enabled_cb.isChecked()
        config._data["discord_bot"]["token"] = self.discord_token_input.text().strip()
        config._data["discord_bot"]["admin_user_id"] = self.discord_admin_input.text().strip()
        config._data["discord_bot"]["webhook_url"] = self.discord_webhook_input.text().strip()
        config._data["discord_bot"]["reward_webhook_url"] = self.discord_reward_webhook_input.text().strip()
        
        # Window Management Settings
        if "window_management" not in config._data:
            config._data["window_management"] = {}
        config._data["window_management"]["enable_process_monitor"] = self.win_proc_cb.isChecked()
        config._data["window_management"]["enable_auto_focus"] = self.win_focus_cb.isChecked()
        try:
            config._data["window_management"]["reconnect_delay_minutes"] = int(self.reconnect_delay_input.text().strip())
        except ValueError:
            pass
            
        # Apply Game Resolution (1080p vs 2K) dynamically
        target_w = 2560 if self.res_combo.currentIndex() == 1 else 1920
        target_h = 1440 if self.res_combo.currentIndex() == 1 else 1080
        current_w = config._data.get("screen", {}).get("width", 1920)
        current_h = config._data.get("screen", {}).get("height", 1080)
        
        if current_w != target_w:
            ratio_x = target_w / current_w
            ratio_y = target_h / current_h
            
            if "screen" not in config._data:
                config._data["screen"] = {}
            config._data["screen"]["width"] = target_w
            config._data["screen"]["height"] = target_h
            
            if "coordinates" in config._data:
                for k, v in config._data["coordinates"].items():
                    if isinstance(v, list) and len(v) == 2:
                        config._data["coordinates"][k] = [int(round(v[0] * ratio_x)), int(round(v[1] * ratio_y))]
                        
            if "reward_regions" in config._data:
                for k, v in config._data["reward_regions"].items():
                    if isinstance(v, list) and len(v) == 4:
                        config._data["reward_regions"][k] = [
                            int(round(v[0] * ratio_x)), int(round(v[1] * ratio_y)),
                            int(round(v[2] * ratio_x)), int(round(v[3] * ratio_y))
                        ]
                        
            if "aim_assist" in config._data and "fov_radius" in config._data["aim_assist"]:
                config._data["aim_assist"]["fov_radius"] = int(round(config._data["aim_assist"]["fov_radius"] * ratio_x))
                
            if "bot" in config._data and "modifier_scroll_amount" in config._data["bot"]:
                scaled_scroll = int(round(config._data["bot"]["modifier_scroll_amount"] * ratio_y))
                config._data["bot"]["modifier_scroll_amount"] = scaled_scroll
                self.scroll_input.setText(str(scaled_scroll))
        
        config.save()
        self.refresh_config_view() # Update live viewer instantly
        self.saved.emit()
        


    def save_and_start(self):
        self.save_settings()
        self.started.emit()
        self.close()

    def on_reload_clicked(self):
        """Phase 1001: Save settings and trigger hot-reload."""
        self.save_settings()
        self.reloaded.emit()

    def force_kill_script(self):
        import os
        os.system(f"taskkill /f /pid {os.getpid()}")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and hasattr(self, 'drag_pos'):
            self.move(event.globalPosition().toPoint() - self.drag_pos)
            event.accept()

    def _stop_hotkey_triggered(self):
        if self.auto_enhance_running:
            self.auto_enhance_running = False
            self.enhance_btn.setText("START AUTO ENHANCE")
            self.enhance_btn.setStyleSheet("background-color: #1976D2; color: #fff; padding: 10px; font-weight: bold; border-radius: 5px;")

    def toggle_auto_enhance(self):
        if self.auto_enhance_running:
            self._stop_hotkey_triggered()
        else:
            self.auto_enhance_running = True
            self.enhance_btn.setText("STOP AUTO ENHANCE")
            self.enhance_btn.setStyleSheet("background-color: #D32F2F; color: #fff; padding: 10px; font-weight: bold; border-radius: 5px;")
            
            import threading
            threading.Thread(target=self._auto_enhance_loop, daemon=True).start()

    def _auto_enhance_loop(self):
        import time
        import pydirectinput
        try:
            import keyboard
        except ImportError:
            pass # Fallback if keyboard isn't installed
        
        x_add, y_add = 1754, 786
        x_enh, y_enh = 1760, 988
        
        while self.auto_enhance_running:
            # Check hotkey
            if 'keyboard' in locals() and keyboard.is_pressed('f8'):
                self.stop_enhance_signal.emit()
                break
                
            if not self.auto_enhance_running: break
            pydirectinput.click(x=x_add, y=y_add)
            time.sleep(0.3)
            
            if 'keyboard' in locals() and keyboard.is_pressed('f8'):
                self.stop_enhance_signal.emit()
                break
                
            if not self.auto_enhance_running: break
            pydirectinput.click(x=x_enh, y=y_enh)
            time.sleep(0.3)


# ─────────────────────────────────────────────────────────────────────────────
# Update Dialog — Premium styled, matching the L.A.R.P. dark theme
# ─────────────────────────────────────────────────────────────────────────────
class UpdateDialog(QDialog):
    """A styled update prompt that notifies the user of a new L.A.R.P. release."""

    def __init__(self, release: dict, parent=None):
        super().__init__(parent)
        from bot.updater import CURRENT_VERSION, open_release_page

        self.release_url = release.get("html_url", "")
        self.open_release_page = open_release_page

        self.setWindowTitle("L.A.R.P — Update Available")
        self.setFixedSize(480, 320)
        self.setModal(True)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)

        self.setStyleSheet("""
            QDialog {
                background-color: #1A1A1A;
                border: 1px solid #2196F3;
                border-radius: 10px;
            }
            QLabel { color: #B0B0B0; font-family: 'Inter', 'Roboto', 'Segoe UI', sans-serif; }
            QTextEdit {
                background-color: #121212;
                color: #888888;
                border: 1px solid #333333;
                border-radius: 4px;
                font-size: 11px;
                font-family: 'Consolas', monospace;
                padding: 6px;
            }
            QPushButton {
                border-radius: 5px;
                padding: 9px 20px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton#DownloadBtn {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2196F3, stop:1 #1565C0);
                color: #FFFFFF;
                border: 1px solid #0D47A1;
            }
            QPushButton#DownloadBtn:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #42A5F5, stop:1 #1976D2);
            }
            QPushButton#LaterBtn {
                background-color: #2A2A2A;
                color: #888888;
                border: 1px solid #444444;
            }
            QPushButton#LaterBtn:hover {
                background-color: #383838;
                color: #AAAAAA;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        # Header
        header_layout = QHBoxLayout()
        badge = QLabel("NEW RELEASE")
        badge.setStyleSheet(
            "color: #2196F3; font-size: 10px; font-weight: bold; "
            "background-color: #1A2D3D; border: 1px solid #2196F3; "
            "border-radius: 3px; padding: 2px 6px;"
        )
        header_layout.addWidget(badge)
        header_layout.addStretch()
        close_x = QPushButton("✕")
        close_x.setFixedSize(24, 24)
        close_x.setStyleSheet(
            "QPushButton { background: transparent; color: #555; border: none; font-size: 14px; }"
            "QPushButton:hover { color: #FFF; }"
        )
        close_x.clicked.connect(self.reject)
        header_layout.addWidget(close_x)
        layout.addLayout(header_layout)

        # Title
        title = QLabel(f"Update Available: v{release.get('tag_name', '?')}")
        title.setStyleSheet("color: #FFFFFF; font-size: 16px; font-weight: bold;")
        layout.addWidget(title)

        subtitle = QLabel(f"You are on <b>v{CURRENT_VERSION}</b>. The latest version is <b>v{release.get('tag_name', '?')}</b>.")
        subtitle.setStyleSheet("color: #888888; font-size: 12px;")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # Release Notes
        notes_label = QLabel("Release Notes:")
        notes_label.setStyleSheet("color: #666666; font-size: 11px;")
        layout.addWidget(notes_label)

        notes_box = QTextEdit()
        notes_box.setReadOnly(True)
        notes_box.setFixedHeight(80)
        notes_box.setPlainText(release.get("body", "No release notes provided."))
        layout.addWidget(notes_box)

        layout.addStretch()

        # Buttons
        btn_layout = QHBoxLayout()
        later_btn = QPushButton("Later")
        later_btn.setObjectName("LaterBtn")
        later_btn.clicked.connect(self.reject)

        download_btn = QPushButton("⬇  Download Now")
        download_btn.setObjectName("DownloadBtn")
        download_btn.clicked.connect(self._on_download)

        btn_layout.addWidget(later_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(download_btn)
        layout.addLayout(btn_layout)

    def _on_download(self):
        self.open_release_page(self.release_url)
        self.accept()


if __name__ == "__main__":

    from PyQt6.QtWidgets import QApplication
    app = QApplication([])
    window = SettingsWindow()
    window.show()
    app.exec()
