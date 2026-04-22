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

### Option A — Automatic (Recommended)
Double-click **`install.bat`** — it will:
1. Check your Python version
2. Ask if you have an NVIDIA GPU and install the correct PyTorch build
3. Install all remaining dependencies
4. Create `config.json` from the template
5. Create required folders

Then place your model in `assets/models/` and double-click **`run.bat`** to start.

---

### Option B — Manual

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

## Recommended Build (AOTR)

> **This section is a recommendation, not a requirement.** The bot can run on any build,
> but the configurations below are optimized to get the best possible performance and efficiency
> from the automation. Deviating significantly from the recommended perks may noticeably reduce results.

---

### Family

The following families are recommended for their passive stat bonuses and extra perk slots, which synergize well with the Thunder Spear build this bot is designed around.

---

#### Helos — Mythical
The strongest dedicated ODM family in the game. Cannot become a Titan Shifter, but in return offers an exceptional all-round stat boost for ODM combat.

| Stat | Bonus |
|---|---|
| CRIT Chance / Damage | +20% |
| ODM / TS Damage | +30% |
| ODM / TS Control / Gas / Range / Speed | +15% |
| Blade Durability / Conservation Chance | +15% / +7.5% |
| Cooldown Reduction | +10% |
| Boost Dash | +1 |
| Extra Perk Slots | +1 Offense, +1 Support |

---

#### Shiki — Secret Mythical
The rarest family in the game, unlocked by collecting 64 Achievements (Apex achievement). Offers the highest raw damage bonus and the most Boost Dashes.

| Stat | Bonus |
|---|---|
| CRIT Chance / Damage | +15% |
| Damage | +20% |
| Damage in Raids | +20% |
| ODM Control / Gas / Range | +10% |
| Luck Boost | +7.5% |
| Boost Dash | +2 |
| Extra Perk Slots | +1 Core |

---

#### Ackerman — Legendary
A more accessible choice compared to Mythical families. Cannot become a Titan Shifter. Offers solid all-round bonuses with an extra Offensive Perk Slot and a Double Jump, which helps with positioning during combat.

| Stat | Bonus |
|---|---|
| Damage | +20% |
| Damage in Raids | +20% |
| Critical Chance / Damage | +15% |
| ODM Control / Gas / Range | +10% |
| Boost Dash | +1 |
| Jump | +1 (Double Jump) |
| Extra Perk Slots | +1 Offense |

---

### Perks

#### Required Perks
These three perks are considered **essential**. Removing any of them will result in a noticeable drop in bot performance.

| Perk | Effect |
|---|---|
| **Everlasting Flame** | Increases Thunder Spear blast radius and ignites titans hit by the explosion |
| **Maximum Firepower** | Increases ammo capacity to 4 spears, boosts spear projectile speed by 40%, and raises all stats by 7.5% |
| **Explosive Fortune** | Adds 10% conservation chance and a 5% chance to gain +1 spear on titan kill |

#### Optional Perks
These perks provide meaningful bonuses and are recommended if available.

| Perk | Effect |
|---|---|
| **Kengo** | +40% Thunder Spear damage, +10% conservation chance, and allows spears to hit two titan body parts simultaneously |
| **Immortal** | Survivability perk — useful for maintaining uptime during extended sessions |

---

### Stats Priority

Maximize the following stats in this order for best results:

1. **Conservation Chance** — directly increases spear sustainability
2. **Thunder Spear Damage** — higher burst damage means faster titan kills
3. **Critical Chance** — amplifies overall damage output
4. **Blast Radius** — increases AOE effectiveness per spear hit

---

### Skills and Talents

#### Recommended Skill Loadout

| Slot | Skill | Notes |
|---|---|---|
| 1 | **Grasp Blast** | Detonate a thunder spear when grabbed |
| 2 | **Combustive Counter** | Grasp Blast but instant kill a titan |
| 3 | **Acoustic Shells** | Aggro all titans within 750m range |
| 4-5 | *(free choice)* | Any preferred utility skill |

#### Recommended Talent

| Talent | Reason |
|---|---|
| **Survivalist** | Grants "Grab Escaping" skills +20% conservation chance — directly boosts spear uptime, which the bot depends on heavily |

---

### Objective

The bot currently **only supports the Guard objective**. Other objectives are not yet implemented.

---

### Recommended Modifiers

Stacking the modifiers below maximizes Gold and EXP bonus multipliers per run:

| Modifier | Type |
|---|---|
| No Skills | Difficulty |
| No Talents | Difficulty |
| Nightmare | Difficulty |
| Oddball | Difficulty |
| Injury Prone | Difficulty |
| Chronic Injuries | Difficulty |
| Fog | Difficulty |
| Glass Cannon | Difficulty |
| Time Trial | Difficulty |

> These modifiers increase reward multipliers without fundamentally changing the combat flow
> that the bot is designed around, making them safe to stack for farming efficiency.

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

- **Screen Resolution:** The bot natively supports **1080p** and **1440p** displays. You can configure your exact screen width and height in the Settings GUI.
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
