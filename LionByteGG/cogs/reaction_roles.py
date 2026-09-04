import discord
from discord.ext import commands
import json
import os
import asyncio
from utils.safe_json import safe_json_dump, safe_json_load

DATA_DIR = "data"
REACTION_ROLE_FILE = os.path.join(DATA_DIR, "reaction_roles.json")

class ReactionRoles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.reaction_role_messages = self.load_reaction_roles()
        # Rate limit tracking per user to prevent spam
        self._role_cooldowns = {}

    def load_reaction_roles(self):
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR)
        data = safe_json_load(REACTION_ROLE_FILE, {})
        if data:
            return {int(mid): {emoji: rid for emoji, rid in emojis.items()} for mid, emojis in data.items()}
        return {}

    def save_reaction_roles(self):
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR)
        # Convert message IDs to str for JSON
        data = {str(mid): emojis for mid, emojis in self.reaction_role_messages.items()}
        safe_json_dump(data, REACTION_ROLE_FILE, indent=2)

    async def _handle_role_change(self, member, role, add=True, reason="Reaction role"):
        """Handle role change with rate limit protection"""
        try:
            if add:
                await member.add_roles(role, reason=reason)
            else:
                await member.remove_roles(role, reason=reason)
            # Small delay to prevent rate limiting when multiple reactions happen quickly
            await asyncio.sleep(0.5)
            return True
        except discord.HTTPException as e:
            if e.status == 429:  # Rate limited
                retry_after = getattr(e, 'retry_after', 5)
                print(f"[REACTION ROLES] Rate limited, waiting {retry_after}s...")
                await asyncio.sleep(retry_after + 1)
                try:
                    if add:
                        await member.add_roles(role, reason=f"{reason} (retry)")
                    else:
                        await member.remove_roles(role, reason=f"{reason} (retry)")
                    return True
                except Exception:
                    return False
            return False
        except discord.Forbidden:
            return False
        except Exception:
            return False

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if payload.message_id in self.reaction_role_messages:
            emoji = str(payload.emoji)
            role_id = self.reaction_role_messages[payload.message_id].get(emoji)
            if role_id:
                guild = self.bot.get_guild(payload.guild_id)
                if guild:
                    member = guild.get_member(payload.user_id)
                    if member and not member.bot:
                        role = guild.get_role(role_id)
                        if role:
                            success = await self._handle_role_change(member, role, add=True, reason="Reaction role assigned")
                            if success:
                                # DM the user
                                try:
                                    await member.send(
                                        f"You are now subscribed to **{role.name}** and will receive notifications for this role."
                                    )
                                except Exception:
                                    pass  # Ignore if DMs are closed

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        if payload.message_id in self.reaction_role_messages:
            emoji = str(payload.emoji)
            role_id = self.reaction_role_messages[payload.message_id].get(emoji)
            if role_id:
                guild = self.bot.get_guild(payload.guild_id)
                if guild:
                    member = guild.get_member(payload.user_id)
                    if member and not member.bot:
                        role = guild.get_role(role_id)
                        if role:
                            success = await self._handle_role_change(member, role, add=False, reason="Reaction role removed")
                            if success:
                                # DM the user
                                try:
                                    await member.send(
                                        f"You have been unsubscribed from **{role.name}** and will no longer receive notifications for this role."
                                    )
                                except Exception:
                                    pass  # Ignore if DMs are closed

    # Call this method from admin_commands.py whenever you update reaction_role_messages
    def update_reaction_role(self, message_id, emoji, role_id):
        if message_id not in self.reaction_role_messages:
            self.reaction_role_messages[message_id] = {}
        self.reaction_role_messages[message_id][emoji] = role_id
        self.save_reaction_roles()

async def setup(bot):
    await bot.add_cog(ReactionRoles(bot))