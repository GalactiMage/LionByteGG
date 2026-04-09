import discord
from discord.ext import commands, tasks
from discord import app_commands, Interaction, Embed
from discord.ui import View
import os
import json
import asyncio
import traceback
from utils.safe_json import safe_json_dump

# Absolute path — never depends on CWD
_SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VC_GENERATORS_FILE = os.path.join(_SCRIPT_DIR, "data", "vc-generators.json")


# ---------------------------------------------------------------------------
# Persistent JSON helpers
# ---------------------------------------------------------------------------

def _load_json():
    """Load generator config from disk. Always returns a dict with all keys."""
    default = {"normal": [], "tryout": [], "generated": []}
    try:
        if os.path.exists(VC_GENERATORS_FILE):
            with open(VC_GENERATORS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for key in default:
                if key not in data:
                    data[key] = default[key]
            return data
    except Exception as e:
        print(f"[VCSystem] WARNING: Could not read {VC_GENERATORS_FILE}: {e}")
    return default


def _save_json(data):
    """Atomic-write generator config to disk."""
    os.makedirs(os.path.dirname(VC_GENERATORS_FILE), exist_ok=True)
    safe_json_dump(data, VC_GENERATORS_FILE, indent=2)


# ---------------------------------------------------------------------------
# VC Controls View (sent in the VC text-chat)
# ---------------------------------------------------------------------------

class VCControls(View):
    def __init__(self, owner_id, vc):
        super().__init__(timeout=None)
        self.owner_id = owner_id
        self.vc = vc

    async def interaction_check(self, interaction: Interaction) -> bool:
        return interaction.user.id == self.owner_id


# ---------------------------------------------------------------------------
# The Cog
# ---------------------------------------------------------------------------

class VCSystem(commands.Cog):
    """Reliable VC generator system — creates temp VCs and deletes them when empty."""

    def __init__(self, bot):
        self.bot = bot
        # In-memory sets (source of truth between disk reloads)
        self.generator_vc_ids: set[int] = set()
        self.tryout_generator_vc_ids: set[int] = set()
        self.generated_vc_ids: set[int] = set()
        # Load from disk
        self._load_from_disk()
        self._print_status()

    # ------------------------------------------------------------------
    # Disk I/O
    # ------------------------------------------------------------------

    def _load_from_disk(self):
        """Refresh all three sets from the JSON file."""
        data = _load_json()
        self.generator_vc_ids = set(int(x) for x in data.get("normal", []))
        self.tryout_generator_vc_ids = set(int(x) for x in data.get("tryout", []))
        self.generated_vc_ids = set(int(x) for x in data.get("generated", []))

    def _save_to_disk(self):
        """Persist all three sets to the JSON file."""
        _save_json({
            "normal": [int(x) for x in self.generator_vc_ids],
            "tryout": [int(x) for x in self.tryout_generator_vc_ids],
            "generated": [int(x) for x in self.generated_vc_ids],
        })

    def _track(self, vc_id: int):
        """Start tracking a generated VC and save to disk."""
        self.generated_vc_ids.add(vc_id)
        self._save_to_disk()

    def _untrack(self, vc_id: int):
        """Stop tracking a generated VC and save to disk."""
        self.generated_vc_ids.discard(vc_id)
        self._save_to_disk()

    # ------------------------------------------------------------------
    # Delete helper
    # ------------------------------------------------------------------

    async def _try_delete(self, channel_id: int, reason: str = "Auto-deleted empty generated VC") -> bool:
        """Delete a generated VC if it is empty. Returns True if deleted/gone."""
        try:
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                self._untrack(channel_id)
                return True
            if not isinstance(channel, discord.VoiceChannel):
                self._untrack(channel_id)
                return True
            if all(m.bot for m in channel.members):       # empty (or only bots)
                await channel.delete(reason=reason)
                self._untrack(channel_id)
                print(f"[VCSystem] Deleted empty VC: {channel.name} ({channel_id})")
                return True
        except discord.NotFound:
            self._untrack(channel_id)
            return True
        except discord.Forbidden:
            print(f"[VCSystem] No permission to delete VC {channel_id}")
        except Exception as e:
            print(f"[VCSystem] Error deleting VC {channel_id}: {e}")
        return False

    # ------------------------------------------------------------------
    # Status helper
    # ------------------------------------------------------------------

    def _print_status(self):
        print("=" * 60)
        print("[VCSystem] Status Report")
        print(f"  Normal generators : {list(self.generator_vc_ids)}")
        print(f"  Tryout generators : {list(self.tryout_generator_vc_ids)}")
        print(f"  Tracked generated : {len(self.generated_vc_ids)}")
        if not self.generator_vc_ids and not self.tryout_generator_vc_ids:
            print("  WARNING: No generators configured! Use /setup_vc_generator or /setup_tryout_vc")
        else:
            print("  VC generator system is READY.")
        print("=" * 60)

    # ------------------------------------------------------------------
    # Slash commands (setup / list)
    # ------------------------------------------------------------------

    @app_commands.command(name="setup_vc_generator",
                          description="Setup a VC generator with a voice channel and category.")
    @app_commands.describe(voice_channel="The voice channel to use as generator",
                           category="The category for generated VCs")
    async def setup_vc_generator(self, interaction: Interaction,
                                  voice_channel: discord.VoiceChannel,
                                  category: discord.CategoryChannel):
        self._load_from_disk()
        self.generator_vc_ids.add(voice_channel.id)
        self._save_to_disk()
        await voice_channel.edit(category=category)
        await interaction.response.send_message(
            f"Set up {voice_channel.mention} as a generator in category {category.name}.",
            ephemeral=True,
        )
        self._print_status()

    @app_commands.command(name="setup_tryout_vc",
                          description="Setup a tryout VC generator with a voice channel and category.")
    @app_commands.describe(voice_channel="The voice channel to use as tryout generator",
                           category="The category for generated tryout VCs")
    async def setup_tryout_vc(self, interaction: Interaction,
                               voice_channel: discord.VoiceChannel,
                               category: discord.CategoryChannel):
        self._load_from_disk()
        self.tryout_generator_vc_ids.add(voice_channel.id)
        self._save_to_disk()
        await voice_channel.edit(category=category)
        await interaction.response.send_message(
            f"Set up {voice_channel.mention} as a tryout generator in category {category.name}.",
            ephemeral=True,
        )
        self._print_status()

    @app_commands.command(name="list_vc_generators",
                          description="List all current VC generators.")
    async def list_vc_generators(self, interaction: Interaction):
        self._load_from_disk()
        normal = ", ".join(f"<#{v}>" for v in self.generator_vc_ids) or "None"
        tryout = ", ".join(f"<#{v}>" for v in self.tryout_generator_vc_ids) or "None"
        embed = Embed(title="VC Generator Status",
                      description="Current generator voice channels.",
                      color=discord.Color.blue())
        embed.add_field(name="Normal Generators", value=normal, inline=False)
        embed.add_field(name="Tryout Generators", value=tryout, inline=False)
        embed.add_field(name="Tracked Generated VCs",
                        value=str(len(self.generated_vc_ids)), inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------
    # Voice state handler — the core logic
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Fires every time anyone joins / leaves / moves voice channels."""
        try:
            # Refresh generator IDs from disk every event (cheap file read,
            # guarantees we always respect setup changes immediately).
            self._load_from_disk()

            # 1. GENERATE — user joined a generator channel
            if after.channel:
                if after.channel.id in self.tryout_generator_vc_ids:
                    await self._create_tryout_vc(member, after.channel)
                    return
                if after.channel.id in self.generator_vc_ids:
                    await self._create_normal_vc(member, after.channel)
                    return

            # 2. DELETE — user left a generated channel (check if now empty)
            if before.channel and before.channel != after.channel:
                if before.channel.id in self.generated_vc_ids:
                    await self._try_delete(before.channel.id)

        except Exception as e:
            print(f"[VCSystem] ERROR in on_voice_state_update: {e}")
            traceback.print_exc()

    # ------------------------------------------------------------------
    # VC creation helpers
    # ------------------------------------------------------------------

    async def _create_tryout_vc(self, member: discord.Member, generator: discord.VoiceChannel):
        category = generator.category
        overwrites = {
            member.guild.default_role: discord.PermissionOverwrite(
                connect=False, view_channel=False),
            member: discord.PermissionOverwrite(
                manage_channels=True, connect=True, view_channel=True, move_members=True),
        }
        for role in member.guild.roles:
            if role.permissions.administrator:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True, connect=True, move_members=True)

        new_vc = await category.create_voice_channel(
            f"{member.display_name}'s Tryout VC", overwrites=overwrites)
        self._track(new_vc.id)

        try:
            await member.move_to(new_vc)
        except Exception as e:
            print(f"[VCSystem] move_to failed (tryout), cleaning up: {e}")
            try:
                await new_vc.delete(reason="Cleanup: move_to failed")
            except Exception:
                pass
            self._untrack(new_vc.id)
            return

        try:
            await member.send(embed=Embed(
                title="Tryout VC Created",
                description="You can now drag players from the waiting room into your Tryout VC.",
                color=0x00ff00))
        except Exception:
            pass

    async def _create_normal_vc(self, member: discord.Member, generator: discord.VoiceChannel):
        category = generator.category
        overwrites = {
            member.guild.default_role: discord.PermissionOverwrite(
                connect=True, view_channel=True),
            member: discord.PermissionOverwrite(
                manage_channels=True, connect=True, view_channel=True),
        }

        new_vc = await category.create_voice_channel(
            f"{member.display_name}'s VC", overwrites=overwrites)
        self._track(new_vc.id)

        try:
            await member.move_to(new_vc)
        except Exception as e:
            print(f"[VCSystem] move_to failed (normal), cleaning up: {e}")
            try:
                await new_vc.delete(reason="Cleanup: move_to failed")
            except Exception:
                pass
            self._untrack(new_vc.id)
            return

        # Try to find the auto-generated VC text chat
        vc_chat = None
        for _ in range(10):
            vc_chat = getattr(new_vc, "text_channel", None)
            if vc_chat:
                break
            await asyncio.sleep(0.5)
        if not vc_chat:
            expected = new_vc.name.replace(" ", "-").lower()
            for ch in category.text_channels:
                if ch.name.startswith(expected):
                    vc_chat = ch
                    break

        if vc_chat:
            chat_ow = {
                member.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                member: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            }
            for role in member.guild.roles:
                if role.permissions.administrator:
                    chat_ow[role] = discord.PermissionOverwrite(
                        read_messages=True, send_messages=True)
            await vc_chat.edit(overwrites=chat_ow)
            await vc_chat.send(
                content=f"{member.mention}",
                embed=Embed(title="VC Controls",
                            description="Use the buttons below to manage your VC.",
                            color=0x00ff00),
                view=VCControls(member.id, new_vc))

    # ------------------------------------------------------------------
    # Lifecycle events
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_ready(self):
        print("[VCSystem] on_ready fired.")
        self._load_from_disk()
        self._print_status()
        await self._startup_cleanup()
        # Ensure the background cleanup loop is running
        if not self.periodic_cleanup.is_running():
            self.periodic_cleanup.start()
            print("[VCSystem] periodic_cleanup task started.")

    @commands.Cog.listener()
    async def on_connect(self):
        print("[VCSystem] Connected to Discord gateway.")

    @commands.Cog.listener()
    async def on_disconnect(self):
        print("[VCSystem] WARNING: Disconnected from Discord gateway. Will auto-reconnect.")

    @commands.Cog.listener()
    async def on_resumed(self):
        print("[VCSystem] Resumed connection to Discord.")
        self._load_from_disk()
        # Make sure the cleanup loop survived the disconnect
        if not self.periodic_cleanup.is_running():
            print("[VCSystem] Restarting periodic_cleanup after resume.")
            self.periodic_cleanup.start()

    # ------------------------------------------------------------------
    # Startup cleanup
    # ------------------------------------------------------------------

    async def _startup_cleanup(self):
        """Delete empty tracked VCs and scan for orphans after bot (re)start."""
        # 1. Delete known-empty generated VCs
        if self.generated_vc_ids:
            print(f"[VCSystem] Startup: checking {len(self.generated_vc_ids)} tracked VCs...")
            stale = list(self.generated_vc_ids)
            cleaned = 0
            for vc_id in stale:
                if await self._try_delete(vc_id, reason="Startup cleanup"):
                    cleaned += 1
                await asyncio.sleep(0.5)
            print(f"[VCSystem] Startup cleanup: {cleaned}/{len(stale)} removed.")

        # 2. Scan categories for orphaned VCs not in tracking
        await self._scan_orphans()

    async def _scan_orphans(self):
        """Find generated-looking VCs that aren't tracked and clean/re-track them."""
        all_gens = self.generator_vc_ids | self.tryout_generator_vc_ids
        categories_done: set[int] = set()
        for guild in self.bot.guilds:
            for gen_id in all_gens:
                ch = guild.get_channel(gen_id)
                if not ch or not ch.category or ch.category.id in categories_done:
                    continue
                categories_done.add(ch.category.id)
                for vc in ch.category.voice_channels:
                    if vc.id in all_gens:
                        continue
                    if vc.name.endswith("'s VC") or vc.name.endswith("'s Tryout VC"):
                        humans = [m for m in vc.members if not m.bot]
                        if not humans:
                            try:
                                await vc.delete(reason="Orphan cleanup")
                                self.generated_vc_ids.discard(vc.id)
                                print(f"[VCSystem] Orphan deleted: {vc.name} ({vc.id})")
                            except Exception as e:
                                print(f"[VCSystem] Orphan delete failed: {vc.name}: {e}")
                            await asyncio.sleep(0.5)
                        elif vc.id not in self.generated_vc_ids:
                            self.generated_vc_ids.add(vc.id)
                            print(f"[VCSystem] Re-tracking orphan: {vc.name} ({vc.id})")
        self._save_to_disk()

    # ------------------------------------------------------------------
    # Background cleanup loop — catches anything the event handler missed
    # ------------------------------------------------------------------

    @tasks.loop(minutes=2)
    async def periodic_cleanup(self):
        """Every 2 minutes, delete any tracked generated VCs that are empty."""
        if not self.generated_vc_ids:
            return
        for vc_id in list(self.generated_vc_ids):
            await self._try_delete(vc_id, reason="Periodic cleanup")
            await asyncio.sleep(0.3)

    @periodic_cleanup.before_loop
    async def _before_cleanup(self):
        await self.bot.wait_until_ready()

    @periodic_cleanup.error
    async def _cleanup_error(self, error):
        print(f"[VCSystem] periodic_cleanup crashed: {error}")
        traceback.print_exc()
        # Always restart — this loop must never stay dead
        await asyncio.sleep(15)
        if not self.periodic_cleanup.is_running():
            print("[VCSystem] Restarting periodic_cleanup after crash.")
            self.periodic_cleanup.start()


async def setup(bot):
    await bot.add_cog(VCSystem(bot))

