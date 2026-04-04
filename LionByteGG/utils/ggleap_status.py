import os
import json
import requests  # Make sure to install with: pip install requests
import discord
from discord.ext import commands, tasks
from discord import app_commands
import re
from utils.safe_json import safe_json_dump

GGLEAP_AUTH_TOKEN = os.environ.get("GGLEAP_AUTH_TOKEN_STATUS", "DnRx4l0umS3vaw3bR/22yjvTFYtMC6QxTkvvI77g3Lrn3nX1BFwo4if37zZHJj83I4to+ruOnilshG3Mzhza3m+sonBs4YUx9v0EiC6738gAa0QAuwH+14Jso1197He/")
BASE_URL = "https://api.ggleap.com/beta"  # Updated base URL
PANEL_STORE_FILE = os.path.join("data", "ggleap_panels.json")

jwt_token = None

def get_jwt():
    global jwt_token
    # Remove "Refreshing JWT..." and "Received JWT: ..." logs, keep errors only
    try:
        r = requests.post(
            "https://api.ggleap.com/beta/authorization/public-api/auth",
            headers={
                "Content-Type": "application/json-patch+json"
            },
            json={"AuthToken": GGLEAP_AUTH_TOKEN}
        )
        r.raise_for_status()
        jwt_token = r.json().get("Jwt")
        if not jwt_token:
            print("JWT not found in response! Check your AuthToken and permissions.")
    except requests.exceptions.ConnectionError as e:
        print("Connection error: Could not reach api.ggleap.com. Check your internet connection and DNS settings.")
        print(f"Details: {e}")
    except Exception as e:
        print(f"Error refreshing JWT: {e}")

def is_pc(device):
    # Print all device types for debugging
    print(f"Device: {device.get('Name')} Type: {device.get('Type')}")
    # Accept both "WindowsPC" and "PC" types, and also check for "Other" if your PCs are marked as "Other"
    return device.get("Type") in {"WindowsPC", "PC", "Other"}

def get_pc_status():
    global jwt_token
    # If JWT is missing, try to refresh it
    if not jwt_token:
        print("JWT missing, refreshing...")
        get_jwt()
        if not jwt_token:
            print("Failed to obtain JWT. Aborting device status request.")
            return []
    try:
        r = requests.get(
            f"{BASE_URL}/machines/get-all",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {jwt_token}"
            }
        )
        r.raise_for_status()
        data = r.json()
        devices = data.get("Machines", [])
        device_status_list = []
        for device in devices:
            name = device.get("Name", "Unknown")
            # --- Filter out Stage PCs and VMs ---
            if (
                re.match(r"stage[1-6]$", name, re.IGNORECASE)
                or device.get("GgRockVm", False)
            ):
                continue
            state = device.get("State", "Unknown")
            if state in {"ReadyForUser", "IdleShuttingDown"}:
                status = "Available"
            elif state == "Off":
                status = "Off"
            elif state in {"UserLoggedIn", "UserLoggingIn", "AdminMode", "Restarting", "StartingUp", "ShuttingDown"}:
                status = "Not Available"
            else:
                status = "Unknown"
            device_status_list.append({
                "name": format_pc_name(name),  # Always format name as 'Island# S#'
                "type": "PC",
                "status": status
            })
        return device_status_list
    except requests.exceptions.HTTPError as e:
        print(f"HTTP error when fetching PC status: {e}")
        print(f"Response: {getattr(e.response, 'text', '')}")
        if getattr(e.response, "status_code", None) == 401:
            print("JWT may be expired or invalid, refreshing...")
            get_jwt()
            try:
                r = requests.get(
                    f"{BASE_URL}/machines/get-all",
                    headers={
                        "Accept": "application/json",
                        "Authorization": f"Bearer {jwt_token}"
                    }
                )
                r.raise_for_status()
                data = r.json()
                devices = data.get("Machines", [])
                device_status_list = []
                for device in devices:
                    name = device.get("Name", "Unknown")
                    if (
                        re.match(r"stage[1-6]$", name, re.IGNORECASE)
                        or device.get("GgRockVm", False)
                    ):
                        continue
                    state = device.get("State", "Unknown")
                    if state in {"ReadyForUser", "IdleShuttingDown"}:
                        status = "Available"
                    elif state == "Off":
                        status = "Off"
                    elif state in {"UserLoggedIn", "UserLoggingIn", "AdminMode", "Restarting", "StartingUp", "ShuttingDown"}:
                        status = "Not Available"
                    else:
                        status = "Unknown"
                    device_status_list.append({
                        "name": format_pc_name(name),  # Always format name as 'Island# S#'
                        "type": "PC",
                        "status": status
                    })
                return device_status_list
            except Exception as e2:
                print(f"Retry failed: {e2}")
        return []
    except Exception as e:
        print(f"Error fetching PC status: {e}")
        return []

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

def sort_pc_names(names):
    def parse_island(name):
        # Match Island{N}S{M}, e.g., Island1S2
        m = re.match(r"Island(\d+)S(\d+)", name, re.IGNORECASE)
        if m:
            return (int(m.group(1)), int(m.group(2)), name)
        return (float('inf'), float('inf'), name.lower())
    return sorted(names, key=parse_island)

def format_pc_name(name):
    m = re.match(r"Island(\d+)S(\d+)", name, re.IGNORECASE)
    if m:
        return f"Island {m.group(1)} S{m.group(2)}"
    return name

def grid_format(names, columns=4):
    # Format names into a grid with the given number of columns
    if not names:
        return "None"
    rows = []
    for i in range(0, len(names), columns):
        row = " | ".join(names[i:i+columns])
        rows.append(row)
    return "\n".join(rows)

def grid_island_format(names, columns=4):
    # Just show all names in a grid, no section headers
    pcs = [format_pc_name(n) for n in sort_pc_names(names)]
    return grid_format(pcs, columns)

class ReservePCTypeView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="Student Use", style=discord.ButtonStyle.green, custom_id="reserve_student")
    async def student_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Proceed to the LionByteGG Student Reservation Portal:\nhttps://centers.ggcircuit.com/pnw",
            ephemeral=True
        )

    @discord.ui.button(label="Event", style=discord.ButtonStyle.red, custom_id="reserve_event")
    async def event_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Proceed to the PNW Athletics Event Reservation Form:\nhttps://pnwathletics.com/sb_output.aspx?form=6",
            ephemeral=True
        )

class ReservePCButtonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Reserve a PC", style=discord.ButtonStyle.green, custom_id="reserve_pc_main")
    async def reserve_pc(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="🖥️ Welcome to the LionByteGG Reserve PC System",
            description=(
                "Is this reservation going to be for an **event** or for **student use**?\n\n"
                "Please choose one of the options below."
            ),
            color=discord.Color.gold()
        )
        await interaction.response.send_message(embed=embed, view=ReservePCTypeView(), ephemeral=True)

class GGLeapStatus(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.refresh_jwt.start()
        self.panel_messages = {}  # {guild_id: message}
        self.panel_channels = {}  # {guild_id: channel_id}
        self.panel_store = load_panel_store()
        self.bot.loop.create_task(self.restore_panels())
        self.panel_updater.start()

    async def restore_panels(self):
        await self.bot.wait_until_ready()
        for guild_id_str, info in self.panel_store.items():
            guild_id = int(guild_id_str)
            channel_id = info.get("channel_id")
            message_id = info.get("message_id")
            guild = self.bot.get_guild(guild_id)
            if guild and channel_id and message_id:
                channel = guild.get_channel(channel_id)
                if channel:
                    try:
                        msg = await channel.fetch_message(message_id)
                        self.panel_messages[guild_id] = msg
                        self.panel_channels[guild_id] = channel_id
                    except Exception as e:
                        print(f"[GGLeapStatus] Could not restore panel for guild {guild_id}: {e}")

    @tasks.loop(minutes=5)
    async def refresh_jwt(self):
        get_jwt()

    @commands.command()
    async def pcstatus(self, ctx):
        device_status_list = get_pc_status()
        available = [f"``{d['name']}``" for d in device_status_list if d["status"] == "Available"]
        not_available = [f"``{d['name']}``" for d in device_status_list if d["status"] == "Not Available"]
        off = [f"``{d['name']}``" for d in device_status_list if d["status"] == "Off"]

        embed = discord.Embed(title="GGLeap Device Status", color=0x00ff00)
        embed.add_field(name="✅ Available", value=len(available))
        embed.add_field(name="🚫 Not Available", value=len(not_available))
        embed.add_field(name="❌ Off", value=len(off))
        embed.add_field(
            name="🖥 All Devices (Type: Name)",
            value="\n".join([f"{d['type']}: ``{d['name']}``" for d in device_status_list]) or "None",
            inline=False
        )
        await ctx.send(embed=embed)

    def build_panel_embed(self, device_status_list):
        available = [f"``{d['name']}``" for d in device_status_list if d["status"] == "Available"]
        not_available = [f"``{d['name']}``" for d in device_status_list if d["status"] == "Not Available"]
        not_usable = [f"``{d['name']}``" for d in device_status_list if d["status"] in ("Off", "Unknown")]

        available_display = grid_island_format(available)
        not_available_display = grid_island_format(not_available)
        not_usable_display = grid_island_format(not_usable)

        info_embed = discord.Embed(
            title="📊 PNW Esports System Dashboard",
            color=discord.Color.gold(),
            description=(
                "Live overview of all PNW Esports systems and their current status.\n\n"
                "• **Available**: Systems ready for use.\n"
                "• **Not Available**: Systems currently occupied or in transition.\n"
                "• **Not Usable**: Systems offline or experiencing issues.\n\n"
                "**Status updates every 15 seconds.**\n\n"
                "*System created by Jay Moon (Mage)*"
            )
        )
        info_embed.set_footer(text="PNW Esports | System Dashboard")
        info_embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png")

        status_embed = discord.Embed(
            color=discord.Color.gold(),
            description="**PNW Hammond Esports Arena 🔴 LIVE FEED 🔴**\n"
        )
        status_embed.set_image(url="https://cdn.discordapp.com/attachments/1316453330695884912/1406635195725250692/A7AC3964-39CA-4158-A4F5-23046D3E6EE9.png?ex=68a32e9c&is=68a1dd1c&hm=3586921327f2adbc631fe9f7f5144ab264e9937cb0d01603b6a257738c181add&")
        status_embed.add_field(
            name=f"✅ Available ({len(available)})",
            value=available_display,
            inline=False
        )
        status_embed.add_field(
            name=f"🟠 Not Available ({len(not_available)})",
            value=not_available_display,
            inline=False
        )
        status_embed.add_field(
            name=f"🚫 Not Usable ({len(not_usable)})",
            value=not_usable_display,
            inline=False
        )
        status_embed.set_footer(text="PNW Esports | System Dashboard")

        return [info_embed, status_embed]

    @tasks.loop(seconds=15)
    async def panel_updater(self):
        for guild_id, msg in list(self.panel_messages.items()):
            try:
                device_status_list = get_pc_status()
                embeds = self.build_panel_embed(device_status_list)
                # Add ReservePCButtonView below the live feed
                await msg.edit(embeds=embeds, view=ReservePCButtonView())
            except Exception as e:
                print(f"[GGLeapStatus] Failed to update panel for guild {guild_id}: {e}")

    @app_commands.command(name="setup_ggpanel", description="Setup a GGLeap device status panel in this channel.")
    async def setup_ggpanel(self, interaction: discord.Interaction):
        await interaction.response.defer()
        device_status_list = get_pc_status()
        embeds = self.build_panel_embed(device_status_list)
        # Add ReservePCButtonView below the live feed
        msg = await interaction.channel.send(embeds=embeds, view=ReservePCButtonView())
        guild_id = interaction.guild_id
        channel_id = interaction.channel_id
        self.panel_messages[guild_id] = msg
        self.panel_channels[guild_id] = channel_id
        self.panel_store[str(guild_id)] = {
            "channel_id": channel_id,
            "message_id": msg.id
        }
        save_panel_store(self.panel_store)
        await interaction.followup.send("✅ GGLeap panel created and will update every 15 seconds.", ephemeral=True)

    # --- /pclookup slash command with dropdown ---
    @app_commands.command(name="pclookup", description="Lookup the status of a specific PC.")
    async def pclookup_slash(self, interaction: discord.Interaction):
        device_status_list = get_pc_status()
        options = [discord.SelectOption(label=f"{d['type']}: ``{d['name']}``", value=d["name"]) for d in device_status_list]
        if not options:
            await interaction.response.send_message("No devices found.", ephemeral=True)
            return

        class DeviceSelectView(discord.ui.View):
            def __init__(self, device_status_list):
                super().__init__(timeout=30)
                self.device_status_list = device_status_list

            @discord.ui.select(
                placeholder="Select a PC",  # Updated placeholder
                min_values=1,
                max_values=1,
                options=options
            )
            async def select_callback(self, select_interaction: discord.Interaction, select: discord.ui.Select):
                selected_name = select.values[0]
                device = next((d for d in self.device_status_list if d["name"] == selected_name), None)
                if not device:
                    await select_interaction.response.send_message("Device not found.", ephemeral=True)
                    return
                status = device["status"]
                color = (
                    discord.Color.green() if status == "Available"
                    else discord.Color.red() if status == "Off"
                    else discord.Color.orange()
                )
                embed = discord.Embed(
                    title=f"🖥 Device Status: {device['type']}: ``{device['name']}``",
                    description=f"Status: **{status}**",
                    color=color
                )
                await select_interaction.response.send_message(embed=embed, ephemeral=True)

        await interaction.response.send_message(
            "Select a PC to check its status:",
            view=DeviceSelectView(device_status_list),
            ephemeral=True
        )
async def setup(bot):
    await bot.add_cog(GGLeapStatus(bot))

