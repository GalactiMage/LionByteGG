"""
Verification Cog for BoilerCraftGG
Handles student verification for Purdue Network Minecraft Server
Uses buttons, modals, and dropdowns for a seamless verification flow
"""

import discord
from discord import app_commands
from discord.ext import commands
from discord import ui
import re
import aiohttp

import config
import settings
from utils.embeds import EmbedBuilder


class VerificationModal(ui.Modal, title="🎓 Purdue Network Verification"):
    """Modal form for student verification"""
    
    first_name = ui.TextInput(
        label="First Name",
        placeholder="Enter your first name...",
        style=discord.TextStyle.short,
        required=True,
        min_length=2,
        max_length=50
    )
    
    minecraft_ign = ui.TextInput(
        label="Minecraft Username (IGN)",
        placeholder="Enter your Minecraft username...",
        style=discord.TextStyle.short,
        required=True,
        min_length=3,
        max_length=16
    )
    
    purdue_email = ui.TextInput(
        label="Purdue Email",
        placeholder="yourname@purdue.edu, @pnw.edu, or @pfw.edu",
        style=discord.TextStyle.short,
        required=True,
        min_length=10,
        max_length=100
    )
    
    phone_number = ui.TextInput(
        label="Phone Number (Optional)",
        placeholder="(123) 456-7890",
        style=discord.TextStyle.short,
        required=False,
        max_length=20
    )
    
    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot
        
    async def validate_minecraft_username(self, username: str) -> dict | None:
        """Validate Minecraft username via Mojang API"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"https://api.mojang.com/users/profiles/minecraft/{username}"
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {
                            "username": data.get("name"),
                            "uuid": data.get("id")
                        }
                    return None
        except Exception:
            return None
            
    def validate_purdue_email(self, email: str) -> bool:
        """Validate that email is a valid Purdue email"""
        email_lower = email.lower().strip()
        
        # Check if it ends with a valid Purdue domain
        for domain in settings.VALID_EMAIL_DOMAINS:
            if email_lower.endswith(domain):
                # Basic email format validation
                pattern = r'^[a-zA-Z0-9._%+-]+' + re.escape(domain) + r'$'
                if re.match(pattern, email_lower):
                    return True
        return False
        
    def is_valid_minecraft_username(self, username: str) -> bool:
        """Validate Minecraft username format"""
        pattern = r'^[a-zA-Z0-9_]{3,16}$'
        return bool(re.match(pattern, username))
        
    async def on_submit(self, interaction: discord.Interaction):
        """Handle modal submission"""
        await interaction.response.defer(ephemeral=True)
        
        first_name = self.first_name.value.strip()
        minecraft_ign = self.minecraft_ign.value.strip()
        purdue_email = self.purdue_email.value.strip().lower()
        phone_number = self.phone_number.value.strip() if self.phone_number.value else None
        
        # Validate Minecraft username format
        if not self.is_valid_minecraft_username(minecraft_ign):
            embed = EmbedBuilder.error(
                title="Invalid Minecraft Username",
                description=(
                    "Your Minecraft username is invalid.\n\n"
                    "**Requirements:**\n"
                    "• 3-16 characters\n"
                    "• Only letters, numbers, and underscores\n\n"
                    "Please try again with a valid username."
                )
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
            
        # Validate Purdue email
        if not self.validate_purdue_email(purdue_email):
            embed = EmbedBuilder.error(
                title="Invalid Purdue Email",
                description=(
                    "You must use a valid Purdue email address.\n\n"
                    "**Accepted email domains:**\n"
                    "• `@purdue.edu` (West Lafayette)\n"
                    "• `@pnw.edu` (Purdue Northwest)\n"
                    "• `@pfw.edu` (Purdue Fort Wayne)\n\n"
                    "Please try again with your Purdue email."
                )
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
            
        # Verify Minecraft account exists
        mc_data = await self.validate_minecraft_username(minecraft_ign)
        if not mc_data:
            embed = EmbedBuilder.error(
                title="Minecraft Account Not Found",
                description=(
                    f"Could not find a Minecraft account with username **{minecraft_ign}**.\n\n"
                    "Please make sure:\n"
                    "• You spelled your username correctly\n"
                    "• You have a valid Java Edition account\n\n"
                    "Try again with the correct username."
                )
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
            
        # Check if user already has the verified role
        if settings.VERIFIED_ROLE_ID:
            verified_role = interaction.guild.get_role(settings.VERIFIED_ROLE_ID)
            if verified_role and verified_role in interaction.user.roles:
                embed = EmbedBuilder.warning(
                    title="Already Verified",
                    description="You already have the verified role!"
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
        # Store verification data temporarily and show campus selection
        verification_data = {
            "first_name": first_name,
            "minecraft_username": mc_data["username"],
            "minecraft_uuid": mc_data["uuid"],
            "email": purdue_email,
            "phone": phone_number
        }
        
        # Create campus selection embed
        embed = EmbedBuilder.create_embed(
            title="🏫 Select Your Campus",
            description=(
                f"Great job, **{first_name}**! You're almost done!\n\n"
                "Please select the Purdue campus you're currently enrolled at:"
            ),
            color=config.COLORS["primary"]
        )
        embed.set_thumbnail(url=interaction.client.user.display_avatar.url)
        
        # Add campus selection dropdown
        view = CampusSelectView(self.bot, verification_data)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


class CampusSelectView(ui.View):
    """View containing campus selection dropdown"""
    
    def __init__(self, bot: commands.Bot, verification_data: dict):
        super().__init__(timeout=None)  # No timeout - persist until used
        self.bot = bot
        self.verification_data = verification_data
        
    @ui.select(
        placeholder="🎓 Select your campus...",
        options=[
            discord.SelectOption(
                label="West Lafayette",
                value="west_lafayette",
                emoji="🏛️",
                description="Main campus in West Lafayette, IN"
            ),
            discord.SelectOption(
                label="Purdue Northwest",
                value="northwest",
                emoji="🌊",
                description="Hammond & Westville campuses"
            ),
            discord.SelectOption(
                label="Purdue Fort Wayne",
                value="fort_wayne",
                emoji="🏰",
                description="Fort Wayne, IN campus"
            ),
            discord.SelectOption(
                label="Purdue Indianapolis",
                value="indianapolis",
                emoji="🏙️",
                description="Indianapolis, IN campus"
            )
        ]
    )
    async def campus_select(self, interaction: discord.Interaction, select: ui.Select):
        """Handle campus selection"""
        await interaction.response.defer(ephemeral=True)
        
        campus_key = select.values[0]
        campus_info = config.CAMPUSES[campus_key]
        
        # Assign roles
        roles_assigned = []
        
        # Add verified role
        if settings.VERIFIED_ROLE_ID:
            verified_role = interaction.guild.get_role(settings.VERIFIED_ROLE_ID)
            if verified_role:
                try:
                    await interaction.user.add_roles(verified_role)
                    roles_assigned.append(verified_role.name)
                except discord.Forbidden:
                    pass
                    
        # Add campus role
        campus_role_id = settings.CAMPUS_ROLES.get(campus_key)
        if campus_role_id:
            campus_role = interaction.guild.get_role(campus_role_id)
            if campus_role:
                try:
                    await interaction.user.add_roles(campus_role)
                    roles_assigned.append(campus_role.name)
                except discord.Forbidden:
                    pass
        
        # Save to database
        await self.bot.db.add_verified_user(
            discord_id=interaction.user.id,
            minecraft_username=self.verification_data["minecraft_username"],
            minecraft_uuid=self.verification_data.get("minecraft_uuid"),
            first_name=self.verification_data["first_name"],
            email=self.verification_data["email"],
            phone=self.verification_data.get("phone"),
            campus=campus_key
        )
                    
        # Create success embed
        embed = discord.Embed(
            title="✅ You're all set!",
            description=(
                f"Welcome, **{self.verification_data['first_name']}**! 🎉\n\n"
                f"**Server IP:** `{settings.MINECRAFT_SERVER_IP}`\n"
                f"**Your IGN:** `{self.verification_data['minecraft_username']}`"
            ),
            color=config.COLORS["success"]
        )
        embed.set_footer(text="Boiler Up! 🚂 • Purdue Network")
        
        # Send success message
        await interaction.followup.send(embed=embed, ephemeral=True)
        
        # Delete their welcome message
        try:
            welcome_msg_id = await interaction.client.db.get_setting(f"welcome_msg_{interaction.user.id}")
            welcome_channel_id = await interaction.client.db.get_setting(f"welcome_channel_{interaction.user.id}")
            
            if welcome_msg_id and welcome_channel_id:
                channel = interaction.guild.get_channel(int(welcome_channel_id))
                if channel:
                    try:
                        msg = await channel.fetch_message(int(welcome_msg_id))
                        await msg.delete()
                    except:
                        pass
        except:
            pass
        
        # Disable the view
        self.stop()
        
        print(f"[VERIFICATION] {interaction.user.name} verified as {self.verification_data['minecraft_username']} ({campus_info['name']})")


class StartVerificationView(ui.View):
    """Persistent view with Start button for verification"""
    
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)  # Persistent view
        self.bot = bot
        
    @ui.button(
        label="Start Verification",
        style=discord.ButtonStyle.green,
        emoji="🚀",
        custom_id="verification:start"
    )
    async def start_verification(self, interaction: discord.Interaction, button: ui.Button):
        """Handle Start button click"""
        # Check if user already has the verified role
        if settings.VERIFIED_ROLE_ID:
            verified_role = interaction.guild.get_role(settings.VERIFIED_ROLE_ID)
            if verified_role and verified_role in interaction.user.roles:
                embed = EmbedBuilder.warning(
                    title="Already Verified",
                    description="You already have the verified role!"
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
        # Show verification modal
        modal = VerificationModal(self.bot)
        await interaction.response.send_modal(modal)


class Verification(commands.Cog):
    """Student verification system for Purdue Network"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        
    async def cog_load(self):
        """Called when the cog is loaded"""
        # Register persistent views for buttons that must survive restarts
        self.bot.add_view(StartVerificationView(self.bot))
        self.bot.add_view(DMVerificationView(self.bot, settings.GUILD_ID))
        
        # Check if we have a saved verification panel and verify it still exists
        await self.restore_verification_panel()
        
    async def restore_verification_panel(self):
        """Restore the verification panel from database on startup"""
        try:
            # Get saved channel and message IDs
            channel_id = await self.bot.db.get_setting("verification_channel_id")
            message_id = await self.bot.db.get_setting("verification_message_id")
            
            if channel_id and message_id:
                channel_id = int(channel_id)
                message_id = int(message_id)
                
                # Try to find the channel and message
                for guild in self.bot.guilds:
                    channel = guild.get_channel(channel_id)
                    if channel:
                        try:
                            message = await channel.fetch_message(message_id)
                            print(f"[VERIFICATION] ✅ Restored verification panel in #{channel.name}")
                            return
                        except discord.NotFound:
                            print(f"[VERIFICATION] ⚠️ Saved verification panel message was deleted")
                            # Clear the saved settings since message is gone
                            await self.bot.db.set_setting("verification_channel_id", "")
                            await self.bot.db.set_setting("verification_message_id", "")
                        except discord.Forbidden:
                            print(f"[VERIFICATION] ⚠️ Cannot access verification panel channel")
                        break
            else:
                print(f"[VERIFICATION] ℹ️ No verification panel saved. Run /setup_verification to create one.")
        except Exception as e:
            print(f"[VERIFICATION] ❌ Error restoring verification panel: {e}")
        
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Handle new member joins - send welcome message"""
        
        # Don't process bots
        if member.bot:
            return
                    
        # Get the start-here channel
        if not settings.START_HERE_CHANNEL_ID:
            return
            
        channel = member.guild.get_channel(settings.START_HERE_CHANNEL_ID)
        if not channel:
            return
            
        # Create welcome embed
        embed = discord.Embed(
            title="👋 Welcome!",
            description=(
                f"Hey {member.mention}!\n\n"
                "To keep our community **Purdue students only**, please verify your account.\n\n"
                "Click the button below to get started!"
            ),
            color=config.COLORS["purdue_gold"]
        )
        embed.set_footer(text="Boiler Up! 🚂")
        
        # Send welcome message with Start button
        view = StartVerificationView(self.bot)
        welcome_msg = await channel.send(content=member.mention, embed=embed, view=view)
        
        # Store welcome message ID for deletion later
        await self.bot.db.set_setting(f"welcome_msg_{member.id}", str(welcome_msg.id))
        await self.bot.db.set_setting(f"welcome_channel_{member.id}", str(channel.id))
        
        print(f"[VERIFICATION] Sent welcome message to {member.name}")
        
    @app_commands.command(name="setup_verification", description="Setup the verification system (Admin only)")
    async def setup_verification(self, interaction: discord.Interaction):
        """Setup the verification channel with a persistent Start button"""
        
        # Check permissions
        if not interaction.user.guild_permissions.administrator:
            embed = EmbedBuilder.error(
                title="Permission Denied",
                description="You don't have permission to use this command!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        # Create the verification embed
        embed = discord.Embed(
            title="🎓 Purdue Network Student Verification",
            description=(
                "Welcome to **Purdue Network** - The Official Purdue Minecraft Server!\n\n"
                "To gain access to the server and our Discord community, you must verify that you're a Purdue student.\n\n"
                "**Click the green button below to start the verification process!**"
            ),
            color=config.COLORS["purdue_gold"]
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        
        embed.add_field(
            name="📋 Requirements",
            value=(
                "• Valid Purdue email address\n"
                "• Minecraft Java Edition account\n"
                "• Current Purdue student status"
            ),
            inline=True
        )
        
        embed.add_field(
            name="🏫 Accepted Campuses",
            value=(
                "• West Lafayette\n"
                "• Purdue Northwest\n"
                "• Purdue Fort Wayne\n"
                "• Purdue Indianapolis"
            ),
            inline=True
        )
        
        embed.add_field(
            name="🎮 Server Info",
            value=f"**IP:** `{settings.MINECRAFT_SERVER_IP}`",
            inline=False
        )
        
        embed.set_footer(
            text="Boiler Up! 🚂 • Purdue Network",
            icon_url=self.bot.user.display_avatar.url
        )
        
        # Send the embed with persistent button
        view = StartVerificationView(self.bot)
        panel_message = await interaction.channel.send(embed=embed, view=view)
        
        # Save the channel and message IDs to database for persistence
        await self.bot.db.set_setting("verification_channel_id", str(interaction.channel.id))
        await self.bot.db.set_setting("verification_message_id", str(panel_message.id))
        
        print(f"[VERIFICATION] Panel created in #{interaction.channel.name} by {interaction.user.name}")
        
        # Confirm to admin
        confirm_embed = EmbedBuilder.success(
            title="Setup Complete",
            description=(
                "Verification panel has been created!\n\n"
                "✅ Panel will persist across bot restarts\n"
                "✅ New members can click the button to verify"
            )
        )
        await interaction.response.send_message(embed=confirm_embed, ephemeral=True)
        
    @app_commands.command(name="unverify", description="Remove a user's verified role (Admin only)")
    @app_commands.describe(user="The Discord user to unverify")
    async def unverify(self, interaction: discord.Interaction, user: discord.Member):
        """Remove a user's verified role (Admin only)"""
        
        # Check permissions
        if not interaction.user.guild_permissions.administrator:
            embed = EmbedBuilder.error(
                title="Permission Denied",
                description="You don't have permission to use this command!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        # Check if user has verified role
        if settings.VERIFIED_ROLE_ID:
            verified_role = interaction.guild.get_role(settings.VERIFIED_ROLE_ID)
            if not verified_role or verified_role not in user.roles:
                embed = EmbedBuilder.info(
                    title="Not Verified",
                    description=f"{user.mention} doesn't have the verified role."
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
                
            # Remove verified role
            try:
                await user.remove_roles(verified_role)
            except discord.Forbidden:
                pass
                    
        # Remove campus roles
        for campus_key, role_id in settings.CAMPUS_ROLES.items():
            if role_id:
                campus_role = interaction.guild.get_role(role_id)
                if campus_role and campus_role in user.roles:
                    try:
                        await user.remove_roles(campus_role)
                    except discord.Forbidden:
                        pass
                    
        embed = EmbedBuilder.success(
            title="User Unverified",
            description=f"{user.mention}'s verified role has been removed."
        )
        await interaction.response.send_message(embed=embed)
        
        print(f"[VERIFICATION] {user.name} unverified by {interaction.user.name}")

    @app_commands.command(name="send-verify", description="Send a verification request to a user via DM (Admin only)")
    @app_commands.describe(user="The Discord user to send the verification DM to")
    async def send_verify(self, interaction: discord.Interaction, user: discord.Member):
        """Send a user a professional verification DM with the full verification flow"""
        
        # Check permissions
        if not interaction.user.guild_permissions.administrator:
            embed = EmbedBuilder.error(
                title="Permission Denied",
                description="You don't have permission to use this command!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Don't send to bots
        if user.bot:
            embed = EmbedBuilder.error(
                title="Invalid User",
                description="You can't send a verification request to a bot!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Check if user already has the verified role
        if settings.VERIFIED_ROLE_ID:
            verified_role = interaction.guild.get_role(settings.VERIFIED_ROLE_ID)
            if verified_role and verified_role in user.roles:
                embed = EmbedBuilder.warning(
                    title="Already Verified",
                    description=f"{user.mention} already has the verified role!"
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
        
        # Try to DM the user
        try:
            dm_embed = discord.Embed(
                title="🎓 Purdue Network — Verification Required",
                description=(
                    f"Hey **{user.display_name}**,\n\n"
                    "You've been asked to verify your identity for the "
                    "**Purdue Network Minecraft Server**.\n\n"
                    "Verification ensures that our community remains exclusive to "
                    "Purdue students and helps us maintain a safe, welcoming environment "
                    "for everyone.\n\n"
                    "Please complete the quick verification below to secure your "
                    "permanent spot on the server. It only takes a minute!\n\n"
                    "**Click the button below to get started.**"
                ),
                color=config.COLORS["purdue_gold"]
            )
            dm_embed.set_thumbnail(url=self.bot.user.display_avatar.url)
            
            dm_embed.add_field(
                name="📋 What You'll Need",
                value=(
                    "• A valid Purdue email address\n"
                    "• Your Minecraft Java Edition username\n"
                    "• Your first name"
                ),
                inline=True
            )
            
            dm_embed.add_field(
                name="🏫 Accepted Campuses",
                value=(
                    "• West Lafayette\n"
                    "• Purdue Northwest\n"
                    "• Purdue Fort Wayne\n"
                    "• Purdue Indianapolis"
                ),
                inline=True
            )
            
            dm_embed.add_field(
                name="🎮 Server IP",
                value=f"`{settings.MINECRAFT_SERVER_IP}`",
                inline=False
            )
            
            dm_embed.set_footer(
                text="Boiler Up! 🚂 • Purdue Network",
                icon_url=self.bot.user.display_avatar.url
            )
            
            view = DMVerificationView(self.bot, interaction.guild.id)
            await user.send(embed=dm_embed, view=view)
            
            # Confirm in the server
            confirm_embed = EmbedBuilder.success(
                title="Verification Request Sent",
                description=(
                    f"A verification DM has been sent to {user.mention}.\n\n"
                    "They'll be prompted to complete the verification process in their DMs."
                )
            )
            await interaction.response.send_message(embed=confirm_embed, ephemeral=True)
            
            print(f"[VERIFICATION] {interaction.user.name} sent verification request to {user.name}")
            
        except discord.Forbidden:
            embed = EmbedBuilder.error(
                title="Unable to Send DM",
                description=(
                    f"I couldn't send a DM to {user.mention}.\n\n"
                    "This usually means they have DMs disabled for this server. "
                    "Please ask them to enable **Allow direct messages from server members** "
                    "in their Privacy Settings, then try again."
                )
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)


class DMVerificationView(ui.View):
    """View sent in DMs with a Start Verification button"""
    
    def __init__(self, bot: commands.Bot, guild_id: int):
        super().__init__(timeout=None)
        self.bot = bot
        self.guild_id = guild_id
    
    @ui.button(
        label="Start Verification",
        style=discord.ButtonStyle.green,
        emoji="🚀",
        custom_id="verification:dm_start"
    )
    async def start_dm_verification(self, interaction: discord.Interaction, button: ui.Button):
        """Handle Start button click in DMs"""
        guild = self.bot.get_guild(self.guild_id)
        if not guild:
            await interaction.response.send_message("❌ Could not find the server. Please try again.", ephemeral=True)
            return
            
        member = guild.get_member(interaction.user.id)
        if not member:
            await interaction.response.send_message("❌ You don't appear to be in the server.", ephemeral=True)
            return
        
        # Check if already verified
        if settings.VERIFIED_ROLE_ID:
            verified_role = guild.get_role(settings.VERIFIED_ROLE_ID)
            if verified_role and verified_role in member.roles:
                await interaction.response.send_message("✅ You're already verified!", ephemeral=True)
                return
        
        modal = DMVerificationModal(self.bot, self.guild_id)
        await interaction.response.send_modal(modal)


class DMVerificationModal(ui.Modal, title="🎓 Purdue Network Verification"):
    """Modal form for DM-based verification"""
    
    first_name = ui.TextInput(
        label="First Name",
        placeholder="Enter your first name...",
        style=discord.TextStyle.short,
        required=True,
        min_length=2,
        max_length=50
    )
    
    minecraft_ign = ui.TextInput(
        label="Minecraft Username (IGN)",
        placeholder="Enter your Minecraft username...",
        style=discord.TextStyle.short,
        required=True,
        min_length=3,
        max_length=16
    )
    
    purdue_email = ui.TextInput(
        label="Purdue Email",
        placeholder="yourname@purdue.edu, @pnw.edu, or @pfw.edu",
        style=discord.TextStyle.short,
        required=True,
        min_length=10,
        max_length=100
    )
    
    phone_number = ui.TextInput(
        label="Phone Number (Optional)",
        placeholder="(123) 456-7890",
        style=discord.TextStyle.short,
        required=False,
        max_length=20
    )
    
    def __init__(self, bot: commands.Bot, guild_id: int):
        super().__init__()
        self.bot = bot
        self.guild_id = guild_id
    
    async def on_submit(self, interaction: discord.Interaction):
        """Handle DM modal submission"""
        await interaction.response.defer()
        
        first_name = self.first_name.value.strip()
        minecraft_ign = self.minecraft_ign.value.strip()
        purdue_email = self.purdue_email.value.strip().lower()
        phone_number = self.phone_number.value.strip() if self.phone_number.value else None
        
        # Validate Minecraft username format
        import re
        if not re.match(r'^[a-zA-Z0-9_]{3,16}$', minecraft_ign):
            embed = EmbedBuilder.error(
                title="Invalid Minecraft Username",
                description=(
                    "Your Minecraft username is invalid.\n\n"
                    "**Requirements:**\n"
                    "• 3-16 characters\n"
                    "• Only letters, numbers, and underscores"
                )
            )
            await interaction.followup.send(embed=embed)
            return
        
        # Validate Purdue email
        email_lower = purdue_email.lower()
        valid_email = False
        for domain in settings.VALID_EMAIL_DOMAINS:
            if email_lower.endswith(domain):
                pattern = r'^[a-zA-Z0-9._%+-]+' + re.escape(domain) + r'$'
                if re.match(pattern, email_lower):
                    valid_email = True
                    break
        
        if not valid_email:
            embed = EmbedBuilder.error(
                title="Invalid Purdue Email",
                description=(
                    "You must use a valid Purdue email address.\n\n"
                    "**Accepted:**\n"
                    "• `@purdue.edu`\n"
                    "• `@pnw.edu`\n"
                    "• `@pfw.edu`"
                )
            )
            await interaction.followup.send(embed=embed)
            return
        
        # Verify Minecraft account via Mojang API
        mc_data = None
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"https://api.mojang.com/users/profiles/minecraft/{minecraft_ign}"
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        mc_data = {"username": data.get("name"), "uuid": data.get("id")}
        except Exception:
            pass
        
        if not mc_data:
            embed = EmbedBuilder.error(
                title="Minecraft Account Not Found",
                description=(
                    f"Could not find **{minecraft_ign}** on Mojang.\n\n"
                    "Make sure you have a valid Java Edition account."
                )
            )
            await interaction.followup.send(embed=embed)
            return
        
        # Show campus selection
        verification_data = {
            "first_name": first_name,
            "minecraft_username": mc_data["username"],
            "minecraft_uuid": mc_data["uuid"],
            "email": purdue_email,
            "phone": phone_number
        }
        
        embed = EmbedBuilder.create_embed(
            title="🏫 Select Your Campus",
            description=(
                f"Great job, **{first_name}**! Almost done!\n\n"
                "Select the Purdue campus you're enrolled at:"
            ),
            color=config.COLORS["primary"]
        )
        
        view = DMCampusSelectView(self.bot, self.guild_id, verification_data)
        await interaction.followup.send(embed=embed, view=view)


class DMCampusSelectView(ui.View):
    """Campus selection for DM verification flow"""
    
    def __init__(self, bot: commands.Bot, guild_id: int, verification_data: dict):
        super().__init__(timeout=None)
        self.bot = bot
        self.guild_id = guild_id
        self.verification_data = verification_data
    
    @ui.select(
        placeholder="🎓 Select your campus...",
        options=[
            discord.SelectOption(label="West Lafayette", value="west_lafayette", emoji="🏛️", description="Main campus in West Lafayette, IN"),
            discord.SelectOption(label="Purdue Northwest", value="northwest", emoji="🌊", description="Hammond & Westville campuses"),
            discord.SelectOption(label="Purdue Fort Wayne", value="fort_wayne", emoji="🏰", description="Fort Wayne, IN campus"),
            discord.SelectOption(label="Purdue Indianapolis", value="indianapolis", emoji="🏙️", description="Indianapolis, IN campus"),
        ]
    )
    async def campus_select(self, interaction: discord.Interaction, select: ui.Select):
        """Handle campus selection in DMs"""
        await interaction.response.defer()
        
        campus_key = select.values[0]
        campus_info = config.CAMPUSES[campus_key]
        
        guild = self.bot.get_guild(self.guild_id)
        if not guild:
            await interaction.followup.send("❌ Could not find the server.")
            self.stop()
            return
        
        member = guild.get_member(interaction.user.id)
        if not member:
            await interaction.followup.send("❌ You don't appear to be in the server.")
            self.stop()
            return
        
        # Assign roles
        roles_assigned = []
        
        if settings.VERIFIED_ROLE_ID:
            verified_role = guild.get_role(settings.VERIFIED_ROLE_ID)
            if verified_role:
                try:
                    await member.add_roles(verified_role)
                    roles_assigned.append(verified_role.name)
                except discord.Forbidden:
                    pass
        
        campus_role_id = settings.CAMPUS_ROLES.get(campus_key)
        if campus_role_id:
            campus_role = guild.get_role(campus_role_id)
            if campus_role:
                try:
                    await member.add_roles(campus_role)
                    roles_assigned.append(campus_role.name)
                except discord.Forbidden:
                    pass
        
        # Save to database
        await self.bot.db.add_verified_user(
            discord_id=interaction.user.id,
            minecraft_username=self.verification_data["minecraft_username"],
            minecraft_uuid=self.verification_data.get("minecraft_uuid"),
            first_name=self.verification_data["first_name"],
            email=self.verification_data["email"],
            phone=self.verification_data.get("phone"),
            campus=campus_key
        )
        
        # Success message
        embed = discord.Embed(
            title="✅ You're all set!",
            description=(
                f"Welcome, **{self.verification_data['first_name']}**! 🎉\n\n"
                f"**Server IP:** `{settings.MINECRAFT_SERVER_IP}`\n"
                f"**Your IGN:** `{self.verification_data['minecraft_username']}`\n"
                f"**Campus:** {campus_info['name']}"
            ),
            color=config.COLORS["success"]
        )
        embed.set_footer(text="Boiler Up! 🚂 • Purdue Network")
        
        await interaction.followup.send(embed=embed)
        
        # Delete their welcome message in the server if it exists
        try:
            welcome_msg_id = await self.bot.db.get_setting(f"welcome_msg_{interaction.user.id}")
            welcome_channel_id = await self.bot.db.get_setting(f"welcome_channel_{interaction.user.id}")
            
            if welcome_msg_id and welcome_channel_id:
                channel = guild.get_channel(int(welcome_channel_id))
                if channel:
                    try:
                        msg = await channel.fetch_message(int(welcome_msg_id))
                        await msg.delete()
                    except (discord.NotFound, discord.Forbidden):
                        pass
        except Exception:
            pass
        
        self.stop()
        print(f"[VERIFICATION] {interaction.user.name} verified via DM as {self.verification_data['minecraft_username']} ({campus_info['name']})")


async def setup(bot: commands.Bot):
    """Setup function for loading the cog"""
    await bot.add_cog(Verification(bot))
