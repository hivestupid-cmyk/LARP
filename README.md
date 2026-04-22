# L.A.R.P — AOTR Bot v1

**L.A.R.P** (Logic AI Robotic Program) is an AI-powered bot for **Attack on Titan: Revolution (AOTR)** on Roblox. It uses a real-time YOLO object detection model to automate gameplay — targeting, combat, reconnecting, and more.

> This is the runtime package. Training tools, datasets, and dev utilities are excluded.

---

## Features

- **AI Combat Engine** — Real-time YOLO detection with Kalman-filter aim assist and dynamic lead prediction
- **Auto-Reconnect** — Monitors Roblox logs and automatically relaunches on disconnect (Error 277, 279, 529, etc.)
- **Macro Playback** — Static approach macro + dynamic airborne pendulum combat engine
- **Discord Integration** — Live status notifications, reward tracking, and remote control via Discord bot and webhooks
- **Settings GUI** — Full PyQt6 settings panel with hot-reload support
- **Debug Overlay** — On-screen detection visualization with FOV circle

---

## Requirements

- **OS:** Windows 10/11
- **Python:** 3.10+
- **GPU:** NVIDIA GPU strongly recommended (for real-time YOLO inference)
- **Roblox:** Must be running before the bot starts

---

## Setup

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Place Your YOLO Model
Copy your trained model into `assets/models/`:

| Format | Status | Notes |
|---|---|---|
| `best.pt` | Supported | PyTorch — requires CUDA for GPU inference |
| `best.onnx` | Not yet supported | Planned for a future release |
| `best.engine` | Not yet supported | Planned for a future release |

The bot auto-detects the latest `train_YYYYMMDD_HHMM` subfolder inside `assets/models/` and loads `best.pt` from it.

To point to a specific model file, set `model_path` in `config.json`:
```json
"model_path": "assets/models/train_20260405_0650/best.pt"
```
Paths can be relative (resolved from the project folder) or absolute.

### 3. Configure
```bash
# Copy the example config and fill in your values
cp config.example.json config.json
```

Edit `config.json` with:
- Your Discord bot token and webhook URLs (optional)
- Your screen resolution (`screen.width` / `screen.height`)
- Your macro file path (optional — leave empty for Dynamic Combat only)

### 4. Run
```bash
python main.py
```

---

## Hotkeys (Default)

| Key | Action |
|---|---|
| `F1` | Start / Resume bot |
| `F2` | Pause bot (opens Settings GUI) |
| `F3` | Stop and Exit |

Hotkeys are configurable in `config.json` under `"bot"`.

---

## Project Structure

```
L.A.R.Pv1/
├── main.py                  <- Entry point
├── config.json              <- Your config (not tracked by git)
├── config.example.json      <- Config template (safe to share)
├── requirements.txt
├── bot/
│   ├── brain.py             <- Core state machine
│   ├── engine.py            <- Bot thread manager
│   ├── in_game_macro.py     <- Combat macro and aim assist
│   ├── detector.py          <- YOLO AI detection
│   ├── screen.py            <- Screen capture
│   ├── controller.py        <- Mouse and keyboard input
│   ├── reconnect.py         <- Auto-reconnect watchdog
│   ├── discord_bot.py       <- Discord integration
│   ├── settings_gui.py      <- Settings GUI (PyQt6)
│   ├── overlay.py           <- On-screen debug overlay
│   ├── ocr_utils.py         <- Reward detection (OCR)
│   ├── config.py            <- Config loader
│   └── templates/           <- Reward icon templates
├── assets/
│   └── models/              <- Place YOLO model here (not tracked by git)
└── logs/                    <- Runtime logs (auto-created, not tracked by git)
```

---

## Discord Setup (Optional)

1. Create a Discord bot at [discord.com/developers](https://discord.com/developers)
2. Copy the bot token into `config.json` under `discord_bot.token`
3. Create a webhook in your Discord server and paste the URL into `webhook_url`
4. Invite the bot to your server with `Send Messages` and `Read Messages` permissions

---

## Notes

- `config.json` is excluded from git (contains your private tokens). Use `config.example.json` as the template.
- AI model files (`*.pt`) are excluded from git due to their size. Distribute separately.
- The bot sets its working directory to the project root on startup — it can be run from any location.

---

## License

Copyright (c) 2026 SGOD. All Rights Reserved.

This project is licensed under a custom proprietary license. See [LICENSE](LICENSE) for full terms.

**In short:**
- You may view and use this software for personal, non-commercial purposes.
- You may NOT redistribute, sell, publish, or claim this software as your own.
- Modified versions may NOT be shared publicly without written permission.
