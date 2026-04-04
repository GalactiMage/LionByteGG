"""
Embed Builder Utility for BoilerCraftGG
Provides consistent embed styling across the bot
"""

import discord
from datetime import datetime
import config


class EmbedBuilder:
    """Utility class for creating consistent embeds"""
    
    @staticmethod
    def create_embed(
        title: str = None,
        description: str = None,
        color: int = None,
        thumbnail: str = None,
        image: str = None,
        footer: str = None,
        timestamp: bool = True
    ) -> discord.Embed:
        """Create a base embed with consistent styling"""
        
        embed = discord.Embed(
            title=title,
            description=description,
            color=color or config.COLORS["primary"]
        )
        
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)
        if image:
            embed.set_image(url=image)
        if footer:
            embed.set_footer(text=footer)
        else:
            embed.set_footer(text=f"{config.BOT_NAME} • Purdue Network")
        if timestamp:
            embed.timestamp = datetime.utcnow()
            
        return embed
    
    @staticmethod
    def success(title: str = "Success", description: str = None) -> discord.Embed:
        """Create a success embed"""
        return EmbedBuilder.create_embed(
            title=f"✅ {title}",
            description=description,
            color=config.COLORS["success"]
        )
    
    @staticmethod
    def error(title: str = "Error", description: str = None) -> discord.Embed:
        """Create an error embed"""
        return EmbedBuilder.create_embed(
            title=f"❌ {title}",
            description=description,
            color=config.COLORS["error"]
        )
    
    @staticmethod
    def warning(title: str = "Warning", description: str = None) -> discord.Embed:
        """Create a warning embed"""
        return EmbedBuilder.create_embed(
            title=f"⚠️ {title}",
            description=description,
            color=config.COLORS["warning"]
        )
    
    @staticmethod
    def info(title: str = "Info", description: str = None) -> discord.Embed:
        """Create an info embed"""
        return EmbedBuilder.create_embed(
            title=f"ℹ️ {title}",
            description=description,
            color=config.COLORS["info"]
        )
    
    @staticmethod
    def verification_prompt() -> discord.Embed:
        """Create the verification prompt embed"""
        embed = EmbedBuilder.create_embed(
            title="🎮 Purdue Network Verification",
            description=(
                "Welcome to **Purdue Network**!\n\n"
                "To gain access to the server, please verify your Minecraft account.\n\n"
                "**How to verify:**\n"
                "1. Use the `/verify` command\n"
                "2. Enter your Minecraft username\n"
                "3. Follow the instructions provided\n\n"
                "Once verified, you'll receive access to all channels!"
            ),
            color=config.COLORS["primary"]
        )
        embed.add_field(
            name="📋 Server Rules",
            value="Make sure to read our rules before playing!",
            inline=False
        )
        return embed
    
    @staticmethod
    def verification_success(minecraft_username: str) -> discord.Embed:
        """Create a verification success embed"""
        return EmbedBuilder.create_embed(
            title="✅ Verification Successful!",
            description=(
                f"Your account has been linked to **{minecraft_username}**!\n\n"
                "You now have access to the server. Enjoy playing on Purdue Network!"
            ),
            color=config.COLORS["success"]
        )
    
    @staticmethod
    def temp_vc_created(channel_name: str) -> discord.Embed:
        """Create a temp VC created embed"""
        return EmbedBuilder.create_embed(
            title="🔊 Voice Channel Created",
            description=(
                f"Your temporary voice channel **{channel_name}** has been created!\n\n"
                "**Controls:**\n"
                "• `/vc rename <name>` - Rename your channel\n"
                "• `/vc limit <number>` - Set user limit\n"
                "• `/vc lock` - Lock the channel\n"
                "• `/vc unlock` - Unlock the channel\n\n"
                "*The channel will be deleted when everyone leaves.*"
            ),
            color=config.COLORS["success"]
        )
    
    @staticmethod
    def help_embed(commands_list: list) -> discord.Embed:
        """Create a help embed with commands list"""
        embed = EmbedBuilder.create_embed(
            title="📚 BoilerCraftGG Commands",
            description="Here are all available commands:",
            color=config.COLORS["primary"]
        )
        
        for cmd in commands_list:
            embed.add_field(
                name=f"`/{cmd['name']}`",
                value=cmd['description'],
                inline=True
            )
            
        return embed
