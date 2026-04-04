import os
import json
import requests  # Make sure to install with: pip install requests
import discord
from discord.ext import commands, tasks
from discord import app_commands
import re
from utils.safe_json import safe_json_dump

GGLEAP_AUTH_TOKEN = os.environ.get("GGLEAP_AUTH_TOKEN_GAMES", "P1Q+Z3jtqCb4Eiw6RGzhoavp50zzOAwc3gsiPZiKhcOaDE75A1mVCPadifqukz1er5pchN+I1WwkIcDG+XvKCubHKmUTESKqGLNNcAge7xUF9y4XQBkP8i3H7028mrHd")
BASE_URL = "https://api.ggleap.com/beta"

jwt_token = None

def get_jwt():
    global jwt_token
    try:
        r = requests.post(
            f"{BASE_URL}/authorization/public-api/auth",
            headers={"Content-Type": "application/json-patch+json"},
            json={"AuthToken": GGLEAP_AUTH_TOKEN}
        )
        r.raise_for_status()
        jwt_token = r.json().get("Jwt")
    except Exception as e:
        print(f"[GGLEAP_GAMES] JWT error: {e}")

def get_enabled_apps():
    global jwt_token
    # Always refresh JWT before making the request to avoid 401 errors
    get_jwt()
    if not jwt_token:
        return []
    try:
        r = requests.get(
            f"{BASE_URL}/apps/get-enabled-apps-summary",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {jwt_token}"
            }
        )
        r.raise_for_status()
        data = r.json()
        apps = data.get("Apps", [])
        enabled_apps = [
            app for app in apps
            if app.get("IsEnabled", False)
        ]
        return enabled_apps
    except Exception as e:
        print(f"[GGLEAP_GAMES] Error fetching enabled apps/games: {e}")
        return []

def split_games_apps(apps):
    games = []
    other_apps = []
    for app in apps:
        app_type = app.get("AppType", "Unknown")
        # Only include enabled games/apps
        if app_type == "Game":
            games.append(app)
        elif app_type in {"Program", "Setting"}:
            other_apps.append(app)
        # Ignore "Unknown" and other types for dashboard
    return games, other_apps

def format_app_list(apps, max_per_line=4):
    if not apps:
        return "None"
    lines = []
    for i in range(0, len(apps), max_per_line):
        chunk = apps[i:i+max_per_line]
        line = " | ".join(f"`{app.get('Name', 'Unknown')}`" for app in chunk)
        lines.append(line)
    return "\n".join(lines)

def format_app_list_by_letter(apps):
    if not apps:
        return "None"
    # Categorize by first letter
    categorized = {}
    for app in apps:
        # Defensive: skip if app is None or missing Name
        if not app or not isinstance(app, dict):
            continue
        name = app.get('Name', None)
        if not name or not isinstance(name, str) or not name.strip():
            continue
        first_letter = name[0].upper()
        if not first_letter.isalpha():
            first_letter = "#"
        categorized.setdefault(first_letter, []).append(name)
    # Sort letters and names
    lines = []
    for letter in sorted(categorized.keys()):
        names = sorted(categorized[letter], key=lambda n: n.lower())
        section = f"**{letter}**\n" + " | ".join(f"`{n}`" for n in names)
        lines.append(section)
    return "\n\n".join(lines) if lines else "None"

PANEL_STORE_FILE = os.path.join("data", "ggleap_games.json")

def load_panel_store():
    if os.path.exists(PANEL_STORE_FILE):
        with open(PANEL_STORE_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except Exception:
                return {}
    return {}

def save_panel_store(panel_data):
    os.makedirs(os.path.dirname(PANEL_STORE_FILE), exist_ok=True)
    safe_json_dump(panel_data, PANEL_STORE_FILE, indent=2)

class RequestGameButtonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="➕ Request a Game", style=discord.ButtonStyle.green, custom_id="request_game")
    async def request_game(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="➕ Request a Game or App",
            description="To request a new game or app for the PNW Esports Arena, please fill out this form:\n[Game/App Request Form](https://www.tinyurl.com/pnwgamerequest)",
            color=discord.Color.green()
        )
        embed.set_footer(text="PNW Esports | Game/App Requests")
        await interaction.response.send_message(embed=embed, ephemeral=True)

class GGLeapGames(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.panel_messages = {}  # {guild_id: {"info": msg}}
        self.panel_channels = {}  # {guild_id: channel_id}
        self.panel_store = load_panel_store()
        self.bot.loop.create_task(self.restore_panels())
        self.refresh_jwt.start()
        self.last_games = None
        self.last_apps = None
        # Register persistent view for button after restart
        bot.add_view(RequestGameButtonView())

    async def restore_panels(self):
        await self.bot.wait_until_ready()
        for guild_id_str, info in self.panel_store.items():
            guild_id = int(guild_id_str)
            channel_id = info.get("channel_id")
            info_msg_id = info.get("info_msg_id")
            guild = self.bot.get_guild(guild_id)
            if guild and channel_id and info_msg_id:
                channel = guild.get_channel(channel_id)
                if channel:
                    try:
                        info_msg = await channel.fetch_message(info_msg_id)
                        self.panel_messages[guild_id] = {
                            "info": info_msg
                        }
                        self.panel_channels[guild_id] = channel_id
                    except Exception as e:
                        print(f"[GGLeapGames] Could not restore panel for guild {guild_id}: {e}")

    @tasks.loop(hours=1)
    async def refresh_jwt(self):
        get_jwt()

    def build_dashboard_embeds(self, games, apps):
        info_embed = discord.Embed(
            title="🎮 PNW Esports Games/Apps Dashboard",
            color=discord.Color.gold(),
            description="Live overview of all enabled games and apps on PNW Esports systems.\n\n*System created by Jay Moon (Mage)*"
        )
        info_embed.set_footer(text="PNW Esports | Games/Apps Dashboard")
        info_embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png")

        games_embed = discord.Embed(
            title=f"🕹️ Enabled Games [`{len(games)}`]",
            color=discord.Color.green(),
            description=format_app_list_by_letter(games)
        )
        games_embed.set_footer(text="PNW Esports | Games Live Feed")

        apps_embed = discord.Embed(
            title=f"🧰 Enabled Apps [`{len(apps)}`]",
            color=discord.Color.blue(),
            description=format_app_list_by_letter(apps)
        )
        apps_embed.set_footer(text="PNW Esports | Apps Live Feed")

        return [info_embed, games_embed, apps_embed]

    @app_commands.command(name="setup_ggleapgames", description="Setup a GGLeap games/apps dashboard in this channel.")
    async def setup_ggleapgames(self, interaction: discord.Interaction):
        await interaction.response.defer()
        apps = get_enabled_apps()
        games, other_apps = split_games_apps(apps)
        embeds = self.build_dashboard_embeds(games, other_apps)
        # Send only one message with all embeds and the button view
        info_msg = await interaction.channel.send(embeds=embeds, view=RequestGameButtonView())
        guild_id = interaction.guild_id
        channel_id = interaction.channel_id
        self.panel_messages[guild_id] = {
            "info": info_msg
        }
        self.panel_channels[guild_id] = channel_id
        self.panel_store[str(guild_id)] = {
            "channel_id": channel_id,
            "info_msg_id": info_msg.id
        }
        save_panel_store(self.panel_store)
        await interaction.followup.send("✅ GGLeap games/apps dashboard created and will update every 15 seconds.", ephemeral=True)

    @app_commands.command(name="sync-games", description="Manually refresh the GGLeap games/apps dashboard for all guilds.")
    async def sync_games(self, interaction: discord.Interaction):
        await interaction.response.defer()
        updated = 0
        for guild_id, msgs in list(self.panel_messages.items()):
            try:
                apps = get_enabled_apps()
                games, other_apps = split_games_apps(apps)
                embeds = self.build_dashboard_embeds(games, other_apps)
                if "info" in msgs:
                    await msgs["info"].edit(embeds=embeds, view=RequestGameButtonView())
                    updated += 1
            except Exception as e:
                print(f"[GGLeapGames] Failed to sync dashboard for guild {guild_id}: {e}")
        await interaction.followup.send(f"✅ Refreshed dashboard for {updated} guild(s).", ephemeral=True)

async def setup(bot):
    # Only add the cog if it hasn't been added yet
    if bot.get_cog("GGLeapGames") is None:
        await bot.add_cog(GGLeapGames(bot))
