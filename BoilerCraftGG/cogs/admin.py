"""
Admin Cog for BoilerCraftGG
Handles administrative commands like /stop, /restart, /reload
"""

import discord
from discord import app_commands
from discord.ext import commands
import sys
import os

from utils.embeds import EmbedBuilder
import config
import settings


class Admin(commands.Cog):
    """Administrative commands for bot management"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        
    def is_admin():
        """Check if user is an admin"""
        async def predicate(interaction: discord.Interaction) -> bool:
            return interaction.user.guild_permissions.administrator
        return app_commands.check(predicate)
    
    @app_commands.command(name="stop", description="Stop the bot (Admin only)")
    @is_admin()
    async def stop(self, interaction: discord.Interaction):
        """Stop the bot"""
        embed = EmbedBuilder.warning(
            title="Shutting Down",
            description=f"Bot is being shut down by {interaction.user.mention}..."
        )
        await interaction.response.send_message(embed=embed)
        
        print(f"[ADMIN] Bot stopped by {interaction.user.name} ({interaction.user.id})")
        await self.bot.close()
        
    @app_commands.command(name="restart", description="Restart the bot (Admin only)")
    @is_admin()
    async def restart(self, interaction: discord.Interaction):
        """Restart the bot"""
        embed = EmbedBuilder.warning(
            title="Restarting",
            description=f"Bot is being restarted by {interaction.user.mention}..."
        )
        await interaction.response.send_message(embed=embed)
        
        print(f"[ADMIN] Bot restarted by {interaction.user.name} ({interaction.user.id})")
        
        # Restart the bot by re-executing the script
        os.execv(sys.executable, ['python'] + sys.argv)
        
    @app_commands.command(name="reload", description="Reload a cog (Admin only)")
    @app_commands.describe(cog="The name of the cog to reload")
    @is_admin()
    async def reload(self, interaction: discord.Interaction, cog: str):
        """Reload a specific cog"""
        try:
            await self.bot.reload_extension(f"cogs.{cog.lower()}")
            embed = EmbedBuilder.success(
                title="Cog Reloaded",
                description=f"Successfully reloaded `cogs.{cog.lower()}`"
            )
        except commands.ExtensionNotLoaded:
            embed = EmbedBuilder.error(
                title="Reload Failed",
                description=f"Cog `{cog}` is not loaded."
            )
        except commands.ExtensionNotFound:
            embed = EmbedBuilder.error(
                title="Reload Failed",
                description=f"Cog `{cog}` was not found."
            )
        except Exception as e:
            embed = EmbedBuilder.error(
                title="Reload Failed",
                description=f"Error: {str(e)}"
            )
            
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    @app_commands.command(name="sync", description="Sync slash commands (Admin only)")
    @is_admin()
    async def sync(self, interaction: discord.Interaction):
        """Sync slash commands with Discord"""
        await interaction.response.defer(ephemeral=True)
        
        try:
            if settings.GUILD_ID:
                guild = discord.Object(id=settings.GUILD_ID)
                self.bot.tree.copy_global_to(guild=guild)
                synced = await self.bot.tree.sync(guild=guild)
            else:
                synced = await self.bot.tree.sync()
                
            embed = EmbedBuilder.success(
                title="Commands Synced",
                description=f"Successfully synced {len(synced)} commands."
            )
        except Exception as e:
            embed = EmbedBuilder.error(
                title="Sync Failed",
                description=f"Error: {str(e)}"
            )
            
        await interaction.followup.send(embed=embed, ephemeral=True)
        
    @app_commands.command(name="status", description="View bot status and statistics")
    async def status(self, interaction: discord.Interaction):
        """View bot status"""
        embed = EmbedBuilder.create_embed(
            title=f"📊 {config.BOT_NAME} Status",
            description="Current bot statistics and information"
        )
        
        embed.add_field(
            name="🤖 Bot Info",
            value=(
                f"**Version:** {config.BOT_VERSION}\n"
                f"**Latency:** {round(self.bot.latency * 1000)}ms\n"
                f"**Guilds:** {len(self.bot.guilds)}"
            ),
            inline=True
        )
        
        embed.add_field(
            name="📈 Statistics",
            value=(
                f"**Users:** {sum(g.member_count for g in self.bot.guilds)}\n"
                f"**Cogs:** {len(self.bot.cogs)}\n"
                f"**Commands:** {len(self.bot.tree.get_commands())}"
            ),
            inline=True
        )
        
        await interaction.response.send_message(embed=embed)
        
    @stop.error
    @restart.error
    @reload.error
    @sync.error
    async def admin_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Error handler for admin commands"""
        if isinstance(error, app_commands.CheckFailure):
            embed = EmbedBuilder.error(
                title="Permission Denied",
                description="You don't have permission to use this command!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            embed = EmbedBuilder.error(
                title="Error",
                description=f"An error occurred: {str(error)}"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    # =========================================================================
    # Minecraft Maintenance Announcement
    # =========================================================================
    @app_commands.command(
        name="mc-maintenance-announcement",
        description="Announce Minecraft server maintenance to all Minecraft role members."
    )
    @app_commands.describe(
        when="Time and date for the maintenance (e.g. 'June 10th, 5pm')",
        servers="Names of the servers affected (e.g. 'Survival, Creative')"
    )
    @is_admin()
    async def mc_maintenance_announcement(self, interaction: discord.Interaction, when: str, servers: str):
        from views.ticket_view import load_bot_config
        cfg = load_bot_config()
        guild = interaction.guild
        announce_id = int(cfg.get("announce_channel_id") or 0) or settings.ANNOUNCE_CHANNEL_ID
        mc_role_id = int(cfg.get("minecraft_role_id") or 0) or settings.MINECRAFT_ROLE_ID
        announce_channel = guild.get_channel(announce_id)
        mc_role = guild.get_role(mc_role_id)
        if not announce_channel or not mc_role:
            await interaction.response.send_message("Announce channel or Minecraft role not found. Please check the IDs in settings.", ephemeral=True)
            return
        embed = discord.Embed(
            title="🛠️ Minecraft Server Maintenance",
            description=(
                "The **Purdue Network Minecraft Server** will be undergoing scheduled maintenance. Please see the details below."
            ),
            color=discord.Color.orange()
        )
        embed.add_field(
            name="🗓️ Date & Time",
            value=f"{when}",
            inline=True
        )
        embed.add_field(
            name="🖥️ Affected Servers",
            value=f"{servers}",
            inline=True
        )
        embed.add_field(
            name="ℹ️ What to Expect",
            value=(
                "• Servers may be **unavailable** or experience interruptions.\n"
                "• We appreciate your patience as we work to improve your experience."
            ),
            inline=False
        )
        embed.set_footer(text="Purdue Network | Minecraft Division")
        await announce_channel.send(content=f"{mc_role.mention}", embed=embed)
        await interaction.response.send_message("Maintenance announcement sent.", ephemeral=True)


async def setup(bot: commands.Bot):
    """Setup function for loading the cog"""
    await bot.add_cog(Admin(bot))
