# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [v1.0.0-beta] - 2026-04-22

This is the initial open-source release of the L.A.R.P (Logic AI Robotic Program) bot. 
As a beta release, core functionality is implemented but stability improvements and bug fixes are ongoing.

### Added
- **AI Core:** Integrated real-time YOLO object detection for identifying Titans and key game elements.
- **Combat Engine:** Implemented Kalman-filter based aim assist and dynamic pendulum combat approach.
- **Discord Integration:** Added both Discord Bot control commands and Webhook support for live status and reward tracking.
- **Settings GUI:** Created a PyQt6 settings panel allowing real-time hot-reloading of configurations without restarting the bot.
- **Auto-Reconnect Watchdog:** Built a system to detect Roblox disconnects (Errors 277, 279, 529) via log scanning and automatically resume farming.
- **Automated Setup:** Included `install.bat` to streamline Python package installation and environment setup for users.
- **Documentation:** Added comprehensive `README.md`, `STRATEGY.md` for recommended in-game builds, and FAQ.

### Known Issues
- Very high graphic settings or unusual in-game fog/weather can occasionally reduce YOLO detection confidence (false positives/negatives).
- PyTorch/CUDA environment setup relies on user hardware compatibility; extreme edge-case driver issues may require manual intervention.
