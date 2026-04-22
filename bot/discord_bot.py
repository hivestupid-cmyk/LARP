import discord
from discord.ext import commands
import threading
import asyncio
import time
import logging
import io
import cv2
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class DiscordBot:
    """
    A lightweight Discord Bot wrapper that runs in a background thread.
    Allows users to query the bot's state and stats via commands.
    """
    def __init__(self, config_obj, brain=None):
        self.brain = brain
        self.config_obj = config_obj
        # Resolve config access (Brain uses a wrapper, but we check raw too)
        self.bot_config = config_obj.get("discord_bot", {})
        
        self.enabled = self.bot_config.get("enabled", False)
        self.token = self.bot_config.get("token", "")
        self.admin_id = str(self.bot_config.get("admin_user_id", ""))
        self.webhook_url = self.bot_config.get("webhook_url", "").strip()
        self.reward_webhook_url = self.bot_config.get("reward_webhook_url", "").strip()
        
        # Support commands with or without "!" prefix
        self.prefix = ("", "!")
        
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.bot: Optional[commands.Bot] = None
        
        self.pause_callback = None
        self.reload_callback = None
        
        if not self.enabled:
            logger.info("[Discord] Bot is disabled in config.")
            return
            
        if not self.token:
            logger.warning("[Discord] Bot enabled but token is missing!")
            return

        self.thread = threading.Thread(target=self._run_thread, name="DiscordBotThread", daemon=True)
        self.thread.start()

    def set_brain(self, brain):
        """Link the bot to the actual macro brain once the engine starts."""
        self.brain = brain
        if self.brain:
            self.brain.discord_bot_instance = self

    def send_notification(self, message: str, edit_category=None, frame=None):
        """Thread-safe method to send a notification. Routes to webhook if configured, else DM."""
        if not self.enabled or not self.bot or not self.loop:
            return
        asyncio.run_coroutine_threadsafe(self._async_send_notification(message, edit_category, frame), self.loop)

    async def _async_send_notification(self, message: str, edit_category=None, frame=None):
        """Send or edit a notification. Uses webhook (preferred) or DM fallback."""
        if not self.admin_id:
            return

        try:
            if not hasattr(self, "_edit_msgs"):
                self._edit_msgs = {}
            if not hasattr(self, "_webhook_msg_ids"):
                self._webhook_msg_ids = getattr(self, "bot_config", {}).get("webhook_msg_ids", {})

            ts = datetime.now().strftime("%H:%M:%S")
            final_msg = f"[`{ts}`] {message}"

            # Encode frame if provided
            img_bytes = None
            img_filename = f"live_{edit_category or 'img'}.png"
            if frame is not None:
                success, buffer = cv2.imencode(".png", frame)
                if success:
                    img_bytes = buffer.tobytes()

            webhook_url = getattr(self, "webhook_url", "")

            if webhook_url:
                # Semua notifikasi lewat webhook jika URL tersedia
                # edit_category=None → kirim pesan baru (tidak di-edit)
                # edit_category=xxx  → edit pesan sebelumnya
                await self._webhook_send_or_edit(
                    webhook_url, edit_category, final_msg, img_bytes, img_filename
                )
            else:
                # DM fallback (text-only edit, no attachment editing)
                user = await self.bot.fetch_user(int(self.admin_id))
                if user:
                    if edit_category:
                        existing = self._edit_msgs.get(edit_category)
                        if existing:
                            if img_bytes:
                                # DM cannot edit attachments — delete and resend
                                try: await existing.delete()
                                except Exception: pass
                                self._edit_msgs[edit_category] = None
                            else:
                                try:
                                    await existing.edit(content=final_msg)
                                    return
                                except Exception:
                                    self._edit_msgs[edit_category] = None

                        if img_bytes:
                            buf = io.BytesIO(img_bytes)
                            file = discord.File(buf, filename=img_filename)
                            self._edit_msgs[edit_category] = await user.send(final_msg, file=file)
                        else:
                            self._edit_msgs[edit_category] = await user.send(final_msg)
                    else:
                        if img_bytes:
                            buf = io.BytesIO(img_bytes)
                            file = discord.File(buf, filename=img_filename)
                            await user.send(final_msg, file=file)
                        else:
                            await user.send(final_msg)
        except Exception as e:
            logger.error(f"[Discord] Failed to send notification: {e}")

    def _save_webhook_ids(self):
        """Helper to persist webhook msg IDs to config.json avoiding spam on restart."""
        if hasattr(self, "config_obj"):
            section = self.config_obj._data.setdefault("discord_bot", {})
            section["webhook_msg_ids"] = getattr(self, "_webhook_msg_ids", {})
            self.config_obj.save()

    async def _webhook_send_or_edit(self, webhook_url: str, category: str,
                                     content: str, img_bytes=None, filename="image.png", force_repost=False):
        """Send or edit a webhook message for a given category. Supports images natively."""
        import aiohttp, json as _json
        
        if not hasattr(self, "_webhook_msg_ids"):
            self._webhook_msg_ids = getattr(self, "bot_config", {}).get("webhook_msg_ids", {})
            
        # category=None → one-off alert, selalu kirim pesan baru (tidak di-edit)
        msg_id = self._webhook_msg_ids.get(category) if category else None
        
        try:
            async with aiohttp.ClientSession() as session:
                if msg_id and force_repost:
                    try: await session.delete(f"{webhook_url}/messages/{msg_id}")
                    except Exception: pass
                    msg_id = None
                    if category:
                        self._webhook_msg_ids[category] = None
                        self._save_webhook_ids()

                if msg_id:
                    # PATCH existing webhook message
                    edit_url = f"{webhook_url}/messages/{msg_id}"
                    if img_bytes:
                        # Wrap bytes in BytesIO untuk kompatibilitas aiohttp
                        file_buf = io.BytesIO(img_bytes)
                        data = aiohttp.FormData()
                        data.add_field(
                            "payload_json",
                            _json.dumps({"content": content, "attachments": [{"id": "0"}]}),
                            content_type="application/json"
                        )
                        data.add_field("files[0]", file_buf,
                                       filename=filename, content_type="image/png")
                        async with session.patch(edit_url, data=data) as resp:
                            if resp.status == 200:
                                pass  # OK
                            elif resp.status == 404:
                                logger.warning("[Discord] Webhook msg 404 (deleted), re-posting [%s]", category)
                                self._webhook_msg_ids[category] = None
                                self._save_webhook_ids()
                                await self._webhook_send_or_edit(webhook_url, category, content, img_bytes, filename)
                            else:
                                # Rate limit atau error lain — simpan msg_id, skip tick ini
                                # JANGAN re-POST, itu penyebab spam!
                                err_body = await resp.text()
                                logger.debug("[Discord] Webhook PATCH image skip (status %d) [%s]: %s",
                                             resp.status, category, err_body[:120])
                    else:
                        async with session.patch(edit_url, json={"content": content}) as resp:
                            if resp.status == 200:
                                pass  # OK
                            elif resp.status == 404:
                                logger.warning("[Discord] Webhook msg 404 (deleted), re-posting [%s]", category)
                                self._webhook_msg_ids[category] = None
                                self._save_webhook_ids()
                                await self._webhook_send_or_edit(webhook_url, category, content)
                            else:
                                # Rate limit atau error lain — simpan msg_id, skip tick ini
                                err_body = await resp.text()
                                logger.debug("[Discord] Webhook PATCH text skip (status %d) [%s]: %s",
                                             resp.status, category, err_body[:120])
                else:
                    # POST new message with ?wait=true to get message ID back
                    post_url = f"{webhook_url}?wait=true"
                    if img_bytes:
                        file_buf = io.BytesIO(img_bytes)
                        data = aiohttp.FormData()
                        data.add_field(
                            "payload_json",
                            _json.dumps({"content": content}),
                            content_type="application/json"
                        )
                        data.add_field("files[0]", file_buf,
                                       filename=filename, content_type="image/png")
                        async with session.post(post_url, data=data) as resp:
                            if resp.status == 200:
                                msg = await resp.json()
                                if category:
                                    self._webhook_msg_ids[category] = msg.get("id")
                                    self._save_webhook_ids()
                            else:
                                err_body = await resp.text()
                                logger.warning("[Discord] Webhook POST image failed (status %d) [%s]: %s",
                                               resp.status, category, err_body[:200])
                    else:
                        async with session.post(post_url, json={"content": content}) as resp:
                            if resp.status == 200:
                                msg = await resp.json()
                                if category:
                                    self._webhook_msg_ids[category] = msg.get("id")
                                    self._save_webhook_ids()
                            else:
                                err_body = await resp.text()
                                logger.warning("[Discord] Webhook POST text failed (status %d) [%s]: %s",
                                               resp.status, category, err_body[:200])
        except Exception as e:
            logger.error(f"[Discord] Webhook send/edit failed ({category}): {e}")

    def send_notification_with_image(self, message: str, frame):
        """Thread-safe method to send a reward notification with image."""
        if not self.enabled or not self.bot or not self.loop or frame is None:
            return
        asyncio.run_coroutine_threadsafe(self._async_send_notification_with_image(message, frame), self.loop)

    async def _async_send_notification_with_image(self, message: str, frame):
        """Send reward notification with image. Uses webhook if available, else DM."""
        if not self.admin_id:
            return

        try:
            if not hasattr(self, "reward_match_count"):
                self.reward_match_count = 0
            self.reward_match_count += 1

            success, buffer = cv2.imencode(".png", frame)
            if not success:
                logger.error("[Discord] Failed to encode reward frame.")
                return

            img_bytes = buffer.tobytes()
            ts = datetime.now().strftime("%H:%M:%S")
            title = f"**REWARD (Game {self.reward_match_count})**"
            final_msg = f"[`{ts}`] {title}\n{message}"
            filename = "latest_reward.png"

            reward_url = getattr(self, "reward_webhook_url", "")
            
            if not reward_url:
                # Mandatory Rule: If no specific reward URL, never send (no fallback)
                logger.debug("[Discord] Reward Notification cancelled: 'Reward Webhook' field is empty in settings!")
                return

            webhook_url = reward_url
            reward_cat = None 
            force_rep = False

            if webhook_url:
                await self._webhook_send_or_edit(webhook_url, reward_cat, final_msg, img_bytes, filename, force_repost=force_rep)
            else:
                # DM fallback: delete old, send new
                user = await self.bot.fetch_user(int(self.admin_id))
                if user:
                    if hasattr(self, "_last_reward_msg") and self._last_reward_msg:
                        try: await self._last_reward_msg.delete()
                        except Exception: pass
                        self._last_reward_msg = None
                    buf = io.BytesIO(img_bytes)
                    file = discord.File(buf, filename=filename)
                    self._last_reward_msg = await user.send(final_msg, file=file)
        except Exception as e:
            logger.error(f"[Discord] Failed to send reward notification: {e}")

    def send_reward_session_ended(self):
        """Thread-safe method to notify reward channel that a bot session ended."""
        if not self.enabled or not self.loop: return
        msg = "🛑 **Main Bot Stopped**\n*A new session boundary has been marked. Ready for next run.*"
        
        async def _async_send():
            reward_url = getattr(self, "reward_webhook_url", "")
            if reward_url:
                await self._webhook_send_or_edit(reward_url, None, msg)
                
        asyncio.run_coroutine_threadsafe(_async_send(), self.loop)

    def send_emergency_notification(self, message: str, frame=None):
        """Send emergency log (e.g. Disconnect, Stuck) and track it for later deletion."""
        if not self.enabled or not self.bot or not self.loop: return
        asyncio.run_coroutine_threadsafe(self._async_send_emergency_notification(message, frame), self.loop)

    async def _async_send_emergency_notification(self, message: str, frame=None):
        if not self.admin_id: return
        if not hasattr(self, "emergency_msgs"): self.emergency_msgs = []
        import aiohttp, json as _json

        ts = datetime.now().strftime("%H:%M:%S")
        final_msg = f"[`{ts}`] {message}"

        img_bytes = None
        if frame is not None:
             success, buffer = cv2.imencode(".png", frame)
             if success: img_bytes = buffer.tobytes()

        webhook_url = getattr(self, "webhook_url", "")
        if webhook_url:
            try:
                async with aiohttp.ClientSession() as session:
                    post_url = f"{webhook_url}?wait=true"
                    if img_bytes:
                        file_buf = io.BytesIO(img_bytes)
                        data = aiohttp.FormData()
                        data.add_field("payload_json", _json.dumps({"content": final_msg}), content_type="application/json")
                        data.add_field("files[0]", file_buf, filename="emergency.png", content_type="image/png")
                        async with session.post(post_url, data=data) as resp:
                            if resp.status == 200:
                                msg_data = await resp.json()
                                self.emergency_msgs.append({"type": "webhook", "url": webhook_url, "id": msg_data.get("id")})
                    else:
                        async with session.post(post_url, json={"content": final_msg}) as resp:
                            if resp.status == 200:
                                msg_data = await resp.json()
                                self.emergency_msgs.append({"type": "webhook", "url": webhook_url, "id": msg_data.get("id")})
            except Exception as e:
                logger.error(f"[Discord] Emergency Webhook send failed: {e}")
        else:
            try:
                user = await self.bot.fetch_user(int(self.admin_id))
                if user:
                    if img_bytes:
                        buf = io.BytesIO(img_bytes)
                        file = discord.File(buf, filename="emergency.png")
                        sent_msg = await user.send(final_msg, file=file)
                    else:
                        sent_msg = await user.send(final_msg)
                    self.emergency_msgs.append({"type": "dm", "msg": sent_msg})
            except Exception as e:
                 logger.error(f"[Discord] Emergency DM send failed: {e}")

    def clear_emergency_messages(self):
        """Deletes all tracked emergency messages to clean up the chat log."""
        if not self.enabled or not self.loop: return
        asyncio.run_coroutine_threadsafe(self._async_clear_emergency_messages(), self.loop)

    def clear_emergency_messages_sync(self):
        """Deletes all tracked emergency messages synchronously (blocks caller)."""
        if not self.enabled or not self.loop: return
        future = asyncio.run_coroutine_threadsafe(self._async_clear_emergency_messages(), self.loop)
        try:
            future.result(timeout=45.0) # Extended timeout for rate limits (up to 45s)
        except Exception as e:
            logger.error(f"[Discord] Timeout/Error clearing emergency messages: {e}")

    async def _async_clear_emergency_messages(self):
        if not hasattr(self, "emergency_msgs") or not self.emergency_msgs: return
        import aiohttp
        try:
            async with aiohttp.ClientSession() as session:
                for em in self.emergency_msgs:
                    try:
                        if em["type"] == "webhook" and em.get("id"):
                            async with session.delete(f"{em['url']}/messages/{em['id']}") as resp:
                                if resp.status == 429:
                                    try:
                                        err_json = await resp.json()
                                        wait_time = err_json.get("retry_after", 1.5)
                                    except:
                                        wait_time = 1.5
                                    await asyncio.sleep(wait_time + 0.2)
                                    # Retry exactly once
                                    try: await session.delete(f"{em['url']}/messages/{em['id']}")
                                    except: pass
                            await asyncio.sleep(0.6) # Pre-emptive pacing
                        elif em["type"] == "dm":
                            await em["msg"].delete()
                            await asyncio.sleep(0.6)
                    except Exception as e_inner:
                        logger.debug(f"[Discord] Error deleting single emergency message: {e_inner}")
        except Exception as e:
            logger.error(f"[Discord] Failed to clear emergencies: {e}")
        self.emergency_msgs.clear()

    def _setup_bot(self):
        intents = discord.Intents.default()
        intents.message_content = True
        
        bot = commands.Bot(command_prefix=self.prefix, intents=intents, help_command=None, case_insensitive=True)
        
        @bot.event
        async def on_ready():
            logger.info(f"[Discord] Logged in as {bot.user} (ID: {bot.user.id})")
            self.send_notification("✅ **Bot connected!** (GUI is open, waiting for Start/F8)", edit_category="system_log")

        @bot.event
        async def on_command_error(ctx, error):
            if isinstance(error, commands.CommandNotFound):
                pass  # Abaikan command yang tidak valid agar chat biasa tidak spam warning di konsol
            else:
                logger.error(f"[Discord] Command Error: {error}")

        def is_admin():
            async def predicate(ctx):
                if not self.admin_id: return True # Public if no ID set
                return str(ctx.author.id) == self.admin_id
            return commands.check(predicate)

        @bot.command(name="help")
        @is_admin()
        async def help_command(ctx):
            embed = discord.Embed(
                title="AOTR Bot - Available Commands",
                description="Use these commands to monitor and control the bot remotely.",
                color=discord.Color.green()
            )
            embed.add_field(name="`status`", value="Show current game state and summary.", inline=False)
            embed.add_field(name="`gold` / `exp` / `gems`", value="Show session statistics.", inline=False)
            embed.add_field(name="`reward`", value="Show rewards from the most recent mission.", inline=False)
            embed.add_field(name="`runtime`", value="Show how long the bot has been running.", inline=False)
            embed.add_field(name="`screenshot`", value="Send a live frame from the game.", inline=False)
            embed.add_field(name="`record [seconds]`", value="Record display as MP4 (default 5s).", inline=False)
            embed.add_field(name="`start`", value="Start or Resume bot execution.", inline=False)
            embed.add_field(name="`pause`", value="Pause bot execution.", inline=False)
            embed.add_field(name="`reload`", value="Restart bot scripts in background.", inline=False)
            embed.add_field(name="`restart`", value="Reset bot internal memory and state.", inline=False)
            embed.add_field(name="`listpro`", value="List top 30 processes by RAM usage.", inline=False)
            embed.add_field(name="`endtask <name>`", value="Kill a specific process by name.", inline=False)
            embed.add_field(name="`changesettings`", value="Edit bot config.json fields interactively.", inline=False)
            embed.add_field(name="`help`", value="Show this help message.", inline=False)
            
            embed.set_footer(text="AOTR Bot - Interactive Remote Control")
            await ctx.send(embed=embed)

        @bot.command(name="changesettings")
        @is_admin()
        async def changesettings(ctx):
            if not self.brain:
                await ctx.send("⚠️ Engine not running.")
                return

            is_running = not self.brain.stop_flag.is_set() if self.brain.stop_flag else False
            if is_running:
                if self.pause_callback:
                    self.pause_callback()
                    await ctx.send("⏸️ **Bot running.** Automatically pausing bot to change config...")
                    await asyncio.sleep(1)

            embed = discord.Embed(
                title="⚙️ Current Settings", 
                description="Type the **setting name** you want to change (e.g. `bot.show_overlay`), or type `cancel` to abort.", 
                color=discord.Color.blue()
            )
            
            flat_settings = {}
            for section, values in self.config_obj._data.items():
                if isinstance(values, dict):
                    msg = ""
                    for k, v in values.items():
                        flat_key = f"{section}.{k}"
                        flat_settings[flat_key] = (section, k, v)
                        msg += f"`{k}`: **{v}**\n"
                    if len(msg) > 1024:
                        msg = msg[:1000] + "..."
                    embed.add_field(name=f"[{section}]", value=msg or "Empty", inline=False)
            
            await ctx.send(embed=embed)
            await ctx.send("📝 **What do you want to change?**")

            def check(m):
                return m.author == ctx.author and m.channel == ctx.channel

            try:
                msg_key = await bot.wait_for('message', check=check, timeout=120.0)
                ans = msg_key.content.strip()
                
                if ans.lower() == 'cancel':
                    await ctx.send("❌ **Cancelled.** Bot ready to resume.")
                    return
                
                ans_lower = ans.lower()
                found_keys = [k for k in flat_settings if k.lower().endswith("." + ans_lower) or k.lower() == ans_lower]
                
                if not found_keys:
                    import difflib
                    # Gather all long and short keys for fuzzy matching
                    mapping = {}
                    for k, v in flat_settings.items():
                        mapping[k.lower()] = k  # long key: bot.target_fps
                        mapping[v[1].lower()] = k # short key: target_fps
                        
                    matches = difflib.get_close_matches(ans_lower, list(mapping.keys()), n=1, cutoff=0.4)
                    if matches:
                        suggested = mapping[matches[0]]
                        await ctx.send(f"⚠️ There's no `{ans}`, you meant `{suggested}`? (y/n)")
                        try:
                            msg_conf = await bot.wait_for('message', check=check, timeout=30.0)
                            if msg_conf.content.strip().lower() in ('y', 'yes'):
                                found_keys = [suggested]
                            else:
                                await ctx.send("❌ **Cancelled.**")
                                return
                        except asyncio.TimeoutError:
                            await ctx.send("⏳ Time's up. Command cancelled.")
                            return
                    else:
                        await ctx.send(f"⚠️ Setting `{ans}` not found. Cancelled.")
                        return
                if len(found_keys) > 1:
                    await ctx.send(f"⚠️ Too many settings: {', '.join(found_keys)}. Type with a clear category. Cancelled.")
                    return
                
                real_key = found_keys[0]
                section, key, old_val = flat_settings[real_key]
                old_type = type(old_val)
                
                await ctx.send(f"Change `{real_key}`. Current value: **{old_val}**. \nType the new value (or `cancel`):")
                msg_val = await bot.wait_for('message', check=check, timeout=120.0)
                new_input = msg_val.content.strip()
                
                if new_input.lower() == 'cancel':
                    await ctx.send("❌ **Cancelled.**")
                    return
                
                new_val = None
                try:
                    if isinstance(old_val, bool):
                        if new_input.lower() in ('true', '1', 'yes', 'y'):
                            new_val = True
                        elif new_input.lower() in ('false', '0', 'no', 'n'):
                            new_val = False
                        else:
                            raise ValueError("Invalid format (must be true/false).")
                    elif isinstance(old_val, int):
                        new_val = int(new_input)
                    elif isinstance(old_val, float):
                        new_val = float(new_input)
                    else:
                        new_val = new_input
                except Exception as e:
                    await ctx.send(f"⚠️ Failed to change value: {e}. Cancelled.")
                    return
                
                self.config_obj._data[section][key] = new_val
                self.config_obj.save()
                
                await ctx.send(f"✅ **Success!** `{real_key}` changed to **{new_val}**.\nSending Hot-Reload command to engine...")
                
                if self.reload_callback:
                    self.reload_callback()
                    
            except asyncio.TimeoutError:
                await ctx.send("⏳ Time's up. Command cancelled.")

        @bot.command(name="status")
        @is_admin()
        async def status(ctx):
            if not self.brain:
                await ctx.send("⚠️ **Bot engine not initialized.** (Critical Error: Link failed)")
                return
            
            # Check if engine is running (Engine thread is active when not stop_flag.is_set)
            is_running = not self.brain.stop_flag.is_set() if self.brain.stop_flag else False
            status_text = "🟢 **RUNNING**" if is_running else "🟡 **PAUSED/STOPPED** (Press F8)"
            
            state = self.brain.state.name
            runtime = time.time() - self.brain.startup_time
            rt_str = time.strftime("%H:%M:%S", time.gmtime(runtime))
            
            embed = discord.Embed(title="AOTR Bot Status", color=discord.Color.blue() if is_running else discord.Color.orange())
            embed.add_field(name="Engine Status", value=status_text, inline=False)
            embed.add_field(name="Current State", value=f"`{state}`", inline=True)
            embed.add_field(name="Runtime", value=f"`{rt_str}`", inline=True)
            
            if hasattr(self.brain, "session_gold"):
                embed.add_field(name="Session Stats", value=f"💰 Gold: `{self.brain.session_gold:,}`\n⭐ Exp: `{self.brain.session_exp:,}`\n💎 Gems: `{self.brain.session_gems:,}`", inline=False)
            
            await ctx.send(embed=embed)

        @bot.command(name="runtime")
        @is_admin()
        async def runtime(ctx):
            if not self.brain:
                await ctx.send("⚠️ **Bot engine not running.**")
                return
            rt = time.time() - self.brain.startup_time
            await ctx.send(f"🕒 Bot has been running for: `{time.strftime('%H:%M:%S', time.gmtime(rt))}`")

        @bot.command(name="gold")
        @is_admin()
        async def gold(ctx):
            if not self.brain:
                await ctx.send("💰 Session Gold: 0 (Engine not running)")
                return
            val = getattr(self.brain, "session_gold", 0)
            await ctx.send(f"💰 Session Gold: **{val:,}**")

        @bot.command(name="exp")
        @is_admin()
        async def exp(ctx):
            if not self.brain:
                await ctx.send("⭐ Session Exp: 0 (Engine not running)")
                return
            val = getattr(self.brain, "session_exp", 0)
            await ctx.send(f"⭐ Session Exp: **{val:,}**")

        @bot.command(name="gems")
        @is_admin()
        async def gems(ctx):
            if not self.brain:
                await ctx.send("💎 Session Gems: 0 (Engine not running)")
                return
            val = getattr(self.brain, "session_gems", 0)
            await ctx.send(f"💎 Session Gems: **{val:,}**")

        @bot.command(name="reward")
        @is_admin()
        async def reward(ctx):
            if not self.brain:
                await ctx.send("📊 **No mission data available.** (Engine not running)")
                return
            
            g = getattr(self.brain, "last_gold", 0)
            e = getattr(self.brain, "last_exp", 0)
            gem = getattr(self.brain, "last_gems", 0)
            
            if g == 0 and e == 0 and gem == 0:
                await ctx.send("📊 **Last Mission Reward: None** (Waiting for result screen OCR)")
                return

            embed = discord.Embed(
                title="📊 Recent Mission Rewards",
                description="Extraction from the latest Mission Completed screen.",
                color=discord.Color.gold()
            )
            embed.add_field(name="💰 Gold", value=f"`+{g:,}`", inline=True)
            embed.add_field(name="⭐ Exp", value=f"`+{e:,}`", inline=True)
            embed.add_field(name="💎 Gems", value=f"`+{gem:,}`", inline=True)
            
            await ctx.send(embed=embed)

        @bot.command(name="screenshot")
        @is_admin()
        async def screenshot(ctx):
            await ctx.send("📸 Capturing entire screen...")
            try:
                from PIL import ImageGrab
                import io
                import discord
                
                # Grab entire display screen independent of engine
                pil_img = ImageGrab.grab(all_screens=True)
                
                # Encode directly to PNG
                io_buf = io.BytesIO()
                pil_img.save(io_buf, format='PNG')
                io_buf.seek(0)
                
                file = discord.File(io_buf, filename="screenshot.png")
                await ctx.send(file=file)
            except Exception as e:
                await ctx.send(f"❌ Error taking screenshot: {e}")

        @bot.command(name="record")
        @is_admin()
        async def record(ctx, duration: int = 5):
            # Batasi durasi max 30 detik agar file tidak kegedean limit Discord (8MB/25MB)
            if duration > 30:
                duration = 30
                await ctx.send("⚠️ Duration is limited to max 30 seconds for Discord upload.")
                
            await ctx.send(f"🎥 **Recording screen for {duration} seconds...** (MP4 Format)")
            
            try:
                from PIL import ImageGrab
                import cv2
                import numpy as np
                import os
                import asyncio
                import time
                import discord
                
                fps = 15 # 15 FPS untuk hasil yang lebih smooth
                total_frames = duration * fps
                spf = 1.0 / fps
                
                mp4_path = "discord_record.mp4"
                video_writer = None
                
                start_time = time.time()
                target_time = start_time
                frames_captured = 0
                
                for _ in range(total_frames):
                    target_time += spf
                    
                    # Grab directly from OS display
                    pil_img = ImageGrab.grab(all_screens=True)
                    frame = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
                    
                    # Resize max 720p untuk kompresi size
                    h, w = frame.shape[:2]
                    scale = min(1.0, 720 / h)
                    if scale < 1.0:
                        new_w, new_h = int(w * scale), int(h * scale)
                        frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
                    else:
                        new_w, new_h = w, h
                        
                    if video_writer is None:
                        # mp4v is codec for mp4 natively
                        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                        video_writer = cv2.VideoWriter(mp4_path, fourcc, fps, (new_w, new_h))
                        
                    video_writer.write(frame)
                    frames_captured += 1
                    
                    delay = target_time - time.time()
                    if delay > 0:
                        await asyncio.sleep(delay)
                    else:
                        await asyncio.sleep(0.001) # Yield to prevent event-loop block
                
                if video_writer is not None:
                    video_writer.release()
                
                if frames_captured == 0:
                    await ctx.send("❌ Error: No frames captured.")
                    return
                
                file = discord.File(mp4_path, filename="record.mp4")
                await ctx.send(file=file)
                
                if os.path.exists(mp4_path):
                    os.remove(mp4_path)
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"[Discord] Recording failed: {e}")
                await ctx.send(f"❌ Recording failed: {e}")

        @bot.command(name="start")
        @is_admin()
        async def start(ctx):
            if self.pause_callback:
                self.pause_callback()
                await ctx.send("▶️ **Start/Resume command sent to Main Engine.**")
            else:
                await ctx.send("⚠️ Error: Start callback not linked.")

        @bot.command(name="pause")
        @is_admin()
        async def pause(ctx):
            if self.pause_callback:
                self.pause_callback()
                await ctx.send("⏸️ **Pause command sent to Main Engine.**")
            else:
                await ctx.send("⚠️ Error: Pause callback not linked.")

        @bot.command(name="reload")
        @is_admin()
        async def reload_cmd(ctx):
            if self.reload_callback:
                self.reload_callback()
                await ctx.send("♻️ **Reload scripts command sent.** Please wait a moment.")
            else:
                await ctx.send("⚠️ Error: Reload callback not linked.")

        @bot.command(name="restart")
        @is_admin()
        async def restart(ctx):
            if not self.brain:
                await ctx.send("⚠️ **Bot engine not running.**")
                return
            
            from bot.brain import BotState
            self.brain.reset_session_flags(reason="Discord cmd restart")
            self.brain.state = BotState.MAIN_MENU
            self.brain._candidate_state = None
            
            await ctx.send("🧠 **Bot AI Memory Restarted!** The state machine will evaluate the current screen from scratch.")

        @bot.command(name="listpro")
        @is_admin()
        async def listpro(ctx):
            try:
                import subprocess
                # Run tasklist and get output
                output = subprocess.check_output('tasklist /fo csv /nh', shell=True).decode('utf-8', errors='ignore')
                processes = {}
                for line in output.strip().split('\n'):
                    parts = line.split('","')
                    if len(parts) >= 5:
                        name = parts[0].strip('"')
                        # memory is something like "1,032 K"
                        mem_str = parts[4].strip('"\r K').replace(',', '')
                        try:
                            mem = int(mem_str)
                        except:
                            mem = 0
                        
                        if name in processes:
                            processes[name] += mem
                        else:
                            processes[name] = mem
                
                # Sort by memory descending
                sorted_procs = sorted(processes.items(), key=lambda x: x[1], reverse=True)[:30]
                
                msg = "**Top 30 Running Processes (by Memory Usage):**\n```\n"
                for name, mem in sorted_procs:
                    msg += f"{name:<30} | {mem/1024:.1f} MB\n"
                msg += "```\n*Tip: Use `endtask process.exe` to kill one.*"
                
                await ctx.send(msg)
            except Exception as e:
                await ctx.send(f"❌ Failed to list processes: {e}")

        @bot.command(name="endtask")
        @is_admin()
        async def endtask(ctx, *, process_name: str):
            try:
                import subprocess
                if not process_name.lower().endswith('.exe'):
                    process_name += '.exe'
                    
                # Use taskkill
                result = subprocess.run(['taskkill', '/f', '/im', process_name], capture_output=True, text=True)
                if result.returncode == 0:
                    await ctx.send(f"✅ Successfully killed `{process_name}`.")
                else:
                    err_msg = result.stderr.strip() or result.stdout.strip()
                    await ctx.send(f"⚠️ Failed to kill `{process_name}`. Error:\n```\n{err_msg}\n```")
            except Exception as e:
                await ctx.send(f"❌ Error executing endtask: {e}")

        return bot

    def _run_thread(self):
        """Thread entry point."""
        asyncio.set_event_loop(asyncio.new_event_loop())
        self.loop = asyncio.get_event_loop()
        self.bot = self._setup_bot()
        
        if self.brain:
            self.brain.discord_bot_instance = self 
        
        try:
            self.loop.run_until_complete(self.bot.start(self.token))
        except Exception as e:
            logger.error(f"[Discord] Bot execution error: {e}")
