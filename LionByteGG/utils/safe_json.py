import json
import os
import shutil
import tempfile
import threading
import time
import logging

logger = logging.getLogger(__name__)

# Shared lock for ALL JSON file operations across bot + web server threads.
# Since both run in the same process (via run_combined.py), a threading.RLock
# protects against concurrent read-modify-write races on shared files.
_json_lock = threading.RLock()

# Files that get a .bak backup before each write (student/player data).
_CRITICAL_PATTERNS = (
    'rosters.json', 'teams.json', 'watchlist.json',
    'ticket_log.json', 'player_reports.json',
)


def _is_critical(filepath):
    """Check if a file path matches a critical data pattern."""
    return any(p in filepath for p in _CRITICAL_PATTERNS)


def safe_json_load(filepath, default=None):
    """
    Thread-safe JSON read with error recovery.
    Returns `default` (or {}) if the file is missing or corrupt.
    """
    if default is None:
        default = {}
    with _json_lock:
        if not os.path.exists(filepath):
            return default
        try:
            with open(filepath, 'r', encoding='utf-8-sig') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError, OSError) as e:
            logger.warning(f"[SAFE JSON] Failed to load {filepath}: {e}")
            # Try .bak if the main file is corrupt
            bak = filepath + '.bak'
            if os.path.exists(bak):
                try:
                    with open(bak, 'r', encoding='utf-8-sig') as f:
                        data = json.load(f)
                    logger.warning(f"[SAFE JSON] Recovered {filepath} from backup")
                    # Restore the good backup over the corrupt file
                    try:
                        shutil.copy2(bak, filepath)
                    except OSError:
                        pass
                    return data
                except (json.JSONDecodeError, IOError, OSError):
                    pass
            return default


def safe_json_dump(data, filepath, **kwargs):
    """
    Thread-safe atomic JSON write with retry and optional backup.

    1. Acquires shared lock
    2. For critical files, copies current file to .bak BEFORE writing
    3. Writes to a temp file in the same directory
    4. os.replace() atomically swaps temp -> target
    5. Retries up to 5 times on Windows PermissionError
    """
    kwargs.setdefault("ensure_ascii", False)
    dirpath = os.path.dirname(os.path.abspath(filepath))
    os.makedirs(dirpath, exist_ok=True)

    with _json_lock:
        # Backup critical files before overwriting
        if _is_critical(filepath) and os.path.exists(filepath):
            try:
                shutil.copy2(filepath, filepath + '.bak')
            except OSError:
                pass  # Non-fatal: proceed with write even if backup fails

        fd, temp_path = tempfile.mkstemp(dir=dirpath, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, **kwargs)

            for attempt in range(5):
                try:
                    os.replace(temp_path, filepath)
                    return
                except PermissionError:
                    if attempt < 4:
                        time.sleep(0.1 * (attempt + 1))
                    else:
                        raise
        except BaseException:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise


def safe_queue_append(filepath, item):
    """
    Thread-safe append to a JSON list file (e.g., notification queues).
    The entire read-modify-write is done under the shared lock.
    """
    with _json_lock:
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r', encoding='utf-8-sig') as f:
                    queue = json.load(f)
            except (json.JSONDecodeError, IOError, OSError):
                queue = []
        else:
            queue = []
        queue.append(item)
        # Write without re-acquiring lock (we already hold it)
        kwargs = {"ensure_ascii": False, "indent": 2}
        dirpath = os.path.dirname(os.path.abspath(filepath))
        os.makedirs(dirpath, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(dir=dirpath, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(queue, f, **kwargs)
            for attempt in range(5):
                try:
                    os.replace(temp_path, filepath)
                    return
                except PermissionError:
                    if attempt < 4:
                        time.sleep(0.1 * (attempt + 1))
                    else:
                        raise
        except BaseException:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise
