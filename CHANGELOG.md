# Changelog

All notable changes to the LionByte systems are documented here.  
Each system has its own section — update only what you need.

---

## LionByteGG (Discord Bot)

### [1.0.1] - 2026-04-09
**Fixed**
- Removed unnecessary `sync_permissions=True` call in `_create_normal_vc` that was wiping custom owner permissions immediately after channel creation, causing an extra API call and stripping the owner's `manage_channels` permission.

---

## BoilerCraftGG (Discord Bot)

### [1.0.1] - 2026-04-09
**Fixed**
- Fixed critical bug: `cog_load()` ran channel cleanup before the Discord cache was ready, causing the bot to wipe valid temp VC entries from the database on every restart. Cleanup now runs in `on_ready` after the cache is fully populated.
- Fixed silent failure in `on_voice_state_update`: a stale database connection would crash the event handler with no error output, making the bot unable to create VCs until restarted. All voice events are now wrapped with error handling and traceback logging.
- Added `ensure_connection()` to the database with automatic reconnection — if the SQLite connection goes stale (e.g. after PC sleep/wake), it self-heals instead of silently breaking.
- Enabled SQLite WAL mode and busy timeout for better resilience and concurrent access.
- Added `on_ready`, `on_resumed`, `on_disconnect` lifecycle handlers to maintain DB health across gateway reconnections.
- Added periodic cleanup task (every 3 minutes) to catch orphaned/empty temp VCs missed during gateway disconnects.
- Added `move_to` failure cleanup: if the bot creates a VC but can't move the user into it, the ghost channel is now deleted and untracked.
- Empty channel detection now ignores bots (only human members count).

---

## LionShiftGG (Discord Bot)

*No changes yet.*

---

## LionBeatsGG (Music Bot)

*No changes yet.*

---

## Nova (Website / Dashboard)

*No changes yet.*
