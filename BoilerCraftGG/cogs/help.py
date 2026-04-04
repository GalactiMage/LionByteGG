"""
Help Cog for BoilerCraftGG
Provides help and information commands
"""

import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import EmbedBuilder
import config


class Help(commands.Cog):
    """Help and information commands"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        
    @app_commands.command(name="help", description="View all available commands")
    async def help(self, interaction: discord.Interaction):
        """Display all available commands"""
        
        embed = EmbedBuilder.create_embed(
            title=f"📚 {config.BOT_NAME} Help",
            description=(
                f"Welcome to **{config.BOT_NAME}**!\n"
                f"The official bot for **Purdue Network** Minecraft Server.\n\n"
                "Here are all available commands:"
            )
        )
        
        # General Commands
        embed.add_field(
            name="🎮 Verification",
            value="Click the **Start Verification** button in #start-here",
            inline=False
        )
        
        # Voice Channel Commands
        embed.add_field(
            name="🔊 Voice Channels",
            value=(
                "`/vc rename <name>` - Rename your channel\n"
                "`/vc limit <number>` - Set user limit\n"
                "`/vc lock` / `/vc unlock` - Lock/unlock channel\n"
                "`/vc permit <user>` - Allow a user to join\n"
                "`/vc reject <user>` - Block & kick a user\n"
                "`/vc kick <user>` - Kick a user\n"
                "`/vc transfer <user>` - Transfer ownership\n"
                "`/vc claim` - Claim an orphaned channel\n"
                "`/vc info` - View channel info"
            ),
            inline=False
        )
        
        # Info Commands
        embed.add_field(
            name="ℹ️ Information",
            value=(
                "`/help` - Show this help message\n"
                "`/status` - View bot status\n"
                "`/serverinfo` - View server information\n"
                "`/userinfo [user]` - View user information"
            ),
            inline=False
        )
        
        # Admin Commands
        if interaction.user.guild_permissions.administrator:
            embed.add_field(
                name="🔧 Admin Commands",
                value=(
                    "`/stop` - Stop the bot\n"
                    "`/restart` - Restart the bot\n"
                    "`/reload <cog>` - Reload a cog\n"
                    "`/sync` - Sync slash commands\n"
                    "`/unverify <user>` - Remove user verification\n"
                    "`/setup_verification` - Setup verification panel\n"
                    "`/setup_tempvc` - Add a Join to Create generator\n"
                    "`/tempvc_list` - List all generators\n"
                    "`/tempvc_remove` - Remove a generator"
                ),
                inline=False
            )
            
        embed.set_footer(text=f"{config.BOT_NAME} v{config.BOT_VERSION} • Purdue Network")
        
        await interaction.response.send_message(embed=embed)
        
    @app_commands.command(name="serverinfo", description="View server information")
    async def serverinfo(self, interaction: discord.Interaction):
        """Display server information"""
        
        guild = interaction.guild
        
        embed = EmbedBuilder.create_embed(
            title=f"📊 {guild.name}",
            description=guild.description or "No description set"
        )
        
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
            
        # Member counts
        total_members = guild.member_count
        bots = sum(1 for m in guild.members if m.bot)
        humans = total_members - bots
        
        embed.add_field(
            name="👥 Members",
            value=(
                f"**Total:** {total_members}\n"
                f"**Humans:** {humans}\n"
                f"**Bots:** {bots}"
            ),
            inline=True
        )
        
        # Channel counts
        text_channels = len(guild.text_channels)
        voice_channels = len(guild.voice_channels)
        categories = len(guild.categories)
        
        embed.add_field(
            name="📁 Channels",
            value=(
                f"**Text:** {text_channels}\n"
                f"**Voice:** {voice_channels}\n"
                f"**Categories:** {categories}"
            ),
            inline=True
        )
        
        # Server info
        embed.add_field(
            name="📋 Info",
            value=(
                f"**Owner:** {guild.owner.mention}\n"
                f"**Created:** <t:{int(guild.created_at.timestamp())}:R>\n"
                f"**Boost Level:** {guild.premium_tier}"
            ),
            inline=True
        )
        
        # Roles
        embed.add_field(
            name="🏷️ Roles",
            value=f"{len(guild.roles)} roles",
            inline=True
        )
        
        # Emojis
        embed.add_field(
            name="😀 Emojis",
            value=f"{len(guild.emojis)}/{guild.emoji_limit}",
            inline=True
        )
        
        # Boosts
        embed.add_field(
            name="💎 Boosts",
            value=f"{guild.premium_subscription_count} boosts",
            inline=True
        )
        
        await interaction.response.send_message(embed=embed)
        
    @app_commands.command(name="userinfo", description="View user information")
    @app_commands.describe(user="The user to view (leave empty for yourself)")
    async def userinfo(self, interaction: discord.Interaction, user: discord.Member = None):
        """Display user information"""
        
        target = user or interaction.user
        
        embed = EmbedBuilder.create_embed(
            title=f"👤 {target.display_name}",
            description=f"{target.mention}"
        )
        
        if target.avatar:
            embed.set_thumbnail(url=target.avatar.url)
            
        embed.add_field(
            name="📋 User Info",
            value=(
                f"**Username:** {target.name}\n"
                f"**ID:** `{target.id}`\n"
                f"**Bot:** {'Yes' if target.bot else 'No'}"
            ),
            inline=True
        )
        
        embed.add_field(
            name="📅 Dates",
            value=(
                f"**Joined:** <t:{int(target.joined_at.timestamp())}:R>\n"
                f"**Created:** <t:{int(target.created_at.timestamp())}:R>"
            ),
            inline=True
        )
        
        # Roles (excluding @everyone)
        roles = [r.mention for r in target.roles if r.name != "@everyone"][:10]
        roles_text = ", ".join(roles) if roles else "No roles"
        
        embed.add_field(
            name=f"🏷️ Roles ({len(target.roles) - 1})",
            value=roles_text,
            inline=False
        )
        
        # Check verification status
        verified = await self.bot.db.get_verified_user(target.id)
        if verified:
            embed.add_field(
                name="🎮 Minecraft Account",
                value=f"**{verified['minecraft_username']}**",
                inline=True
            )
            
        await interaction.response.send_message(embed=embed)
        
    @app_commands.command(name="ping", description="Check bot latency")
    async def ping(self, interaction: discord.Interaction):
        """Check bot latency"""
        
        latency = round(self.bot.latency * 1000)
        
        if latency < 100:
            status = "🟢 Excellent"
        elif latency < 200:
            status = "🟡 Good"
        else:
            status = "🔴 High"
            
        embed = EmbedBuilder.create_embed(
            title="🏓 Pong!",
            description=f"**Latency:** {latency}ms\n**Status:** {status}"
        )
        
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    """Setup function for loading the cog"""
    await bot.add_cog(Help(bot))
