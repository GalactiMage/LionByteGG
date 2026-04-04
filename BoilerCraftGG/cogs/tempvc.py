"""
Temporary Voice Channel Cog for BoilerCraftGG
Handles the Join to Create VC system with support for multiple generators
"""

import discord
from discord import app_commands
from discord.ext import commands
from discord import ui

from utils.embeds import EmbedBuilder
import config
import settings


# Maximum number of temp VC generators allowed
MAX_GENERATORS = 4


class TempVCControlPanel(ui.View):
    """Control panel view with buttons for managing temp VC"""
    
    def __init__(self, bot: commands.Bot, owner_id: int, channel_id: int):
        super().__init__(timeout=None)
        self.bot = bot
        self.owner_id = owner_id
        self.channel_id = channel_id
        
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Check if the user is the channel owner"""
        temp_vc = await self.bot.db.get_temp_vc(self.channel_id)
        if not temp_vc or temp_vc["owner_id"] != interaction.user.id:
            await interaction.response.send_message(
                "❌ Only the channel owner can use these controls!",
                ephemeral=True
            )
            return False
        return True
        
    @ui.button(label="🔒 Lock", style=discord.ButtonStyle.secondary, custom_id="tempvc:lock", row=0)
    async def lock_button(self, interaction: discord.Interaction, button: ui.Button):
        """Lock the channel - deny connect while keeping other category perms"""
        channel = interaction.guild.get_channel(self.channel_id)
        if channel:
            # Get current overwrites and modify only connect
            overwrites = channel.overwrites_for(interaction.guild.default_role)
            overwrites.connect = False
            await channel.set_permissions(interaction.guild.default_role, overwrite=overwrites)
            await interaction.response.send_message("🔒 Channel locked!", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Channel not found!", ephemeral=True)
            
    @ui.button(label="🔓 Unlock", style=discord.ButtonStyle.secondary, custom_id="tempvc:unlock", row=0)
    async def unlock_button(self, interaction: discord.Interaction, button: ui.Button):
        """Unlock the channel - reset connect to category default"""
        channel = interaction.guild.get_channel(self.channel_id)
        if channel:
            # Get current overwrites and reset connect to inherit from category
            overwrites = channel.overwrites_for(interaction.guild.default_role)
            overwrites.connect = None
            await channel.set_permissions(interaction.guild.default_role, overwrite=overwrites)
            await interaction.response.send_message("🔓 Channel unlocked!", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Channel not found!", ephemeral=True)
            
    @ui.button(label="👁️ Hide", style=discord.ButtonStyle.secondary, custom_id="tempvc:hide", row=0)
    async def hide_button(self, interaction: discord.Interaction, button: ui.Button):
        """Hide the channel - deny view while keeping other category perms"""
        channel = interaction.guild.get_channel(self.channel_id)
        if channel:
            # Get current overwrites and modify only view_channel
            overwrites = channel.overwrites_for(interaction.guild.default_role)
            overwrites.view_channel = False
            await channel.set_permissions(interaction.guild.default_role, overwrite=overwrites)
            await interaction.response.send_message("👁️ Channel hidden!", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Channel not found!", ephemeral=True)
            
    @ui.button(label="👀 Reveal", style=discord.ButtonStyle.secondary, custom_id="tempvc:reveal", row=0)
    async def reveal_button(self, interaction: discord.Interaction, button: ui.Button):
        """Reveal the channel - reset view to category default"""
        channel = interaction.guild.get_channel(self.channel_id)
        if channel:
            # Get current overwrites and reset view_channel to inherit from category
            overwrites = channel.overwrites_for(interaction.guild.default_role)
            overwrites.view_channel = None
            await channel.set_permissions(interaction.guild.default_role, overwrite=overwrites)
            await interaction.response.send_message("👀 Channel revealed!", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Channel not found!", ephemeral=True)
            
    @ui.button(label="✏️ Rename", style=discord.ButtonStyle.primary, custom_id="tempvc:rename", row=1)
    async def rename_button(self, interaction: discord.Interaction, button: ui.Button):
        """Open rename modal"""
        modal = RenameModal(self.bot, self.channel_id)
        await interaction.response.send_modal(modal)
        
    @ui.button(label="👥 Set Limit", style=discord.ButtonStyle.primary, custom_id="tempvc:limit", row=1)
    async def limit_button(self, interaction: discord.Interaction, button: ui.Button):
        """Open limit modal"""
        modal = LimitModal(self.bot, self.channel_id)
        await interaction.response.send_modal(modal)
        
    @ui.button(label="🗑️ Delete", style=discord.ButtonStyle.danger, custom_id="tempvc:delete", row=1)
    async def delete_button(self, interaction: discord.Interaction, button: ui.Button):
        """Delete the channel"""
        channel = interaction.guild.get_channel(self.channel_id)
        if channel:
            await interaction.response.send_message("🗑️ Deleting channel...", ephemeral=True)
            await self.bot.db.remove_temp_vc(self.channel_id)
            await channel.delete(reason=f"Deleted by owner {interaction.user.name}")
        else:
            await interaction.response.send_message("❌ Channel not found!", ephemeral=True)


class RenameModal(ui.Modal, title="✏️ Rename Your Channel"):
    """Modal for renaming temp VC"""
    
    new_name = ui.TextInput(
        label="New Channel Name",
        placeholder="Enter a new name for your channel...",
        style=discord.TextStyle.short,
        required=True,
        min_length=1,
        max_length=100
    )
    
    def __init__(self, bot: commands.Bot, channel_id: int):
        super().__init__()
        self.bot = bot
        self.channel_id = channel_id
        
    async def on_submit(self, interaction: discord.Interaction):
        channel = interaction.guild.get_channel(self.channel_id)
        if channel:
            await channel.edit(name=self.new_name.value)
            await interaction.response.send_message(
                f"✅ Channel renamed to **{self.new_name.value}**!",
                ephemeral=True
            )
        else:
            await interaction.response.send_message("❌ Channel not found!", ephemeral=True)


class LimitModal(ui.Modal, title="👥 Set User Limit"):
    """Modal for setting user limit"""
    
    limit = ui.TextInput(
        label="User Limit (0 for unlimited)",
        placeholder="Enter a number between 0-99...",
        style=discord.TextStyle.short,
        required=True,
        max_length=2
    )
    
    def __init__(self, bot: commands.Bot, channel_id: int):
        super().__init__()
        self.bot = bot
        self.channel_id = channel_id
        
    async def on_submit(self, interaction: discord.Interaction):
        try:
            limit_num = int(self.limit.value)
            if limit_num < 0 or limit_num > 99:
                raise ValueError()
        except ValueError:
            await interaction.response.send_message(
                "❌ Please enter a valid number between 0-99!",
                ephemeral=True
            )
            return
            
        channel = interaction.guild.get_channel(self.channel_id)
        if channel:
            await channel.edit(user_limit=limit_num)
            limit_text = "unlimited" if limit_num == 0 else str(limit_num)
            await interaction.response.send_message(
                f"✅ User limit set to **{limit_text}**!",
                ephemeral=True
            )
        else:
            await interaction.response.send_message("❌ Channel not found!", ephemeral=True)


class TempVC(commands.Cog):
    """Temporary Voice Channel management system"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        
    async def cog_load(self):
        """Called when the cog is loaded - cleanup orphaned channels"""
        await self.cleanup_orphaned_channels()
        
    async def cleanup_orphaned_channels(self):
        """Clean up temp VCs that exist in database but not in Discord"""
        try:
            all_temp_vcs = await self.bot.db.get_all_temp_vcs()
            cleaned = 0
            
            for temp_vc in all_temp_vcs:
                channel_found = False
                for guild in self.bot.guilds:
                    channel = guild.get_channel(temp_vc["channel_id"])
                    if channel:
                        # Channel exists, check if it's empty
                        if len(channel.members) == 0:
                            try:
                                await channel.delete(reason="Temp VC cleanup - empty channel")
                                await self.bot.db.remove_temp_vc(temp_vc["channel_id"])
                                cleaned += 1
                            except:
                                pass
                        channel_found = True
                        break
                        
                if not channel_found:
                    # Channel doesn't exist anymore, remove from database
                    await self.bot.db.remove_temp_vc(temp_vc["channel_id"])
                    cleaned += 1
                    
            if cleaned > 0:
                print(f"[TEMP VC] Cleaned up {cleaned} orphaned temp VC(s)")
            else:
                print(f"[TEMP VC] No orphaned channels to clean up")
        except Exception as e:
            print(f"[TEMP VC] Error during cleanup: {e}")
        
    @commands.Cog.listener()
    async def on_voice_state_update(
        self, 
        member: discord.Member, 
        before: discord.VoiceState, 
        after: discord.VoiceState
    ):
        """Handle voice state updates for temp VC creation/deletion"""
        
        # User joined a voice channel - check if it's a generator
        if after.channel:
            # Get all configured generators
            generators = await self.bot.db.get_all_generators()
            
            for generator in generators:
                if after.channel.id == generator["join_channel_id"]:
                    # User joined a Join to Create channel
                    category = member.guild.get_channel(generator["category_id"])
                    await self.create_temp_vc(member, after.channel, category)
                    break
            
        # User left a voice channel - check if it should be deleted
        if before.channel and before.channel != after.channel:
            await self.check_delete_temp_vc(before.channel)
            
    async def create_temp_vc(self, member: discord.Member, trigger_channel: discord.VoiceChannel, category: discord.CategoryChannel = None):
        """Create a temporary voice channel for a user"""
        
        # Check if user already has a temp VC
        existing = await self.bot.db.get_user_temp_vc(member.id)
        if existing:
            # Move user to their existing channel
            existing_channel = member.guild.get_channel(existing["channel_id"])
            if existing_channel:
                await member.move_to(existing_channel)
                return
            else:
                # Channel was deleted, remove from database
                await self.bot.db.remove_temp_vc(existing["channel_id"])
        
        # Use provided category, or fall back to trigger channel's category
        if not category:
            category = trigger_channel.category
            
        # Create the temp voice channel
        channel_name = f"🎮 {member.display_name}'s Channel"
        
        try:
            # Build overwrites: sync category perms but ensure voice activation for everyone
            overwrites = {}
            if category:
                # Copy existing category overwrites
                for target, perms in category.overwrites.items():
                    overwrites[target] = perms

            # Force voice activation (no push-to-talk) for @everyone
            everyone_overwrite = overwrites.get(member.guild.default_role, discord.PermissionOverwrite())
            everyone_overwrite.use_voice_activation = True
            overwrites[member.guild.default_role] = everyone_overwrite

            # Owner permissions
            owner_overwrite = overwrites.get(member, discord.PermissionOverwrite())
            owner_overwrite.connect = True
            owner_overwrite.speak = True
            owner_overwrite.stream = True
            owner_overwrite.use_voice_activation = True
            owner_overwrite.manage_channels = True
            owner_overwrite.move_members = True
            owner_overwrite.mute_members = True
            owner_overwrite.deafen_members = True
            overwrites[member] = owner_overwrite

            # Create channel with all permissions set at once
            new_channel = await member.guild.create_voice_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                reason=f"Temp VC created for {member.name}"
            )
            
            # Add to database
            await self.bot.db.add_temp_vc(new_channel.id, member.id)
            
            # Move user to new channel
            await member.move_to(new_channel)
            
            # Send control panel in the VC's text chat
            embed = discord.Embed(
                title="🎮 Your Channel",
                description=f"**{member.display_name}** owns this channel.",
                color=config.COLORS["purdue_gold"]
            )
            embed.add_field(
                name="Controls",
                value="Use the buttons below or `/vc` commands.",
                inline=False
            )
            embed.set_footer(text="Channel deletes when empty")
            
            view = TempVCControlPanel(self.bot, member.id, new_channel.id)
            await new_channel.send(embed=embed, view=view)
                
            print(f"[TEMP VC] Created channel for {member.name}: {channel_name}")
            
        except discord.Forbidden:
            print(f"[TEMP VC] No permission to create channel for {member.name}")
        except Exception as e:
            print(f"[TEMP VC] Error creating channel: {e}")
            
    async def check_delete_temp_vc(self, channel: discord.VoiceChannel):
        """Check if a temp VC should be deleted (empty)"""
        
        # Check if this is a temp VC
        temp_vc = await self.bot.db.get_temp_vc(channel.id)
        if not temp_vc:
            return
            
        # Check if channel is empty
        if len(channel.members) == 0:
            try:
                await channel.delete(reason="Temp VC empty - auto deleted")
                await self.bot.db.remove_temp_vc(channel.id)
                print(f"[TEMP VC] Deleted empty channel: {channel.name}")
            except discord.NotFound:
                await self.bot.db.remove_temp_vc(channel.id)
            except Exception as e:
                print(f"[TEMP VC] Error deleting channel: {e}")
                
    # ==================== VC Commands Group ====================
    
    vc_group = app_commands.Group(name="vc", description="Temporary voice channel commands")
    
    @vc_group.command(name="rename", description="Rename your temporary voice channel")
    @app_commands.describe(name="The new name for your channel")
    async def vc_rename(self, interaction: discord.Interaction, name: str):
        """Rename user's temp VC"""
        
        # Check if user is in a voice channel
        if not interaction.user.voice or not interaction.user.voice.channel:
            embed = EmbedBuilder.error(
                title="Not in Voice Channel",
                description="You must be in your voice channel to rename it!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        channel = interaction.user.voice.channel
        
        # Check if this is user's temp VC
        temp_vc = await self.bot.db.get_temp_vc(channel.id)
        if not temp_vc or temp_vc["owner_id"] != interaction.user.id:
            embed = EmbedBuilder.error(
                title="Not Your Channel",
                description="You can only rename your own temporary voice channel!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        # Rename the channel
        try:
            await channel.edit(name=name)
            embed = EmbedBuilder.success(
                title="Channel Renamed",
                description=f"Your channel has been renamed to **{name}**"
            )
        except discord.Forbidden:
            embed = EmbedBuilder.error(
                title="Permission Denied",
                description="I don't have permission to rename this channel."
            )
        except Exception as e:
            embed = EmbedBuilder.error(
                title="Error",
                description=f"Failed to rename channel: {str(e)}"
            )
            
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    @vc_group.command(name="limit", description="Set user limit for your temporary voice channel")
    @app_commands.describe(limit="The maximum number of users (0 for unlimited)")
    async def vc_limit(self, interaction: discord.Interaction, limit: int):
        """Set user limit for user's temp VC"""
        
        # Validate limit
        if limit < 0 or limit > 99:
            embed = EmbedBuilder.error(
                title="Invalid Limit",
                description="User limit must be between 0 and 99."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        # Check if user is in a voice channel
        if not interaction.user.voice or not interaction.user.voice.channel:
            embed = EmbedBuilder.error(
                title="Not in Voice Channel",
                description="You must be in your voice channel to set the limit!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        channel = interaction.user.voice.channel
        
        # Check if this is user's temp VC
        temp_vc = await self.bot.db.get_temp_vc(channel.id)
        if not temp_vc or temp_vc["owner_id"] != interaction.user.id:
            embed = EmbedBuilder.error(
                title="Not Your Channel",
                description="You can only modify your own temporary voice channel!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        # Set the limit
        try:
            await channel.edit(user_limit=limit)
            limit_text = "unlimited" if limit == 0 else str(limit)
            embed = EmbedBuilder.success(
                title="User Limit Set",
                description=f"Your channel's user limit has been set to **{limit_text}**"
            )
        except Exception as e:
            embed = EmbedBuilder.error(
                title="Error",
                description=f"Failed to set limit: {str(e)}"
            )
            
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    @vc_group.command(name="lock", description="Lock your temporary voice channel")
    async def vc_lock(self, interaction: discord.Interaction):
        """Lock user's temp VC"""
        
        # Check if user is in a voice channel
        if not interaction.user.voice or not interaction.user.voice.channel:
            embed = EmbedBuilder.error(
                title="Not in Voice Channel",
                description="You must be in your voice channel to lock it!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        channel = interaction.user.voice.channel
        
        # Check if this is user's temp VC
        temp_vc = await self.bot.db.get_temp_vc(channel.id)
        if not temp_vc or temp_vc["owner_id"] != interaction.user.id:
            embed = EmbedBuilder.error(
                title="Not Your Channel",
                description="You can only lock your own temporary voice channel!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        # Lock the channel
        try:
            # Get current overwrites and modify only connect
            overwrites = channel.overwrites_for(interaction.guild.default_role)
            overwrites.connect = False
            await channel.set_permissions(interaction.guild.default_role, overwrite=overwrites)
            embed = EmbedBuilder.success(
                title="Channel Locked",
                description="Your voice channel has been locked. 🔒"
            )
        except Exception as e:
            embed = EmbedBuilder.error(
                title="Error",
                description=f"Failed to lock channel: {str(e)}"
            )
            
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    @vc_group.command(name="unlock", description="Unlock your temporary voice channel")
    async def vc_unlock(self, interaction: discord.Interaction):
        """Unlock user's temp VC"""
        
        # Check if user is in a voice channel
        if not interaction.user.voice or not interaction.user.voice.channel:
            embed = EmbedBuilder.error(
                title="Not in Voice Channel",
                description="You must be in your voice channel to unlock it!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        channel = interaction.user.voice.channel
        
        # Check if this is user's temp VC
        temp_vc = await self.bot.db.get_temp_vc(channel.id)
        if not temp_vc or temp_vc["owner_id"] != interaction.user.id:
            embed = EmbedBuilder.error(
                title="Not Your Channel",
                description="You can only unlock your own temporary voice channel!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        # Unlock the channel
        try:
            # Get current overwrites and reset connect to inherit from category
            overwrites = channel.overwrites_for(interaction.guild.default_role)
            overwrites.connect = None
            await channel.set_permissions(interaction.guild.default_role, overwrite=overwrites)
            embed = EmbedBuilder.success(
                title="Channel Unlocked",
                description="Your voice channel has been unlocked. 🔓"
            )
        except Exception as e:
            embed = EmbedBuilder.error(
                title="Error",
                description=f"Failed to unlock channel: {str(e)}"
            )
            
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    @vc_group.command(name="permit", description="Allow a user to join your locked channel")
    @app_commands.describe(user="The user to permit")
    async def vc_permit(self, interaction: discord.Interaction, user: discord.Member):
        """Permit a user to join a locked temp VC"""
        
        # Check if user is in a voice channel
        if not interaction.user.voice or not interaction.user.voice.channel:
            embed = EmbedBuilder.error(
                title="Not in Voice Channel",
                description="You must be in your voice channel!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        channel = interaction.user.voice.channel
        
        # Check if this is user's temp VC
        temp_vc = await self.bot.db.get_temp_vc(channel.id)
        if not temp_vc or temp_vc["owner_id"] != interaction.user.id:
            embed = EmbedBuilder.error(
                title="Not Your Channel",
                description="You can only permit users to your own channel!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        # Permit the user
        try:
            await channel.set_permissions(user, connect=True)
            embed = EmbedBuilder.success(
                title="User Permitted",
                description=f"{user.mention} can now join your voice channel."
            )
        except Exception as e:
            embed = EmbedBuilder.error(
                title="Error",
                description=f"Failed to permit user: {str(e)}"
            )
            
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    @vc_group.command(name="reject", description="Remove a user's permission to join your channel")
    @app_commands.describe(user="The user to reject")
    async def vc_reject(self, interaction: discord.Interaction, user: discord.Member):
        """Reject a user from joining temp VC"""
        
        # Check if user is in a voice channel
        if not interaction.user.voice or not interaction.user.voice.channel:
            embed = EmbedBuilder.error(
                title="Not in Voice Channel",
                description="You must be in your voice channel!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        channel = interaction.user.voice.channel
        
        # Check if this is user's temp VC
        temp_vc = await self.bot.db.get_temp_vc(channel.id)
        if not temp_vc or temp_vc["owner_id"] != interaction.user.id:
            embed = EmbedBuilder.error(
                title="Not Your Channel",
                description="You can only reject users from your own channel!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        # Reject the user and disconnect if they're in the channel
        try:
            await channel.set_permissions(user, connect=False)
            
            # Disconnect user if they're in the channel
            if user.voice and user.voice.channel == channel:
                await user.move_to(None)
                
            embed = EmbedBuilder.success(
                title="User Rejected",
                description=f"{user.mention} can no longer join your voice channel."
            )
        except Exception as e:
            embed = EmbedBuilder.error(
                title="Error",
                description=f"Failed to reject user: {str(e)}"
            )
            
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    @vc_group.command(name="claim", description="Claim ownership of an orphaned temp VC")
    async def vc_claim(self, interaction: discord.Interaction):
        """Claim an orphaned temp VC"""
        
        # Check if user is in a voice channel
        if not interaction.user.voice or not interaction.user.voice.channel:
            embed = EmbedBuilder.error(
                title="Not in Voice Channel",
                description="You must be in a voice channel to claim it!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        channel = interaction.user.voice.channel
        
        # Check if this is a temp VC
        temp_vc = await self.bot.db.get_temp_vc(channel.id)
        if not temp_vc:
            embed = EmbedBuilder.error(
                title="Not a Temp VC",
                description="This is not a temporary voice channel."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        # Check if original owner is still in the channel
        owner = interaction.guild.get_member(temp_vc["owner_id"])
        if owner and owner.voice and owner.voice.channel == channel:
            embed = EmbedBuilder.error(
                title="Owner Present",
                description="The channel owner is still in the channel!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        # Transfer ownership
        await self.bot.db.remove_temp_vc(channel.id)
        await self.bot.db.add_temp_vc(channel.id, interaction.user.id)
        
        # Update permissions
        if owner:
            await channel.set_permissions(owner, overwrite=None)
        await channel.set_permissions(
            interaction.user,
            connect=True,
            speak=True,
            stream=True,
            manage_channels=True,
            move_members=True,
            mute_members=True,
            deafen_members=True
        )
        
        embed = EmbedBuilder.success(
            title="Channel Claimed",
            description="You are now the owner of this voice channel!"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    @vc_group.command(name="kick", description="Kick a user from your temporary voice channel")
    @app_commands.describe(user="The user to kick")
    async def vc_kick(self, interaction: discord.Interaction, user: discord.Member):
        """Kick a user from temp VC"""
        
        # Check if user is in a voice channel
        if not interaction.user.voice or not interaction.user.voice.channel:
            embed = EmbedBuilder.error(
                title="Not in Voice Channel",
                description="You must be in your voice channel!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        channel = interaction.user.voice.channel
        
        # Check if this is user's temp VC
        temp_vc = await self.bot.db.get_temp_vc(channel.id)
        if not temp_vc or temp_vc["owner_id"] != interaction.user.id:
            embed = EmbedBuilder.error(
                title="Not Your Channel",
                description="You can only kick users from your own channel!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        # Can't kick yourself
        if user.id == interaction.user.id:
            embed = EmbedBuilder.error(
                title="Can't Kick Yourself",
                description="You can't kick yourself from your own channel!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        # Kick the user
        try:
            if user.voice and user.voice.channel == channel:
                await user.move_to(None)
                embed = EmbedBuilder.success(
                    title="User Kicked",
                    description=f"{user.mention} has been kicked from your voice channel."
                )
            else:
                embed = EmbedBuilder.warning(
                    title="User Not in Channel",
                    description=f"{user.mention} is not in your voice channel."
                )
        except Exception as e:
            embed = EmbedBuilder.error(
                title="Error",
                description=f"Failed to kick user: {str(e)}"
            )
            
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    @vc_group.command(name="transfer", description="Transfer ownership of your channel to another user")
    @app_commands.describe(user="The user to transfer ownership to")
    async def vc_transfer(self, interaction: discord.Interaction, user: discord.Member):
        """Transfer temp VC ownership"""
        
        # Check if user is in a voice channel
        if not interaction.user.voice or not interaction.user.voice.channel:
            embed = EmbedBuilder.error(
                title="Not in Voice Channel",
                description="You must be in your voice channel!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        channel = interaction.user.voice.channel
        
        # Check if this is user's temp VC
        temp_vc = await self.bot.db.get_temp_vc(channel.id)
        if not temp_vc or temp_vc["owner_id"] != interaction.user.id:
            embed = EmbedBuilder.error(
                title="Not Your Channel",
                description="You can only transfer ownership of your own channel!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        # Can't transfer to yourself
        if user.id == interaction.user.id:
            embed = EmbedBuilder.error(
                title="Invalid User",
                description="You can't transfer ownership to yourself!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        # Can't transfer to bots
        if user.bot:
            embed = EmbedBuilder.error(
                title="Invalid User",
                description="You can't transfer ownership to a bot!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        # Transfer ownership
        try:
            # Update database
            await self.bot.db.remove_temp_vc(channel.id)
            await self.bot.db.add_temp_vc(channel.id, user.id)
            
            # Update permissions - remove old owner's special perms
            await channel.set_permissions(interaction.user, overwrite=None)
            
            # Give new owner permissions
            await channel.set_permissions(
                user,
                connect=True,
                speak=True,
                stream=True,
                manage_channels=True,
                move_members=True,
                mute_members=True,
                deafen_members=True
            )
            
            # Rename channel to new owner
            new_name = f"🎮 {user.display_name}'s Channel"
            await channel.edit(name=new_name)
            
            embed = EmbedBuilder.success(
                title="Ownership Transferred",
                description=f"{user.mention} is now the owner of this voice channel!"
            )
            
            # Notify new owner
            try:
                notify_embed = discord.Embed(
                    title="🔊 Channel Ownership Transferred",
                    description=(
                        f"**{interaction.user.display_name}** has transferred ownership of "
                        f"their voice channel to you!\n\n"
                        f"You are now the owner of **{new_name}**"
                    ),
                    color=config.COLORS["success"]
                )
                await user.send(embed=notify_embed)
            except discord.Forbidden:
                pass
                
        except Exception as e:
            embed = EmbedBuilder.error(
                title="Error",
                description=f"Failed to transfer ownership: {str(e)}"
            )
            
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    @vc_group.command(name="info", description="View information about your temporary voice channel")
    async def vc_info(self, interaction: discord.Interaction):
        """View temp VC info"""
        
        # Check if user is in a voice channel
        if not interaction.user.voice or not interaction.user.voice.channel:
            embed = EmbedBuilder.error(
                title="Not in Voice Channel",
                description="You must be in a voice channel!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        channel = interaction.user.voice.channel
        
        # Check if this is a temp VC
        temp_vc = await self.bot.db.get_temp_vc(channel.id)
        if not temp_vc:
            embed = EmbedBuilder.info(
                title="Not a Temp VC",
                description="This is not a temporary voice channel."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        # Get owner info
        owner = interaction.guild.get_member(temp_vc["owner_id"])
        owner_name = owner.display_name if owner else "Unknown"
        is_owner = temp_vc["owner_id"] == interaction.user.id
        
        # Build info embed
        embed = discord.Embed(
            title=f"🔊 {channel.name}",
            description="Temporary Voice Channel Information",
            color=config.COLORS["primary"]
        )
        
        embed.add_field(
            name="👑 Owner",
            value=f"{owner.mention if owner else 'Unknown'} {'(You)' if is_owner else ''}",
            inline=True
        )
        
        embed.add_field(
            name="👥 Members",
            value=f"{len(channel.members)}/{channel.user_limit if channel.user_limit else '∞'}",
            inline=True
        )
        
        embed.add_field(
            name="🔒 Status",
            value="Locked" if channel.overwrites_for(interaction.guild.default_role).connect == False else "Open",
            inline=True
        )
        
        embed.add_field(
            name="📅 Created",
            value=f"<t:{int(channel.created_at.timestamp())}:R>",
            inline=True
        )
        
        embed.add_field(
            name="🎵 Bitrate",
            value=f"{channel.bitrate // 1000}kbps",
            inline=True
        )
        
        # List members
        member_list = "\n".join([f"• {m.display_name}" for m in channel.members[:10]])
        if len(channel.members) > 10:
            member_list += f"\n*...and {len(channel.members) - 10} more*"
            
        embed.add_field(
            name="📋 Current Members",
            value=member_list or "No members",
            inline=False
        )
        
        embed.set_footer(
            text="Boiler Up! 🚂 • Purdue Network",
            icon_url=self.bot.user.display_avatar.url
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    # ==================== Admin Setup Command ====================
    
    @app_commands.command(name="setup_tempvc", description="Setup a Join to Create VC generator (Admin only)")
    @app_commands.describe(
        category="The category where temp VCs will be created",
        join_channel="The voice channel users will join to create a temp VC",
        name="Optional name for this generator (e.g., 'Gaming', 'Study')"
    )
    async def setup_tempvc(
        self, 
        interaction: discord.Interaction, 
        category: discord.CategoryChannel,
        join_channel: discord.VoiceChannel,
        name: str = None
    ):
        """Setup a temp VC generator"""
        
        # Check permissions
        if not interaction.user.guild_permissions.administrator:
            embed = EmbedBuilder.error(
                title="Permission Denied",
                description="You don't have permission to use this command!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Check if we've reached the maximum number of generators
        current_count = await self.bot.db.count_generators()
        
        # Check if this join channel is already a generator
        existing = await self.bot.db.get_generator(join_channel.id)
        
        if not existing and current_count >= MAX_GENERATORS:
            embed = EmbedBuilder.error(
                title="Maximum Generators Reached",
                description=f"You can only have up to **{MAX_GENERATORS}** temp VC generators.\n\n"
                           f"Use `/tempvc_list` to see current generators and `/tempvc_remove` to remove one."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        # Save to database
        generator_name = name or f"Generator #{current_count + 1}"
        await self.bot.db.add_generator(join_channel.id, category.id, generator_name)
        
        # Create success embed
        action = "updated" if existing else "created"
        embed = discord.Embed(
            title=f"✅ Temp VC Generator {action.title()}",
            description=(
                f"**{generator_name}** has been {action}!\n\n"
                f"🎤 **Join Channel:** {join_channel.mention}\n"
                f"📁 **Category:** {category.name}\n\n"
                "When users join the trigger channel, a temporary voice channel will be created in this category."
            ),
            color=config.COLORS["success"]
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        
        embed.add_field(
            name="📋 How It Works",
            value=(
                "1. User joins the Join to Create channel\n"
                "2. Bot creates a temp VC in the category\n"
                "3. User is moved to their new channel\n"
                "4. Channel is deleted when empty"
            ),
            inline=False
        )
        
        # Show total generators
        new_count = await self.bot.db.count_generators()
        embed.add_field(
            name="📊 Total Generators",
            value=f"{new_count}/{MAX_GENERATORS}",
            inline=True
        )
        
        embed.set_footer(
            text="Settings saved! Will persist across restarts.",
            icon_url=self.bot.user.display_avatar.url
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
        print(f"[TEMP VC] Generator {action} by {interaction.user.name} - Join: {join_channel.name}, Category: {category.name}")
        
    @app_commands.command(name="tempvc_list", description="List all configured temp VC generators (Admin only)")
    async def tempvc_list(self, interaction: discord.Interaction):
        """List all temp VC generators"""
        
        # Check permissions
        if not interaction.user.guild_permissions.administrator:
            embed = EmbedBuilder.error(
                title="Permission Denied",
                description="You don't have permission to use this command!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        generators = await self.bot.db.get_all_generators()
        
        if not generators:
            embed = discord.Embed(
                title="📋 Temp VC Generators",
                description="No generators configured yet!\n\nUse `/setup_tempvc` to create one.",
                color=config.COLORS["info"]
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        embed = discord.Embed(
            title="📋 Temp VC Generators",
            description=f"You have **{len(generators)}/{MAX_GENERATORS}** generators configured.",
            color=config.COLORS["purdue_gold"]
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        
        for i, gen in enumerate(generators, 1):
            join_channel = interaction.guild.get_channel(gen["join_channel_id"])
            category = interaction.guild.get_channel(gen["category_id"])
            
            join_text = join_channel.mention if join_channel else f"~~Deleted~~ (ID: {gen['join_channel_id']})"
            cat_text = category.name if category else f"~~Deleted~~ (ID: {gen['category_id']})"
            
            embed.add_field(
                name=f"#{i} - {gen['name'] or 'Unnamed'}",
                value=f"🎤 Join: {join_text}\n📁 Category: {cat_text}",
                inline=False
            )
            
        embed.set_footer(
            text="Use /tempvc_remove to remove a generator",
            icon_url=self.bot.user.display_avatar.url
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    @app_commands.command(name="tempvc_remove", description="Remove a temp VC generator (Admin only)")
    @app_commands.describe(join_channel="The Join to Create channel to remove")
    async def tempvc_remove(
        self, 
        interaction: discord.Interaction, 
        join_channel: discord.VoiceChannel
    ):
        """Remove a temp VC generator"""
        
        # Check permissions
        if not interaction.user.guild_permissions.administrator:
            embed = EmbedBuilder.error(
                title="Permission Denied",
                description="You don't have permission to use this command!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        # Check if this channel is a generator
        existing = await self.bot.db.get_generator(join_channel.id)
        
        if not existing:
            embed = EmbedBuilder.error(
                title="Not a Generator",
                description=f"{join_channel.mention} is not configured as a Join to Create channel.\n\n"
                           f"Use `/tempvc_list` to see all configured generators."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        # Remove from database
        await self.bot.db.remove_generator(join_channel.id)
        
        embed = EmbedBuilder.success(
            title="Generator Removed",
            description=f"**{existing['name'] or 'Generator'}** has been removed!\n\n"
                       f"🎤 {join_channel.mention} is no longer a Join to Create channel."
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
        print(f"[TEMP VC] Generator removed by {interaction.user.name} - {join_channel.name}")


async def setup(bot: commands.Bot):
    """Setup function for loading the cog"""
    await bot.add_cog(TempVC(bot))
