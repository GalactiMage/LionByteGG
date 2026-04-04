import discord
import os

from utils.constants import LOG_CHANNEL_NAME, TICKET_LOGS_CHANNEL_NAME, STUDENTWORKER_LOGS_CHANNEL_NAME

async def get_or_create_log_channel(guild):
    """Get the log channel or create it if it doesn't exist."""
    for channel in guild.text_channels:
        if channel.name == LOG_CHANNEL_NAME:
            return channel
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        guild.me: discord.PermissionOverwrite(read_messages=True)
    }
    return await guild.create_text_channel(LOG_CHANNEL_NAME, overwrites=overwrites, reason="Created for LionByteGG moderation logs.")


async def get_or_create_ticket_logs_channel(guild):
    """Get the ticket logs channel or create it if it doesn't exist."""
    for channel in guild.text_channels:
        if channel.name == TICKET_LOGS_CHANNEL_NAME:
            return channel
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        guild.me: discord.PermissionOverwrite(read_messages=True)
    }
    return await guild.create_text_channel(TICKET_LOGS_CHANNEL_NAME, overwrites=overwrites, reason="Created for EMTS ticket logs.")


async def get_or_create_studentworker_logs_channel(guild):
    for channel in guild.text_channels:
        if channel.name == STUDENTWORKER_LOGS_CHANNEL_NAME:
            return channel
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        guild.me: discord.PermissionOverwrite(read_messages=True)
    }
    return await guild.create_text_channel(STUDENTWORKER_LOGS_CHANNEL_NAME, overwrites=overwrites, reason="Created for Student Worker logs.")

