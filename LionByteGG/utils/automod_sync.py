"""
Discord AutoMod rule sync utility for LionByteGG.

Keeps the three flagged-word tiers (bannable / kickable / warning) in sync
with dedicated Discord AutoMod keyword rules. Creates the rules automatically
the first time if they don't exist yet.
"""
import logging
import requests

DISCORD_API_BASE = "https://discord.com/api/v10"

# The names used to identify the three rules we own.
RULE_NAMES = {
    "bannable": "LionByte - Bannable Words",
    "kickable": "LionByte - Kickable Words",
    "warning":  "LionByte - Warning Words",
}

log = logging.getLogger(__name__)


def _headers(bot_token: str) -> dict:
    return {
        "Authorization": f"Bot {bot_token}",
        "Content-Type": "application/json",
    }


def _get_rules(bot_token: str, guild_id: int) -> list:
    url = f"{DISCORD_API_BASE}/guilds/{guild_id}/auto-moderation/rules"
    resp = requests.get(url, headers=_headers(bot_token), timeout=10)
    resp.raise_for_status()
    return resp.json()


def _create_rule(bot_token: str, guild_id: int, name: str, keywords: list) -> dict:
    url = f"{DISCORD_API_BASE}/guilds/{guild_id}/auto-moderation/rules"
    payload = {
        "name": name,
        "event_type": 1,        # MESSAGE_SEND
        "trigger_type": 1,      # KEYWORD
        "trigger_metadata": {
            "keyword_filter": keywords,
            "regex_patterns": [],
        },
        "actions": [{"type": 1}],  # BLOCK_MESSAGE
        "enabled": True,
    }
    resp = requests.post(url, json=payload, headers=_headers(bot_token), timeout=10)
    resp.raise_for_status()
    return resp.json()


def _update_rule(bot_token: str, guild_id: int, rule_id: str, keywords: list) -> dict:
    url = f"{DISCORD_API_BASE}/guilds/{guild_id}/auto-moderation/rules/{rule_id}"
    payload = {
        "trigger_metadata": {
            "keyword_filter": keywords,
            "regex_patterns": [],
        }
    }
    resp = requests.patch(url, json=payload, headers=_headers(bot_token), timeout=10)
    resp.raise_for_status()
    return resp.json()


def sync_automod(bot_token: str, guild_id: int, flagged_words: dict) -> dict:
    """
    Sync all three tiers to their respective Discord AutoMod keyword rules.
    Creates rules if they don't exist yet, updates them if they do.

    Args:
        bot_token:     The Discord bot token.
        guild_id:      The Discord guild (server) ID.
        flagged_words: Dict with keys "bannable", "kickable", "warning", each a list of strings.

    Returns:
        A dict mapping each tier to "created", "updated", or "error: <msg>".
    """
    if not bot_token:
        log.warning("[AutoMod Sync] No bot token configured – skipping Discord sync.")
        return {"error": "No bot token configured"}

    try:
        existing = _get_rules(bot_token, guild_id)
        existing_by_name = {r["name"]: r for r in existing}
    except Exception as exc:
        log.error(f"[AutoMod Sync] Failed to fetch existing rules: {exc}")
        return {"error": str(exc)}

    results = {}
    for tier, rule_name in RULE_NAMES.items():
        keywords = [w.lower() for w in flagged_words.get(tier, [])]
        try:
            if rule_name in existing_by_name:
                rule_id = existing_by_name[rule_name]["id"]
                _update_rule(bot_token, guild_id, rule_id, keywords)
                results[tier] = "updated"
            else:
                _create_rule(bot_token, guild_id, rule_name, keywords)
                results[tier] = "created"
            log.info(f"[AutoMod Sync] {tier}: {results[tier]} ({len(keywords)} words)")
        except Exception as exc:
            log.error(f"[AutoMod Sync] Failed to sync tier '{tier}': {exc}")
            results[tier] = f"error: {exc}"

    return results
