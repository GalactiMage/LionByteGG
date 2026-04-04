import discord
from discord import app_commands, Embed, Interaction
from discord.ext import commands
from discord.ui import View, Button, Modal, TextInput
import sys
import os
import json
from datetime import datetime
from constants import DIRECTOR_ID, STUDENT_WORKER_ROLE_ID
from safe_json import safe_json_dump

# Import shared variables/functions from main
from main import (
    shift_board, shift_counter,
    load_schedules, save_schedules, save_shift_board
)

# Trade tracking file
TRADES_FILE = "trades.json"

def load_trades():
    """Load trades from file"""
    try:
        with open(TRADES_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []

def save_trades(trades):
    """Save trades to file"""
    try:
        safe_json_dump(trades, TRADES_FILE, indent=2)
    except Exception:
        pass

def add_trade(requester_id, requester_name, target_id, target_name, your_shift, wanted_shift, reason, schedule, status="awaiting"):
    """Add a new trade to the tracking file"""
    trades = load_trades()
    trade_id = str(len(trades) + 1)
    
    trade = {
        "id": trade_id,
        "requester_id": str(requester_id),
        "requester_name": requester_name,
        "target_id": str(target_id),
        "target_name": target_name,
        "your_shift": your_shift,
        "wanted_shift": wanted_shift,
        "reason": reason,
        "schedule": {
            "start_date": schedule.get("start_date") if schedule else None,
            "end_date": schedule.get("end_date") if schedule else None,
            "schedule_link": schedule.get("schedule_link") if schedule else None
        } if schedule else None,
        "status": status,
        "created_at": datetime.utcnow().isoformat(),
        "source": "discord_bot"
    }
    
    trades.append(trade)
    save_trades(trades)
    return trade_id

def update_trade_status(trade_id, status, updated_by=None, reason=None):
    """Update trade status"""
    trades = load_trades()
    for trade in trades:
        if str(trade.get("id")) == str(trade_id):
            trade["status"] = status
            trade["updated_at"] = datetime.utcnow().isoformat()
            if updated_by:
                trade["updated_by"] = updated_by
            if reason:
                trade["decline_reason"] = reason
            break
    save_trades(trades)

# --- Offer/Trade UI Components ---
class OfferScheduleSelect(discord.ui.Select):
    def __init__(self, schedules, requester_id):
        options = [
            discord.SelectOption(
                label=f"{s['start_date']} to {s['end_date']}",
                value=str(idx),
                description=s['schedule_link'][:80]
            )
            for idx, s in enumerate(schedules)
        ]
        super().__init__(
            placeholder="Select a schedule...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="offer_schedule_select"
        )
        self.schedules = schedules
        self.requester_id = requester_id

    async def callback(self, interaction: Interaction):
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("Only the requester can use this menu.", ephemeral=True)
            return
        idx = int(self.values[0])
        selected_schedule = self.schedules[idx]
        await interaction.response.send_modal(OfferShiftModal(interaction.user.id, selected_schedule))

class OfferScheduleSelectView(View):
    def __init__(self, schedules, requester_id):
        super().__init__(timeout=180)
        self.add_item(OfferScheduleSelect(schedules, requester_id))

class OfferShiftModal(Modal, title="Offer Your Shift"):
    name = TextInput(label="Your Name", placeholder="Enter your name", required=True)
    date = TextInput(label="Date of Shift", placeholder="DD-MM-YYYY", required=True)
    time = TextInput(label="Time of Shift", placeholder="e.g. 2:00 PM - 6:00 PM", required=True)
    reason = TextInput(label="Reason for Offering", style=discord.TextStyle.paragraph, required=True)

    def __init__(self, author_id, schedule):
        super().__init__()
        self.author_id = author_id
        self.schedule = schedule

    async def on_submit(self, interaction: Interaction):
        global shift_counter
        shift_id = shift_counter
        shift_counter += 1
        shift_info = {
            "user_id": self.author_id,
            "name": self.name.value,
            "date": self.date.value,
            "time": self.time.value,
            "reason": self.reason.value,
            "schedule": self.schedule
        }
        shift_board[shift_id] = shift_info
        # Notify all student workers
        from datetime import datetime
        now_str = datetime.now().strftime("%Y-%m-%d %I:%M %p")
        schedule_str = (
            f"**📅 Schedule:** {self.schedule['start_date']} to {self.schedule['end_date']}\n"
            f"[View Schedule]({self.schedule['schedule_link']})\n"
        )
        embed = Embed(
            title="🟢 Shift Available!",
            description=(
                f"{schedule_str}"
                f"**👤 Name:** {shift_info['name']}\n"
                f"**📅 Date:** {shift_info['date']}\n"
                f"**⏰ Time:** {shift_info['time']}\n"
                f"**📝 Reason:** {shift_info['reason']}\n"
                f"**🆔 Shift ID:** {shift_id}"
            ),
            color=0x27ae60
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_footer(text=f"Posted: {now_str}")
        view = TakeShiftView(shift_id)
        # Send to all student workers (by role mention)
        if STUDENT_WORKER_ROLE_ID:
            role_mention = f"<@&{STUDENT_WORKER_ROLE_ID}>"
            await interaction.channel.send(f"{role_mention} **A NEW SHIFT IS AVAILABLE**", embed=embed, view=view)
        else:
            await interaction.channel.send("**A NEW SHIFT IS AVAILABLE**", embed=embed, view=view)
        await interaction.response.send_message("Your shift offer has been posted!", ephemeral=True)
        # No longer DM the director when a shift is offered

class OfferShiftView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(OfferShiftButton())
        self.add_item(TradeShiftButton())

class OfferShiftButton(Button):
    def __init__(self):
        super().__init__(label="🟥 Offer Shift", style=discord.ButtonStyle.danger, custom_id="offer_shift")

    async def callback(self, interaction: Interaction):
        schedules = load_schedules()
        allowed_schedules = [s for s in schedules if s.get("allow_offers", False)]
        if not allowed_schedules:
            await interaction.response.send_message("No schedules available for offering shifts.", ephemeral=True)
            return
        await interaction.response.send_message(
            "Select the schedule for your shift offer:",
            view=OfferScheduleSelectView(allowed_schedules, interaction.user.id),
            ephemeral=True
        )

class TradeShiftButton(Button):
    def __init__(self):
        super().__init__(label="🟦 Trade Shift", style=discord.ButtonStyle.primary, custom_id="trade_shift", disabled=False)

    async def callback(self, interaction: Interaction):
        schedules = load_schedules()
        if not schedules:
            await interaction.response.send_message("No schedules available for trading.", ephemeral=True)
            return
        # Send the schedule select as an ephemeral message so only the user sees it
        await interaction.response.send_message(
            "Please select the schedule you want to trade a shift in:",
            view=TradeScheduleSelectView(schedules, interaction.user.id),
            ephemeral=True
        )

class TakeShiftView(View):
    def __init__(self, shift_id):
        super().__init__(timeout=None)
        self.add_item(TakeShiftButton(shift_id))

class TakeShiftButton(Button):
    def __init__(self, shift_id):
        super().__init__(label="✅ Take Shift", style=discord.ButtonStyle.success, custom_id=f"take_shift_{shift_id}")
        self.shift_id = shift_id

    async def callback(self, interaction: Interaction):
        shift = shift_board.get(self.shift_id)
        if not shift:
            await interaction.response.send_message("This shift is no longer available.", ephemeral=True)
            return
        if shift["user_id"] == interaction.user.id:
            await interaction.response.send_message("You cannot take your own shift.", ephemeral=True)
            return
        # Get bot instance from cog
        bot = interaction.client
        user = await bot.fetch_user(shift["user_id"])
        # Notify original offerer with an embed
        from datetime import datetime
        now_str = datetime.now().strftime("%Y-%m-%d %I:%M %p")
        embed_dm = Embed(
            title="✅ Your Shift Was Taken!",
            description=f"Your shift (ID: {self.shift_id}) was taken by {interaction.user.mention}.",
            color=0x2ecc71
        )
        embed_dm.add_field(name="📅 Date", value=shift["date"], inline=True)
        embed_dm.add_field(name="⏰ Time", value=shift["time"], inline=True)
        embed_dm.add_field(name="📝 Reason", value=shift["reason"], inline=False)
        embed_dm.set_footer(text=f"Taken: {now_str}")
        try:
            await user.send(embed=embed_dm)
        except Exception:
            pass
        # DM the director about the shift being taken
        director = await bot.fetch_user(DIRECTOR_ID)
        embed_director = Embed(
            title="🔄 Schedule Change",
            description=(
                f"**🆔 Shift ID:** {self.shift_id}\n"
                f"**👤 Offered By:** <@{shift['user_id']}>\n"
                f"**🙋 Taken By:** {interaction.user.mention}\n"
                f"**👤 Name:** {shift['name']}\n"
                f"**📅 Date:** {shift['date']}\n"
                f"**⏰ Time:** {shift['time']}\n"
                f"**📝 Reason:** {shift['reason']}"
            ),
            color=0xe67e22
        )
        embed_director.set_footer(text=f"Changed: {now_str}")
        try:
            await director.send(embed=embed_director)
        except Exception:
            pass
        # Update the original message to show taken and delete after delay
        if interaction.message:
            taken_embed = interaction.message.embeds[0].copy()
            taken_embed.color = 0x95a5a6
            taken_embed.title = "❌ Shift Taken!"
            taken_embed.description += f"\n\n**🙋 Taken by:** {interaction.user.mention}"
            taken_embed.set_footer(text=f"Taken: {now_str}")
            view = View()
            await interaction.message.edit(embed=taken_embed, view=view)
            # Delete the message after 15 seconds
            await interaction.message.delete(delay=15)
        del shift_board[self.shift_id]
        await interaction.response.send_message(f"You have taken shift ID {self.shift_id}.", ephemeral=True)

# --- Slash Command to Setup Offer Shift Board ---
@app_commands.command(name="setup_offershift", description="Setup the Offer Shift board for students.")
@app_commands.checks.has_permissions(administrator=True)
async def setup_offershift(interaction: Interaction):
    embed = Embed(
        title="🦁 LionShiftGG Shift Board",
        description=(
            "Welcome to the **Student Worker Shift Board**!\n\n"
            "🟥 If you need to offer your shift, use the red **Offer Shift** button below.\n"
            "🟦 If you want to trade a shift, use the blue **Trade Shift** button.\n\n"
            "All offered shifts will be posted for student workers to claim."
        ),
        color=0xe74c3c
    )
    embed.set_thumbnail(url="https://media.discordapp.net/attachments/1316453330695884912/1362053646170325032/8875956.png?ex=688a1ace&is=6888c94e&hm=4f0fe97ec1eae9001e4ab62a3effa2ccac9569eafb4838b54ff2ecd24257d5e4&=&format=webp&quality=lossless")
    embed.set_footer(text="🦁 LionShiftGG • Student Worker Shift Board")
    view = OfferShiftView()
    await interaction.response.defer(ephemeral=True)
    await interaction.channel.send(embed=embed, view=view)

# --- Trade Shift UI ---
class TradeScheduleSelect(discord.ui.Select):
    def __init__(self, schedules, requester_id):
        # Only include schedules where allow_offers is True
        allowed_schedules = [s for s in schedules if s.get("allow_offers", False)]
        options = [
            discord.SelectOption(
                label=f"{s['start_date']} to {s['end_date']}",
                value=str(idx),
                description=s['schedule_link'][:80]
            )
            for idx, s in enumerate(allowed_schedules)
        ]
        # Ensure there is at least one option
        if not options:
            options = [discord.SelectOption(label="No schedules available", value="none", description="")]
        super().__init__(
            placeholder="Select a schedule...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="trade_schedule_select"
        )
        self.schedules = allowed_schedules
        self.requester_id = requester_id

    async def callback(self, interaction: Interaction):
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("Only the requester can use this menu.", ephemeral=True)
            return
        if self.values[0] == "none":
            await interaction.response.send_message("No schedules available for trading.", ephemeral=True)
            return
        idx = int(self.values[0])
        selected_schedule = self.schedules[idx]
        # Prepare student select options
        role = interaction.guild.get_role(STUDENT_WORKER_ROLE_ID)
        options = []
        if role:
            for member in role.members:
                options.append(discord.SelectOption(
                    label=member.display_name,
                    value=str(member.id),
                    description=str(member)
                ))
        if not options:
            await interaction.response.send_message("No student workers found for trading.", ephemeral=True)
            return
        # Send student select as ephemeral message
        await interaction.response.send_message(
            "Please select the student you want to trade with:",
            view=TradeStudentSelectView(selected_schedule, options, interaction.user.id),
            ephemeral=True
        )
        self.disabled = True
        try:
            if interaction.message:  # Only try to edit if message exists
                await interaction.message.edit(view=self.view)
        except discord.errors.NotFound:
            pass  # Message was deleted or not found, ignore
        except Exception:
            pass  # Ignore other edit errors

class TradeScheduleSelectView(View):
    def __init__(self, schedules, requester_id):
        super().__init__(timeout=180)
        self.add_item(TradeScheduleSelect(schedules, requester_id))

class TradeStudentSelect(discord.ui.Select):
    def __init__(self, schedule, options, requester_id):
        super().__init__(
            placeholder="Select a student...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="trade_student_select"
        )
        self.schedule = schedule
        self.requester_id = requester_id

    async def callback(self, interaction: Interaction):
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("Only the requester can use this menu.", ephemeral=True)
            return
        target_user_id = int(self.values[0])
        await interaction.response.send_modal(TradeShiftDetailsModal(self.schedule, target_user_id))

class TradeStudentSelectView(View):
    def __init__(self, schedule, options, requester_id):
        super().__init__(timeout=180)
        self.add_item(TradeStudentSelect(schedule, options, requester_id))

class TradeShiftDetailsModal(Modal, title="Trade Shift - Step 2"):
    your_shift = TextInput(label="Your Shift (date/time)", placeholder="e.g. July 10, 2-6pm", required=True)
    wanted_shift = TextInput(label="Shift You Want (date/time)", placeholder="e.g. July 12, 10am-2pm", required=True)
    reason = TextInput(label="Reason for Trading Shift", placeholder="Why do you want to trade?", style=discord.TextStyle.paragraph, required=True)
    def __init__(self, schedule, target_user_id):
        super().__init__()
        self.schedule = schedule
        self.target_user_id = target_user_id

    async def on_submit(self, interaction: Interaction):
        bot = interaction.client
        try:
            user = await bot.fetch_user(self.target_user_id)
        except Exception:
            user = None
        if not user:
            await interaction.response.send_message("Could not find the user to trade with. Please check the selection.", ephemeral=True)
            return
        embed = Embed(
            title="🔄 Shift Trade Offer",
            description=(
                f"{interaction.user.mention} wants to trade shifts with you!\n\n"
                f"**Schedule:** {self.schedule['start_date']} to {self.schedule['end_date']}\n"
                f"**Their Shift:** {self.your_shift.value}\n"
                f"**Wants Your Shift:** {self.wanted_shift.value}\n"
                f"**Reason:** {self.reason.value}\n"
                f"[View Schedule]({self.schedule['schedule_link']})"
            ),
            color=0x3498db
        )
        embed.set_footer(text="LionShiftGG • Shift Trade Request")
        view = TradeAcceptDeclineView(
            requester_id=interaction.user.id,
            target_id=user.id,
            schedule=self.schedule,
            your_shift=self.your_shift.value,
            wanted_shift=self.wanted_shift.value
        )
        # DM the director with all info
        director = await bot.fetch_user(DIRECTOR_ID)
        embed_director = Embed(
            title="🔄 Shift Trade Requested",
            description=(
                f"**Requester:** {interaction.user.mention} (`{interaction.user.id}`)\n"
                f"**Target:** <@{user.id}> (`{user.id}`)\n"
                f"**Schedule:** {self.schedule['start_date']} to {self.schedule['end_date']}\n"
                f"**Requester Shift:** {self.your_shift.value}\n"
                f"**Requested Shift:** {self.wanted_shift.value}\n"
                f"**Reason:** {self.reason.value}\n"
                f"[View Schedule]({self.schedule['schedule_link']})"
            ),
            color=0xe67e22
        )
        embed_director.set_footer(text="LionShiftGG • Trade Notification")
        try:
            await director.send(embed=embed_director)
        except Exception:
            pass
        
        # Log the trade to the tracking file for web dashboard
        try:
            add_trade(
                requester_id=interaction.user.id,
                requester_name=interaction.user.display_name,
                target_id=user.id,
                target_name=user.display_name if hasattr(user, 'display_name') else str(user),
                your_shift=self.your_shift.value,
                wanted_shift=self.wanted_shift.value,
                reason=self.reason.value,
                schedule=self.schedule,
                status="awaiting"
            )
        except Exception:
            pass
        
        try:
            await user.send(embed=embed, view=view)
            await interaction.response.send_message("Trade offer sent! The student will receive a DM to accept or decline.", ephemeral=True)
        except Exception:
            await interaction.response.send_message("Could not DM the user. They may have DMs disabled.", ephemeral=True)

class TradeAcceptDeclineView(View):
    def __init__(self, requester_id, target_id, schedule, your_shift, wanted_shift):
        super().__init__(timeout=3600)
        self.requester_id = requester_id
        self.target_id = target_id
        self.schedule = schedule
        self.your_shift = your_shift
        self.wanted_shift = wanted_shift
        self.add_item(TradeAcceptButton())
        self.add_item(TradeDeclineButton())

class TradeAcceptButton(Button):
    def __init__(self):
        super().__init__(label="✅ Accept", style=discord.ButtonStyle.success, custom_id="trade_accept")

    async def callback(self, interaction: Interaction):
        view: TradeAcceptDeclineView = self.view
        if interaction.user.id != view.target_id:
            await interaction.response.send_message("You are not the recipient of this trade offer.", ephemeral=True)
            return
        # Disable buttons after pressing
        for item in self.view.children:
            item.disabled = True
        try:
            if interaction.message:
                await interaction.message.edit(view=self.view)
        except Exception:
            pass
        bot = interaction.client
        requester = await bot.fetch_user(view.requester_id)
        director = await bot.fetch_user(DIRECTOR_ID)
        embed_director = Embed(
            title="🔄 Director Approval Needed: Shift Trade",
            description=(
                f"**Requester:** <@{view.requester_id}> (`{view.requester_id}`)\n"
                f"**Target:** {interaction.user.mention} (`{interaction.user.id}`)\n"
                f"**Schedule:** {view.schedule['start_date']} to {view.schedule['end_date']}\n"
                f"**Requester Shift:** {view.your_shift}\n"
                f"**Requested Shift:** {view.wanted_shift}\n"
                f"[View Schedule]({view.schedule['schedule_link']})"
            ),
            color=0xf39c12
        )
        embed_director.set_footer(text="LionShiftGG • Director Approval Required")
        approval_view = DirectorApprovalView(
            requester_id=view.requester_id,
            target_id=view.target_id,
            schedule=view.schedule,
            your_shift=view.your_shift,
            wanted_shift=view.wanted_shift
        )
        try:
            await director.send(embed=embed_director, view=approval_view)
        except Exception:
            pass
        await interaction.response.send_message("You have accepted the trade offer. Awaiting director approval.", ephemeral=True)
        try:
            await requester.send("Your trade offer was accepted by the student. Awaiting director approval.")
        except Exception:
            pass
        self.view.stop()

class TradeDeclineButton(Button):
    def __init__(self):
        super().__init__(label="❌ Decline", style=discord.ButtonStyle.danger, custom_id="trade_decline")

    async def callback(self, interaction: Interaction):
        view: TradeAcceptDeclineView = self.view
        if interaction.user.id != view.target_id:
            await interaction.response.send_message("You are not the recipient of this trade offer.", ephemeral=True)
            return
        # Disable buttons after pressing
        for item in self.view.children:
            item.disabled = True
        try:
            if interaction.message:
                await interaction.message.edit(view=self.view)
        except Exception:
            pass
        # Prompt for reason via modal
        await interaction.response.send_modal(StudentDeclineReasonModal(view))

class StudentDeclineReasonModal(Modal, title="Reason for Declining Trade"):
    reason = TextInput(label="Reason for declining", style=discord.TextStyle.paragraph, required=True)
    def __init__(self, trade_view):
        super().__init__()
        self.trade_view = trade_view

    async def on_submit(self, interaction: Interaction):
        bot = interaction.client
        requester = await bot.fetch_user(self.trade_view.requester_id)
        embed = Embed(
            title="❌ Trade Declined",
            description=(
                f"{interaction.user.mention} has **declined** your shift trade.\n\n"
                f"**Schedule:** {self.trade_view.schedule['start_date']} to {self.trade_view.schedule['end_date']}\n"
                f"**Your Shift:** {self.trade_view.your_shift}\n"
                f"**Their Shift:** {self.trade_view.wanted_shift}\n"
                f"**Reason for Decline:** {self.reason.value}\n"
                f"[View Schedule]({self.trade_view.schedule['schedule_link']})"
            ),
            color=0xe74c3c
        )
        try:
            await requester.send(embed=embed)
        except Exception:
            pass
        await interaction.response.send_message("You have declined the trade offer. The requester has been notified.", ephemeral=True)
        self.trade_view.stop()

class DirectorApprovalView(View):
    def __init__(self, requester_id, target_id, schedule, your_shift, wanted_shift):
        super().__init__(timeout=3600)
        self.requester_id = requester_id
        self.target_id = target_id
        self.schedule = schedule
        self.your_shift = your_shift
        self.wanted_shift = wanted_shift
        self.add_item(DirectorApproveButton())
        self.add_item(DirectorDeclineButton())

class DirectorApproveButton(Button):
    def __init__(self):
        super().__init__(label="✅ Approve Trade", style=discord.ButtonStyle.success, custom_id="director_approve")

    async def callback(self, interaction: Interaction):
        if interaction.user.id != DIRECTOR_ID:
            await interaction.response.send_message("Only the director can approve this trade.", ephemeral=True)
            return
        # Disable buttons after pressing
        for item in self.view.children:
            item.disabled = True
        try:
            if interaction.message:
                await interaction.message.edit(view=self.view)
        except Exception:
            pass
        bot = interaction.client
        view: DirectorApprovalView = self.view
        requester = await bot.fetch_user(view.requester_id)
        target = await bot.fetch_user(view.target_id)
        embed = Embed(
            title="✅ Trade Approved by Director",
            description=(
                f"Your shift trade has been **approved** by the director!\n\n"
                f"**Schedule:** {view.schedule['start_date']} to {view.schedule['end_date']}\n"
                f"**Requester Shift:** {view.your_shift}\n"
                f"**Requested Shift:** {view.wanted_shift}\n"
                f"[View Schedule]({view.schedule['schedule_link']})"
            ),
            color=0x2ecc71
        )
        try:
            await requester.send(embed=embed)
        except Exception:
            pass
        try:
            await target.send(embed=embed)
        except Exception:
            pass
        await interaction.response.send_message("Trade approved. Both students have been notified.", ephemeral=True)
        self.view.stop()

class DirectorDeclineButton(Button):
    def __init__(self):
        super().__init__(label="❌ Decline Trade", style=discord.ButtonStyle.danger, custom_id="director_decline")

    async def callback(self, interaction: Interaction):
        if interaction.user.id != DIRECTOR_ID:
            await interaction.response.send_message("Only the director can decline this trade.", ephemeral=True)
            return
        # Disable buttons after pressing
        for item in self.view.children:
            item.disabled = True
        try:
            if interaction.message:
                await interaction.message.edit(view=self.view)
        except Exception:
            pass
        # Prompt for reason via modal
        await interaction.response.send_modal(DirectorDeclineReasonModal(self.view))

class DirectorDeclineReasonModal(Modal, title="Reason for Declining Trade"):
    reason = TextInput(label="Reason for declining", style=discord.TextStyle.paragraph, required=True)
    def __init__(self, director_view):
        super().__init__()
        self.director_view = director_view

    async def on_submit(self, interaction: Interaction):
        bot = interaction.client
        requester = await bot.fetch_user(self.director_view.requester_id)
        target = await bot.fetch_user(self.director_view.target_id)
        embed = Embed(
            title="❌ Trade Declined by Director",
            description=(
                f"Your shift trade has been **declined** by the director.\n\n"
                f"**Schedule:** {self.director_view.schedule['start_date']} to {self.director_view.schedule['end_date']}\n"
                f"**Requester Shift:** {self.director_view.your_shift}\n"
                f"**Requested Shift:** {self.director_view.wanted_shift}\n"
                f"**Reason for Decline:** {self.reason.value}\n"
                f"[View Schedule]({self.director_view.schedule['schedule_link']})"
            ),
            color=0xe74c3c
        )
        try:
            await requester.send(embed=embed)
        except Exception:
            pass
        try:
            await target.send(embed=embed)
        except Exception:
            pass
        await interaction.response.send_message("Trade declined. Both students have been notified.", ephemeral=True)
        self.director_view.stop()

async def setup(bot):
    await bot.add_cog(OfferTradeCog(bot))

class OfferTradeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    # Register only offer/trade related commands
    # ...existing code...