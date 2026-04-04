import discord
from discord.ext import commands, tasks
from discord import app_commands, Interaction, Embed, ButtonStyle
from discord.ui import View, button
import os
import json
import asyncio
from utils.safe_json import safe_json_dump

VC_GENERATORS_FILE = os.path.join("data", "vc-generators.json")

def load_generator_data():
    if os.path.exists(VC_GENERATORS_FILE):
        with open(VC_GENERATORS_FILE, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
                return {
                    "normal": set(data.get("normal", [])),
                    "tryout": set(data.get("tryout", [])),
                    "generated": set(data.get("generated", []))
                }
            except Exception:
                return {"normal": set(), "tryout": set(), "generated": set()}
    return {"normal": set(), "tryout": set(), "generated": set()}

def save_generator_data(normal_ids, tryout_ids, generated_ids=None):
    os.makedirs(os.path.dirname(VC_GENERATORS_FILE), exist_ok=True)
    payload = {
        "normal": list(normal_ids),
        "tryout": list(tryout_ids)
    }
    if generated_ids is not None:
        payload["generated"] = list(generated_ids)
    safe_json_dump(payload, VC_GENERATORS_FILE, indent=2)

class VCControls(View):
    def __init__(self, owner_id, vc):
        super().__init__(timeout=None)
        self.owner_id = owner_id
        self.vc = vc

    async def interaction_check(self, interaction: Interaction) -> bool:
        return interaction.user.id == self.owner_id


class VCSystem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.reload_generators()
        self.print_status()

    def reload_generators(self):
        data = load_generator_data()
        self.generator_vc_ids = set(data["normal"])
        self.tryout_generator_vc_ids = set(data["tryout"])
        self.generated_vc_ids = set(data.get("generated", set()))

    def save_generators(self):
        save_generator_data(self.generator_vc_ids, self.tryout_generator_vc_ids, self.generated_vc_ids)

    def track_generated(self, vc_id):
        """Add a generated VC to tracking and persist immediately."""
        self.generated_vc_ids.add(vc_id)
        self.save_generators()

    def untrack_generated(self, vc_id):
        """Remove a generated VC from tracking and persist immediately."""
        self.generated_vc_ids.discard(vc_id)
        self.save_generators()

    async def try_delete_vc(self, channel_id, reason="Auto-deleted empty generated VC"):
        """Attempt to delete a generated VC by ID. Returns True if deleted or already gone."""
        try:
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                # Channel no longer exists (already deleted or bot can't see it)
                self.untrack_generated(channel_id)
                return True
            if not isinstance(channel, discord.VoiceChannel):
                self.untrack_generated(channel_id)
                return True
            non_bot_members = [m for m in channel.members if not m.bot]
            if len(non_bot_members) == 0:
                await channel.delete(reason=reason)
                self.untrack_generated(channel_id)
                print(f"[VCSystem] Deleted empty VC: {channel.name} ({channel_id})")
                return True
        except discord.NotFound:
            # Channel was already deleted
            self.untrack_generated(channel_id)
            return True
        except discord.Forbidden:
            print(f"[VCSystem] No permission to delete VC {channel_id}")
        except Exception as e:
            print(f"[VCSystem] Error deleting VC {channel_id}: {e}")
        return False

    def print_status(self):
        print("=" * 60)
        print("[VCSystem] Startup Status Report")
        print(f"Normal VC Generators: {list(self.generator_vc_ids)}")
        print(f"Tryout VC Generators: {list(self.tryout_generator_vc_ids)}")
        if not self.generator_vc_ids and not self.tryout_generator_vc_ids:
            print("[VCSystem] WARNING: No VC generators configured! The VC generator system will not function.")
            print("[VCSystem] Please use /setup_vc_generator or /setup_tryout_vc to configure generator VCs.")
        else:
            print("[VCSystem] VC generator system is ready.")
        print("=" * 60)

    @app_commands.command(name="setup_vc_generator", description="Setup a VC generator with a voice channel and category.")
    @app_commands.describe(voice_channel="The voice channel to use as generator", category="The category for generated VCs")
    async def setup_vc_generator(self, interaction: Interaction, voice_channel: discord.VoiceChannel, category: discord.CategoryChannel):
        self.reload_generators()
        self.generator_vc_ids.add(voice_channel.id)
        self.save_generators()
        await voice_channel.edit(category=category)
        await interaction.response.send_message(
            f"Set up {voice_channel.mention} as a generator in category {category.name}.", ephemeral=True
        )
        self.print_status()

    @app_commands.command(name="setup_tryout_vc", description="Setup a tryout VC generator with a voice channel and category.")
    @app_commands.describe(voice_channel="The voice channel to use as tryout generator", category="The category for generated tryout VCs")
    async def setup_tryout_vc(self, interaction: Interaction, voice_channel: discord.VoiceChannel, category: discord.CategoryChannel):
        self.reload_generators()
        await voice_channel.edit(category=category)
        self.tryout_generator_vc_ids.add(voice_channel.id)
        self.save_generators()
        await interaction.response.send_message(
            f"Set up {voice_channel.mention} as a tryout generator in category {category.name}.", ephemeral=True
        )
        self.print_status()

    @app_commands.command(name="list_vc_generators", description="List all current VC generators.")
    async def list_vc_generators(self, interaction: Interaction):
        self.reload_generators()
        normal = ", ".join(f"<#{vid}>" for vid in self.generator_vc_ids) or "None"
        tryout = ", ".join(f"<#{vid}>" for vid in self.tryout_generator_vc_ids) or "None"
        embed = Embed(
            title="VC Generator Status",
            description="Current generator voice channels.",
            color=discord.Color.blue()
        )
        embed.add_field(name="Normal Generators", value=normal, inline=False)
        embed.add_field(name="Tryout Generators", value=tryout, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        self.reload_generators()
        # --- Tryout VC Generation ---
        if after.channel and after.channel.id in getattr(self, "tryout_generator_vc_ids", set()):
            category = after.channel.category
            overwrites = {
                member.guild.default_role: discord.PermissionOverwrite(connect=False, view_channel=False),
                member: discord.PermissionOverwrite(manage_channels=True, connect=True, view_channel=True, move_members=True)
            }
            # Allow admins to see and join
            for role in member.guild.roles:
                if role.permissions.administrator:
                    overwrites[role] = discord.PermissionOverwrite(view_channel=True, connect=True, move_members=True)
            # Create a new tryout VC for the user in the same category as the generator
            new_vc = await category.create_voice_channel(
                f"{member.display_name}'s Tryout VC", overwrites=overwrites
            )
            self.track_generated(new_vc.id)
            try:
                await member.move_to(new_vc)
            except Exception as e:
                # Move failed — member may have disconnected; clean up the empty VC
                print(f"[VCSystem] move_to failed for tryout VC, cleaning up: {e}")
                try:
                    await new_vc.delete(reason="Cleanup: move_to failed")
                except Exception:
                    pass
                self.untrack_generated(new_vc.id)
                return
            # Optionally DM the user
            embed = Embed(
                title="Tryout VC Created",
                description="You can now drag players from the waiting room into your Tryout VC.",
                color=0x00ff00
            )
            try:
                await member.send(embed=embed)
            except Exception:
                pass
            return  # Don't process normal generator logic

        # --- Normal VC Generation ---
        if after.channel and after.channel.id in self.generator_vc_ids:
            category = after.channel.category
            overwrites = {
                member.guild.default_role: discord.PermissionOverwrite(connect=True, view_channel=True),
                member: discord.PermissionOverwrite(manage_channels=True, connect=True, view_channel=True)
            }
            new_vc = await category.create_voice_channel(f"{member.display_name}'s VC", overwrites=overwrites)
            self.track_generated(new_vc.id)
            # Sync permissions from category to VC
            await new_vc.edit(sync_permissions=True)
            try:
                await member.move_to(new_vc)
            except Exception as e:
                # Move failed — member may have disconnected; clean up the empty VC
                print(f"[VCSystem] move_to failed for normal VC, cleaning up: {e}")
                try:
                    await new_vc.delete(reason="Cleanup: move_to failed")
                except Exception:
                    pass
                self.untrack_generated(new_vc.id)
                return

            # Wait for Discord to create the voice channel chat (if available)
            vc_chat = None
            for _ in range(10):  # Try for up to ~5 seconds
                vc_chat = getattr(new_vc, "text_channel", None)
                if vc_chat:
                    break
                await discord.utils.sleep_until(discord.utils.utcnow() + discord.utils.timedelta(milliseconds=500))
            # Fallback: try to find by name in the same category
            if not vc_chat:
                expected_name = new_vc.name.replace(" ", "-").lower()
                for ch in category.text_channels:
                    if ch.name.startswith(expected_name):
                        vc_chat = ch
                        break

            if vc_chat:
                # Hide from everyone except the owner and admins
                chat_overwrites = {
                    member.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                    member: discord.PermissionOverwrite(read_messages=True, send_messages=True)
                }
                for role in member.guild.roles:
                    if role.permissions.administrator:
                        chat_overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
                await vc_chat.edit(overwrites=chat_overwrites)

                embed = Embed(
                    title="VC Controls",
                    description="Use the buttons below to manage your VC.",
                    color=0x00ff00
                )
                view = VCControls(member.id, new_vc)
                await vc_chat.send(content=f"{member.mention}", embed=embed, view=view)
        # --- VC Auto-Delete ---
        # Only delete generated VCs, never generator VCs
        if before.channel and before.channel != after.channel:
            if before.channel.id in getattr(self, "generated_vc_ids", set()):
                await self.try_delete_vc(before.channel.id)

    @commands.Cog.listener()
    async def on_ready(self):
        print("[VCSystem] on_ready event fired.")
        self.reload_generators()
        self.print_status()

        # --- Startup Cleanup: delete any empty generated VCs that survived a restart ---
        if self.generated_vc_ids:
            print(f"[VCSystem] Checking {len(self.generated_vc_ids)} tracked generated VCs for cleanup...")
            stale_ids = list(self.generated_vc_ids)
            cleaned = 0
            for vc_id in stale_ids:
                deleted = await self.try_delete_vc(vc_id, reason="Startup cleanup: empty generated VC")
                if deleted:
                    cleaned += 1
                await asyncio.sleep(0.5)  # Respect rate limits
            print(f"[VCSystem] Startup cleanup complete: {cleaned}/{len(stale_ids)} VCs removed.")

        # --- Also scan categories for orphaned VCs not in our tracking ---
        await self.scan_orphaned_vcs()

        # Start periodic cleanup loop
        if not self.periodic_cleanup.is_running():
            self.periodic_cleanup.start()

    async def scan_orphaned_vcs(self):
        """Scan generator categories for VCs matching the generated name pattern but not tracked."""
        for guild in self.bot.guilds:
            all_generator_ids = self.generator_vc_ids | self.tryout_generator_vc_ids
            categories_checked = set()
            for gen_id in all_generator_ids:
                gen_channel = guild.get_channel(gen_id)
                if gen_channel and gen_channel.category and gen_channel.category.id not in categories_checked:
                    categories_checked.add(gen_channel.category.id)
                    for vc in gen_channel.category.voice_channels:
                        # Skip generator channels themselves
                        if vc.id in all_generator_ids:
                            continue
                        # Check if it looks like a generated VC (ends with "'s VC" or "'s Tryout VC")
                        if vc.name.endswith("'s VC") or vc.name.endswith("'s Tryout VC"):
                            non_bot = [m for m in vc.members if not m.bot]
                            if len(non_bot) == 0:
                                try:
                                    await vc.delete(reason="Orphan cleanup: empty generated VC")
                                    self.generated_vc_ids.discard(vc.id)
                                    print(f"[VCSystem] Orphan cleanup: deleted '{vc.name}' ({vc.id})")
                                except Exception as e:
                                    print(f"[VCSystem] Orphan cleanup failed for '{vc.name}': {e}")
                                await asyncio.sleep(0.5)
                            else:
                                # It has members but wasn't tracked — start tracking it
                                if vc.id not in self.generated_vc_ids:
                                    self.generated_vc_ids.add(vc.id)
                                    print(f"[VCSystem] Re-tracking orphaned VC: '{vc.name}' ({vc.id})")
            self.save_generators()

    @tasks.loop(minutes=5)
    async def periodic_cleanup(self):
        """Every 5 minutes, check all tracked generated VCs and delete empty ones."""
        if not self.generated_vc_ids:
            return
        stale_ids = list(self.generated_vc_ids)
        for vc_id in stale_ids:
            await self.try_delete_vc(vc_id, reason="Periodic cleanup: empty generated VC")
            await asyncio.sleep(0.3)

    @periodic_cleanup.before_loop
    async def before_periodic_cleanup(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(VCSystem(bot))
    # await bot.tree.sync()

