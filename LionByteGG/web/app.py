"""
LionByteGG Web Dashboard API
A comprehensive Flask API for managing the Discord bot through a web interface.
Features Discord OAuth2 authentication with role-based permissions.
"""

from flask import Flask, render_template, request, jsonify, redirect, url_for, session, send_from_directory, Response
from flask_cors import CORS
from functools import wraps
import os
import sys
import json
import uuid
from datetime import datetime, timezone, timedelta
import hashlib
import secrets
import requests
import tempfile
import threading
import csv
import io

# Add parent directory imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Add web directory for local imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.constants import (
    GUILD_ID, STUDENT_ROLE_ID, GUEST_ROLE_ID, SECURITY_CODE,
    USER_RECORDS_DIR, GUEST_TIMES_DIR, VARSITY_REG_DIR, SCHEDULE_IMAGES_DIR, LOG_CHANNEL_NAME
)
from utils.safe_json import safe_json_dump

# Import OAuth config
from oauth_config import (
    DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, DISCORD_REDIRECT_URI,
    DISCORD_BOT_TOKEN, DISCORD_API_BASE, DISCORD_AUTH_URL, DISCORD_TOKEN_URL,
    OAUTH_SCOPES, PermissionLevel, ROLE_PERMISSIONS, FEATURE_PERMISSIONS,
    get_user_permission_level, has_permission, get_user_features,
    get_permission_level_name, oauth_login_required, permission_required,
    api_permission_required
)

# Import auth database
import auth_db

app = Flask(__name__, static_folder='static', template_folder='templates')

# Enable gzip compression for all responses
try:
    from flask_compress import Compress
    Compress(app)
except ImportError:
    pass  # flask-compress not installed, skip compression

# Production Configuration — persist the secret key so sessions survive restarts
_secret_key_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', '.flask_secret_key')
def _get_or_create_secret_key():
    """Load secret key from env or a persisted file so sessions survive restarts."""
    env_key = os.environ.get('FLASK_SECRET_KEY')
    if env_key:
        return env_key
    os.makedirs(os.path.dirname(_secret_key_path), exist_ok=True)
    if os.path.exists(_secret_key_path):
        with open(_secret_key_path, 'r') as f:
            return f.read().strip()
    new_key = secrets.token_hex(32)
    with open(_secret_key_path, 'w') as f:
        f.write(new_key)
    return new_key

app.secret_key = _get_or_create_secret_key()
app.config.update(
    SESSION_COOKIE_SECURE=os.environ.get('FLASK_ENV') == 'production',  # HTTPS only in production
    SESSION_COOKIE_HTTPONLY=True,  # Prevent JavaScript access to session cookie
    SESSION_COOKIE_SAMESITE='Lax',  # CSRF protection
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),  # Session expires after 12 hours
    MAX_CONTENT_LENGTH=16 * 1024 * 1024,  # Max 16MB upload
)

# Enable CORS with proper configuration
CORS(app, supports_credentials=True)

# Initialize auth database (creates tables + master admin on first run)
auth_db.init_db()

@app.before_request
def make_session_permanent():
    """Ensure every request uses permanent sessions so PERMANENT_SESSION_LIFETIME applies."""
    session.permanent = True

# Logging configuration for production
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('LionByteGG')

# Cache static files for 1 hour (browsers won't re-request CSS/JS/images)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 3600

@app.context_processor
def inject_user_perms():
    """Make user_perms and has_perm available in all templates."""
    perms = get_user_perms() if (session.get('discord_user') or session.get('dashboard_user') or (session.get('authenticated') and session.get('legacy_login'))) else []
    resolved = set(auth_db.resolve_perm(p) for p in perms)
    return dict(user_perms=perms, has_perm=lambda p: auth_db.resolve_perm(p) in resolved)

# Configuration
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
FLAGGED_WORDS_PATH = os.path.join(DATA_DIR, "flagged_words.json")
BOT_STATUS_FILE = os.path.join(DATA_DIR, "bot_status.json")
MEMBERS_CACHE_FILE = os.path.join(DATA_DIR, "members_cache.json")
ROLES_CACHE_FILE = os.path.join(DATA_DIR, "roles_cache.json")
BOT_CONTROL_FILE = os.path.join(DATA_DIR, "bot_control.json")
BOT_PID_FILE = os.path.join(DATA_DIR, "bot.pid")
JOB_PROGRESS_FILE = os.path.join(DATA_DIR, "job_progress.json")
ACTIVITY_LOG_FILE = os.path.join(DATA_DIR, "activity_log.json")
MODERATION_TEMPLATES_FILE = os.path.join(DATA_DIR, "moderation_templates.json")
WATCHLIST_FILE = os.path.join(DATA_DIR, "watchlist.json")
VC_GENERATORS_FILE = os.path.join(DATA_DIR, "vc-generators.json")
VC_LIVE_CACHE_FILE = os.path.join(DATA_DIR, "vc_live_cache.json")

# Bot instance (will be set by main.py)
bot_instance = None
bot_process = None

def set_bot_instance(bot):
    global bot_instance
    bot_instance = bot

def set_bot_process(process):
    global bot_process
    bot_process = process

# ============ Authentication Decorators ============

def login_required(f):
    """Decorator to require authentication (OAuth, dashboard user, or legacy)"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check for Discord OAuth session
        if session.get('discord_user'):
            return f(*args, **kwargs)
        # Check for dashboard user (new auth system)
        if session.get('dashboard_user'):
            return f(*args, **kwargs)
        # Check for legacy authentication
        if session.get('authenticated') and session.get('legacy_login'):
            return f(*args, **kwargs)
        return redirect(url_for('login'))
    return decorated_function

def api_auth_required(f):
    """Decorator for API endpoints (supports OAuth, dashboard user, legacy session, and token)"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check for Discord OAuth session
        if session.get('discord_user'):
            return f(*args, **kwargs)
        # Check for dashboard user (new auth system)
        if session.get('dashboard_user'):
            return f(*args, **kwargs)
        # Check for legacy session
        if session.get('authenticated') and session.get('legacy_login'):
            return f(*args, **kwargs)
        # Check for API token
        auth_token = request.headers.get('Authorization')
        if auth_token == f"Bearer {SECURITY_CODE}":
            return f(*args, **kwargs)
        return jsonify({"error": "Unauthorized"}), 401
    return decorated_function

def admin_required(f):
    """Decorator to require admin privileges"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Dashboard user (new auth system)
        user = session.get('dashboard_user')
        if user and user.get('is_admin'):
            return f(*args, **kwargs)
        # Discord OAuth users with OWNER/DIRECTOR level get admin access
        discord_user = session.get('discord_user')
        if discord_user and discord_user.get('permission_level', 0) >= PermissionLevel.DIRECTOR:
            return f(*args, **kwargs)
        # Legacy login gets admin access (they had the security code)
        if session.get('authenticated') and session.get('legacy_login'):
            return f(*args, **kwargs)
        return jsonify({"error": "Admin access required"}), 403
    return decorated_function

def _is_full_access_user():
    """Check if the current user has full unrestricted access (Discord OAuth or legacy login)."""
    if session.get('discord_user'):
        return True
    if session.get('authenticated') and session.get('legacy_login'):
        return True
    return False

def page_permission_required(permission_key):
    """Decorator factory to require a specific page permission"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Discord OAuth users and legacy users get full access
            if _is_full_access_user():
                return f(*args, **kwargs)
            # Dashboard users need the specific permission (resolved via alias)
            resolved = auth_db.resolve_perm(permission_key)
            perms = session.get('dashboard_permissions', [])
            if resolved in set(auth_db.resolve_perm(p) for p in perms):
                return f(*args, **kwargs)
            return redirect(url_for('smart_landing'))
        return decorated_function
    return decorator

def has_perm(permission_key):
    """Check if current user has a specific permission. Discord/legacy users always have all perms."""
    if _is_full_access_user():
        return True
    resolved = auth_db.resolve_perm(permission_key)
    perms = session.get('dashboard_permissions', [])
    return resolved in set(auth_db.resolve_perm(p) for p in perms)

def get_user_perms():
    """Get the current user's permission list. Returns ALL_PERMISSIONS for Discord/legacy users."""
    if _is_full_access_user():
        return auth_db.ALL_PERMISSIONS
    return session.get('dashboard_permissions', [])

def api_perm_required(permission_key):
    """Decorator factory for API endpoints requiring a specific action permission"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Discord OAuth users and legacy users get full access
            if _is_full_access_user():
                return f(*args, **kwargs)
            # API token gets full access
            auth_token = request.headers.get('Authorization')
            if auth_token == f"Bearer {SECURITY_CODE}":
                return f(*args, **kwargs)
            # Dashboard users need the specific permission (resolved via alias)
            resolved = auth_db.resolve_perm(permission_key)
            perms = session.get('dashboard_permissions', [])
            if resolved in set(auth_db.resolve_perm(p) for p in perms):
                return f(*args, **kwargs)
            return jsonify({"error": "Permission denied"}), 403
        return decorated_function
    return decorator

# ============ Discord OAuth2 Helper Functions ============

def get_oauth_url(state=None):
    """Generate Discord OAuth2 authorization URL"""
    from urllib.parse import urlencode
    params = {
        'client_id': DISCORD_CLIENT_ID,
        'redirect_uri': DISCORD_REDIRECT_URI,
        'response_type': 'code',
        'scope': ' '.join(OAUTH_SCOPES),
    }
    if state:
        params['state'] = state
    return f"{DISCORD_AUTH_URL}?{urlencode(params)}"

def exchange_code(code):
    """Exchange authorization code for access token"""
    data = {
        'client_id': DISCORD_CLIENT_ID,
        'client_secret': DISCORD_CLIENT_SECRET,
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': DISCORD_REDIRECT_URI,
    }
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    
    try:
        response = requests.post(DISCORD_TOKEN_URL, data=data, headers=headers, timeout=DISCORD_API_TIMEOUT)
        if response.status_code != 200:
            print(f"[OAUTH] Token exchange failed: {response.status_code} - {response.text}")
            return None
        return response.json()
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
        logger.error(f"[OAUTH] Token exchange timed out or connection failed: {e}")
        return None

def get_discord_user(access_token):
    """Fetch user information from Discord API"""
    headers = {'Authorization': f'Bearer {access_token}'}
    try:
        response = requests.get(f"{DISCORD_API_BASE}/users/@me", headers=headers, timeout=DISCORD_API_TIMEOUT)
        if response.status_code != 200:
            print(f"[OAUTH] Failed to fetch user: {response.status_code}")
            return None
        return response.json()
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
        logger.error(f"[OAUTH] Failed to fetch Discord user: {e}")
        return None

def get_guild_member(user_id):
    """Fetch guild member data using bot token to get roles"""
    if not DISCORD_BOT_TOKEN or DISCORD_BOT_TOKEN == 'YOUR_BOT_TOKEN_HERE':
        # Try reading from bot's members cache instead
        if os.path.exists(MEMBERS_CACHE_FILE):
            try:
                with open(MEMBERS_CACHE_FILE, 'r', encoding='utf-8') as f:
                    members = json.load(f)
                for member in members:
                    if str(member.get('id')) == str(user_id):
                        return {
                            'roles': [r['id'] for r in member.get('roles', [])],
                            'nick': member.get('nick'),
                            'joined_at': member.get('joined_at')
                        }
            except (json.JSONDecodeError, IOError, OSError, KeyError) as e:
                logger.warning(f"[OAUTH] Failed to read members cache: {e}")
        return None
    
    headers = {'Authorization': f'Bot {DISCORD_BOT_TOKEN}'}
    try:
        response = requests.get(
            f"{DISCORD_API_BASE}/guilds/{GUILD_ID}/members/{user_id}",
            headers=headers,
            timeout=DISCORD_API_TIMEOUT
        )
        if response.status_code != 200:
            print(f"[OAUTH] Failed to fetch guild member: {response.status_code}")
            return None
        return response.json()
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
        logger.error(f"[OAUTH] Failed to fetch guild member {user_id}: {e}")
        return None

def get_guild_info():
    """Fetch guild info to check owner"""
    if not DISCORD_BOT_TOKEN or DISCORD_BOT_TOKEN == 'YOUR_BOT_TOKEN_HERE':
        return None
    
    headers = {'Authorization': f'Bot {DISCORD_BOT_TOKEN}'}
    try:
        response = requests.get(f"{DISCORD_API_BASE}/guilds/{GUILD_ID}", headers=headers, timeout=DISCORD_API_TIMEOUT)
        if response.status_code != 200:
            return None
        return response.json()
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
        logger.error(f"[OAUTH] Failed to fetch guild info: {e}")
        return None

# ============ Helper Functions ============

# Reentrant lock for JSON file operations to prevent race conditions
# RLock allows the same thread to re-acquire (needed for safe_queue_append which calls load/save)
_json_file_lock = threading.RLock()

# Discord API request timeout (seconds) - prevents hanging when Discord is slow/down
DISCORD_API_TIMEOUT = 10

def load_json_file(filepath, default=None):
    if default is None:
        default = {}
    if os.path.exists(filepath):
        try:
            with _json_file_lock:
                with open(filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except (json.JSONDecodeError, IOError, OSError) as e:
            logger.warning(f"Failed to load JSON file {filepath}: {e}")
            return default
    return default

def save_json_file(filepath, data):
    """Atomic JSON save - writes to temp file first, then renames to prevent corruption."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    try:
        dir_name = os.path.dirname(filepath)
        fd, tmp_path = tempfile.mkstemp(suffix='.tmp', dir=dir_name)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            # Retry os.replace - Windows fails with PermissionError if another process has the file open
            for attempt in range(5):
                try:
                    with _json_file_lock:
                        os.replace(tmp_path, filepath)
                    break
                except PermissionError:
                    if attempt < 4:
                        import time
                        time.sleep(0.1 * (attempt + 1))
                    else:
                        raise
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception as e:
        logger.error(f"Failed to save JSON file {filepath}: {e}")
        raise

def safe_queue_append(filepath, item):
    """Thread-safe append to a JSON list file (e.g., notification queues)."""
    with _json_file_lock:
        queue = load_json_file(filepath, [])
        queue.append(item)
        save_json_file(filepath, queue)

def load_flagged_words():
    return load_json_file(FLAGGED_WORDS_PATH, {"bannable": [], "kickable": [], "warning": []})

def save_flagged_words(words):
    save_json_file(FLAGGED_WORDS_PATH, words)

def delete_schedule_images(attachments):
    """Delete schedule image files from local storage.
    
    Args:
        attachments: List of filenames (local) to delete
    Returns:
        Number of files deleted
    """
    deleted = 0
    if not attachments or not isinstance(attachments, list):
        return deleted
    for filename in attachments:
        # Skip if it's a URL (old format) instead of a local filename
        if isinstance(filename, str) and not filename.startswith('http'):
            filepath = os.path.join(SCHEDULE_IMAGES_DIR, filename)
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
                    deleted += 1
            except Exception as e:
                print(f"Error deleting schedule image {filename}: {e}")
    return deleted

def transform_attachments_to_urls(data):
    """Transform attachment filenames to proper URLs for the frontend.
    
    Handles both old format (Discord CDN URLs) and new format (local filenames).
    Falls back to attachments_cdn if local files don't exist.
    
    Args:
        data: Dictionary containing 'attachments' and optionally 'attachments_cdn'
    Returns:
        List of valid image URLs
    """
    if not data:
        return []
    
    attachments = data.get('attachments', [])
    attachments_cdn = data.get('attachments_cdn', [])
    
    if not attachments:
        return []
    
    result = []
    for idx, attachment in enumerate(attachments):
        if not isinstance(attachment, str):
            continue
            
        # If it's already a URL (old format), use it directly
        if attachment.startswith('http'):
            result.append(attachment)
        else:
            # It's a local filename - check if file exists
            filepath = os.path.join(SCHEDULE_IMAGES_DIR, attachment)
            if os.path.exists(filepath):
                # File exists locally, use local URL
                result.append(f'/schedule-images/{attachment}')
            elif attachments_cdn and idx < len(attachments_cdn):
                # File doesn't exist locally, try CDN backup
                result.append(attachments_cdn[idx])
            else:
                # No backup available, still try local URL (will 404 if missing)
                result.append(f'/schedule-images/{attachment}')
    
    return result

def load_user_records():
    records = {}
    if os.path.exists(USER_RECORDS_DIR):
        for fname in os.listdir(USER_RECORDS_DIR):
            if fname.endswith("_record.json"):
                user_id = fname.split("_")[0]
                records[user_id] = load_json_file(os.path.join(USER_RECORDS_DIR, fname), [])
    return records

def get_members_lookup():
    """Build a dict of user_id -> member info for fast lookups."""
    members_data = load_json_file(MEMBERS_CACHE_FILE, [])
    if isinstance(members_data, dict):
        members_data = members_data.get('members', [])
    if not isinstance(members_data, list):
        members_data = []
    return {str(m.get('id', '')): m for m in members_data if isinstance(m, dict)}

def queue_discord_notification(notification_data):
    """Queue a notification for the Discord bot to process (thread-safe)"""
    queue_file = os.path.join(DATA_DIR, "discord_notification_queue.json")
    
    # Add notification with pending status and timestamp
    notification_data["status"] = "pending"
    notification_data["queued_at"] = datetime.now(timezone.utc).isoformat()
    
    # Thread-safe append
    safe_queue_append(queue_file, notification_data)

def log_activity(action, category, details, target_id=None, target_name=None, success=True, source="website"):
    """
    Log an activity to the unified activity log.
    
    Args:
        action: The action performed (e.g., 'kick', 'ban', 'warn', 'login', 'logout')
        category: Category of action ('moderation', 'auth', 'admin', 'settings')
        details: Description of what happened
        target_id: Discord ID of the target user (if applicable)
        target_name: Name of the target user (if applicable)
        success: Whether the action was successful
        source: Where the action originated ('website', 'bot', 'discord')
    """
    try:
        activity_log = load_json_file(ACTIVITY_LOG_FILE, [])
        
        # Get current user info from session
        moderator_info = {
            "type": "unknown",
            "name": "System",
            "id": None,
            "avatar": None
        }
        
        discord_user = session.get('discord_user')
        dashboard_user = session.get('dashboard_user')
        if discord_user:
            moderator_info = {
                "type": "discord",
                "name": discord_user.get('global_name') or discord_user.get('username'),
                "id": discord_user.get('id'),
                "avatar": discord_user.get('avatar_url')
            }
        elif dashboard_user:
            moderator_info = {
                "type": "dashboard",
                "name": dashboard_user.get('display_name') or dashboard_user.get('username'),
                "id": dashboard_user.get('id'),
                "avatar": None
            }
        elif session.get('legacy_login'):
            moderator_info = {
                "type": "legacy",
                "name": session.get('user_name', 'Admin'),
                "id": None,
                "avatar": None
            }
        elif source == "bot":
            # Bot-initiated actions
            moderator_info = {
                "type": "bot",
                "name": "LionByteGG Bot",
                "id": None,
                "avatar": None
            }
        
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user": moderator_info,
            "ip_address": request.remote_addr if request else None,
            "action": action,
            "category": category,
            "success": success,
            "details": details,
            "target_id": str(target_id) if target_id else None,
            "target_name": target_name,
            "source": source,
            "path": request.path if request else None,
            "method": request.method if request else None
        }
        
        # Add to beginning of log (newest first)
        activity_log.insert(0, log_entry)
        
        # Keep only last 1000 entries
        activity_log = activity_log[:1000]
        
        save_json_file(ACTIVITY_LOG_FILE, activity_log)
        
    except Exception as e:
        print(f"[ACTIVITY LOG] Error logging activity: {e}")

def get_moderator_name():
    """Get the current moderator's name from session"""
    discord_user = session.get('discord_user')
    if discord_user:
        return discord_user.get('global_name') or discord_user.get('username')
    dashboard_user = session.get('dashboard_user')
    if dashboard_user:
        return dashboard_user.get('display_name') or dashboard_user.get('username')
    elif session.get('legacy_login'):
        return session.get('user_name', 'Admin')
    return 'Dashboard Admin'

def get_moderator_id():
    """Get the current moderator's Discord ID from session"""
    discord_user = session.get('discord_user')
    if discord_user:
        return discord_user.get('id')
    return None

def load_guest_times():
    guests = {}
    if os.path.exists(GUEST_TIMES_DIR):
        for fname in os.listdir(GUEST_TIMES_DIR):
            if fname.endswith("_guest_time.json"):
                user_id = fname.split("_")[0]
                guests[user_id] = load_json_file(os.path.join(GUEST_TIMES_DIR, fname))
    return guests

def get_bot_stats():
    """Get current bot statistics from status file"""
    # Try to read from bot status file (written by the bot)
    if os.path.exists(BOT_STATUS_FILE):
        try:
            with open(BOT_STATUS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Check if status is recent (within last 2 minutes)
                last_update = data.get('last_update', '')
                if last_update:
                    update_time = datetime.fromisoformat(last_update.replace('Z', '+00:00'))
                    now = datetime.now(timezone.utc)
                    if (now - update_time).total_seconds() < 120:
                        return data
        except:
            pass
    
    # If bot instance is available (integrated mode)
    if bot_instance is not None:
        try:
            total_members = sum(g.member_count for g in bot_instance.guilds)
            return {
                "status": "online",
                "guilds": len(bot_instance.guilds),
                "members": total_members,
                "latency": round(bot_instance.latency * 1000),
                "last_update": datetime.now(timezone.utc).isoformat()
            }
        except:
            pass
    
    return {
        "status": "offline",
        "guilds": 0,
        "members": 0,
        "latency": 0,
        "message": "Bot status file not found. Run the bot to sync status."
    }

# ============ Routes - Pages ============

@app.route('/')
def index():
    # If already logged in, go to dashboard
    if session.get('discord_user') or (session.get('authenticated') and session.get('legacy_login')) or session.get('dashboard_user'):
        return redirect(url_for('smart_landing'))
    return redirect(url_for('login'))

@app.route('/schedule-images/<filename>')
@api_auth_required
def serve_schedule_image(filename):
    """Serve schedule images from the local storage"""
    # Ensure the directory exists
    if not os.path.exists(SCHEDULE_IMAGES_DIR):
        return jsonify({"error": "Image directory not found"}), 404
    # Security: only allow alphanumeric, underscore, dash, and dot in filename
    import re
    if not re.match(r'^[\w\-\.]+$', filename):
        return jsonify({"error": "Invalid filename"}), 400
    return send_from_directory(SCHEDULE_IMAGES_DIR, filename)

@app.route('/api/validate-login', methods=['POST'])
def validate_login():
    """Validate login credentials without creating a session - used for AJAX pre-validation"""
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '')
    
    # Validate inputs
    if not username or len(username) < 2:
        return jsonify({"valid": False, "error": "Invalid username"})
    if not password:
        return jsonify({"valid": False, "error": "Password required"})
    
    # Authenticate against database
    user = auth_db.authenticate_user(username, password)
    if user:
        return jsonify({"valid": True, "display_name": user.get('display_name', username)})
    else:
        return jsonify({"valid": False, "error": "Invalid username or password"})

@app.route('/login', methods=['GET', 'POST'])
def login():
    # If already logged in via OAuth, redirect to dashboard
    if session.get('discord_user'):
        return redirect(url_for('smart_landing'))
    
    error = request.args.get('error')
    error_messages = {
        'discord_auth_failed': 'Discord authorization failed. Please try again.',
        'token_exchange_failed': 'Failed to authenticate with Discord. Please try again.',
        'failed_to_fetch_user': 'Could not retrieve your Discord profile. Please try again.',
        'not_server_member': 'You must be a member of the PNW Esports Discord server to access the dashboard.',
        'no_dashboard_access': 'Your Discord roles do not grant dashboard access. Contact an admin if you believe this is an error.',
        'permission_denied': 'You do not have permission to access that feature.',
    }
    
    if request.method == 'POST':
        # Username/password login
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        user = auth_db.authenticate_user(username, password)
        if user:
            # Set session for new auth system
            session['dashboard_user'] = user
            session['dashboard_permissions'] = auth_db.get_user_permissions(user['id'])
            # Log the login activity
            log_activity(
                action="login",
                category="auth",
                details=f"Dashboard login successful",
                target_name=user['display_name'],
                success=True
            )
            return redirect(url_for('smart_landing'))
        # Log failed login attempt
        log_activity(
            action="login_failed",
            category="auth",
            details=f"Failed login attempt for '{username}'",
            target_name=username,
            success=False
        )
        return render_template('login.html', error="Invalid username or password", 
                             oauth_enabled=_is_oauth_configured())
    
    return render_template('login.html', 
                         error=error_messages.get(error),
                         oauth_enabled=_is_oauth_configured())

def _is_oauth_configured():
    """Check if Discord OAuth is properly configured"""
    return (DISCORD_CLIENT_ID and DISCORD_CLIENT_ID != 'YOUR_CLIENT_ID_HERE' and
            DISCORD_CLIENT_SECRET and DISCORD_CLIENT_SECRET != 'YOUR_CLIENT_SECRET_HERE')

@app.route('/auth/discord')
def discord_login():
    """Initiate Discord OAuth2 login flow"""
    if not _is_oauth_configured():
        return redirect(url_for('login', error='oauth_not_configured'))
    
    # Generate state for CSRF protection
    state = secrets.token_urlsafe(32)
    session['oauth_state'] = state
    
    return redirect(get_oauth_url(state))

@app.route('/auth/callback')
def discord_callback():
    """Handle Discord OAuth2 callback"""
    # Verify state for CSRF protection
    state = request.args.get('state')
    stored_state = session.pop('oauth_state', None)
    
    if state != stored_state:
        return redirect(url_for('login', error='invalid_state'))
    
    # Check for errors from Discord
    error = request.args.get('error')
    if error:
        error_desc = request.args.get('error_description', 'Unknown error')
        print(f"[OAUTH] Authorization error: {error} - {error_desc}")
        return redirect(url_for('login', error='discord_auth_failed'))
    
    # Get authorization code
    code = request.args.get('code')
    if not code:
        return redirect(url_for('login', error='discord_auth_failed'))
    
    # Exchange code for tokens
    token_data = exchange_code(code)
    if not token_data:
        return redirect(url_for('login', error='token_exchange_failed'))
    
    access_token = token_data.get('access_token')
    refresh_token = token_data.get('refresh_token')
    
    # Get user info
    user_info = get_discord_user(access_token)
    if not user_info:
        return redirect(url_for('login', error='failed_to_fetch_user'))
    
    user_id = user_info.get('id')
    
    # Get guild member info (for roles)
    member_info = get_guild_member(user_id)
    is_member = member_info is not None
    
    if not is_member:
        return redirect(url_for('login', error='not_server_member'))
    
    # Get guild info to check for owner
    guild_info = get_guild_info()
    is_owner = guild_info and str(guild_info.get('owner_id')) == str(user_id)
    
    # Build avatar URL
    avatar_hash = user_info.get('avatar')
    if avatar_hash:
        avatar_ext = 'gif' if avatar_hash.startswith('a_') else 'png'
        avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.{avatar_ext}?size=256"
    else:
        discriminator = int(user_info.get('discriminator', '0'))
        avatar_url = f"https://cdn.discordapp.com/embed/avatars/{discriminator % 5}.png"
    
    # Build user data
    user_data = {
        'id': user_id,
        'username': user_info.get('username'),
        'global_name': user_info.get('global_name'),
        'discriminator': user_info.get('discriminator'),
        'avatar': avatar_hash,
        'avatar_url': avatar_url,
        'roles': member_info.get('roles', []) if member_info else [],
        'nick': member_info.get('nick') if member_info else None,
        'joined_at': member_info.get('joined_at') if member_info else None,
        'is_member': is_member,
        'is_owner': is_owner,
    }
    
    # Calculate permission level
    permission_level = get_user_permission_level(user_data)
    user_data['permission_level'] = permission_level
    user_data['permission_name'] = get_permission_level_name(permission_level)
    user_data['features'] = get_user_features(user_data)
    
    # Check minimum access
    if permission_level < PermissionLevel.VIEWER:
        return redirect(url_for('login', error='no_dashboard_access'))
    
    # Store in session
    session['discord_user'] = user_data
    session['authenticated'] = True
    session['user_name'] = user_data.get('global_name') or user_data.get('username')
    
    # Log the Discord OAuth login
    log_activity(
        action="login",
        category="auth",
        details=f"Discord OAuth login - Permission: {user_data['permission_name']}",
        target_id=user_id,
        target_name=user_data.get('global_name') or user_data.get('username'),
        success=True
    )
    
    print(f"[OAUTH] User {user_data['username']} logged in - Permission: {user_data['permission_name']}")
    
    return redirect(url_for('smart_landing'))

@app.route('/logout')
def logout():
    user = session.get('discord_user')
    dashboard_user = session.get('dashboard_user')
    user_name = None
    user_id = None
    
    if user:
        user_name = user.get('global_name') or user.get('username')
        user_id = user.get('id')
        print(f"[OAUTH] User {user.get('username')} logged out")
    elif dashboard_user:
        user_name = dashboard_user.get('display_name') or dashboard_user.get('username')
        user_id = dashboard_user.get('id')
    elif session.get('legacy_login'):
        user_name = session.get('user_name', 'Admin')
    
    # Log the logout activity before clearing session
    if user_name:
        log_activity(
            action="logout",
            category="auth",
            details=f"User logged out",
            target_id=user_id,
            target_name=user_name,
            success=True
        )
    
    session.clear()
    return redirect(url_for('login'))

# ============ OAuth API Endpoints ============

@app.route('/api/auth/user')
def get_current_user():
    """API endpoint to get current logged-in user info"""
    user_data = session.get('discord_user')
    
    if not user_data:
        # Check for dashboard user (new auth)
        dashboard_user = session.get('dashboard_user')
        if dashboard_user:
            return jsonify({
                'authenticated': True,
                'dashboard_login': True,
                'user': {
                    'id': dashboard_user.get('id'),
                    'username': dashboard_user.get('username'),
                    'display_name': dashboard_user.get('display_name'),
                    'is_admin': dashboard_user.get('is_admin', False),
                    'permissions': session.get('dashboard_permissions', [])
                }
            })
        # Check for legacy login
        if session.get('authenticated') and session.get('legacy_login'):
            return jsonify({
                'authenticated': True,
                'legacy_login': True,
                'user': {
                    'username': session.get('user_name', 'Admin'),
                    'permission_level': PermissionLevel.OWNER,  # Legacy has full access
                    'permission_name': 'Owner (Legacy)',
                    'features': list(FEATURE_PERMISSIONS.keys())
                }
            })
        return jsonify({'authenticated': False}), 401
    
    # Return user data without sensitive tokens
    safe_user_data = {k: v for k, v in user_data.items() 
                      if k not in ['access_token', 'refresh_token']}
    
    return jsonify({
        'authenticated': True,
        'user': safe_user_data
    })

@app.route('/api/auth/permissions')
def get_user_permissions():
    """API endpoint to get current user's permissions"""
    user_data = session.get('discord_user')
    
    if not user_data:
        if session.get('authenticated') and session.get('legacy_login'):
            # Legacy login has full permissions
            return jsonify({
                'permission_level': PermissionLevel.OWNER,
                'permission_name': 'Owner (Legacy)',
                'features': list(FEATURE_PERMISSIONS.keys()),
                'is_owner': True,
                'is_member': True,
                'legacy_login': True
            })
        return jsonify({'authenticated': False}), 401
    
    return jsonify({
        'permission_level': user_data.get('permission_level', 0),
        'permission_name': user_data.get('permission_name', 'None'),
        'features': user_data.get('features', []),
        'is_owner': user_data.get('is_owner', False),
        'is_member': user_data.get('is_member', False),
    })

@app.route('/api/auth/check-feature/<feature>')
def check_feature_permission(feature):
    """API endpoint to check if user has permission for a feature"""
    user_data = session.get('discord_user')
    
    if not user_data:
        if session.get('authenticated') and session.get('legacy_login'):
            return jsonify({'has_permission': True, 'feature': feature, 'legacy_login': True})
        return jsonify({'has_permission': False, 'authenticated': False}), 401
    
    return jsonify({
        'has_permission': has_permission(user_data, feature),
        'feature': feature
    })

# ============ Admin Panel Routes ============

@app.route('/admin')
@login_required
def admin_panel():
    # Check admin access for page route (redirect instead of JSON 403)
    user = session.get('dashboard_user')
    discord_user = session.get('discord_user')
    is_admin = (
        (user and user.get('is_admin')) or
        (discord_user and discord_user.get('permission_level', 0) >= PermissionLevel.DIRECTOR) or
        (session.get('authenticated') and session.get('legacy_login'))
    )
    if not is_admin:
        return redirect(url_for('smart_landing'))
    return render_template('admin.html')

@app.route('/api/admin/users', methods=['GET'])
@login_required
@admin_required
def api_admin_get_users():
    """Get all users"""
    users = auth_db.get_all_users()
    return jsonify(users)

@app.route('/api/admin/users', methods=['POST'])
@login_required
@admin_required
@api_perm_required('admin.manage_users')
def api_admin_create_user():
    """Create a new user"""
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '')
    display_name = data.get('display_name', '').strip()
    group_id = data.get('group_id')
    is_admin = data.get('is_admin', False)
    
    if not username or not password or not display_name:
        return jsonify({"error": "Username, password, and display name are required"}), 400
    if len(username) < 3:
        return jsonify({"error": "Username must be at least 3 characters"}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400
    
    try:
        user = auth_db.create_user(username, password, display_name, group_id, is_admin)
        log_activity(
            action="create_user",
            category="admin",
            details=f"Created user '{username}' (admin={is_admin})",
            target_name=display_name,
            success=True
        )
        return jsonify(user), 201
    except Exception as e:
        if "UNIQUE constraint" in str(e):
            return jsonify({"error": "Username already exists"}), 409
        return jsonify({"error": str(e)}), 500

@app.route('/api/admin/users/<int:user_id>', methods=['PUT'])
@login_required
@admin_required
@api_perm_required('admin.manage_users')
def api_admin_update_user(user_id):
    """Update a user"""
    data = request.get_json()
    display_name = data.get('display_name')
    group_id = data.get('group_id')
    is_admin = data.get('is_admin')
    is_active = data.get('is_active')
    
    user = auth_db.update_user(user_id, display_name=display_name, group_id=group_id, is_admin=is_admin, is_active=is_active)
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    log_activity(
        action="update_user",
        category="admin",
        details=f"Updated user '{user['username']}'",
        target_name=user['display_name'],
        success=True
    )
    
    # If we just updated ourselves, refresh session permissions
    current_user = session.get('dashboard_user')
    if current_user and current_user['id'] == user_id:
        session['dashboard_user'] = user
        session['dashboard_permissions'] = auth_db.get_user_permissions(user_id)
    
    return jsonify(user)

@app.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
@login_required
@admin_required
@api_perm_required('admin.manage_users')
def api_admin_delete_user(user_id):
    """Delete a user"""
    # Prevent self-deletion
    current_user = session.get('dashboard_user')
    if current_user and current_user['id'] == user_id:
        return jsonify({"error": "Cannot delete your own account"}), 400
    
    target = auth_db.get_user_by_id(user_id)
    if not target:
        return jsonify({"error": "User not found"}), 404
    
    result = auth_db.delete_user(user_id)
    if not result:
        return jsonify({"error": "Cannot delete the last admin account"}), 400
    
    log_activity(
        action="delete_user",
        category="admin",
        details=f"Deleted user '{target['username']}'",
        target_name=target['display_name'],
        success=True
    )
    return jsonify({"success": True})

@app.route('/api/admin/users/<int:user_id>/password', methods=['PUT'])
@login_required
@admin_required
@api_perm_required('admin.reset_passwords')
def api_admin_reset_password(user_id):
    """Reset or change a user's password"""
    data = request.get_json()
    new_password = data.get('password', '')
    
    if len(new_password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400
    
    target = auth_db.get_user_by_id(user_id)
    if not target:
        return jsonify({"error": "User not found"}), 404
    
    auth_db.change_password(user_id, new_password)
    
    log_activity(
        action="reset_password",
        category="admin",
        details=f"Password reset for user '{target['username']}'",
        target_name=target['display_name'],
        success=True
    )
    return jsonify({"success": True})

# ============ Self-Service Account Endpoints ============

@app.route('/api/account/change-password', methods=['POST'])
@login_required
def api_account_change_password():
    """Allow dashboard users to change their own password."""
    dashboard_user = session.get('dashboard_user')
    if not dashboard_user:
        return jsonify({"error": "Only dashboard users can change passwords here"}), 403

    data = request.get_json()
    current_password = data.get('current_password', '')
    new_password = data.get('new_password', '')

    if not current_password or not new_password:
        return jsonify({"error": "Both current and new password are required"}), 400

    if len(new_password) < 6:
        return jsonify({"error": "New password must be at least 6 characters"}), 400

    # Verify current password
    user = auth_db.authenticate_user(dashboard_user['username'], current_password)
    if not user:
        return jsonify({"error": "Current password is incorrect"}), 403

    auth_db.change_password(dashboard_user['id'], new_password)

    log_activity(
        action="change_password",
        category="auth",
        details=f"User '{dashboard_user['username']}' changed their own password",
        target_name=dashboard_user.get('display_name', dashboard_user['username']),
        success=True
    )
    return jsonify({"success": True})

@app.route('/api/admin/groups', methods=['GET'])
@login_required
@admin_required
def api_admin_get_groups():
    """Get all groups"""
    groups = auth_db.get_all_groups()
    return jsonify(groups)

@app.route('/api/admin/groups', methods=['POST'])
@login_required
@admin_required
@api_perm_required('admin.manage_groups')
def api_admin_create_group():
    """Create a new group"""
    data = request.get_json()
    name = data.get('name', '').strip()
    description = data.get('description', '').strip()
    permissions = data.get('permissions', [])
    
    if not name:
        return jsonify({"error": "Group name is required"}), 400
    
    try:
        group = auth_db.create_group(name, description, permissions)
        log_activity(
            action="create_group",
            category="admin",
            details=f"Created group '{name}' with {len(permissions)} permissions",
            target_name=name,
            success=True
        )
        return jsonify(group), 201
    except Exception as e:
        if "UNIQUE constraint" in str(e):
            return jsonify({"error": "Group name already exists"}), 409
        return jsonify({"error": str(e)}), 500

@app.route('/api/admin/groups/<int:group_id>', methods=['PUT'])
@login_required
@admin_required
@api_perm_required('admin.manage_groups')
def api_admin_update_group(group_id):
    """Update a group"""
    data = request.get_json()
    name = data.get('name')
    description = data.get('description')
    permissions = data.get('permissions')
    
    group = auth_db.update_group(group_id, name=name, description=description, permissions=permissions)
    if not group:
        return jsonify({"error": "Group not found"}), 404
    
    log_activity(
        action="update_group",
        category="admin",
        details=f"Updated group '{group['name']}'",
        target_name=group['name'],
        success=True
    )
    return jsonify(group)

@app.route('/api/admin/groups/<int:group_id>', methods=['DELETE'])
@login_required
@admin_required
@api_perm_required('admin.manage_groups')
def api_admin_delete_group(group_id):
    """Delete a group"""
    group = auth_db.get_group_by_id(group_id)
    if not group:
        return jsonify({"error": "Group not found"}), 404
    
    auth_db.delete_group(group_id)
    
    log_activity(
        action="delete_group",
        category="admin",
        details=f"Deleted group '{group['name']}'",
        target_name=group['name'],
        success=True
    )
    return jsonify({"success": True})

@app.route('/api/admin/permissions', methods=['GET'])
@login_required
@admin_required
def api_admin_get_permissions():
    """Get list of all available permission keys"""
    return jsonify(auth_db.ALL_PERMISSIONS)

@app.route('/home')
@login_required
def smart_landing():
    """Redirect to the first section the user has access to."""
    # Full-access users go to main dashboard
    if _is_full_access_user():
        return redirect(url_for('dashboard'))
    perms = set(auth_db.resolve_perm(p) for p in session.get('dashboard_permissions', []))
    # Check sections in priority order
    if 'section.lionbyte' in perms and 'page.dashboard' in perms:
        return redirect(url_for('dashboard'))
    if 'section.boilercraft' in perms and 'page.boilercraft' in perms:
        return redirect('/boilercraft/dashboard')
    if 'section.onduty' in perms and 'page.onduty_dashboard' in perms:
        return redirect('/onduty/dashboard')
    if 'section.lionshift' in perms and 'page.shift_dashboard' in perms:
        return redirect('/lionshift/dashboard')
    if 'section.lionbeats' in perms and 'page.music_dashboard' in perms:
        return redirect('/music/dashboard')
    if 'admin.panel' in perms:
        return redirect('/admin')
    # No sections accessible — show an error
    return redirect(url_for('login', error='no_dashboard_access'))

@app.route('/dashboard')
@login_required
@page_permission_required('page.dashboard')
def dashboard():
    return render_template('dashboard.html')

@app.route('/moderation')
@login_required
@page_permission_required('page.moderation')
def moderation():
    return render_template('moderation.html')

@app.route('/users')
@login_required
@page_permission_required('page.users')
def users():
    return render_template('users.html')

@app.route('/tickets')
@login_required
@page_permission_required('page.tickets')
def tickets():
    return render_template('tickets.html')

# ============ WORKER ON DUTY ROUTES ============

@app.route('/onduty/dashboard')
@login_required
@page_permission_required('page.onduty_dashboard')
def onduty_dashboard():
    return render_template('onduty.html', active_tab='dashboard')

@app.route('/onduty/equipment')
@login_required
@page_permission_required('page.onduty_equipment')
def onduty_equipment():
    return render_template('onduty.html', active_tab='equipment')

# ============ LIONBEATSGG MUSIC BOT ROUTES ============

MUSIC_BOT_API_URL = os.environ.get('MUSIC_BOT_API_URL', 'http://127.0.0.1:3847')

@app.route('/music/dashboard')
@login_required
@page_permission_required('page.music_dashboard')
def music_dashboard():
    return render_template('music_dashboard.html')

@app.route('/music/nowplaying')
@login_required
@page_permission_required('page.music_dashboard')
def music_nowplaying():
    return render_template('music_dashboard.html')

@app.route('/music/settings')
@login_required
@page_permission_required('page.music_dashboard')
def music_settings():
    return render_template('music_dashboard.html')

@app.route('/music/features')
@login_required
@page_permission_required('page.music_features')
def music_features():
    """Music bot features page with quiz, stats, history, panels, controls, settings, commands"""
    return render_template('music_features.html')

@app.route('/api/music/status')
@api_auth_required
def api_music_status():
    """Proxy endpoint to fetch music bot status"""
    try:
        response = requests.get(f"{MUSIC_BOT_API_URL}/api/status", timeout=5)
        data = response.json()
        
        # Enhance with additional stats
        data['tracksToday'] = data.get('tracksToday', 0)
        data['totalListeners'] = sum(p.get('listenerCount', 1) for p in data.get('players', []))
        
        return jsonify(data)
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Music bot is not running", "status": "offline"}), 200
    except requests.exceptions.Timeout:
        return jsonify({"error": "Music bot did not respond in time", "status": "offline"}), 200
    except Exception as e:
        return jsonify({"error": str(e), "status": "offline"}), 200

@app.route('/api/music/top-tracks')
@api_auth_required
def api_music_top_tracks():
    """Get top played tracks"""
    try:
        response = requests.get(f"{MUSIC_BOT_API_URL}/api/stats", timeout=5)
        data = response.json()
        
        # Get top tracks from stats
        top_tracks = data.get('topTracks', [])
        if not top_tracks:
            # Try to build from history
            history_response = requests.get(f"{MUSIC_BOT_API_URL}/api/history?limit=500", timeout=5)
            history = history_response.json().get('history', [])
            
            # Count track plays
            track_counts = {}
            for item in history:
                title = item.get('title', 'Unknown')
                if title not in track_counts:
                    track_counts[title] = {'title': title, 'artist': item.get('author', 'Unknown'), 'plays': 0}
                track_counts[title]['plays'] += 1
            
            top_tracks = sorted(track_counts.values(), key=lambda x: x['plays'], reverse=True)[:10]
        
        return jsonify({'tracks': top_tracks})
    except Exception as e:
        return jsonify({'tracks': [], 'error': str(e)})

@app.route('/api/music/recent-activity')
@api_auth_required
def api_music_recent_activity():
    """Get recent music activity"""
    try:
        response = requests.get(f"{MUSIC_BOT_API_URL}/api/history?limit=20", timeout=5)
        history = response.json().get('history', [])
        
        activities = []
        for item in history[:10]:
            activities.append({
                'type': 'play',
                'user': item.get('requester', {}).get('username', 'Unknown'),
                'action': f"played {item.get('title', 'a track')}",
                'time': format_relative_time(item.get('playedAt', ''))
            })
        
        return jsonify({'activities': activities})
    except Exception as e:
        return jsonify({'activities': [], 'error': str(e)})

@app.route('/api/music/command/<command>', methods=['POST'])
@api_auth_required
@api_perm_required('music.player_controls')
def api_music_command(command):
    """Send a command to the music bot - finds first active player"""
    try:
        valid_commands = ['pause', 'resume', 'skip', 'stop']
        if command not in valid_commands:
            return jsonify({'success': False, 'error': 'Invalid command'})
        
        # First get the status to find an active player
        status_response = requests.get(f"{MUSIC_BOT_API_URL}/api/status", timeout=5)
        status = status_response.json()
        
        players = status.get('players', [])
        if not players:
            return jsonify({'success': False, 'error': 'No active music players'})
        
        # Get the first active player's guild ID
        guild_id = players[0].get('guildId')
        if not guild_id:
            return jsonify({'success': False, 'error': 'Could not find active player'})
        
        # Send command to that player
        response = requests.post(f"{MUSIC_BOT_API_URL}/api/player/{guild_id}/{command}", timeout=5)
        return jsonify(response.json())
    except requests.exceptions.ConnectionError:
        return jsonify({'success': False, 'error': 'Music bot is not running'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

def format_relative_time(timestamp_str):
    """Format a timestamp as relative time (e.g., '5m ago')"""
    try:
        if not timestamp_str:
            return 'Just now'
        
        timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        diff = now - timestamp
        
        seconds = diff.total_seconds()
        if seconds < 60:
            return 'Just now'
        elif seconds < 3600:
            return f'{int(seconds // 60)}m ago'
        elif seconds < 86400:
            return f'{int(seconds // 3600)}h ago'
        else:
            return f'{int(seconds // 86400)}d ago'
    except:
        return 'Recently'

@app.route('/api/music/history')
@api_auth_required
def api_music_history():
    """Proxy endpoint to fetch play history"""
    try:
        limit = request.args.get('limit', 100)
        response = requests.get(f"{MUSIC_BOT_API_URL}/api/history?limit={limit}", timeout=5)
        return jsonify(response.json())
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Music bot is not running", "history": []}), 200
    except Exception as e:
        return jsonify({"error": str(e), "history": []}), 200

@app.route('/api/music/history/clear', methods=['POST'])
@api_auth_required
@api_perm_required('music.history')
def api_music_history_clear():
    """Proxy endpoint to clear play history"""
    try:
        response = requests.post(f"{MUSIC_BOT_API_URL}/api/history/clear", timeout=5)
        return jsonify(response.json())
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Music bot is not running", "success": False}), 200
    except Exception as e:
        return jsonify({"error": str(e), "success": False}), 200

@app.route('/api/music/stats')
@api_auth_required
def api_music_stats():
    """Proxy endpoint to fetch music statistics"""
    try:
        response = requests.get(f"{MUSIC_BOT_API_URL}/api/stats", timeout=5)
        return jsonify(response.json())
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Music bot is not running", "totalPlays": 0}), 200
    except Exception as e:
        return jsonify({"error": str(e), "totalPlays": 0}), 200

@app.route('/api/music/stats/clear', methods=['POST'])
@api_auth_required
@api_perm_required('music.stats')
def api_music_stats_clear():
    """Proxy endpoint to clear statistics"""
    try:
        response = requests.post(f"{MUSIC_BOT_API_URL}/api/stats/clear", timeout=5)
        return jsonify(response.json())
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Music bot is not running", "success": False}), 200
    except Exception as e:
        return jsonify({"error": str(e), "success": False}), 200

@app.route('/api/music/quiz/songs', methods=['GET', 'POST', 'DELETE'])
@api_auth_required
def api_music_quiz_songs():
    """Proxy endpoint for quiz songs management"""
    try:
        if request.method == 'GET':
            response = requests.get(f"{MUSIC_BOT_API_URL}/api/quiz/songs", timeout=5)
        elif request.method == 'POST':
            if not has_perm('music.quiz_manager'):
                return jsonify({"error": "Permission denied"}), 403
            response = requests.post(f"{MUSIC_BOT_API_URL}/api/quiz/songs", 
                                    json=request.json, timeout=5)
        elif request.method == 'DELETE':
            if not has_perm('music.quiz_manager'):
                return jsonify({"error": "Permission denied"}), 403
            response = requests.delete(f"{MUSIC_BOT_API_URL}/api/quiz/songs", 
                                      json=request.json, timeout=5)
        return jsonify(response.json())
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Music bot is not running", "genres": [], "allSongs": {}}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 200

@app.route('/api/music/panels')
@api_auth_required
def api_music_panels():
    """Proxy endpoint to fetch music panels"""
    try:
        response = requests.get(f"{MUSIC_BOT_API_URL}/api/panels", timeout=5)
        return jsonify(response.json())
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Music bot is not running", "panels": []}), 200
    except Exception as e:
        return jsonify({"error": str(e), "panels": []}), 200

@app.route('/api/music/panels/<guild_id>', methods=['DELETE'])
@api_auth_required
@api_perm_required('music.panels')
def api_music_panel_delete(guild_id):
    """Proxy endpoint to delete a music panel"""
    try:
        response = requests.delete(f"{MUSIC_BOT_API_URL}/api/panels/{guild_id}", timeout=5)
        return jsonify(response.json())
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Music bot is not running", "success": False}), 200
    except Exception as e:
        return jsonify({"error": str(e), "success": False}), 200

@app.route('/api/music/settings', methods=['GET', 'PUT'])
@api_auth_required
def api_music_settings():
    """Proxy endpoint for bot settings"""
    try:
        if request.method == 'GET':
            response = requests.get(f"{MUSIC_BOT_API_URL}/api/settings", timeout=5)
        elif request.method == 'PUT':
            if not has_perm('music.settings'):
                return jsonify({"error": "Permission denied"}), 403
            response = requests.put(f"{MUSIC_BOT_API_URL}/api/settings", 
                                   json=request.json, timeout=5)
        return jsonify(response.json())
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Music bot is not running"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 200

@app.route('/api/music/player/<guild_id>/<action>', methods=['POST'])
@api_auth_required
@api_perm_required('music.player_controls')
def api_music_player_action(guild_id, action):
    """Proxy endpoint for player control actions"""
    try:
        data = request.json if request.json else {}
        response = requests.post(f"{MUSIC_BOT_API_URL}/api/player/{guild_id}/{action}", 
                                json=data, timeout=5)
        return jsonify(response.json())
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Music bot is not running", "success": False}), 200
    except Exception as e:
        return jsonify({"error": str(e), "success": False}), 200

@app.route('/api/music/commands')
@api_auth_required
def api_music_commands():
    """Proxy endpoint to fetch commands list"""
    try:
        response = requests.get(f"{MUSIC_BOT_API_URL}/api/commands", timeout=5)
        return jsonify(response.json())
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Music bot is not running", "slashCommands": [], "prefixCommands": [], "buttonControls": []}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 200

# ============ TICKET API ENDPOINTS ============

TICKET_LOG_FILE = os.path.join(DATA_DIR, "ticket_log.json")

def load_ticket_log():
    """Load ticket log data"""
    return load_json_file(TICKET_LOG_FILE, {"open": [], "closed": [], "blacklist": []})

def save_ticket_log(data):
    """Save ticket log data"""
    save_json_file(TICKET_LOG_FILE, data)

@app.route('/api/tickets')
@api_auth_required
def api_tickets():
    """Get all ticket data"""
    ticket_data = load_ticket_log()
    
    # Calculate stats
    stats = {
        "total_open": len(ticket_data.get("open", [])),
        "total_closed": len(ticket_data.get("closed", [])),
        "total_created": len(ticket_data.get("open", [])) + len(ticket_data.get("closed", [])),
        "blacklisted_users": len(ticket_data.get("blacklist", []))
    }
    
    return jsonify({
        "open": ticket_data.get("open", []),
        "closed": ticket_data.get("closed", []),
        "blacklist": ticket_data.get("blacklist", []),
        "stats": stats
    })

@app.route('/api/tickets/<ticket_id>')
@api_auth_required
def api_ticket_detail(ticket_id):
    """Get details for a specific ticket"""
    ticket_data = load_ticket_log()
    
    # Search in open tickets (compare as strings to handle both int and string IDs)
    for ticket in ticket_data.get("open", []):
        if str(ticket.get("id")) == str(ticket_id) or ticket.get("channel_name") == ticket_id:
            return jsonify(ticket)
    
    # Search in closed tickets
    for ticket in ticket_data.get("closed", []):
        if str(ticket.get("id")) == str(ticket_id) or ticket.get("channel_name") == ticket_id:
            return jsonify(ticket)
    
    return jsonify({"error": "Ticket not found"}), 404

@app.route('/api/tickets/transcripts/<ticket_id>')
@api_auth_required
def api_ticket_transcript(ticket_id):
    """Get transcript for a specific ticket"""
    ticket_data = load_ticket_log()
    
    # Search in closed tickets (transcripts are usually for closed tickets)
    for ticket in ticket_data.get("closed", []):
        if str(ticket.get("id")) == str(ticket_id) or ticket.get("channel_name") == ticket_id:
            # Return flattened structure that frontend expects
            return jsonify({
                "id": ticket.get("id"),
                "channel_name": ticket.get("channel_name"),
                "user": ticket.get("user"),
                "user_id": ticket.get("user_id"),
                "type": ticket.get("type"),
                "first_name": ticket.get("first_name"),
                "email": ticket.get("email"),
                "explanation": ticket.get("explanation"),
                "status": ticket.get("status"),
                "staff_assisting": ticket.get("staff_assisting"),
                "created_at": ticket.get("created_at"),
                "closed_at": ticket.get("closed_at"),
                "closed_by": ticket.get("closed_by"),
                "close_reason": ticket.get("close_reason"),
                "messages": ticket.get("messages", []),
                "transcript": ticket.get("transcript", [])
            })
    
    # Also check open tickets
    for ticket in ticket_data.get("open", []):
        if str(ticket.get("id")) == str(ticket_id) or ticket.get("channel_name") == ticket_id:
            return jsonify({
                "id": ticket.get("id"),
                "channel_name": ticket.get("channel_name"),
                "user": ticket.get("user"),
                "user_id": ticket.get("user_id"),
                "type": ticket.get("type"),
                "first_name": ticket.get("first_name"),
                "email": ticket.get("email"),
                "explanation": ticket.get("explanation"),
                "status": ticket.get("status"),
                "staff_assisting": ticket.get("staff_assisting"),
                "created_at": ticket.get("created_at"),
                "messages": ticket.get("messages", []),
                "transcript": ticket.get("transcript", [])
            })
    
    return jsonify({"error": "Transcript not found"}), 404

@app.route('/api/tickets/<ticket_id>/close', methods=['POST'])
@api_auth_required
@api_perm_required('tickets.close')
def api_close_ticket(ticket_id):
    """Close a ticket from dashboard"""
    data = request.json or {}
    reason = data.get("reason", "Closed from dashboard")
    closed_by = session.get('user_name', 'Dashboard Admin')
    
    ticket_data = load_ticket_log()
    
    # Find and move ticket from open to closed (compare as strings)
    open_tickets = ticket_data.get("open", [])
    for i, ticket in enumerate(open_tickets):
        if str(ticket.get("id")) == str(ticket_id) or ticket.get("channel_name") == ticket_id:
            # Move to closed
            ticket["status"] = "closed"
            ticket["closed_at"] = datetime.now(timezone.utc).isoformat()
            ticket["closed_by"] = closed_by
            ticket["close_reason"] = reason
            
            closed_tickets = ticket_data.get("closed", [])
            closed_tickets.insert(0, ticket)
            ticket_data["closed"] = closed_tickets
            
            # Remove from open
            open_tickets.pop(i)
            ticket_data["open"] = open_tickets
            
            save_ticket_log(ticket_data)
            
            # Queue Discord notification to close the channel
            queue_discord_notification({
                "type": "close_ticket",
                "channel_name": ticket.get("channel_name"),
                "reason": reason,
                "closed_by": closed_by
            })
            
            return jsonify({"success": True, "message": "Ticket closed"})
    
    return jsonify({"error": "Ticket not found"}), 404

@app.route('/api/tickets/blacklist/add', methods=['POST'])
@api_auth_required
@api_perm_required('tickets.blacklist')
def api_add_to_blacklist():
    """Add a user to the ticket blacklist"""
    data = request.json
    user_id = data.get("user_id")
    reason = data.get("reason", "Added from dashboard")
    
    if not user_id:
        return jsonify({"error": "User ID required"}), 400
    
    ticket_data = load_ticket_log()
    blacklist = ticket_data.get("blacklist", [])
    
    # Check if already blacklisted
    for entry in blacklist:
        if str(entry.get("user_id")) == str(user_id):
            return jsonify({"error": "User already blacklisted"}), 400
    
    # Add to blacklist
    blacklist.append({
        "user_id": str(user_id),
        "reason": reason,
        "added_at": datetime.now(timezone.utc).isoformat(),
        "added_by": session.get('user_name', 'Dashboard Admin')
    })
    
    ticket_data["blacklist"] = blacklist
    save_ticket_log(ticket_data)
    
    # Queue Discord notification
    queue_discord_notification({
        "type": "ticket_blacklist_add",
        "user_id": str(user_id)
    })
    
    return jsonify({"success": True, "message": "User added to blacklist"})

@app.route('/api/tickets/blacklist/remove', methods=['POST'])
@api_auth_required
@api_perm_required('tickets.blacklist')
def api_remove_from_blacklist():
    """Remove a user from the ticket blacklist"""
    data = request.json
    user_id = data.get("user_id")
    
    if not user_id:
        return jsonify({"error": "User ID required"}), 400
    
    ticket_data = load_ticket_log()
    blacklist = ticket_data.get("blacklist", [])
    
    # Find and remove user
    for i, entry in enumerate(blacklist):
        if str(entry.get("user_id")) == str(user_id):
            blacklist.pop(i)
            ticket_data["blacklist"] = blacklist
            save_ticket_log(ticket_data)
            
            # Queue Discord notification
            queue_discord_notification({
                "type": "ticket_blacklist_remove",
                "user_id": str(user_id)
            })
            
            return jsonify({"success": True, "message": "User removed from blacklist"})
    
    return jsonify({"error": "User not found in blacklist"}), 404

@app.route('/api/tickets/closed/<ticket_id>/delete', methods=['DELETE'])
@api_auth_required
@api_perm_required('tickets.delete_closed')
def api_delete_closed_ticket(ticket_id):
    """Delete a closed ticket from the log"""
    ticket_data = load_ticket_log()
    closed = ticket_data.get("closed", [])
    
    # Find and remove the ticket
    for i, ticket in enumerate(closed):
        if str(ticket.get("id")) == str(ticket_id):
            deleted_ticket = closed.pop(i)
            ticket_data["closed"] = closed
            save_ticket_log(ticket_data)
            return jsonify({
                "success": True, 
                "message": f"Ticket #{ticket_id} deleted",
                "deleted": deleted_ticket
            })
    
    return jsonify({"error": "Ticket not found in closed tickets"}), 404

@app.route('/api/tickets/closed/delete-all', methods=['DELETE'])
@api_auth_required
@api_perm_required('tickets.delete_closed')
def api_delete_all_closed_tickets():
    """Delete all closed tickets from the log"""
    ticket_data = load_ticket_log()
    deleted_count = len(ticket_data.get("closed", []))
    ticket_data["closed"] = []
    save_ticket_log(ticket_data)
    return jsonify({
        "success": True,
        "message": f"Deleted {deleted_count} closed tickets",
        "deleted_count": deleted_count
    })

@app.route('/api/tickets/<ticket_id>/message', methods=['POST'])
@api_auth_required
@api_perm_required('tickets.send_message')
def api_send_ticket_message(ticket_id):
    """Send a message to a ticket channel via the bot"""
    data = request.json or {}
    message = data.get("message", "").strip()
    mention_user = data.get("mention_user", True)
    index = data.get("index")
    
    if not message:
        return jsonify({"error": "Message is required"}), 400
    
    ticket_data = load_ticket_log()
    
    # Find the ticket
    ticket = None
    if index is not None and index < len(ticket_data.get("open", [])):
        ticket = ticket_data["open"][index]
    else:
        for t in ticket_data.get("open", []):
            if str(t.get("id")) == str(ticket_id):
                ticket = t
                break
    
    if not ticket:
        return jsonify({"error": "Ticket not found"}), 404
    
    sender_name = session.get('user_name', 'Dashboard Admin')
    
    # Queue Discord notification to send message
    queue_discord_notification({
        "type": "ticket_message",
        "channel_name": ticket.get("channel_name"),
        "message": message,
        "mention_user": mention_user,
        "user_id": ticket.get("user_id"),
        "sender": sender_name
    })
    
    return jsonify({"success": True, "message": "Message queued for delivery"})

@app.route('/api/tickets/<ticket_id>/assign', methods=['POST'])
@api_auth_required
@api_perm_required('tickets.assign')
def api_assign_ticket(ticket_id):
    """Assign a ticket to the current user"""
    data = request.json or {}
    index = data.get("index")
    
    ticket_data = load_ticket_log()
    assigned_to = session.get('user_name', 'Dashboard Admin')
    
    # Find and update the ticket
    updated = False
    if index is not None and index < len(ticket_data.get("open", [])):
        ticket_data["open"][index]["staff_assisting"] = assigned_to
        updated = True
        ticket = ticket_data["open"][index]
    else:
        for t in ticket_data.get("open", []):
            if str(t.get("id")) == str(ticket_id):
                t["staff_assisting"] = assigned_to
                ticket = t
                updated = True
                break
    
    if not updated:
        return jsonify({"error": "Ticket not found"}), 404
    
    save_ticket_log(ticket_data)
    
    # Queue Discord notification
    queue_discord_notification({
        "type": "ticket_assign",
        "channel_name": ticket.get("channel_name"),
        "assigned_to": assigned_to,
        "user_id": ticket.get("user_id")
    })
    
    return jsonify({"success": True, "message": f"Ticket assigned to {assigned_to}"})

# ============ BoilerCraftGG Dashboard ============

BOILERCRAFT_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "BoilerCraftGG", "data")
BOILERCRAFT_TICKET_LOG = os.path.join(BOILERCRAFT_DATA_DIR, "ticket_log.json")
BOILERCRAFT_MEMBERS_CACHE = os.path.join(BOILERCRAFT_DATA_DIR, "members_cache.json")
BOILERCRAFT_USER_RECORDS_DIR = os.path.join(BOILERCRAFT_DATA_DIR, "user_records")
BOILERCRAFT_MODERATION_TEMPLATES = os.path.join(BOILERCRAFT_DATA_DIR, "moderation_templates.json")

def load_boilercraft_tickets():
    return load_json_file(BOILERCRAFT_TICKET_LOG, {"open": [], "closed": [], "blacklist": []})

def save_boilercraft_tickets(data):
    save_json_file(BOILERCRAFT_TICKET_LOG, data)

@app.route('/boilercraft/dashboard')
@login_required
@page_permission_required('page.boilercraft')
def boilercraft_dashboard():
    perms = list(session.get('dashboard_permissions', []))
    # Discord users & legacy admin get full boilercraft access
    if session.get('discord_user') or session.get('legacy_login'):
        perms = perms + ['boilercraft.blacklist', 'boilercraft.settings']
    return render_template('boilercraft.html', bc_perms=perms)

@app.route('/boilercraft/faq')
@login_required
@page_permission_required('page.boilercraft_faq')
def boilercraft_faq():
    return render_template('boilercraft_faq.html')

@app.route('/api/boilercraft/server-status')
@api_auth_required
def api_boilercraft_server_status():
    """Fetch Minecraft server status from mcsrvstat.us API."""
    try:
        resp = requests.get('https://api.mcsrvstat.us/3/mc.esports.purdue.edu', timeout=5)
        data = resp.json()
        return jsonify({
            'success': True,
            'online': data.get('online', False),
            'ip': data.get('ip', ''),
            'port': data.get('port', 25565),
            'hostname': data.get('hostname', 'mc.esports.purdue.edu'),
            'players': {
                'online': data.get('players', {}).get('online', 0),
                'max': data.get('players', {}).get('max', 0),
                'list': [p.get('name', p) if isinstance(p, dict) else p for p in data.get('players', {}).get('list', [])][:50],
            },
            'version': data.get('version', 'Unknown'),
            'motd': data.get('motd', {}).get('clean', []),
            'icon': data.get('icon', ''),
            'software': data.get('software', ''),
        })
    except Exception as e:
        return jsonify({'success': False, 'online': False, 'error': str(e)})

@app.route('/api/boilercraft/tickets')
@api_auth_required
def api_boilercraft_tickets():
    data = load_boilercraft_tickets()
    return jsonify(data)

@app.route('/api/boilercraft/tickets/<ticket_id>/close', methods=['POST'])
@api_auth_required
@api_perm_required('boilercraft.close_tickets')
def api_boilercraft_ticket_close(ticket_id):
    data = load_boilercraft_tickets()
    body = request.get_json() or {}
    reason = body.get('reason', 'Closed from dashboard')
    index = body.get('index')

    ticket = None
    if index is not None and 0 <= index < len(data.get('open', [])):
        ticket = data['open'][index]
        if str(ticket.get('id')) == str(ticket_id):
            data['open'].pop(index)
        else:
            ticket = None

    if not ticket:
        for i, t in enumerate(data.get('open', [])):
            if str(t.get('id')) == str(ticket_id):
                ticket = data['open'].pop(i)
                break

    if not ticket:
        return jsonify({"error": "Ticket not found"}), 404

    ticket['status'] = 'closed'
    ticket['closed_by'] = 'Dashboard'
    ticket['close_reason'] = reason
    ticket['closed_at'] = datetime.now(timezone.utc).isoformat()
    data.setdefault('closed', []).append(ticket)
    save_boilercraft_tickets(data)

    # Queue command for BoilerCraft bot (uses its own command queue)
    commands_list = load_json_file(BOILERCRAFT_COMMANDS_FILE, [])
    commands_list.append({
        "type": "ticket_close",
        "channel_name": ticket.get("channel_name"),
        "reason": reason,
        "user_id": ticket.get("user_id"),
        "status": "pending",
        "queued_at": datetime.now(timezone.utc).isoformat()
    })
    save_json_file(BOILERCRAFT_COMMANDS_FILE, commands_list)

    return jsonify({"success": True})

@app.route('/api/boilercraft/tickets/<ticket_id>/message', methods=['POST'])
@api_auth_required
@api_perm_required('boilercraft.send_messages')
def api_boilercraft_ticket_message(ticket_id):
    data = load_boilercraft_tickets()
    body = request.get_json() or {}
    message = body.get('message', '')

    if not message:
        return jsonify({"error": "Message is required"}), 400

    ticket = None
    for t in data.get('open', []):
        if str(t.get('id')) == str(ticket_id):
            ticket = t
            break

    if not ticket:
        return jsonify({"error": "Ticket not found"}), 404

    # Queue command for BoilerCraft bot (uses its own command queue)
    commands_list = load_json_file(BOILERCRAFT_COMMANDS_FILE, [])
    commands_list.append({
        "type": "ticket_message",
        "channel_name": ticket.get("channel_name"),
        "message": message,
        "status": "pending",
        "queued_at": datetime.now(timezone.utc).isoformat()
    })
    save_json_file(BOILERCRAFT_COMMANDS_FILE, commands_list)

    return jsonify({"success": True})

@app.route('/api/boilercraft/tickets/blacklist/add', methods=['POST'])
@api_auth_required
@api_perm_required('boilercraft.blacklist')
def api_boilercraft_blacklist_add():
    data = load_boilercraft_tickets()
    body = request.get_json() or {}
    user_id = body.get('user_id')
    username = body.get('username', 'Unknown')
    reason = body.get('reason', 'No reason provided')

    if not user_id:
        return jsonify({"error": "User ID is required"}), 400

    existing_ids = [str(entry.get("user_id")) for entry in data.get("blacklist", [])]
    if str(user_id) in existing_ids:
        return jsonify({"error": "User is already blacklisted"}), 400

    dashboard_user = session.get('dashboard_user', {}).get('username') or session.get('discord_user', {}).get('username') or 'Dashboard'
    data.setdefault("blacklist", []).append({
        "user_id": str(user_id),
        "username": username,
        "reason": reason,
        "blacklisted_by": dashboard_user,
        "blacklisted_at": datetime.now(timezone.utc).isoformat()
    })
    save_boilercraft_tickets(data)
    return jsonify({"success": True})

@app.route('/api/boilercraft/tickets/blacklist/remove', methods=['POST'])
@api_auth_required
@api_perm_required('boilercraft.blacklist')
def api_boilercraft_blacklist_remove():
    data = load_boilercraft_tickets()
    body = request.get_json() or {}
    user_id = body.get('user_id')

    if not user_id:
        return jsonify({"error": "User ID is required"}), 400

    original_len = len(data.get("blacklist", []))
    data["blacklist"] = [e for e in data.get("blacklist", []) if str(e.get("user_id")) != str(user_id)]

    if len(data["blacklist"]) == original_len:
        return jsonify({"error": "User not found in blacklist"}), 404

    save_boilercraft_tickets(data)
    return jsonify({"success": True})

@app.route('/api/boilercraft/tickets/closed/<ticket_id>/delete', methods=['DELETE'])
@api_auth_required
@api_perm_required('boilercraft.delete_closed')
def api_boilercraft_delete_closed(ticket_id):
    data = load_boilercraft_tickets()
    original_len = len(data.get("closed", []))
    data["closed"] = [t for t in data.get("closed", []) if str(t.get("id")) != str(ticket_id)]

    if len(data["closed"]) == original_len:
        return jsonify({"error": "Ticket not found"}), 404

    save_boilercraft_tickets(data)
    return jsonify({"success": True})

@app.route('/api/boilercraft/tickets/closed/delete-all', methods=['DELETE'])
@api_auth_required
@api_perm_required('boilercraft.delete_closed')
def api_boilercraft_delete_all_closed():
    data = load_boilercraft_tickets()
    count = len(data.get("closed", []))
    data["closed"] = []
    save_boilercraft_tickets(data)
    return jsonify({"success": True, "deleted": count})

# ---- BoilerCraftGG Settings API ----

BOILERCRAFT_CONFIG_FILE = os.path.join(BOILERCRAFT_DATA_DIR, "bot_config.json")
BOILERCRAFT_COMMANDS_FILE = os.path.join(BOILERCRAFT_DATA_DIR, "dashboard_commands.json")

BOILERCRAFT_FAQ_FILE = os.path.join(BOILERCRAFT_DATA_DIR, "faqs.json")

BOILERCRAFT_DEFAULT_CONFIG = {
    "staff_role_id": None,
    "ticket_panel_channel_id": None,
    "ticket_category_name": "MC Tickets",
    "ticket_channel_prefix": "mc-ticket-",
    "faq_channel_id": None,
    "support_categories": [
        {"label": "Player Support", "value": "Player Support", "emoji": "🎮", "description": "General gameplay help and questions"},
        {"label": "Server Bugs", "value": "Server Bugs", "emoji": "🐛", "description": "Report server issues or bugs"},
        {"label": "Report a Player", "value": "Report a Player", "emoji": "🛡️", "description": "Report rule-breaking behavior"},
        {"label": "Appeal / Unban", "value": "Appeal / Unban", "emoji": "⚖️", "description": "Appeal a ban or punishment"},
        {"label": "General Question", "value": "General Question", "emoji": "❓", "description": "Anything else not listed above"},
    ]
}

def load_boilercraft_config():
    data = load_json_file(BOILERCRAFT_CONFIG_FILE, BOILERCRAFT_DEFAULT_CONFIG)
    return {**BOILERCRAFT_DEFAULT_CONFIG, **data}

def save_boilercraft_config(data):
    save_json_file(BOILERCRAFT_CONFIG_FILE, data)

@app.route('/api/boilercraft/settings')
@api_auth_required
def api_boilercraft_settings_get():
    cfg = load_boilercraft_config()
    return jsonify(cfg)

@app.route('/api/boilercraft/settings', methods=['POST'])
@api_auth_required
@api_perm_required('boilercraft.settings')
def api_boilercraft_settings_save():
    body = request.get_json() or {}
    cfg = load_boilercraft_config()

    # Update allowed fields
    allowed_fields = ["staff_role_id", "ticket_panel_channel_id", "ticket_category_name", "ticket_channel_prefix", "support_categories", "announce_channel_id", "minecraft_role_id", "faq_channel_id"]
    for field in allowed_fields:
        if field in body:
            cfg[field] = body[field]

    # Validate support_categories structure
    if "support_categories" in body:
        cats = body["support_categories"]
        if not isinstance(cats, list):
            return jsonify({"error": "support_categories must be a list"}), 400
        for cat in cats:
            if not isinstance(cat, dict) or "label" not in cat:
                return jsonify({"error": "Each category must have a 'label'"}), 400

    save_boilercraft_config(cfg)
    return jsonify({"success": True})

@app.route('/api/boilercraft/deploy-panel', methods=['POST'])
@api_auth_required
@api_perm_required('boilercraft.deploy_panel')
def api_boilercraft_deploy_panel():
    cfg = load_boilercraft_config()
    channel_id = cfg.get("ticket_panel_channel_id")
    if not channel_id:
        return jsonify({"error": "No ticket panel channel configured. Set it in Settings first."}), 400

    # Queue a deploy command for the BoilerCraft bot to pick up
    try:
        commands_list = load_json_file(BOILERCRAFT_COMMANDS_FILE, [])
        commands_list.append({
            "type": "deploy_panel",
            "channel_id": int(channel_id),
            "status": "pending",
            "queued_at": datetime.now(timezone.utc).isoformat()
        })
        save_json_file(BOILERCRAFT_COMMANDS_FILE, commands_list)
    except Exception as e:
        return jsonify({"error": f"Failed to queue command: {str(e)}"}), 500

    return jsonify({"success": True, "message": "Panel deployment queued. The bot will deploy it shortly."})

@app.route('/api/boilercraft/refresh-panel', methods=['POST'])
@api_auth_required
@api_perm_required('boilercraft.deploy_panel')
def api_boilercraft_refresh_panel():
    cfg = load_boilercraft_config()
    channel_id = cfg.get("ticket_panel_channel_id")
    if not channel_id:
        return jsonify({"error": "No ticket panel channel configured."}), 400

    try:
        commands_list = load_json_file(BOILERCRAFT_COMMANDS_FILE, [])
        commands_list.append({
            "type": "refresh_panel",
            "channel_id": int(channel_id),
            "status": "pending",
            "queued_at": datetime.now(timezone.utc).isoformat()
        })
        save_json_file(BOILERCRAFT_COMMANDS_FILE, commands_list)
    except Exception as e:
        return jsonify({"error": f"Failed to queue command: {str(e)}"}), 500

    return jsonify({"success": True, "message": "Panel refresh queued. The bot will update it shortly."})

# =========================================================================
# BoilerCraftGG FAQ API endpoints
# =========================================================================

def load_boilercraft_faqs():
    return load_json_file(BOILERCRAFT_FAQ_FILE, [])

def save_boilercraft_faqs(data):
    save_json_file(BOILERCRAFT_FAQ_FILE, data)

@app.route('/api/boilercraft/faqs')
@api_auth_required
def api_boilercraft_faqs_get():
    faqs = load_boilercraft_faqs()
    return jsonify(faqs)

@app.route('/api/boilercraft/faqs', methods=['POST'])
@api_auth_required
@api_perm_required('boilercraft.faq_manage')
def api_boilercraft_faqs_add():
    body = request.get_json() or {}
    question = body.get('question', '').strip()
    answer = body.get('answer', '').strip()

    if not question or not answer:
        return jsonify({"error": "Question and answer are required"}), 400

    cfg = load_boilercraft_config()
    faq_channel_id = cfg.get("faq_channel_id")
    if not faq_channel_id:
        return jsonify({"error": "No FAQ channel configured. Set it first."}), 400

    faqs = load_boilercraft_faqs()
    new_faq = {
        "question": question,
        "answer": answer,
        "message_id": None
    }
    faqs.append(new_faq)
    save_boilercraft_faqs(faqs)

    # Queue bot command to post the FAQ embed
    faq_index = len(faqs) - 1
    commands_list = load_json_file(BOILERCRAFT_COMMANDS_FILE, [])
    commands_list.append({
        "type": "faq_post",
        "faq_index": faq_index,
        "channel_id": int(faq_channel_id),
        "status": "pending",
        "queued_at": datetime.now(timezone.utc).isoformat()
    })
    save_json_file(BOILERCRAFT_COMMANDS_FILE, commands_list)

    return jsonify({"success": True})

@app.route('/api/boilercraft/faqs/<int:index>', methods=['PUT'])
@api_auth_required
@api_perm_required('boilercraft.faq_manage')
def api_boilercraft_faqs_edit(index):
    body = request.get_json() or {}
    question = body.get('question', '').strip()
    answer = body.get('answer', '').strip()

    if not question or not answer:
        return jsonify({"error": "Question and answer are required"}), 400

    cfg = load_boilercraft_config()
    faq_channel_id = cfg.get("faq_channel_id")
    if not faq_channel_id:
        return jsonify({"error": "No FAQ channel configured."}), 400

    faqs = load_boilercraft_faqs()
    if index < 0 or index >= len(faqs):
        return jsonify({"error": "FAQ not found"}), 404

    faqs[index]["question"] = question
    faqs[index]["answer"] = answer
    save_boilercraft_faqs(faqs)

    # Queue bot command to edit the FAQ embed
    commands_list = load_json_file(BOILERCRAFT_COMMANDS_FILE, [])
    commands_list.append({
        "type": "faq_edit",
        "faq_index": index,
        "channel_id": int(faq_channel_id),
        "message_id": faqs[index].get("message_id"),
        "status": "pending",
        "queued_at": datetime.now(timezone.utc).isoformat()
    })
    save_json_file(BOILERCRAFT_COMMANDS_FILE, commands_list)

    return jsonify({"success": True})

@app.route('/api/boilercraft/faqs/<int:index>', methods=['DELETE'])
@api_auth_required
@api_perm_required('boilercraft.faq_manage')
def api_boilercraft_faqs_delete(index):
    cfg = load_boilercraft_config()
    faq_channel_id = cfg.get("faq_channel_id")

    faqs = load_boilercraft_faqs()
    if index < 0 or index >= len(faqs):
        return jsonify({"error": "FAQ not found"}), 404

    removed = faqs.pop(index)
    save_boilercraft_faqs(faqs)

    # Queue bot command to delete the message and re-number remaining
    commands_list = load_json_file(BOILERCRAFT_COMMANDS_FILE, [])
    commands_list.append({
        "type": "faq_delete",
        "message_id": removed.get("message_id"),
        "channel_id": int(faq_channel_id) if faq_channel_id else None,
        "status": "pending",
        "queued_at": datetime.now(timezone.utc).isoformat()
    })
    # Also queue a full re-number to update all remaining FAQ embeds
    commands_list.append({
        "type": "faq_renumber",
        "channel_id": int(faq_channel_id) if faq_channel_id else None,
        "status": "pending",
        "queued_at": datetime.now(timezone.utc).isoformat()
    })
    save_json_file(BOILERCRAFT_COMMANDS_FILE, commands_list)

    return jsonify({"success": True})

# ============ BoilerCraftGG Verified Players ============

BOILERCRAFT_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "BoilerCraftGG", "data", "boilercraft.db")

@app.route('/boilercraft/verified-players')
@login_required
@page_permission_required('page.boilercraft')
def boilercraft_verified_players():
    return render_template('boilercraft_verified_players.html')

@app.route('/api/boilercraft/verified-players')
@api_auth_required
def api_boilercraft_verified_players():
    """Return all verified players from the BoilerCraft SQLite database."""
    import sqlite3
    players = []
    if os.path.exists(BOILERCRAFT_DB_PATH):
        conn = sqlite3.connect(BOILERCRAFT_DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.execute("SELECT discord_id, minecraft_username, minecraft_uuid, first_name, email, campus, verified_at FROM verified_users ORDER BY verified_at DESC")
            for row in cursor:
                players.append({
                    "discord_id": str(row["discord_id"]),
                    "minecraft_username": row["minecraft_username"],
                    "minecraft_uuid": row["minecraft_uuid"],
                    "first_name": row["first_name"],
                    "email": row["email"],
                    "campus": row["campus"],
                    "verified_at": row["verified_at"],
                })
        finally:
            conn.close()

    # Enrich with Discord display names from members cache
    members_data = load_json_file(BOILERCRAFT_MEMBERS_CACHE, [])
    members_map = {str(m.get("id", "")): m for m in members_data}
    for p in players:
        member = members_map.get(p["discord_id"])
        if member:
            p["discord_name"] = member.get("display_name") or member.get("name", "Unknown")
            p["discord_avatar"] = member.get("avatar_url", "")
        else:
            p["discord_name"] = f"User#{p['discord_id'][-4:]}"
            p["discord_avatar"] = ""

    return jsonify({"players": players, "total": len(players)})

@app.route('/api/boilercraft/verified-players/export')
@api_auth_required
def api_boilercraft_verified_players_export():
    """Export verified players as Excel."""
    import sqlite3
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    players = []
    if os.path.exists(BOILERCRAFT_DB_PATH):
        conn = sqlite3.connect(BOILERCRAFT_DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.execute("SELECT discord_id, minecraft_username, first_name, email, campus, verified_at FROM verified_users ORDER BY verified_at DESC")
            for row in cursor:
                players.append(dict(row))
        finally:
            conn.close()

    members_data = load_json_file(BOILERCRAFT_MEMBERS_CACHE, [])
    members_map = {str(m.get("id", "")): m for m in members_data}

    wb = Workbook()
    ws = wb.active
    ws.title = "Verified Players"
    ws.sheet_properties.tabColor = "CFA630"

    header_font = Font(name="Segoe UI", bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="CFA630", end_color="CFA630", fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center")
    thin_border = Border(
        left=Side(style="thin", color="3a3a4a"),
        right=Side(style="thin", color="3a3a4a"),
        top=Side(style="thin", color="3a3a4a"),
        bottom=Side(style="thin", color="3a3a4a"),
    )
    alt_fill = PatternFill(start_color="2a2a3a", end_color="2a2a3a", fill_type="solid")

    headers = ["Discord Name", "Minecraft IGN", "First Name", "Email", "Campus", "Verified Date"]
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = thin_border
    ws.freeze_panes = "A2"

    data_font = Font(name="Segoe UI", size=10, color="e0e0e0")
    for i, p in enumerate(players, 2):
        member = members_map.get(str(p["discord_id"]))
        discord_name = (member.get("display_name") or member.get("name", "Unknown")) if member else f"User#{str(p['discord_id'])[-4:]}"
        verified_str = ""
        if p["verified_at"]:
            try:
                dt = datetime.fromisoformat(str(p["verified_at"]).replace("Z", "+00:00"))
                verified_str = dt.strftime("%B %d, %Y %I:%M %p")
            except Exception:
                verified_str = str(p["verified_at"])
        row_data = [discord_name, p["minecraft_username"], p.get("first_name", ""), p.get("email", ""), p.get("campus", ""), verified_str]
        for col, val in enumerate(row_data, 1):
            cell = ws.cell(row=i, column=col, value=val or "")
            cell.font = data_font
            cell.border = thin_border
            if i % 2 == 0:
                cell.fill = alt_fill

    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 22
    ws.column_dimensions["C"].width = 18
    ws.column_dimensions["D"].width = 30
    ws.column_dimensions["E"].width = 22
    ws.column_dimensions["F"].width = 24

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(output, download_name=f"verified_players_{datetime.now().strftime('%Y%m%d')}.xlsx",
                     as_attachment=True, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ============ BoilerWatch (Chat Monitor Flagged Logs) ============

BOILERWATCH_LOG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "BoilerCraftGG", "data", "flagged_log.json")
BOILERWATCH_CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "BoilerCraftGG", "data", "chat_monitor_config.json")
BOILERWATCH_WORDS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "BoilerCraftGG", "data", "flagged_words.json")

@app.route('/boilercraft/boilerwatch')
@login_required
@page_permission_required('page.boilercraft')
def boilercraft_boilerwatch():
    return render_template('boilercraft_boilerwatch.html')

@app.route('/api/boilercraft/boilerwatch/logs')
@api_auth_required
def api_boilerwatch_logs():
    """Return all flagged chat logs."""
    logs = load_json_file(BOILERWATCH_LOG_FILE, [])
    return jsonify(logs)

@app.route('/api/boilercraft/boilerwatch/stats')
@api_auth_required
def api_boilerwatch_stats():
    """Return stats for BoilerWatch dashboard."""
    logs = load_json_file(BOILERWATCH_LOG_FILE, [])
    config = load_json_file(BOILERWATCH_CONFIG_FILE, {})
    words = load_json_file(BOILERWATCH_WORDS_FILE, {"words": []})

    total = len(logs)
    whispers = sum(1 for l in logs if l.get("type") == "Whisper")
    public = total - whispers

    # Unique players flagged
    players = set(l.get("player", "") for l in logs)

    # Most flagged words
    word_counts = {}
    for l in logs:
        for w in l.get("flagged_words", []):
            word_counts[w] = word_counts.get(w, 0) + 1
    top_words = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    # Most flagged players
    player_counts = {}
    for l in logs:
        p = l.get("player", "Unknown")
        player_counts[p] = player_counts.get(p, 0) + 1
    top_players = sorted(player_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    # Today's count
    today_str = datetime.now().strftime("%Y-%m-%d")
    today_count = sum(1 for l in logs if l.get("timestamp", "").startswith(today_str))

    return jsonify({
        "total": total,
        "whispers": whispers,
        "public": public,
        "unique_players": len(players),
        "today": today_count,
        "enabled": config.get("enabled", True),
        "flagged_words": words.get("words", []),
        "top_words": top_words,
        "top_players": top_players,
        "servers": config.get("servers", {})
    })

@app.route('/api/boilercraft/boilerwatch/logs/clear', methods=['POST'])
@api_auth_required
def api_boilerwatch_clear_logs():
    """Clear all flagged logs."""
    save_json_file(BOILERWATCH_LOG_FILE, [])
    return jsonify({"success": True})

# ============ BoilerCraftGG Members ============

@app.route('/boilercraft/members')
@login_required
@page_permission_required('page.boilercraft')
def boilercraft_members():
    return render_template('boilercraft_members.html')

@app.route('/api/boilercraft/members')
@api_auth_required
def api_boilercraft_members():
    """Get all members from the BoilerCraftGG members cache"""
    members = load_json_file(BOILERCRAFT_MEMBERS_CACHE, [])
    return jsonify(members)

@app.route('/api/boilercraft/members/<user_id>')
@api_auth_required
def api_boilercraft_member_detail(user_id):
    """Get detailed info for a specific BoilerCraftGG member"""
    members = load_json_file(BOILERCRAFT_MEMBERS_CACHE, [])
    member = next((m for m in members if str(m.get('id')) == str(user_id)), None)
    
    if not member:
        return jsonify({"error": "Member not found"}), 404
    
    # Get user's moderation records
    records = load_json_file(os.path.join(BOILERCRAFT_USER_RECORDS_DIR, f"{user_id}_record.json"), [])
    
    return jsonify({
        "member": member,
        "records": records
    })

@app.route('/api/boilercraft/members/<user_id>/action', methods=['POST'])
@api_auth_required
def api_boilercraft_member_action(user_id):
    """Queue a moderation action for a BoilerCraftGG member"""
    data = request.json
    action = data.get('action')
    reason = data.get('reason', 'No reason provided')
    duration = data.get('duration')
    
    if action not in ['kick', 'ban', 'timeout', 'unban', 'warn']:
        return jsonify({"success": False, "message": "Invalid action"})
    
    moderator_name = get_moderator_name()
    moderator_id = get_moderator_id()
    
    members = load_json_file(BOILERCRAFT_MEMBERS_CACHE, [])
    target_member = next((m for m in members if str(m.get('id')) == str(user_id)), None)
    target_name = target_member.get('display_name') or target_member.get('name') if target_member else f"User {user_id}"
    
    if action == 'warn':
        os.makedirs(BOILERCRAFT_USER_RECORDS_DIR, exist_ok=True)
        record_file = os.path.join(BOILERCRAFT_USER_RECORDS_DIR, f"{user_id}_record.json")
        records = load_json_file(record_file, [])
        
        records.append({
            "user_id": str(user_id),
            "type": "Warning",
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "moderator": moderator_name,
            "moderator_id": moderator_id,
            "source": "website"
        })
        
        save_json_file(record_file, records)
        
        return jsonify({
            "success": True,
            "message": f"Warning issued to {target_name} and added to their record."
        })
    
    # For kick/ban/timeout/unban - queue for BoilerCraftGG bot
    commands_list = load_json_file(BOILERCRAFT_COMMANDS_FILE, [])
    commands_list.append({
        "type": f"member_{action}",
        "user_id": str(user_id),
        "reason": reason,
        "duration": duration,
        "moderator": moderator_name,
        "moderator_id": moderator_id,
        "status": "pending",
        "queued_at": datetime.now(timezone.utc).isoformat()
    })
    save_json_file(BOILERCRAFT_COMMANDS_FILE, commands_list)
    
    return jsonify({
        "success": True,
        "message": f"Action '{action}' queued for {target_name}. The bot will process this action."
    })

@app.route('/api/boilercraft/send-dm', methods=['POST'])
@api_auth_required
def api_boilercraft_send_dm():
    """Send a DM to a user via the BoilerCraftGG bot"""
    data = request.get_json()
    user_id = data.get('user_id')
    message = data.get('message', '')
    
    if not user_id:
        return jsonify({"success": False, "message": "User ID is required"})
    if not message.strip():
        return jsonify({"success": False, "message": "Message cannot be empty"})
    
    moderator = get_moderator_name()
    
    commands_list = load_json_file(BOILERCRAFT_COMMANDS_FILE, [])
    commands_list.append({
        "type": "send_dm",
        "user_id": str(user_id),
        "message": message,
        "moderator": moderator,
        "status": "pending",
        "queued_at": datetime.now(timezone.utc).isoformat()
    })
    save_json_file(BOILERCRAFT_COMMANDS_FILE, commands_list)
    
    members = load_json_file(BOILERCRAFT_MEMBERS_CACHE, [])
    member = next((m for m in members if str(m.get('id')) == str(user_id)), None)
    target_name = member.get('display_name') or member.get('name') if member else f"User {user_id}"
    
    return jsonify({"success": True, "message": f"DM queued for delivery to {target_name}"})

@app.route('/api/boilercraft/moderation/templates')
@api_auth_required
def api_boilercraft_moderation_templates():
    """Get moderation reason templates for BoilerCraftGG"""
    templates_data = load_json_file(BOILERCRAFT_MODERATION_TEMPLATES, {"templates": [], "categories": []})
    
    all_templates = templates_data.get("templates", []) + templates_data.get("custom_templates", [])
    
    return jsonify({
        "templates": all_templates,
        "categories": templates_data.get("categories", [])
    })

# ============ BoilerCraftGG Server Analytics ============

BOILERCRAFT_ANALYTICS_FILE = os.path.join(BOILERCRAFT_DATA_DIR, "server_analytics.json")

@app.route('/boilercraft/analytics')
@login_required
@page_permission_required('page.boilercraft')
def boilercraft_analytics():
    return render_template('boilercraft_analytics.html')

@app.route('/api/boilercraft/analytics')
@api_auth_required
def api_boilercraft_analytics():
    """Return server analytics data, optionally filtered by range."""
    data = load_json_file(BOILERCRAFT_ANALYTICS_FILE, [])
    return jsonify({"data": data})

@app.route('/api/boilercraft/analytics/export')
@api_auth_required
def api_boilercraft_analytics_export():
    """Export analytics data as an Excel (.xlsx) file."""
    range_param = request.args.get('range', '30d')
    range_hours = {'24h': 24, '7d': 168, '14d': 336, '30d': 720}.get(range_param, 720)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=range_hours)

    data = load_json_file(BOILERCRAFT_ANALYTICS_FILE, [])
    filtered = [d for d in data if datetime.fromisoformat(d['timestamp'].replace('Z', '+00:00')) >= cutoff]

    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    except ImportError:
        # Fallback to CSV if openpyxl is not installed
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Timestamp', 'Online', 'Players Online', 'Players Max', 'Player Names'])
        for entry in filtered:
            writer.writerow([
                entry.get('timestamp', ''),
                entry.get('online', False),
                entry.get('players_online', 0),
                entry.get('players_max', 0),
                ', '.join(entry.get('player_names', []))
            ])
        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment; filename=boilercraft_analytics_{range_param}.csv'}
        )

    from openpyxl.chart import LineChart, BarChart, Reference
    from openpyxl.chart.series import SeriesLabel
    from openpyxl.chart.label import DataLabelList
    from openpyxl.utils import get_column_letter

    wb = Workbook()

    # ── Shared styles ──
    BRAND_COLOR = "5865F2"
    BRAND_DARK  = "4752C4"
    ACCENT_GREEN = "57F287"
    ACCENT_RED   = "ED4245"

    title_font     = Font(bold=True, color="FFFFFF", size=14)
    subtitle_font  = Font(bold=True, color="333333", size=11)
    header_font    = Font(bold=True, color="FFFFFF", size=11)
    header_fill    = PatternFill(start_color=BRAND_COLOR, end_color=BRAND_COLOR, fill_type="solid")
    header_fill_dk = PatternFill(start_color=BRAND_DARK, end_color=BRAND_DARK, fill_type="solid")
    stripe_fill    = PatternFill(start_color="F2F3F5", end_color="F2F3F5", fill_type="solid")
    online_fill    = PatternFill(start_color="DCFCE7", end_color="DCFCE7", fill_type="solid")
    offline_fill   = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid")
    stat_value_font = Font(bold=True, color=BRAND_COLOR, size=20)
    stat_label_font = Font(color="666666", size=10)
    thin_border = Border(
        left=Side(style='thin', color='E0E0E0'),
        right=Side(style='thin', color='E0E0E0'),
        top=Side(style='thin', color='E0E0E0'),
        bottom=Side(style='thin', color='E0E0E0')
    )
    center_align = Alignment(horizontal='center', vertical='center')
    wrap_align   = Alignment(horizontal='center', vertical='center', wrap_text=True)

    def _apply_header_row(ws, headers, widths, row=1, fill=None):
        """Apply styled header row to a worksheet."""
        _fill = fill or header_fill
        for col, (hdr, w) in enumerate(zip(headers, widths), 1):
            cell = ws.cell(row=row, column=col, value=hdr)
            cell.font = header_font
            cell.fill = _fill
            cell.alignment = center_align
            cell.border = thin_border
            ws.column_dimensions[get_column_letter(col)].width = w
        ws.freeze_panes = ws.cell(row=row + 1, column=1).coordinate

    def _write_data_row(ws, row, values, is_striped=False):
        """Write a row of data with optional striping."""
        for col, val in enumerate(values, 1):
            cell = ws.cell(row=row, column=col, value=val)
            cell.border = thin_border
            cell.alignment = Alignment(horizontal='center')
            if is_striped:
                cell.fill = stripe_fill

    # ── Pre-compute all analytics ──
    hour_buckets = {h: [] for h in range(24)}
    day_buckets = {}
    player_stats = {}
    total_online_checks = 0
    total_offline_checks = 0
    all_counts = []

    for entry in filtered:
        count = entry.get('players_online', 0)
        all_counts.append(count)
        if entry.get('online'):
            total_online_checks += 1
        else:
            total_offline_checks += 1
        try:
            ts = datetime.fromisoformat(entry['timestamp'].replace('Z', '+00:00'))
            hour_buckets[ts.hour].append(count)
            day_key = ts.strftime('%Y-%m-%d')
            if day_key not in day_buckets:
                day_buckets[day_key] = {'counts': [], 'players': set()}
            day_buckets[day_key]['counts'].append(count)
            for name in entry.get('player_names', []):
                day_buckets[day_key]['players'].add(name)
        except (ValueError, KeyError):
            pass
        for name in entry.get('player_names', []):
            if name not in player_stats:
                player_stats[name] = {'count': 0, 'last_seen': entry['timestamp']}
            player_stats[name]['count'] += 1
            if entry['timestamp'] > player_stats[name]['last_seen']:
                player_stats[name]['last_seen'] = entry['timestamp']

    peak_players = max(all_counts) if all_counts else 0
    avg_players  = round(sum(all_counts) / len(all_counts), 1) if all_counts else 0
    total_unique = len(player_stats)
    uptime_pct   = round((total_online_checks / len(filtered)) * 100, 1) if filtered else 0
    peak_hour_val = 0
    peak_hour_label = "N/A"
    for h in range(24):
        arr = hour_buckets[h]
        if arr and (sum(arr) / len(arr)) > peak_hour_val:
            peak_hour_val = sum(arr) / len(arr)
            peak_hour_label = f"{h % 12 or 12}:00 {'AM' if h < 12 else 'PM'}"

    range_labels = {'24h': 'Last 24 Hours', '7d': 'Last 7 Days', '14d': 'Last 14 Days', '30d': 'Last 30 Days'}
    report_title = range_labels.get(range_param, 'Last 30 Days')

    # ════════════════════════════════════════════════════
    # Sheet 1: Executive Summary / Dashboard
    # ════════════════════════════════════════════════════
    ws_dash = wb.active
    ws_dash.title = "Dashboard"
    ws_dash.sheet_properties.tabColor = BRAND_COLOR

    # Title banner
    ws_dash.merge_cells('A1:H2')
    title_cell = ws_dash['A1']
    title_cell.value = f"BoilerCraft Server Analytics — {report_title}"
    title_cell.font = Font(bold=True, color="FFFFFF", size=18)
    title_cell.fill = PatternFill(start_color=BRAND_COLOR, end_color=BRAND_DARK, fill_type="solid")
    title_cell.alignment = Alignment(horizontal='center', vertical='center')

    ws_dash.merge_cells('A3:H3')
    gen_cell = ws_dash['A3']
    gen_cell.value = f"Generated {datetime.now(timezone.utc).strftime('%B %d, %Y at %I:%M %p UTC')}  •  {len(filtered)} data points"
    gen_cell.font = Font(italic=True, color="888888", size=10)
    gen_cell.alignment = Alignment(horizontal='center')

    # KPI Cards (row 5-7)
    kpi_data = [
        ("Peak Players", str(peak_players)),
        ("Avg Players", str(avg_players)),
        ("Unique Players", str(total_unique)),
        ("Server Uptime", f"{uptime_pct}%"),
        ("Peak Hour", peak_hour_label),
        ("Days Tracked", str(len(day_buckets))),
    ]
    for i, (label, value) in enumerate(kpi_data):
        col = i + 1
        ws_dash.column_dimensions[get_column_letter(col)].width = 18
        # Value cell
        val_cell = ws_dash.cell(row=5, column=col, value=value)
        val_cell.font = stat_value_font
        val_cell.alignment = center_align
        val_cell.border = Border(
            left=Side(style='thin', color='E0E0E0'),
            right=Side(style='thin', color='E0E0E0'),
            top=Side(style='medium', color=BRAND_COLOR),
        )
        # Label cell
        lbl_cell = ws_dash.cell(row=6, column=col, value=label)
        lbl_cell.font = stat_label_font
        lbl_cell.alignment = center_align
        lbl_cell.border = Border(
            left=Side(style='thin', color='E0E0E0'),
            right=Side(style='thin', color='E0E0E0'),
            bottom=Side(style='thin', color='E0E0E0'),
        )

    # Mini daily table on dashboard (row 8+)
    ws_dash.cell(row=8, column=1, value="Daily Overview").font = subtitle_font
    dash_headers = ['Date', 'Peak', 'Average', 'Unique Players', 'Uptime %', 'Samples']
    dash_widths  = [14, 10, 10, 16, 12, 10]
    for col, (hdr, w) in enumerate(zip(dash_headers, dash_widths), 1):
        cell = ws_dash.cell(row=9, column=col, value=hdr)
        cell.font = header_font
        cell.fill = header_fill_dk
        cell.alignment = center_align
        cell.border = thin_border
        ws_dash.column_dimensions[get_column_letter(col)].width = max(w, ws_dash.column_dimensions[get_column_letter(col)].width)

    sorted_days = sorted(day_buckets.keys())
    for r, day in enumerate(sorted_days, 10):
        info = day_buckets[day]
        day_online = sum(1 for e in filtered
                         if e.get('online') and e.get('timestamp', '').startswith(day))
        day_total = len(info['counts'])
        day_uptime = round((day_online / day_total) * 100, 1) if day_total else 0
        vals = [
            day,
            max(info['counts']) if info['counts'] else 0,
            round(sum(info['counts']) / len(info['counts']), 1) if info['counts'] else 0,
            len(info['players']),
            f"{day_uptime}%",
            day_total,
        ]
        _write_data_row(ws_dash, r, vals, is_striped=(r % 2 == 0))

    ws_dash.freeze_panes = 'A10'

    # ════════════════════════════════════════════════════
    # Sheet 2: Player Timeline (with Line Chart)
    # ════════════════════════════════════════════════════
    ws_timeline = wb.create_sheet("Player Timeline")
    ws_timeline.sheet_properties.tabColor = "57F287"

    tl_headers = ['Timestamp (UTC)', 'Players Online', 'Server Status']
    tl_widths  = [26, 16, 16]
    _apply_header_row(ws_timeline, tl_headers, tl_widths)

    for r, entry in enumerate(filtered, 2):
        ts_str = entry.get('timestamp', '')
        try:
            ts_dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
            display_ts = ts_dt.strftime('%Y-%m-%d %I:%M %p')
        except (ValueError, AttributeError):
            display_ts = ts_str
        online = entry.get('online', False)
        status_text = 'Online' if online else 'Offline'

        ws_timeline.cell(row=r, column=1, value=display_ts).border = thin_border
        c2 = ws_timeline.cell(row=r, column=2, value=entry.get('players_online', 0))
        c2.border = thin_border
        c2.alignment = center_align
        c3 = ws_timeline.cell(row=r, column=3, value=status_text)
        c3.border = thin_border
        c3.alignment = center_align
        c3.fill = online_fill if online else offline_fill
        if r % 2 == 0:
            ws_timeline.cell(row=r, column=1).fill = stripe_fill

    # Player Count Line Chart
    if len(filtered) > 1:
        chart = LineChart()
        chart.title = "Player Count Over Time"
        chart.style = 10
        chart.y_axis.title = "Players Online"
        chart.x_axis.title = "Time"
        chart.width = 32
        chart.height = 16
        chart.y_axis.numFmt = '0'
        chart.legend = None

        data_ref = Reference(ws_timeline, min_col=2, min_row=1, max_row=len(filtered) + 1)
        cats_ref = Reference(ws_timeline, min_col=1, min_row=2, max_row=len(filtered) + 1)
        chart.add_data(data_ref, titles_from_data=True)
        chart.set_categories(cats_ref)

        # Style the line
        s = chart.series[0]
        s.graphicalProperties.line.solidFill = BRAND_COLOR
        s.graphicalProperties.line.width = 22000  # ~2pt
        s.smooth = True

        # Place chart below data or at a reasonable position
        chart_row = min(len(filtered) + 3, 35)
        ws_timeline.add_chart(chart, f"A{chart_row}")

    # ════════════════════════════════════════════════════
    # Sheet 3: Peak Hours (with Bar Chart)
    # ════════════════════════════════════════════════════
    ws_hourly = wb.create_sheet("Peak Hours")
    ws_hourly.sheet_properties.tabColor = "FEE75C"

    h_headers = ['Hour (UTC)', 'Avg Players', 'Peak Players', 'Data Points']
    h_widths  = [14, 14, 14, 14]
    _apply_header_row(ws_hourly, h_headers, h_widths)

    for hour in range(24):
        row = hour + 2
        arr = hour_buckets[hour]
        h_label = f"{hour % 12 or 12}:00 {'AM' if hour < 12 else 'PM'}"
        avg_val = round(sum(arr) / len(arr), 1) if arr else 0
        peak_val = max(arr) if arr else 0
        _write_data_row(ws_hourly, row, [h_label, avg_val, peak_val, len(arr)], is_striped=(row % 2 == 0))

    # Peak Hours Bar Chart
    bar_chart = BarChart()
    bar_chart.type = "col"
    bar_chart.title = "Average Players by Hour (UTC)"
    bar_chart.style = 10
    bar_chart.y_axis.title = "Players"
    bar_chart.x_axis.title = "Hour of Day"
    bar_chart.width = 32
    bar_chart.height = 16
    bar_chart.y_axis.numFmt = '0'

    avg_ref  = Reference(ws_hourly, min_col=2, min_row=1, max_row=26)
    peak_ref = Reference(ws_hourly, min_col=3, min_row=1, max_row=26)
    cats_ref = Reference(ws_hourly, min_col=1, min_row=2, max_row=26)

    bar_chart.add_data(avg_ref, titles_from_data=True)
    bar_chart.add_data(peak_ref, titles_from_data=True)
    bar_chart.set_categories(cats_ref)

    bar_chart.series[0].graphicalProperties.solidFill = BRAND_COLOR
    bar_chart.series[1].graphicalProperties.solidFill = ACCENT_GREEN
    bar_chart.series[1].graphicalProperties.line.solidFill = ACCENT_GREEN

    ws_hourly.add_chart(bar_chart, "A28")

    # ════════════════════════════════════════════════════
    # Sheet 4: Daily Summary (with Line Chart)
    # ════════════════════════════════════════════════════
    ws_daily = wb.create_sheet("Daily Summary")
    ws_daily.sheet_properties.tabColor = "EB459E"

    d_headers = ['Date', 'Peak Players', 'Avg Players', 'Unique Players', 'Data Points']
    d_widths  = [14, 14, 14, 16, 14]
    _apply_header_row(ws_daily, d_headers, d_widths)

    for r, day in enumerate(sorted_days, 2):
        info = day_buckets[day]
        peak = max(info['counts']) if info['counts'] else 0
        avg  = round(sum(info['counts']) / len(info['counts']), 1) if info['counts'] else 0
        _write_data_row(ws_daily, r, [day, peak, avg, len(info['players']), len(info['counts'])], is_striped=(r % 2 == 0))

    # Daily Summary Chart
    if len(sorted_days) > 1:
        daily_chart = LineChart()
        daily_chart.title = "Daily Player Trends"
        daily_chart.style = 10
        daily_chart.y_axis.title = "Players"
        daily_chart.x_axis.title = "Date"
        daily_chart.width = 32
        daily_chart.height = 16
        daily_chart.y_axis.numFmt = '0'

        day_count = len(sorted_days)
        peak_ref = Reference(ws_daily, min_col=2, min_row=1, max_row=day_count + 1)
        avg_ref  = Reference(ws_daily, min_col=3, min_row=1, max_row=day_count + 1)
        cats_ref = Reference(ws_daily, min_col=1, min_row=2, max_row=day_count + 1)

        daily_chart.add_data(peak_ref, titles_from_data=True)
        daily_chart.add_data(avg_ref, titles_from_data=True)
        daily_chart.set_categories(cats_ref)

        daily_chart.series[0].graphicalProperties.line.solidFill = ACCENT_RED
        daily_chart.series[0].graphicalProperties.line.width = 22000
        daily_chart.series[1].graphicalProperties.line.solidFill = BRAND_COLOR
        daily_chart.series[1].graphicalProperties.line.width = 22000

        chart_row = day_count + 3
        ws_daily.add_chart(daily_chart, f"A{chart_row}")

    # ════════════════════════════════════════════════════
    # Sheet 5: Player Leaderboard
    # ════════════════════════════════════════════════════
    ws_players = wb.create_sheet("Player Leaderboard")
    ws_players.sheet_properties.tabColor = "ED4245"

    p_headers = ['Rank', 'Player Name', 'Times Seen', 'Est. Play Time', 'Last Seen (UTC)']
    p_widths  = [8, 22, 14, 16, 24]
    _apply_header_row(ws_players, p_headers, p_widths)

    sorted_players = sorted(player_stats.items(), key=lambda x: x[1]['count'], reverse=True)
    for r, (name, info) in enumerate(sorted_players, 2):
        # Each data point ≈ 5 min interval
        est_minutes = info['count'] * 5
        if est_minutes >= 60:
            est_time = f"{est_minutes // 60}h {est_minutes % 60}m"
        else:
            est_time = f"{est_minutes}m"
        try:
            last_dt = datetime.fromisoformat(info['last_seen'].replace('Z', '+00:00'))
            last_display = last_dt.strftime('%Y-%m-%d %I:%M %p')
        except (ValueError, AttributeError):
            last_display = info['last_seen']
        _write_data_row(ws_players, r, [r - 1, name, info['count'], est_time, last_display], is_striped=(r % 2 == 0))

    # Leaderboard bar chart (top 20)
    if sorted_players:
        top_n = min(len(sorted_players), 20)
        lb_chart = BarChart()
        lb_chart.type = "bar"
        lb_chart.title = f"Top {top_n} Most Active Players"
        lb_chart.style = 10
        lb_chart.x_axis.title = "Times Seen"
        lb_chart.y_axis.title = "Player"
        lb_chart.width = 28
        lb_chart.height = max(12, top_n * 0.6)
        lb_chart.legend = None

        data_ref = Reference(ws_players, min_col=3, min_row=1, max_row=top_n + 1)
        cats_ref = Reference(ws_players, min_col=2, min_row=2, max_row=top_n + 1)
        lb_chart.add_data(data_ref, titles_from_data=True)
        lb_chart.set_categories(cats_ref)
        lb_chart.series[0].graphicalProperties.solidFill = BRAND_COLOR

        chart_row = len(sorted_players) + 3
        ws_players.add_chart(lb_chart, f"A{chart_row}")

    # ════════════════════════════════════════════════════
    # Sheet 6: Raw Data (moved to last)
    # ════════════════════════════════════════════════════
    ws_raw = wb.create_sheet("Raw Data")
    ws_raw.sheet_properties.tabColor = "99AAB5"

    raw_headers = ['Timestamp (UTC)', 'Server Online', 'Players Online', 'Players Max', 'Player Names']
    raw_widths  = [26, 14, 16, 14, 40]
    _apply_header_row(ws_raw, raw_headers, raw_widths)

    for r, entry in enumerate(filtered, 2):
        ts_str = entry.get('timestamp', '')
        try:
            ts_dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
            display_ts = ts_dt.strftime('%Y-%m-%d %I:%M:%S %p')
        except (ValueError, AttributeError):
            display_ts = ts_str
        online = entry.get('online', False)
        vals = [
            display_ts,
            'Online' if online else 'Offline',
            entry.get('players_online', 0),
            entry.get('players_max', 0),
            ', '.join(entry.get('player_names', [])),
        ]
        _write_data_row(ws_raw, r, vals, is_striped=(r % 2 == 0))
        # Color the status column
        status_cell = ws_raw.cell(row=r, column=2)
        status_cell.fill = online_fill if online else offline_fill

    # Write to response
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return Response(
        output.getvalue(),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f'attachment; filename=BoilerCraft_Analytics_{range_param}.xlsx'}
    )

@app.route('/settings')
@login_required
@page_permission_required('page.settings')
def settings():
    return render_template('settings.html')

@app.route('/logs')
@login_required
@page_permission_required('page.logs')
def logs():
    return render_template('logs.html')

@app.route('/members')
@login_required
@page_permission_required('page.members')
def members():
    return render_template('members.html')

@app.route('/varsity')
@login_required
@page_permission_required('page.varsity')
def varsity():
    return render_template('varsity.html')

@app.route('/analytics')
@login_required
@page_permission_required('page.analytics')
def analytics():
    return render_template('analytics.html')

@app.route('/reaction-roles')
@login_required
@page_permission_required('page.reaction_roles')
def reaction_roles_page():
    return render_template('reaction_roles.html')

@app.route('/vc-system')
@login_required
@page_permission_required('page.vc_system')
def vc_system():
    return render_template('vc_system.html')

@app.route('/ggleap')
@login_required
@page_permission_required('page.ggleap')
def ggleap():
    return render_template('ggleap.html')

@app.route('/rosters')
@login_required
@page_permission_required('page.rosters')
def rosters():
    return render_template('rosters.html')

# ============ API Routes ============

# Path for bot activity file
BOT_ACTIVITY_FILE = os.path.join(DATA_DIR, "bot_activity.json")

@app.route('/api/bot/activity', methods=['GET', 'POST'])
@api_auth_required
@api_perm_required('dashboard.bot_activity')
def api_bot_activity():
    """Get or set bot activity/status"""
    if request.method == 'GET':
        activity_data = load_json_file(BOT_ACTIVITY_FILE, {"activity": None, "status": "online"})
        return jsonify(activity_data)
    
    if request.method == 'POST':
        try:
            data = request.get_json() or {}
            activity_text = data.get('activity', '').strip()
            
            # Load current activity data
            activity_data = load_json_file(BOT_ACTIVITY_FILE, {"activity": None, "status": "online"})
            
            # Update activity
            if activity_text:
                activity_data['activity'] = activity_text
            else:
                activity_data['activity'] = None  # Reset to default
            
            activity_data['updated_at'] = datetime.now(timezone.utc).isoformat()
            activity_data['updated_by'] = session.get('discord_user', {}).get('username', 'Dashboard')
            
            # Save to file
            save_json_file(BOT_ACTIVITY_FILE, activity_data)
            
            # Queue notification to bot to update activity
            queue_discord_notification({
                'type': 'bot_activity',
                'activity': activity_text or None,
                'status': activity_data.get('status', 'online')
            })
            
            return jsonify({"success": True, "message": "Activity updated successfully"})
        except Exception as e:
            return jsonify({"success": False, "message": str(e)}), 500

# ============ Bot Control API ============

BOT_PID_FILE = os.path.join(DATA_DIR, "bot.pid")

@app.route('/api/bot/control/restart', methods=['POST'])
@api_auth_required
@api_perm_required('dashboard.bot_restart')
def api_bot_restart():
    """Restart the bot by queuing a notification for the bot to restart itself"""
    try:
        # Queue a restart notification for the bot to pick up
        queue_discord_notification({
            'type': 'bot_restart',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'requested_by': session.get('discord_user', {}).get('username', 'Dashboard')
        })
        
        log_activity(
            action="restart_bot",
            category="admin",
            details="Bot restart initiated from dashboard",
            success=True
        )
        
        return jsonify({"success": True, "message": "Bot restart initiated. The bot will restart shortly."})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/bot/control/stop', methods=['POST'])
@api_auth_required
@api_perm_required('dashboard.bot_stop')
def api_bot_stop():
    """Stop the bot by queuing a notification for the bot to stop itself"""
    try:
        # Queue a stop notification for the bot to pick up
        queue_discord_notification({
            'type': 'bot_stop',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'requested_by': session.get('discord_user', {}).get('username', 'Dashboard')
        })
        
        log_activity(
            action="stop_bot",
            category="admin",
            details="Bot stop initiated from dashboard",
            success=True
        )
        
        return jsonify({"success": True, "message": "Bot stop initiated. The bot will stop shortly."})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/logs')
@api_auth_required
def api_logs():
    """Get aggregated activity logs from all sources"""
    try:
        logs = []
        members = get_members_lookup()
        
        # Load moderation logs from user records
        user_records = load_user_records()
        for user_id, records in user_records.items():
            member = members.get(user_id, {})
            for record in records:
                logs.append({
                    "type": "moderation",
                    "action": record.get('type', 'Unknown'),
                    "user_id": user_id,
                    "username": member.get('username', member.get('name', '')),
                    "display_name": member.get('display_name', member.get('username', member.get('name', ''))),
                    "avatar_url": member.get('avatar') or member.get('avatar_url'),
                    "reason": record.get('reason', 'No reason'),
                    "moderator": record.get('moderator', 'Unknown'),
                    "timestamp": record.get('timestamp'),
                    "message": f"{record.get('type', 'Action')}: {record.get('reason', 'No reason')}"
                })
        
        # Load ticket logs
        ticket_log_path = os.path.join(DATA_DIR, "ticket_log.json")
        if os.path.exists(ticket_log_path):
            ticket_data = load_json_file(ticket_log_path, {"open": [], "closed": []})
            
            # Add open tickets
            for ticket in ticket_data.get('open', []):
                uid = str(ticket.get('user_id', ''))
                tmember = members.get(uid, {})
                logs.append({
                    "type": "ticket",
                    "action": "Opened",
                    "user_id": uid,
                    "username": tmember.get('username', tmember.get('name', '')),
                    "display_name": tmember.get('display_name', tmember.get('username', tmember.get('name', ''))),
                    "avatar_url": tmember.get('avatar') or tmember.get('avatar_url'),
                    "reason": f"Ticket #{ticket.get('id')} - {ticket.get('type', 'General')}",
                    "moderator": ticket.get('user'),
                    "timestamp": ticket.get('created_at'),
                    "message": f"Ticket opened: {ticket.get('explanation', '')[:100]}"
                })
            
            # Add closed tickets
            for ticket in ticket_data.get('closed', []):
                uid = str(ticket.get('user_id', ''))
                tmember = members.get(uid, {})
                logs.append({
                    "type": "ticket",
                    "action": "Closed",
                    "user_id": uid,
                    "username": tmember.get('username', tmember.get('name', '')),
                    "display_name": tmember.get('display_name', tmember.get('username', tmember.get('name', ''))),
                    "avatar_url": tmember.get('avatar') or tmember.get('avatar_url'),
                    "reason": ticket.get('close_reason', 'Closed'),
                    "moderator": ticket.get('closed_by', 'Unknown'),
                    "timestamp": ticket.get('closed_at'),
                    "message": f"Ticket #{ticket.get('id')} closed: {ticket.get('close_reason', 'No reason')}"
                })
        
        # Load varsity registration logs
        if os.path.exists(VARSITY_REG_DIR):
            for filename in os.listdir(VARSITY_REG_DIR):
                if filename.endswith('.json'):
                    filepath = os.path.join(VARSITY_REG_DIR, filename)
                    try:
                        with open(filepath, 'r', encoding='utf-8') as f:
                            regs = json.load(f)
                        for reg in regs:
                            if reg.get('type') == 'VarsityRegistration':
                                status = reg.get('status', 'Pending')
                                vid = filename.replace('.json', '').split('_')[0]
                                vmember = members.get(vid, {})
                                logs.append({
                                    "type": "varsity",
                                    "action": status,
                                    "user_id": vid,
                                    "username": vmember.get('username', vmember.get('name', '')),
                                    "display_name": vmember.get('display_name', vmember.get('username', vmember.get('name', ''))),
                                    "avatar_url": vmember.get('avatar') or vmember.get('avatar_url'),
                                    "reason": f"{reg.get('data', {}).get('Full Name', 'Unknown')} - {reg.get('data', {}).get('Primary Game Title', 'Unknown')}",
                                    "moderator": reg.get('moderated_by', {}).get('name', 'System') if isinstance(reg.get('moderated_by'), dict) else 'System',
                                    "timestamp": reg.get('moderated_at') or reg.get('timestamp'),
                                    "message": f"Registration {status}: {reg.get('data', {}).get('Full Name', 'Unknown')}"
                                })
                    except:
                        pass
        
        # Load bot event logs from activity_log.json
        activity_log_path = os.path.join(DATA_DIR, "activity_log.json")
        if os.path.exists(activity_log_path):
            activity_logs = load_json_file(activity_log_path, [])
            if isinstance(activity_logs, list):
                for log in activity_logs:
                    logs.append({
                        "type": "bot",
                        "action": log.get('event', 'Event'),
                        "user_id": log.get('user_id'),
                        "reason": log.get('details', ''),
                        "moderator": log.get('source', 'Bot'),
                        "timestamp": log.get('timestamp'),
                        "message": log.get('message', log.get('details', ''))
                    })
        
        # Sort by timestamp (newest first)
        logs.sort(key=lambda x: x.get('timestamp') or '', reverse=True)
        
        # Limit to most recent 500 entries
        return jsonify(logs[:500])
        
    except Exception as e:
        print(f"[API] Error loading logs: {e}")
        return jsonify([])

@app.route('/api/activity-log')
@api_auth_required
def api_activity_log():
    """Get unified activity log with filtering options"""
    try:
        # Get filter parameters
        category = request.args.get('category')  # moderation, auth, admin, settings
        action = request.args.get('action')  # kick, ban, warn, login, etc.
        source = request.args.get('source')  # website, discord, bot
        target_id = request.args.get('target_id')
        limit = int(request.args.get('limit', 100))
        offset = int(request.args.get('offset', 0))
        
        activity_log = load_json_file(ACTIVITY_LOG_FILE, [])
        
        # Apply filters
        if category:
            activity_log = [l for l in activity_log if l.get('category') == category]
        if action:
            activity_log = [l for l in activity_log if l.get('action') == action]
        if source:
            activity_log = [l for l in activity_log if l.get('source') == source]
        if target_id:
            activity_log = [l for l in activity_log if str(l.get('target_id')) == str(target_id)]
        
        total = len(activity_log)
        
        # Apply pagination
        activity_log = activity_log[offset:offset + limit]
        
        return jsonify({
            "logs": activity_log,
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": offset + limit < total
        })
        
    except Exception as e:
        print(f"[API] Error loading activity log: {e}")
        return jsonify({"logs": [], "total": 0, "error": str(e)})

@app.route('/api/activity-log/stats')
@api_auth_required
def api_activity_log_stats():
    """Get statistics from the activity log"""
    try:
        activity_log = load_json_file(ACTIVITY_LOG_FILE, [])
        
        # Count by category
        categories = {}
        actions = {}
        sources = {}
        moderators = {}
        
        for log in activity_log:
            cat = log.get('category', 'unknown')
            categories[cat] = categories.get(cat, 0) + 1
            
            act = log.get('action', 'unknown')
            actions[act] = actions.get(act, 0) + 1
            
            src = log.get('source', 'unknown')
            sources[src] = sources.get(src, 0) + 1
            
            mod = log.get('user', {}).get('name', 'Unknown')
            moderators[mod] = moderators.get(mod, 0) + 1
        
        return jsonify({
            "total_entries": len(activity_log),
            "by_category": categories,
            "by_action": actions,
            "by_source": sources,
            "by_moderator": moderators,
            "recent_count": len([l for l in activity_log if l.get('timestamp', '')[:10] == datetime.now().strftime('%Y-%m-%d')])
        })
        
    except Exception as e:
        print(f"[API] Error loading activity log stats: {e}")
        return jsonify({"error": str(e)})

@app.route('/api/stats')
@api_auth_required
def api_stats():
    stats = get_bot_stats()
    
    # Add additional stats
    user_records = load_user_records()
    guest_times = load_guest_times()
    
    stats["total_warnings"] = sum(len([r for r in records if r.get("type") == "Warning"]) 
                                   for records in user_records.values())
    stats["total_kicks"] = sum(len([r for r in records if r.get("type") == "Kick"]) 
                                for records in user_records.values())
    stats["total_bans"] = sum(len([r for r in records if r.get("type") == "Ban"]) 
                               for records in user_records.values())
    stats["active_guests"] = len(guest_times)
    stats["users_with_records"] = len(user_records)
    
    return jsonify(stats)

@app.route('/api/search')
@api_auth_required
def api_search():
    """Global search across members, users, and records"""
    try:
        query = request.args.get('q', '').strip().lower()
        
        if len(query) < 2:
            return jsonify({"results": []})
        
        results = []
        
        # Search in members cache
        try:
            members_data = load_json_file(MEMBERS_CACHE_FILE, [])
            # Handle both list and dict formats
            if isinstance(members_data, dict):
                members = members_data.get('members', [])
            else:
                members = members_data if isinstance(members_data, list) else []
            
            for member in members:
                if not isinstance(member, dict):
                    continue
                member_id = str(member.get('id', ''))
                username = str(member.get('username', '')).lower()
                display_name = str(member.get('display_name', '')).lower()
                
                if (query in member_id or 
                    query in username or 
                    query in display_name):
                    results.append({
                        "type": "member",
                        "id": member_id,
                        "username": member.get('username', ''),
                        "display_name": member.get('display_name', ''),
                        "avatar_url": member.get('avatar_url'),
                        "bot": member.get('bot', False),
                        "roles": member.get('roles', [])
                    })
                    if len(results) >= 10:
                        break
        except Exception as e:
            print(f"Error searching members: {e}")
        
        # Search in user records
        if len(results) < 10:
            try:
                user_records = load_user_records()
                for user_id, records in user_records.items():
                    if query in user_id.lower():
                        # Calculate record stats
                        warnings = len([r for r in records if r.get('type') == 'Warning'])
                        automod_flags = len([r for r in records if r.get('type') == 'AutoMod Flag'])
                        kicks = len([r for r in records if r.get('type') == 'Kick'])
                        bans = len([r for r in records if r.get('type') == 'Ban'])
                        results.append({
                            "type": "user_record",
                            "id": user_id,
                            "record_count": len(records),
                            "warnings": warnings,
                            "automod_flags": automod_flags,
                            "kicks": kicks,
                            "bans": bans,
                            "records": records[:3]  # Include first 3 records as preview
                        })
                        if len(results) >= 10:
                            break
            except Exception as e:
                print(f"Error searching user records: {e}")
        
        # Search in guest times
        if len(results) < 10:
            try:
                guest_times = load_guest_times()
                for user_id, guest_data in guest_times.items():
                    guest_name = str(guest_data.get('name', '')).lower() if isinstance(guest_data, dict) else ''
                    guest_username = str(guest_data.get('username', '')).lower() if isinstance(guest_data, dict) else ''
                    if query in user_id.lower() or query in guest_name or query in guest_username:
                        expires_at = guest_data.get('expires_at', '') if isinstance(guest_data, dict) else ''
                        results.append({
                            "type": "guest",
                            "id": user_id,
                            "name": guest_data.get('name', '') if isinstance(guest_data, dict) else '',
                            "username": guest_data.get('username', '') if isinstance(guest_data, dict) else '',
                            "expires_at": expires_at,
                            "data": guest_data
                        })
                        if len(results) >= 10:
                            break
            except Exception as e:
                print(f"Error searching guests: {e}")
        
        # Search in varsity registrations
        if len(results) < 10:
            try:
                if os.path.exists(VARSITY_REG_DIR):
                    for fname in os.listdir(VARSITY_REG_DIR):
                        if fname.endswith("_varsity.json"):
                            user_id = fname.replace("_varsity.json", "")
                            data = load_json_file(os.path.join(VARSITY_REG_DIR, fname), [])
                            if data:
                                latest = data[-1] if isinstance(data, list) else data
                                reg_data = latest.get('data', {}) if isinstance(latest, dict) else {}
                                full_name = reg_data.get('Full Name', '') if isinstance(reg_data, dict) else ''
                                game = reg_data.get('Primary Game Title', '') if isinstance(reg_data, dict) else ''
                                player_type = reg_data.get('player_type', 'varsity') if isinstance(reg_data, dict) else 'varsity'
                                status = latest.get('status', 'Pending') if isinstance(latest, dict) else 'Pending'
                                
                                # Search in user_id, full_name, and game
                                if (query in user_id.lower() or 
                                    query in full_name.lower() or 
                                    query in game.lower()):
                                    results.append({
                                        "type": "varsity",
                                        "id": user_id,
                                        "full_name": full_name,
                                        "status": status,
                                        "game": game,
                                        "player_type": player_type
                                    })
                                    if len(results) >= 10:
                                        break
            except Exception as e:
                print(f"Error searching varsity registrations: {e}")
        
        return jsonify({"results": results})
    except Exception as e:
        print(f"Search API error: {e}")
        return jsonify({"results": [], "error": str(e)})

@app.route('/api/analytics')
@api_auth_required
def api_analytics():
    """Get analytics data for the analytics dashboard"""
    # User records stats
    user_records = load_user_records()
    total_warnings = sum(len([r for r in records if r.get("type") == "Warning"]) 
                         for records in user_records.values())
    total_kicks = sum(len([r for r in records if r.get("type") == "Kick"]) 
                      for records in user_records.values())
    total_bans = sum(len([r for r in records if r.get("type") == "Ban"]) 
                     for records in user_records.values())
    
    # Guest stats
    guest_times = load_guest_times()
    
    # Members stats from cache
    members = load_json_file(MEMBERS_CACHE_FILE, [])
    
    # Varsity stats
    varsity_stats = {"pending": 0, "approved": 0, "denied": 0}
    if os.path.exists(VARSITY_REG_DIR):
        for fname in os.listdir(VARSITY_REG_DIR):
            if fname.endswith("_varsity.json"):
                try:
                    data = load_json_file(os.path.join(VARSITY_REG_DIR, fname), [])
                    if isinstance(data, list):
                        for reg in data:
                            status = reg.get("status", "Pending").lower()
                            if status == "pending":
                                varsity_stats["pending"] += 1
                            elif status == "approved":
                                varsity_stats["approved"] += 1
                            elif status == "denied":
                                varsity_stats["denied"] += 1
                except:
                    pass
    
    # Get roles data from cache
    roles_data = load_json_file(ROLES_CACHE_FILE, [])
    top_roles = sorted(roles_data, key=lambda x: x.get('member_count', 0), reverse=True)[:10]
    top_roles_formatted = [{"name": r.get("name", "Unknown"), "count": r.get("member_count", 0)} for r in top_roles]
    
    return jsonify({
        "members": {
            "total": len(members),
            "humans": len([m for m in members if not m.get('bot', False)]),
            "bots": len([m for m in members if m.get('bot', False)]),
            "guests": len(guest_times)
        },
        "moderation": {
            "total_warnings": total_warnings,
            "total_kicks": total_kicks,
            "total_bans": total_bans,
            "users_with_records": len(user_records)
        },
        "varsity": varsity_stats,
        "roles": {
            "top_roles": top_roles_formatted
        }
    })

@app.route('/api/commands')
@api_auth_required
def api_commands():
    """Get list of available bot commands for the dashboard"""
    commands = [
        # General Commands
        {"name": "/about", "description": "Learn about LionByteGG and its features", "category": "General", "admin": False},
        {"name": "/help", "description": "Get help with bot commands and features", "category": "General", "admin": False},
        {"name": "/userinfo", "description": "View information about a user", "category": "General", "admin": False},
        {"name": "/ping", "description": "Check the bot's latency", "category": "General", "admin": False},
        
        # Moderation Commands
        {"name": "/warn", "description": "Warn a member for rule violations", "category": "Moderation", "admin": True},
        {"name": "/kick", "description": "Kick a member from the server", "category": "Moderation", "admin": True},
        {"name": "/ban", "description": "Ban a member from the server", "category": "Moderation", "admin": True},
        {"name": "/unban", "description": "Unban a previously banned member", "category": "Moderation", "admin": True},
        {"name": "/timeout", "description": "Temporarily timeout a member", "category": "Moderation", "admin": True},
        {"name": "/record", "description": "View a member's moderation history", "category": "Moderation", "admin": True},
        {"name": "/clear", "description": "Clear messages from a channel", "category": "Moderation", "admin": True},
        
        # Admin Commands
        {"name": "/setup_ticket_panel", "description": "Create the ticket support panel", "category": "Admin", "admin": True},
        {"name": "/setup_reaction_roles", "description": "Create reaction role panels", "category": "Admin", "admin": True},
        {"name": "/setup_vc_generator", "description": "Set up voice channel generators", "category": "Admin", "admin": True},
        {"name": "/migrate_to_student", "description": "Migrate a guest to student role", "category": "Admin", "admin": True},
        {"name": "/send_varsity_registration", "description": "Send registration to a user", "category": "Admin", "admin": True},
        {"name": "/set_guest_time", "description": "Set guest pass expiration time", "category": "Admin", "admin": True},
        {"name": "/restart_service", "description": "Restart the bot service", "category": "Admin", "admin": True},
        {"name": "/sync", "description": "Sync slash commands with Discord", "category": "Admin", "admin": True},
        
        # Voice Channel Commands
        {"name": "/vc_name", "description": "Rename your voice channel", "category": "General", "admin": False},
        {"name": "/vc_limit", "description": "Set user limit for your voice channel", "category": "General", "admin": False},
        {"name": "/vc_lock", "description": "Lock your voice channel", "category": "General", "admin": False},
        {"name": "/vc_unlock", "description": "Unlock your voice channel", "category": "General", "admin": False},
        {"name": "/vc_permit", "description": "Allow a user into your locked channel", "category": "General", "admin": False},
        {"name": "/vc_reject", "description": "Remove a user's access to your channel", "category": "General", "admin": False},
        {"name": "/vc_claim", "description": "Claim ownership of an abandoned channel", "category": "General", "admin": False},
        {"name": "/vc_transfer", "description": "Transfer channel ownership to another user", "category": "General", "admin": False},
        
        # Ticket Commands
        {"name": "/ticket_add", "description": "Add a user to a ticket", "category": "Moderation", "admin": True},
        {"name": "/ticket_remove", "description": "Remove a user from a ticket", "category": "Moderation", "admin": True},
        {"name": "/ticket_close", "description": "Close a ticket channel", "category": "Moderation", "admin": True},
        
        # GGLeap Commands
        {"name": "/ggleap_status", "description": "Check PC availability in the arena", "category": "General", "admin": False},
        {"name": "/ggleap_games", "description": "View available games on arena PCs", "category": "General", "admin": False},
    ]
    
    return jsonify(commands)

@app.route('/api/flagged-words', methods=['GET', 'POST'])
@api_auth_required
def api_flagged_words():
    if request.method == 'GET':
        return jsonify(load_flagged_words())
    
    if request.method == 'POST':
        if not has_perm('moderation.flagged_words'):
            return jsonify({"error": "Permission denied"}), 403
        data = request.json
        words = load_flagged_words()
        
        action = data.get('action')
        category = data.get('category')
        word = data.get('word')
        
        if action == 'add' and category in words and word:
            if word not in words[category]:
                words[category].append(word.lower())
                save_flagged_words(words)
                return jsonify({"success": True, "message": f"Added '{word}' to {category}"})
        
        elif action == 'remove' and category in words and word:
            if word.lower() in words[category]:
                words[category].remove(word.lower())
                save_flagged_words(words)
                return jsonify({"success": True, "message": f"Removed '{word}' from {category}"})
        
        return jsonify({"success": False, "message": "Invalid action or word"})

@app.route('/api/user-records')
@api_auth_required
def api_user_records():
    records = load_user_records()
    members = get_members_lookup()
    
    # Format records for display with enriched member info
    formatted = []
    for user_id, user_records in records.items():
        member = members.get(user_id, {})
        formatted.append({
            "user_id": user_id,
            "username": member.get('username', member.get('name', '')),
            "display_name": member.get('display_name', member.get('username', member.get('name', ''))),
            "avatar_url": member.get('avatar') or member.get('avatar_url'),
            "records": user_records,
            "warning_count": len([r for r in user_records if r.get("type") == "Warning"]),
            "automod_count": len([r for r in user_records if r.get("type") == "AutoMod Flag"]),
            "kick_count": len([r for r in user_records if r.get("type") == "Kick"]),
            "ban_count": len([r for r in user_records if r.get("type") == "Ban"])
        })
    
    return jsonify(formatted)

@app.route('/api/user-records/<user_id>')
@api_auth_required
def api_user_record(user_id):
    filepath = os.path.join(USER_RECORDS_DIR, f"{user_id}_record.json")
    records = load_json_file(filepath, [])
    return jsonify({"user_id": user_id, "records": records})

@app.route('/api/user-records/<user_id>/clear', methods=['POST'])
@api_auth_required
@api_perm_required('moderation.user_records')
def api_clear_user_record(user_id):
    filepath = os.path.join(USER_RECORDS_DIR, f"{user_id}_record.json")
    if os.path.exists(filepath):
        os.remove(filepath)
        return jsonify({"success": True, "message": f"Cleared records for user {user_id}"})
    return jsonify({"success": False, "message": "User record not found"})

@app.route('/api/send-dm', methods=['POST'])
@api_auth_required
@api_perm_required('members.send_dm')
def api_send_dm():
    """Send a direct message to a user via the bot"""
    data = request.get_json()
    user_id = data.get('user_id')
    message = data.get('message', '')
    
    if not user_id:
        return jsonify({"success": False, "message": "User ID is required"})
    
    if not message.strip():
        return jsonify({"success": False, "message": "Message cannot be empty"})
    
    moderator = get_moderator_name()
    
    # Queue notification to bot to DM the user
    queue_discord_notification({
        "type": "send_dm",
        "user_id": str(user_id),
        "message": message,
        "moderator": moderator
    })
    
    # Log activity
    members = load_json_file(MEMBERS_CACHE_FILE, [])
    member = next((m for m in members if str(m.get('id')) == str(user_id)), None)
    target_name = member.get('display_name') or member.get('name') if member else f"User {user_id}"
    
    log_activity(
        action="send_dm",
        category="communication",
        details=f"Sent DM: {message[:50]}{'...' if len(message) > 50 else ''}",
        target_id=user_id,
        target_name=target_name,
        success=True
    )
    
    return jsonify({"success": True, "message": f"DM queued for delivery to {target_name}"})

@app.route('/api/warn-user', methods=['POST'])
@api_auth_required
@api_perm_required('members.warn')
def api_warn_user():
    """Send a warning to a user - bot will DM them"""
    data = request.get_json()
    user_id = data.get('user_id')
    reason = data.get('reason', 'No reason provided')
    moderator = data.get('moderator', 'Dashboard')
    
    if not user_id:
        return jsonify({"success": False, "message": "User ID is required"})
    
    # Add record to user's file
    filepath = os.path.join(USER_RECORDS_DIR, f"{user_id}_record.json")
    records = load_json_file(filepath, [])
    
    record = {
        "user_id": str(user_id),
        "type": "Warning",
        "reason": reason,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "moderator": moderator
    }
    records.append(record)
    
    safe_json_dump(records, filepath, indent=2)
    
    # Queue notification to bot to DM the user
    queue_discord_notification({
        "type": "warn_user",
        "user_id": str(user_id),
        "reason": reason,
        "moderator": moderator
    })
    
    return jsonify({"success": True, "message": f"Warning sent to user {user_id}"})

@app.route('/api/user-records/<user_id>/remove-warning', methods=['POST'])
@api_auth_required
@api_perm_required('moderation.user_records')
def api_remove_warning(user_id):
    """Remove a specific warning from a user's record"""
    data = request.get_json()
    warning_index = data.get('index')
    
    if warning_index is None:
        return jsonify({"success": False, "message": "Warning index is required"})
    
    filepath = os.path.join(USER_RECORDS_DIR, f"{user_id}_record.json")
    records = load_json_file(filepath, [])
    
    if not records:
        return jsonify({"success": False, "message": "No records found for this user"})
    
    # Filter to only warnings
    warnings = [(i, r) for i, r in enumerate(records) if r.get('type') == 'Warning']
    
    if warning_index < 0 or warning_index >= len(warnings):
        return jsonify({"success": False, "message": "Invalid warning index"})
    
    # Get the actual index in the records list
    actual_index = warnings[warning_index][0]
    removed = records.pop(actual_index)
    
    # Save updated records
    safe_json_dump(records, filepath, indent=2)
    
    return jsonify({
        "success": True, 
        "message": f"Removed warning: {removed.get('reason', 'No reason')}"
    })

@app.route('/api/user/<user_id>/full-profile')
@api_auth_required
def api_user_full_profile(user_id):
    """Get comprehensive user profile including member info, records, guest status, and varsity"""
    try:
        profile = {
            "user_id": user_id,
            "member": None,
            "records": [],
            "guest_time": None,
            "varsity_registrations": [],
            "stats": {
                "warnings": 0,
                "automod_flags": 0,
                "kicks": 0,
                "bans": 0,
                "timeouts": 0
            }
        }
        
        # Get member info from cache
        members_data = load_json_file(MEMBERS_CACHE_FILE, [])
        if isinstance(members_data, dict):
            members = members_data.get('members', [])
        else:
            members = members_data if isinstance(members_data, list) else []
        
        member = next((m for m in members if str(m.get('id')) == str(user_id)), None)
        if member:
            # Get avatar URL - check both 'avatar' and 'avatar_url' for compatibility
            avatar_url = member.get('avatar') or member.get('avatar_url')
            
            profile["member"] = {
                "id": str(member.get('id', '')),
                "username": member.get('username', member.get('name', '')),
                "display_name": member.get('display_name', member.get('username', member.get('name', ''))),
                "avatar": avatar_url,
                "avatar_url": avatar_url,  # Duplicate for frontend compatibility
                "bot": member.get('bot', False),
                "roles": member.get('roles', []),
                "joined_at": member.get('joined_at'),
                "created_at": member.get('created_at')
            }
        
        # Get user records and calculate stats
        record_filepath = os.path.join(USER_RECORDS_DIR, f"{user_id}_record.json")
        if os.path.exists(record_filepath):
            records = load_json_file(record_filepath, [])
            profile["records"] = records
            
            # Calculate stats from records
            for record in records:
                record_type = record.get('type', '').lower()
                if record_type == 'warning':
                    profile["stats"]["warnings"] += 1
                elif record_type == 'automod flag':
                    profile["stats"]["automod_flags"] += 1
                elif record_type == 'kick':
                    profile["stats"]["kicks"] += 1
                elif record_type == 'ban':
                    profile["stats"]["bans"] += 1
                elif record_type == 'timeout':
                    profile["stats"]["timeouts"] += 1
        
        # Get guest info (frontend expects 'guest_time')
        guest_filepath = os.path.join(GUEST_TIMES_DIR, f"{user_id}_guest_time.json")
        if os.path.exists(guest_filepath):
            guest_data = load_json_file(guest_filepath, {})
            if guest_data:
                try:
                    now = datetime.now(timezone.utc)
                    expires_at = datetime.fromisoformat(guest_data.get("expires_at", "").replace("Z", "+00:00"))
                    remaining = expires_at - now
                    profile["guest_time"] = {
                        "username": guest_data.get("username", "Unknown"),
                        "joined_at": guest_data.get("joined_at"),
                        "expires_at": guest_data.get("expires_at"),
                        "days_remaining": max(0, remaining.days),
                        "expired": remaining.total_seconds() < 0
                    }
                except:
                    profile["guest_time"] = guest_data
        
        # Get varsity registrations (frontend expects array 'varsity_registrations')
        varsity_filepath = os.path.join(VARSITY_REG_DIR, f"{user_id}_varsity.json")
        if os.path.exists(varsity_filepath):
            varsity_data = load_json_file(varsity_filepath, [])
            if varsity_data:
                if isinstance(varsity_data, list):
                    for reg in varsity_data:
                        reg_data = reg.get('data', {}) if isinstance(reg, dict) else {}
                        profile["varsity_registrations"].append({
                            "full_name": reg_data.get('Full Name', ''),
                            "game": reg_data.get('Primary Game Title', ''),
                            "player_type": reg_data.get('player_type', 'varsity'),
                            "ign": reg_data.get('IGN', ''),
                            "rank": reg_data.get('Current Rank in Game', ''),
                            "status": reg.get('status', 'Pending') if isinstance(reg, dict) else 'Pending',
                            "timestamp": reg.get('timestamp') if isinstance(reg, dict) else None
                        })
                else:
                    reg_data = varsity_data.get('data', {}) if isinstance(varsity_data, dict) else {}
                    profile["varsity_registrations"].append({
                        "full_name": reg_data.get('Full Name', ''),
                        "game": reg_data.get('Primary Game Title', ''),
                        "player_type": reg_data.get('player_type', 'varsity'),
                        "ign": reg_data.get('IGN', ''),
                        "rank": reg_data.get('Current Rank in Game', ''),
                        "status": varsity_data.get('status', 'Pending') if isinstance(varsity_data, dict) else 'Pending',
                        "timestamp": varsity_data.get('timestamp') if isinstance(varsity_data, dict) else None
                    })
        
        return jsonify(profile)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/user/<user_id>/add-note', methods=['POST'])
@api_auth_required
@api_perm_required('members.add_notes')
def api_add_user_note(user_id):
    """Add a note/record to a user's moderation history"""
    try:
        data = request.json or {}
        note_type = data.get('type', 'Note')
        note_content = data.get('note', '')
        
        if not note_content:
            return jsonify({"success": False, "message": "Note content is required"})
        
        # Load existing records
        filepath = os.path.join(USER_RECORDS_DIR, f"{user_id}_record.json")
        records = load_json_file(filepath, [])
        
        # Add new record
        new_record = {
            "type": note_type,
            "reason": note_content,
            "moderator": "Dashboard Admin",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        records.append(new_record)
        
        # Save records
        os.makedirs(USER_RECORDS_DIR, exist_ok=True)
        save_json_file(filepath, records)
        
        return jsonify({"success": True, "message": "Note added successfully"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/guests')
@api_auth_required
def api_guests():
    guests = load_guest_times()
    
    formatted = []
    now = datetime.now(timezone.utc)
    
    for user_id, data in guests.items():
        try:
            expires_at = datetime.fromisoformat(data.get("expires_at", "").replace("Z", "+00:00"))
            remaining = expires_at - now
            
            formatted.append({
                "user_id": user_id,
                "username": data.get("username", "Unknown"),
                "joined_at": data.get("joined_at"),
                "expires_at": data.get("expires_at"),
                "days_remaining": max(0, remaining.days),
                "expired": remaining.total_seconds() < 0
            })
        except:
            formatted.append({
                "user_id": user_id,
                "username": data.get("username", "Unknown"),
                "joined_at": data.get("joined_at"),
                "expires_at": data.get("expires_at"),
                "days_remaining": 0,
                "expired": True
            })
    
    return jsonify(formatted)

@app.route('/api/guests/<user_id>/cancel', methods=['POST'])
@api_auth_required
@api_perm_required('users.remove_guest')
def api_cancel_guest(user_id):
    filepath = os.path.join(GUEST_TIMES_DIR, f"{user_id}_guest_time.json")
    if os.path.exists(filepath):
        os.remove(filepath)
        return jsonify({"success": True, "message": f"Cancelled guest timer for user {user_id}"})
    return jsonify({"success": False, "message": "Guest timer not found"})

@app.route('/api/guests/<user_id>/reset', methods=['POST'])
@api_auth_required
@api_perm_required('users.reset_timer')
def api_reset_guest(user_id):
    filepath = os.path.join(GUEST_TIMES_DIR, f"{user_id}_guest_time.json")
    if os.path.exists(filepath):
        data = load_json_file(filepath)
        expires_at = datetime.now(timezone.utc) + timedelta(days=30)
        data["expires_at"] = expires_at.isoformat()
        save_json_file(filepath, data)
        return jsonify({"success": True, "message": f"Reset guest timer for user {user_id}"})
    return jsonify({"success": False, "message": "Guest timer not found"})

@app.route('/api/arena-hours', methods=['GET', 'POST'])
@api_auth_required
def api_arena_hours():
    hours_file = os.path.join(DATA_DIR, "arena_hours.json")
    
    default_hours = {
        "monday": {"open": "10:00", "close": "17:00", "closed": False},
        "tuesday": {"open": "10:00", "close": "17:00", "closed": False},
        "wednesday": {"open": "10:00", "close": "17:00", "closed": False},
        "thursday": {"open": "10:00", "close": "17:00", "closed": False},
        "friday": {"open": "10:00", "close": "17:00", "closed": False},
        "saturday": {"open": "10:00", "close": "17:00", "closed": True},
        "sunday": {"open": "10:00", "close": "14:00", "closed": False}
    }
    
    if request.method == 'GET':
        return jsonify(load_json_file(hours_file, default_hours))
    
    if request.method == 'POST':
        if not has_perm('settings.arena_hours'):
            return jsonify({"error": "Permission denied"}), 403
        data = request.json
        save_json_file(hours_file, data)
        return jsonify({"success": True, "message": "Arena hours updated"})

# ============ Team Role Mapping API ============

TEAM_ROLE_SETTINGS_FILE = os.path.join(DATA_DIR, "team_role_settings.json")

@app.route('/api/settings/team-roles', methods=['GET', 'POST'])
@api_auth_required
def api_team_role_settings():
    """Get or set team role mapping configuration"""
    
    if request.method == 'GET':
        settings = load_json_file(TEAM_ROLE_SETTINGS_FILE, {
            "mapping": {},
            "varsity_role_id": None,
            "captain_role_id": None,
            "jv_role_id": None
        })
        return jsonify(settings)
    
    if request.method == 'POST':
        if not has_perm('settings.team_roles'):
            return jsonify({"error": "Permission denied"}), 403
        data = request.json
        
        settings = {
            "mapping": data.get("mapping", {}),
            "varsity_role_id": data.get("varsity_role_id"),
            "captain_role_id": data.get("captain_role_id"),
            "jv_role_id": data.get("jv_role_id"),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        save_json_file(TEAM_ROLE_SETTINGS_FILE, settings)
        
        # Also queue an update for the bot to reload settings
        queue_file = os.path.join(DATA_DIR, "discord_notification_queue.json")
        safe_queue_append(queue_file, {
            "type": "reload_team_role_settings",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        
        return jsonify({"success": True, "message": "Team role settings saved"})

# ============ Esports Games Management API ============

ESPORTS_GAMES_FILE = os.path.join(DATA_DIR, "esports_games.json")

# Default games list if file doesn't exist
DEFAULT_ESPORTS_GAMES = {
    "games": [
        {"name": "Valorant", "icon": "fa-crosshairs", "color": "#ff4655"},
        {"name": "Overwatch 2", "icon": "fa-shield-alt", "color": "#fa9c1e"},
        {"name": "League of Legends", "icon": "fa-chess-queen", "color": "#c89b3c"},
        {"name": "Rocket League", "icon": "fa-car", "color": "#0088ff"},
        {"name": "Super Smash Bros", "icon": "fa-fist-raised", "color": "#e60012"},
        {"name": "Counter-Strike 2", "icon": "fa-bomb", "color": "#de9b35"},
        {"name": "Apex Legends", "icon": "fa-skull", "color": "#da292a"},
        {"name": "Call of Duty", "icon": "fa-helicopter", "color": "#1e7b1e"},
        {"name": "Fortnite", "icon": "fa-hammer", "color": "#9d4dbb"},
        {"name": "Rainbow Six Siege", "icon": "fa-shield-virus", "color": "#ffffff"},
        {"name": "Marvel Rivals", "icon": "fa-mask", "color": "#ed1d24"},
        {"name": "iRacing", "icon": "fa-flag-checkered", "color": "#005aff"}
    ]
}

@app.route('/api/settings/games', methods=['GET', 'POST'])
@api_auth_required
def api_esports_games():
    """Manage esports game titles for team creation"""
    
    if request.method == 'GET':
        data = load_json_file(ESPORTS_GAMES_FILE, DEFAULT_ESPORTS_GAMES)
        # Return just game names for backward compatibility
        game_names = [g["name"] if isinstance(g, dict) else g for g in data.get("games", [])]
        return jsonify({
            "games": game_names,
            "games_data": data.get("games", [])  # Full data with icons/colors
        })
    
    if request.method == 'POST':
        if not has_perm('settings.games'):
            return jsonify({"error": "Permission denied"}), 403
        action = request.json.get("action")
        game_name = request.json.get("game")
        
        if not game_name:
            return jsonify({"success": False, "error": "Game name is required"}), 400
        
        data = load_json_file(ESPORTS_GAMES_FILE, DEFAULT_ESPORTS_GAMES)
        games = data.get("games", [])
        
        # Normalize to list of dicts
        games = [g if isinstance(g, dict) else {"name": g, "icon": "fa-gamepad", "color": "#5865F2"} for g in games]
        game_names = [g["name"].lower() for g in games]
        
        if action == "add":
            if game_name.lower() in game_names:
                return jsonify({"success": False, "error": "Game already exists"}), 400
            
            game_icon = request.json.get("icon", "fa-gamepad")
            game_color = request.json.get("color", "#5865F2")
            
            games.append({
                "name": game_name,
                "icon": game_icon,
                "color": game_color,
                "added_at": datetime.now(timezone.utc).isoformat()
            })
            
            data["games"] = games
            data["updated_at"] = datetime.now(timezone.utc).isoformat()
            save_json_file(ESPORTS_GAMES_FILE, data)
            
            return jsonify({"success": True, "message": f"Added {game_name}"})
        
        elif action == "remove":
            if game_name.lower() not in game_names:
                return jsonify({"success": False, "error": "Game not found"}), 404
            
            games = [g for g in games if g["name"].lower() != game_name.lower()]
            
            data["games"] = games
            data["updated_at"] = datetime.now(timezone.utc).isoformat()
            save_json_file(ESPORTS_GAMES_FILE, data)
            
            return jsonify({"success": True, "message": f"Removed {game_name}"})
        
        else:
            return jsonify({"success": False, "error": "Invalid action. Use 'add' or 'remove'"}), 400

# ============ GGLEAP API ENDPOINTS ============

# Import GGLeap utilities at the top of the API section
import sys
import os
import re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# GGLeap API configuration
GGLEAP_AUTH_TOKEN = "DnRx4l0umS3vaw3bR/22yjvTFYtMC6QxTkvvI77g3Lrn3nX1BFwo4if37zZHJj83I4to+ruOnilshG3Mzhza3m+sonBs4YUx9v0EiC6738gAa0QAuwH+14Jso1197He/"
GGLEAP_GAMES_AUTH_TOKEN = "P1Q+Z3jtqCb4Eiw6RGzhoavp50zzOAwc3gsiPZiKhcOaDE75A1mVCPadifqukz1er5pchN+I1WwkIcDG+XvKCubHKmUTESKqGLNNcAge7xUF9y4XQBkP8i3H7028mrHd"
GGLEAP_BASE_URL = "https://api.ggleap.com/beta"
ggleap_jwt_token = None
ggleap_games_jwt_token = None

def get_ggleap_jwt():
    """Refresh JWT token for GGLeap status API"""
    global ggleap_jwt_token
    try:
        import requests
        r = requests.post(
            f"{GGLEAP_BASE_URL}/authorization/public-api/auth",
            headers={"Content-Type": "application/json-patch+json"},
            json={"AuthToken": GGLEAP_AUTH_TOKEN},
            timeout=10
        )
        r.raise_for_status()
        ggleap_jwt_token = r.json().get("Jwt")
        return ggleap_jwt_token
    except Exception as e:
        print(f"[GGLEAP] JWT error: {e}")
        return None

def get_ggleap_games_jwt():
    """Refresh JWT token for GGLeap games API"""
    global ggleap_games_jwt_token
    try:
        import requests
        r = requests.post(
            f"{GGLEAP_BASE_URL}/authorization/public-api/auth",
            headers={"Content-Type": "application/json-patch+json"},
            json={"AuthToken": GGLEAP_GAMES_AUTH_TOKEN},
            timeout=10
        )
        r.raise_for_status()
        ggleap_games_jwt_token = r.json().get("Jwt")
        return ggleap_games_jwt_token
    except Exception as e:
        print(f"[GGLEAP_GAMES] JWT error: {e}")
        return None

def format_pc_name(name):
    """Format PC name like 'Island1S2' to 'Island 1 S2' or 'Stage1' to 'Stage S1'"""
    m = re.match(r"Island(\d+)S(\d+)", name, re.IGNORECASE)
    if m:
        return f"Island {m.group(1)} S{m.group(2)}"
    m = re.match(r"Stage(\d+)", name, re.IGNORECASE)
    if m:
        return f"Stage S{m.group(1)}"
    return name

# ============ Arena PC Usage Tracking ============
ARENA_USAGE_FILE = os.path.join(DATA_DIR, "arena_usage_log.json")
_arena_previous_states = {}  # Track previous PC states for session detection

def _load_arena_usage():
    return load_json_file(ARENA_USAGE_FILE, {"sessions": [], "active_sessions": {}, "event_log": []})

def _save_arena_usage(data):
    save_json_file(ARENA_USAGE_FILE, data)

def _track_pc_sessions(current_pcs):
    """Compare current PC states with previous states to detect session start/end and log all state changes."""
    global _arena_previous_states
    now = datetime.now(timezone.utc).isoformat()
    usage = _load_arena_usage()
    # Ensure event_log list exists for older data files
    if "event_log" not in usage:
        usage["event_log"] = []
    changed = False

    for pc in current_pcs:
        name = pc["name"]
        new_status = pc["status"]
        raw_state = pc.get("state", "Unknown")
        old_status = _arena_previous_states.get(name, {}).get("status") if isinstance(_arena_previous_states.get(name), dict) else _arena_previous_states.get(name)
        old_raw = _arena_previous_states.get(name, {}).get("raw_state", "Unknown") if isinstance(_arena_previous_states.get(name), dict) else None

        # Extract user info from PC data
        user_uuid = pc.get("user_uuid")
        has_guest = pc.get("has_guest", False)
        open_windows = pc.get("open_windows", [])

        # Log every state change as an event
        if old_status is not None and (old_status != new_status or old_raw != raw_state):
            event_entry = {
                "pc_name": name,
                "timestamp": now,
                "event": _classify_event(old_status, new_status, old_raw, raw_state),
                "from_status": old_status,
                "to_status": new_status,
                "from_state": old_raw or "Unknown",
                "to_state": raw_state,
            }
            if user_uuid:
                event_entry["user_uuid"] = user_uuid
            if has_guest:
                event_entry["is_guest"] = True
            usage["event_log"].append(event_entry)
            changed = True

        if old_status != "in-use" and new_status == "in-use":
            # Session started
            active_data = {"pc_name": name, "start_time": now, "raw_state": raw_state}
            if user_uuid:
                active_data["user_uuid"] = user_uuid
            if has_guest:
                active_data["is_guest"] = True
            if open_windows:
                active_data["open_windows"] = open_windows
            usage["active_sessions"][name] = active_data
            changed = True
        elif old_status == "in-use" and new_status != "in-use":
            # Session ended
            active = usage["active_sessions"].pop(name, None)
            if active:
                start = datetime.fromisoformat(active["start_time"])
                end = datetime.fromisoformat(now)
                duration = round((end - start).total_seconds() / 60, 1)
                if duration >= 1:  # Only log sessions >= 1 minute
                    session_entry = {
                        "pc_name": name,
                        "start_time": active["start_time"],
                        "end_time": now,
                        "duration_minutes": duration,
                        "end_reason": raw_state,
                    }
                    if active.get("user_uuid"):
                        session_entry["user_uuid"] = active["user_uuid"]
                    if active.get("is_guest"):
                        session_entry["is_guest"] = True
                    if active.get("open_windows"):
                        session_entry["open_windows"] = active["open_windows"]
                    usage["sessions"].append(session_entry)
                changed = True
        elif new_status == "in-use" and name in usage.get("active_sessions", {}):
            # Session still active — update open windows and user if changed
            active = usage["active_sessions"][name]
            updated = False
            if user_uuid and active.get("user_uuid") != user_uuid:
                active["user_uuid"] = user_uuid
                updated = True
            if open_windows and active.get("open_windows") != open_windows:
                active["open_windows"] = open_windows
                updated = True
            if updated:
                changed = True

        _arena_previous_states[name] = {"status": new_status, "raw_state": raw_state}

    # Prune sessions older than 90 days to keep file manageable
    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    before = len(usage["sessions"])
    usage["sessions"] = [s for s in usage["sessions"] if s["end_time"] >= cutoff]
    if len(usage["sessions"]) != before:
        changed = True

    # Prune event log older than 90 days
    before_events = len(usage["event_log"])
    usage["event_log"] = [e for e in usage["event_log"] if e["timestamp"] >= cutoff]
    if len(usage["event_log"]) != before_events:
        changed = True

    if changed:
        _save_arena_usage(usage)

def _classify_event(old_status, new_status, old_raw, new_raw):
    """Classify a state change into a human-readable event type."""
    if new_raw == "Off":
        return "shutdown"
    if new_raw in ("StartingUp", "Restarting"):
        return "boot"
    if new_raw == "UserLoggedIn":
        return "user_login"
    if new_raw == "UserLoggingIn":
        return "user_logging_in"
    if old_raw == "UserLoggedIn" and new_raw in ("ReadyForUser", "IdleShuttingDown"):
        return "user_logout"
    if new_raw == "ReadyForUser":
        return "ready"
    if new_raw == "AdminMode":
        return "admin_mode"
    if new_raw == "ShuttingDown" or new_raw == "IdleShuttingDown":
        return "shutting_down"
    return "state_change"

# ── Server-side cache for GGLeap status (avoids burning API rate limits) ──
_ggleap_status_cache = {"data": None, "fetched_at": 0}
_GGLEAP_CACHE_TTL = 15  # seconds — one real API call per 15s max

def _fetch_ggleap_status():
    """Fetch live PC status from GGLeap API, with 15-second server-side cache.
    Rate budget: Basic plan = 20 req/min, 10k/day.
    Cached: 4 req/min max regardless of viewer count."""
    import time as _time
    global ggleap_jwt_token

    now_ts = _time.time()
    if _ggleap_status_cache["data"] and (now_ts - _ggleap_status_cache["fetched_at"]) < _GGLEAP_CACHE_TTL:
        return _ggleap_status_cache["data"]

    import requests as _req

    if not ggleap_jwt_token:
        get_ggleap_jwt()
    if not ggleap_jwt_token:
        return {
            "error": "Failed to authenticate with GGLeap API",
            "pcs": [], "available": 0, "in_use": 0, "offline": 0,
            "last_updated": datetime.now(timezone.utc).isoformat()
        }

    try:
        r = _req.get(
            f"{GGLEAP_BASE_URL}/machines/get-all",
            headers={"Accept": "application/json", "Authorization": f"Bearer {ggleap_jwt_token}"},
            timeout=15
        )
        if r.status_code == 401:
            get_ggleap_jwt()
            if ggleap_jwt_token:
                r = _req.get(
                    f"{GGLEAP_BASE_URL}/machines/get-all",
                    headers={"Accept": "application/json", "Authorization": f"Bearer {ggleap_jwt_token}"},
                    timeout=15
                )
        r.raise_for_status()
        data = r.json()
        devices = data.get("Machines", [])

        pcs = []
        available = 0
        in_use = 0
        offline = 0

        for device in devices:
            name = device.get("Name", "Unknown")
            if device.get("GgRockVm", False):
                continue

            state = device.get("State", "Unknown")
            if state in {"ReadyForUser", "IdleShuttingDown"}:
                status = "available"
                available += 1
            elif state == "Off":
                status = "offline"
                offline += 1
            elif state in {"UserLoggedIn", "UserLoggingIn", "AdminMode", "Restarting", "StartingUp", "ShuttingDown"}:
                status = "in-use"
                in_use += 1
            else:
                status = "offline"
                offline += 1

            user_uuid = device.get("UserUuid")
            has_guest = device.get("HasGuest", False)
            open_windows = [w.get("Title", "") for w in device.get("OpenedWindows", []) if w.get("Title")]
            last_state_update = device.get("LastStateUpdate")

            pcs.append({
                "name": format_pc_name(name),
                "status": status,
                "state": state,
                "user_uuid": user_uuid,
                "has_guest": has_guest,
                "open_windows": open_windows,
                "last_state_update": last_state_update,
            })

        def pc_sort_key(pc):
            m = re.match(r"Island (\d+) S(\d+)", pc["name"], re.IGNORECASE)
            if m:
                return (0, int(m.group(1)), int(m.group(2)))
            m = re.match(r"Stage S(\d+)", pc["name"], re.IGNORECASE)
            if m:
                return (1, 0, int(m.group(1)))
            return (2, 999, 999)

        pcs.sort(key=pc_sort_key)

        try:
            _track_pc_sessions(pcs)
        except Exception as e:
            logger.warning(f"[ARENA] Session tracking error: {e}")

        result = {
            "pcs": pcs,
            "available": available,
            "in_use": in_use,
            "offline": offline,
            "last_updated": datetime.now(timezone.utc).isoformat()
        }
        _ggleap_status_cache["data"] = result
        _ggleap_status_cache["fetched_at"] = now_ts
        return result

    except _req.exceptions.Timeout:
        return {
            "error": "GGLeap API request timed out",
            "pcs": [], "available": 0, "in_use": 0, "offline": 0,
            "last_updated": datetime.now(timezone.utc).isoformat()
        }
    except _req.exceptions.RequestException as e:
        return {
            "error": f"Failed to connect to GGLeap API: {str(e)}",
            "pcs": [], "available": 0, "in_use": 0, "offline": 0,
            "last_updated": datetime.now(timezone.utc).isoformat()
        }

@app.route('/api/ggleap/status')
@api_auth_required
def api_ggleap_status():
    """Get live PC status from GGLeap API (server-cached, 15s TTL)."""
    return jsonify(_fetch_ggleap_status())

@app.route('/api/ggleap/games')
@api_auth_required
def api_ggleap_games():
    """Get available games and apps from GGLeap"""
    global ggleap_games_jwt_token
    import requests
    
    # Always try to get fresh JWT
    if not ggleap_games_jwt_token:
        get_ggleap_games_jwt()
    
    if not ggleap_games_jwt_token:
        return jsonify({
            "error": "Failed to authenticate with GGLeap Games API",
            "games": [],
            "apps": []
        })
    
    try:
        r = requests.get(
            f"{GGLEAP_BASE_URL}/apps/get-enabled-apps-summary",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {ggleap_games_jwt_token}"
            },
            timeout=15
        )
        
        # Handle 401 - refresh token and retry
        if r.status_code == 401:
            get_ggleap_games_jwt()
            if ggleap_games_jwt_token:
                r = requests.get(
                    f"{GGLEAP_BASE_URL}/apps/get-enabled-apps-summary",
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {ggleap_games_jwt_token}"
                    },
                    timeout=15
                )
        
        r.raise_for_status()
        data = r.json()
        apps_data = data.get("Apps", [])
        
        games = []
        apps = []
        
        for app in apps_data:
            if not app.get("IsEnabled", False):
                continue
            
            app_type = app.get("AppType", "Unknown")
            app_entry = {
                "name": app.get("Name", "Unknown"),
                "icon": app.get("ImageUrl") or app.get("IconUrl") or None
            }
            
            if app_type == "Game":
                games.append(app_entry)
            elif app_type in {"Program", "Setting"}:
                apps.append(app_entry)
        
        # Sort alphabetically
        games.sort(key=lambda x: x["name"].lower())
        apps.sort(key=lambda x: x["name"].lower())
        
        return jsonify({
            "games": games,
            "apps": apps
        })
        
    except requests.exceptions.Timeout:
        return jsonify({
            "error": "GGLeap API request timed out",
            "games": [],
            "apps": []
        })
    except requests.exceptions.RequestException as e:
        return jsonify({
            "error": f"Failed to connect to GGLeap API: {str(e)}",
            "games": [],
            "apps": []
        })

# ============ Arena PC Activity Report ============

@app.route('/api/arena/pc/<path:pc_name>')
@api_auth_required
def api_arena_pc_detail(pc_name):
    """Return detailed info for a single PC: sessions, events, stats."""
    period = request.args.get('period', 'month')
    now = datetime.now(timezone.utc)

    if period == 'today':
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == 'week':
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    start_iso = start.isoformat()
    usage = _load_arena_usage()

    # Filter sessions for this PC
    sessions = [s for s in usage.get("sessions", []) if s["pc_name"] == pc_name and s["end_time"] >= start_iso]
    events = [e for e in usage.get("event_log", []) if e["pc_name"] == pc_name and e["timestamp"] >= start_iso]

    total_sessions = len(sessions)
    total_minutes = sum(s["duration_minutes"] for s in sessions)
    avg_duration = round(total_minutes / total_sessions, 1) if total_sessions else 0
    longest = max((s["duration_minutes"] for s in sessions), default=0)
    shortest = min((s["duration_minutes"] for s in sessions), default=0) if sessions else 0

    # Current status from live state cache
    current_info = _arena_previous_states.get(pc_name, {})
    current_status = current_info.get("status", "unknown") if isinstance(current_info, dict) else (current_info or "unknown")
    current_raw = current_info.get("raw_state", "Unknown") if isinstance(current_info, dict) else "Unknown"

    # Check active session
    active = usage.get("active_sessions", {}).get(pc_name)
    active_since = None
    if active:
        active_since = active.get("start_time")

    # Hourly breakdown for this PC
    hourly = [0] * 24
    for s in sessions:
        try:
            st = datetime.fromisoformat(s["start_time"])
            hourly[st.hour] += 1
        except Exception:
            pass

    # Shutdown count
    shutdowns = len([e for e in events if e.get("event") == "shutdown"])
    boots = len([e for e in events if e.get("event") == "boot"])

    # User stats
    unique_users = set()
    guest_sessions = 0
    for s in sessions:
        if s.get("user_uuid"):
            unique_users.add(s["user_uuid"])
        if s.get("is_guest"):
            guest_sessions += 1

    # Current user from active session
    current_user_uuid = None
    current_is_guest = False
    current_open_windows = []
    if active:
        current_user_uuid = active.get("user_uuid")
        current_is_guest = active.get("is_guest", False)
        current_open_windows = active.get("open_windows", [])

    return jsonify({
        "pc_name": pc_name,
        "period": period,
        "current_status": current_status,
        "current_raw_state": current_raw,
        "active_since": active_since,
        "current_user_uuid": current_user_uuid,
        "current_is_guest": current_is_guest,
        "current_open_windows": current_open_windows,
        "total_sessions": total_sessions,
        "total_hours": round(total_minutes / 60, 1),
        "avg_duration_minutes": avg_duration,
        "longest_session_minutes": round(longest, 1),
        "shortest_session_minutes": round(shortest, 1),
        "shutdowns": shutdowns,
        "boots": boots,
        "unique_users": len(unique_users),
        "guest_sessions": guest_sessions,
        "hourly": hourly,
        "sessions": sorted(sessions, key=lambda s: s["start_time"], reverse=True)[:100],
        "events": sorted(events, key=lambda e: e["timestamp"], reverse=True)[:200],
    })

@app.route('/arena-report')
@login_required
@page_permission_required('page.ggleap')
def arena_report():
    return render_template('arena_report.html')

@app.route('/api/arena/usage')
@api_auth_required
def api_arena_usage():
    """Return aggregated arena usage data for charts."""
    period = request.args.get('period', 'today')  # today, week, month
    now = datetime.now(timezone.utc)

    if period == 'today':
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == 'week':
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == 'month':
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        start = now - timedelta(days=30)

    usage = _load_arena_usage()
    start_iso = start.isoformat()
    sessions = [s for s in usage.get("sessions", []) if s["end_time"] >= start_iso]
    active = usage.get("active_sessions", {})

    total_sessions = len(sessions)
    total_minutes = sum(s["duration_minutes"] for s in sessions)
    avg_duration = round(total_minutes / total_sessions, 1) if total_sessions > 0 else 0

    # Per-PC breakdown
    pc_stats = {}
    for s in sessions:
        pc = s["pc_name"]
        if pc not in pc_stats:
            pc_stats[pc] = {"sessions": 0, "total_minutes": 0}
        pc_stats[pc]["sessions"] += 1
        pc_stats[pc]["total_minutes"] += s["duration_minutes"]

    per_pc = [{"pc_name": k, "sessions": v["sessions"], "total_hours": round(v["total_minutes"] / 60, 1)}
              for k, v in sorted(pc_stats.items())]

    busiest_pc = max(per_pc, key=lambda x: x["total_hours"])["pc_name"] if per_pc else "N/A"

    # Hourly utilization (sessions active per hour of day)
    hourly = [0] * 24
    for s in sessions:
        try:
            st = datetime.fromisoformat(s["start_time"])
            et = datetime.fromisoformat(s["end_time"])
            h = st.hour
            while h != et.hour or st.date() != et.date():
                hourly[h % 24] += 1
                h += 1
                if h >= 24:
                    h = 0
                    break  # cap at one day loop
            hourly[et.hour % 24] += 1
        except Exception:
            pass

    peak_hour = hourly.index(max(hourly)) if any(hourly) else 0

    # Daily breakdown (sessions per day)
    daily = {}
    for s in sessions:
        try:
            day = s["start_time"][:10]
            if day not in daily:
                daily[day] = {"sessions": 0, "total_minutes": 0}
            daily[day]["sessions"] += 1
            daily[day]["total_minutes"] += s["duration_minutes"]
        except Exception:
            pass

    daily_list = [{"date": k, "sessions": v["sessions"], "total_hours": round(v["total_minutes"] / 60, 1)}
                  for k, v in sorted(daily.items())]

    busiest_day = max(daily_list, key=lambda x: x["sessions"])["date"] if daily_list else "N/A"

    # Weekly heatmap (day_of_week x hour)
    heatmap = [[0] * 24 for _ in range(7)]
    for s in sessions:
        try:
            st = datetime.fromisoformat(s["start_time"])
            heatmap[st.weekday()][st.hour] += 1
        except Exception:
            pass

    return jsonify({
        "period": period,
        "total_sessions": total_sessions,
        "total_hours": round(total_minutes / 60, 1),
        "avg_duration_minutes": avg_duration,
        "busiest_pc": busiest_pc,
        "busiest_day": busiest_day,
        "peak_hour": peak_hour,
        "active_now": len(active),
        "per_pc": per_pc,
        "hourly": hourly,
        "daily": daily_list,
        "heatmap": heatmap,
        "sessions_raw": sessions[-200:]  # Latest 200 for the table
    })

@app.route('/api/arena/export')
@api_auth_required
def api_arena_export():
    """Export arena usage data to a professionally styled Excel spreadsheet."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side, numbers
    from openpyxl.utils import get_column_letter

    period = request.args.get('period', 'month')
    now = datetime.now(timezone.utc)

    if period == 'today':
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        label = now.strftime('%Y-%m-%d')
        period_label = f"Today — {now.strftime('%B %d, %Y')}"
    elif period == 'week':
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        label = f"Week_{start.strftime('%Y-%m-%d')}"
        period_label = f"Week of {start.strftime('%B %d, %Y')}"
    else:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        label = now.strftime('%Y-%m')
        period_label = now.strftime('%B %Y')

    usage = _load_arena_usage()
    start_iso = start.isoformat()
    sessions = [s for s in usage.get("sessions", []) if s["end_time"] >= start_iso]
    events = [e for e in usage.get("event_log", []) if e.get("timestamp", "") >= start_iso]

    wb = Workbook()

    # ── Professional color palette ──
    PURPLE = '7C3AED'
    PURPLE_DARK = '5B21B6'
    PURPLE_LIGHT = 'EDE9FE'
    PURPLE_MED = 'DDD6FE'
    PURPLE_SOFT = 'F5F3FF'
    GREEN = '059669'
    GREEN_LIGHT = 'D1FAE5'
    BLUE = '2563EB'
    AMBER = 'D97706'
    RED = 'DC2626'
    DARK_BG = '1E1B4B'
    WHITE = 'FFFFFF'
    GRAY_50 = 'F9FAFB'
    GRAY_200 = 'E5E7EB'
    GRAY_400 = '9CA3AF'
    GRAY_700 = '374151'

    # ── Fonts ──
    title_font = Font(name='Calibri', bold=True, size=20, color=WHITE)
    subtitle_font = Font(name='Calibri', size=12, color=PURPLE_MED)
    header_font = Font(name='Calibri', bold=True, color=WHITE, size=11)
    subheader_font = Font(name='Calibri', bold=True, size=11, color=PURPLE_DARK)
    data_font = Font(name='Calibri', size=11)
    bold_font = Font(name='Calibri', bold=True, size=11)
    small_font = Font(name='Calibri', size=10, color=GRAY_400)
    metric_val_font = Font(name='Calibri', bold=True, size=16, color=PURPLE)
    metric_lbl_font = Font(name='Calibri', size=10, color=GRAY_700)
    total_font = Font(name='Calibri', bold=True, size=11, color=WHITE)

    # ── Fills ──
    cover_fill = PatternFill(start_color=DARK_BG, end_color=DARK_BG, fill_type='solid')
    header_fill = PatternFill(start_color=PURPLE, end_color=PURPLE, fill_type='solid')
    alt_fill = PatternFill(start_color=PURPLE_SOFT, end_color=PURPLE_SOFT, fill_type='solid')
    total_fill = PatternFill(start_color=PURPLE_DARK, end_color=PURPLE_DARK, fill_type='solid')
    metric_fill = PatternFill(start_color=PURPLE_LIGHT, end_color=PURPLE_LIGHT, fill_type='solid')
    green_fill = PatternFill(start_color=GREEN_LIGHT, end_color=GREEN_LIGHT, fill_type='solid')

    # ── Alignment & borders ──
    center = Alignment(horizontal='center', vertical='center', wrap_text=False)
    left_a = Alignment(horizontal='left', vertical='center')
    right_a = Alignment(horizontal='right', vertical='center')
    thin_border = Border(
        left=Side(style='thin', color=GRAY_200),
        right=Side(style='thin', color=GRAY_200),
        top=Side(style='thin', color=GRAY_200),
        bottom=Side(style='thin', color=GRAY_200),
    )
    thick_bottom = Border(bottom=Side(style='medium', color=PURPLE))

    def style_header_row(ws, row, cols):
        for c in range(1, cols + 1):
            cell = ws.cell(row=row, column=c)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = center
            cell.border = thin_border

    def style_data_row(ws, row, cols, alt=False):
        for c in range(1, cols + 1):
            cell = ws.cell(row=row, column=c)
            cell.font = data_font
            cell.alignment = center
            cell.border = thin_border
            if alt:
                cell.fill = alt_fill

    def style_total_row(ws, row, cols):
        for c in range(1, cols + 1):
            cell = ws.cell(row=row, column=c)
            cell.font = total_font
            cell.fill = total_fill
            cell.alignment = center
            cell.border = thin_border

    def auto_width(ws, min_w=10, max_w=35):
        for col_cells in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col_cells[0].column)
            for cell in col_cells:
                if cell.value:
                    max_len = max(max_len, len(str(cell.value)))
            ws.column_dimensions[col_letter].width = max(min(max_len + 4, max_w), min_w)

    def freeze_below_header(ws, row=2):
        ws.freeze_panes = ws.cell(row=row, column=1)

    # ── Compute stats ──
    total_mins = sum(s["duration_minutes"] for s in sessions)
    total_sessions = len(sessions)
    avg_dur = round(total_mins / total_sessions, 1) if total_sessions else 0

    pc_map = {}
    for s in sessions:
        pc = s["pc_name"]
        if pc not in pc_map:
            pc_map[pc] = {"sessions": 0, "minutes": 0, "longest": 0, "shortest": float('inf')}
        pc_map[pc]["sessions"] += 1
        pc_map[pc]["minutes"] += s["duration_minutes"]
        pc_map[pc]["longest"] = max(pc_map[pc]["longest"], s["duration_minutes"])
        pc_map[pc]["shortest"] = min(pc_map[pc]["shortest"], s["duration_minutes"])

    busiest_pc = max(pc_map.items(), key=lambda x: x[1]["minutes"])[0] if pc_map else "N/A"
    day_map = {}
    for s in sessions:
        d = s["start_time"][:10]
        day_map[d] = day_map.get(d, 0) + 1
    busiest_day = max(day_map.items(), key=lambda x: x[1])[0] if day_map else "N/A"

    hourly_counts = [0] * 24
    for s in sessions:
        try:
            hourly_counts[datetime.fromisoformat(s["start_time"]).hour] += 1
        except Exception:
            pass
    peak_hour = hourly_counts.index(max(hourly_counts)) if any(hourly_counts) else 0

    # ══════════ Sheet 1: Cover Page ══════════
    ws = wb.active
    ws.title = "Overview"
    ws.sheet_properties.tabColor = PURPLE

    # Dark cover background (columns A-F, rows 1-20)
    for r in range(1, 21):
        for c in range(1, 7):
            cell = ws.cell(row=r, column=c)
            cell.fill = cover_fill

    ws.merge_cells('A3:F3')
    ws.cell(row=3, column=1, value="PNW ESPORTS ARENA").font = title_font
    ws.cell(row=3, column=1).alignment = Alignment(horizontal='center', vertical='center')
    ws.cell(row=3, column=1).fill = cover_fill

    ws.merge_cells('A4:F4')
    ws.cell(row=4, column=1, value="PC Activity Report").font = Font(name='Calibri', size=14, color=PURPLE_MED)
    ws.cell(row=4, column=1).alignment = Alignment(horizontal='center')
    ws.cell(row=4, column=1).fill = cover_fill

    ws.merge_cells('A6:F6')
    ws.cell(row=6, column=1, value=period_label).font = Font(name='Calibri', size=12, color=WHITE, bold=True)
    ws.cell(row=6, column=1).alignment = Alignment(horizontal='center')
    ws.cell(row=6, column=1).fill = cover_fill

    ws.merge_cells('A7:F7')
    ws.cell(row=7, column=1, value=f"Generated {now.strftime('%B %d, %Y at %I:%M %p UTC')}").font = small_font
    ws.cell(row=7, column=1).alignment = Alignment(horizontal='center')
    ws.cell(row=7, column=1).fill = cover_fill

    # KPI boxes on cover page (row 10-12)
    kpis = [
        ("Total Sessions", str(total_sessions)),
        ("Total Hours", str(round(total_mins / 60, 1))),
        ("Avg Session", f"{avg_dur} min"),
        ("Busiest PC", busiest_pc),
        ("Peak Hour", f"{peak_hour:02d}:00"),
        ("PCs Tracked", str(len(pc_map))),
    ]
    for ci, (lbl, val) in enumerate(kpis):
        col = ci + 1
        cell_v = ws.cell(row=10, column=col, value=val)
        cell_v.font = metric_val_font
        cell_v.fill = metric_fill
        cell_v.alignment = center
        cell_v.border = thin_border
        cell_l = ws.cell(row=11, column=col, value=lbl)
        cell_l.font = metric_lbl_font
        cell_l.fill = metric_fill
        cell_l.alignment = center
        cell_l.border = thin_border

    # Additional info
    ws.merge_cells('A14:F14')
    ws.cell(row=14, column=1, value=f"Busiest Day: {busiest_day}   |   Days in Period: {len(day_map)}   |   Total Events Logged: {len(events)}").font = Font(name='Calibri', size=10, color=GRAY_400)
    ws.cell(row=14, column=1).alignment = Alignment(horizontal='center')
    ws.cell(row=14, column=1).fill = cover_fill

    for c in range(1, 7):
        ws.column_dimensions[get_column_letter(c)].width = 22
    ws.sheet_view.showGridLines = False

    # ══════════ Sheet 2: Daily Breakdown ══════════
    ws2 = wb.create_sheet("Daily Breakdown")
    ws2.sheet_properties.tabColor = BLUE
    headers2 = ["Date", "Day of Week", "Sessions", "Total Hours", "Avg Session (min)", "Longest Session (min)"]
    ws2.append(headers2)
    style_header_row(ws2, 1, len(headers2))

    daily_sorted = {}
    for s in sessions:
        d = s["start_time"][:10]
        if d not in daily_sorted:
            daily_sorted[d] = {"sessions": 0, "minutes": 0, "longest": 0}
        daily_sorted[d]["sessions"] += 1
        daily_sorted[d]["minutes"] += s["duration_minutes"]
        daily_sorted[d]["longest"] = max(daily_sorted[d]["longest"], s["duration_minutes"])

    for i, (day, v) in enumerate(sorted(daily_sorted.items()), 2):
        try:
            dow = datetime.fromisoformat(day + "T00:00:00").strftime('%A')
        except Exception:
            dow = ""
        ws2.append([day, dow, v["sessions"], round(v["minutes"] / 60, 1),
                     round(v["minutes"] / v["sessions"], 1) if v["sessions"] else 0,
                     round(v["longest"], 1)])
        style_data_row(ws2, i, len(headers2), alt=(i % 2 == 0))

    r = ws2.max_row + 1
    ws2.cell(row=r, column=1, value="TOTAL")
    ws2.cell(row=r, column=2, value="")
    ws2.cell(row=r, column=3, value=total_sessions)
    ws2.cell(row=r, column=4, value=round(total_mins / 60, 1))
    ws2.cell(row=r, column=5, value=avg_dur)
    ws2.cell(row=r, column=6, value="")
    style_total_row(ws2, r, len(headers2))
    auto_width(ws2)
    freeze_below_header(ws2)

    # ══════════ Sheet 3: Per-PC Breakdown ══════════
    ws3 = wb.create_sheet("Per-PC Breakdown")
    ws3.sheet_properties.tabColor = GREEN
    headers3 = ["PC Name", "Sessions", "Total Hours", "Avg Session (min)", "Longest (min)", "Shortest (min)", "% of Usage"]
    ws3.append(headers3)
    style_header_row(ws3, 1, len(headers3))

    sorted_pcs = sorted(pc_map.items(), key=lambda x: x[1]["minutes"], reverse=True)
    for i, (pc, v) in enumerate(sorted_pcs, 2):
        pct = round((v["minutes"] / total_mins) * 100, 1) if total_mins else 0
        shortest = round(v["shortest"], 1) if v["shortest"] != float('inf') else 0
        ws3.append([pc, v["sessions"], round(v["minutes"] / 60, 1),
                     round(v["minutes"] / v["sessions"], 1) if v["sessions"] else 0,
                     round(v["longest"], 1), shortest, f"{pct}%"])
        style_data_row(ws3, i, len(headers3), alt=(i % 2 == 0))
        # Highlight top 3 PCs
        if i <= 4:
            for c in range(1, len(headers3) + 1):
                ws3.cell(row=i, column=c).fill = green_fill

    r = ws3.max_row + 1
    ws3.cell(row=r, column=1, value="TOTAL")
    ws3.cell(row=r, column=2, value=total_sessions)
    ws3.cell(row=r, column=3, value=round(total_mins / 60, 1))
    ws3.cell(row=r, column=4, value=avg_dur)
    ws3.cell(row=r, column=5, value="")
    ws3.cell(row=r, column=6, value="")
    ws3.cell(row=r, column=7, value="100%")
    style_total_row(ws3, r, len(headers3))
    auto_width(ws3)
    freeze_below_header(ws3)

    # ══════════ Sheet 4: Peak Hours Heatmap ══════════
    ws4 = wb.create_sheet("Peak Hours")
    ws4.sheet_properties.tabColor = AMBER
    heatmap = [[0] * 24 for _ in range(7)]
    day_labels = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    for s in sessions:
        try:
            st = datetime.fromisoformat(s["start_time"])
            heatmap[st.weekday()][st.hour] += 1
        except Exception:
            pass

    hour_headers = ["Day"] + [f"{h:02d}:00" for h in range(24)]
    ws4.append(hour_headers)
    style_header_row(ws4, 1, len(hour_headers))

    max_val = max(max(row) for row in heatmap) if any(any(r) for r in heatmap) else 1
    hm_fills = [
        PatternFill(start_color=PURPLE_SOFT, end_color=PURPLE_SOFT, fill_type='solid'),
        PatternFill(start_color=PURPLE_MED, end_color=PURPLE_MED, fill_type='solid'),
        PatternFill(start_color='A78BFA', end_color='A78BFA', fill_type='solid'),
        PatternFill(start_color=PURPLE, end_color=PURPLE, fill_type='solid'),
    ]

    for i, (day_name, row_data) in enumerate(zip(day_labels, heatmap), 2):
        ws4.cell(row=i, column=1, value=day_name).font = bold_font
        ws4.cell(row=i, column=1).border = thin_border
        ws4.cell(row=i, column=1).alignment = left_a
        for h, val in enumerate(row_data):
            cell = ws4.cell(row=i, column=h + 2, value=val if val else "")
            cell.alignment = center
            cell.border = thin_border
            cell.font = data_font
            ratio = val / max_val if max_val > 0 else 0
            if ratio > 0.75:
                cell.fill = hm_fills[3]
                cell.font = Font(name='Calibri', size=11, color=WHITE, bold=True)
            elif ratio > 0.5:
                cell.fill = hm_fills[2]
                cell.font = Font(name='Calibri', size=11, color=WHITE)
            elif ratio > 0.25:
                cell.fill = hm_fills[1]
            elif val > 0:
                cell.fill = hm_fills[0]

    # Row totals
    ws4.cell(row=1, column=26, value="Total").font = header_font
    ws4.cell(row=1, column=26).fill = header_fill
    ws4.cell(row=1, column=26).alignment = center
    ws4.cell(row=1, column=26).border = thin_border
    for i, row_data in enumerate(heatmap, 2):
        cell = ws4.cell(row=i, column=26, value=sum(row_data))
        cell.font = bold_font
        cell.alignment = center
        cell.border = thin_border

    ws4.column_dimensions['A'].width = 14
    for c in range(2, 27):
        ws4.column_dimensions[get_column_letter(c)].width = 7
    freeze_below_header(ws4)

    # ══════════ Sheet 5: All Sessions ══════════
    ws5 = wb.create_sheet("All Sessions")
    ws5.sheet_properties.tabColor = PURPLE
    headers5 = ["PC Name", "Start Time", "End Time", "Duration (min)", "End Reason"]
    ws5.append(headers5)
    style_header_row(ws5, 1, len(headers5))

    for i, s in enumerate(sorted(sessions, key=lambda x: x["start_time"], reverse=True), 2):
        try:
            st = datetime.fromisoformat(s["start_time"]).strftime('%Y-%m-%d %H:%M')
        except Exception:
            st = s["start_time"]
        try:
            et = datetime.fromisoformat(s["end_time"]).strftime('%Y-%m-%d %H:%M')
        except Exception:
            et = s["end_time"]
        ws5.append([s["pc_name"], st, et, s["duration_minutes"], s.get("end_reason", "")])
        style_data_row(ws5, i, len(headers5), alt=(i % 2 == 0))
    auto_width(ws5)
    freeze_below_header(ws5)

    # ══════════ Sheet 6: Event Log ══════════
    ws6 = wb.create_sheet("Event Log")
    ws6.sheet_properties.tabColor = RED
    headers6 = ["Timestamp", "PC Name", "Event", "From Status", "To Status", "From State", "To State"]
    ws6.append(headers6)
    style_header_row(ws6, 1, len(headers6))

    event_fills = {
        "shutdown": PatternFill(start_color='FEE2E2', end_color='FEE2E2', fill_type='solid'),
        "shutting_down": PatternFill(start_color='FEE2E2', end_color='FEE2E2', fill_type='solid'),
        "boot": PatternFill(start_color='D1FAE5', end_color='D1FAE5', fill_type='solid'),
        "user_login": PatternFill(start_color='FEF3C7', end_color='FEF3C7', fill_type='solid'),
        "user_logging_in": PatternFill(start_color='FEF3C7', end_color='FEF3C7', fill_type='solid'),
        "user_logout": PatternFill(start_color='DBEAFE', end_color='DBEAFE', fill_type='solid'),
    }
    sorted_events = sorted(events, key=lambda x: x.get("timestamp", ""), reverse=True)[:2000]

    for i, ev in enumerate(sorted_events, 2):
        try:
            ts = datetime.fromisoformat(ev.get("timestamp", "")).strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            ts = ev.get("timestamp", "")
        ws6.append([
            ts, ev.get("pc_name", ""), ev.get("event", ""),
            ev.get("from_status", ""), ev.get("to_status", ""),
            ev.get("from_state", ""), ev.get("to_state", "")
        ])
        style_data_row(ws6, i, len(headers6), alt=(i % 2 == 0))
        # Color-code event type column
        evt = ev.get("event", "")
        if evt in event_fills:
            ws6.cell(row=i, column=3).fill = event_fills[evt]

    auto_width(ws6)
    freeze_below_header(ws6)

    # ══════════ Sheet 7: Hourly Summary ══════════
    ws7 = wb.create_sheet("Hourly Summary")
    ws7.sheet_properties.tabColor = '6366F1'
    headers7 = ["Hour", "Sessions", "Visual"]
    ws7.append(headers7)
    style_header_row(ws7, 1, len(headers7))

    max_hourly = max(hourly_counts) if any(hourly_counts) else 1
    for i, (h, cnt) in enumerate(enumerate(hourly_counts), 2):
        hr_label = f"{h:02d}:00"
        bar = "█" * round(cnt / max_hourly * 20) if max_hourly else ""
        ws7.append([hr_label, cnt, bar])
        style_data_row(ws7, i, 2, alt=(i % 2 == 0))
        bar_cell = ws7.cell(row=i, column=3)
        bar_cell.font = Font(name='Calibri', size=11, color=PURPLE)
        bar_cell.alignment = left_a
        bar_cell.border = thin_border
        if cnt == max_hourly and cnt > 0:
            for c in range(1, 4):
                ws7.cell(row=i, column=c).fill = green_fill

    auto_width(ws7, min_w=8, max_w=30)
    ws7.column_dimensions['C'].width = 28
    freeze_below_header(ws7)

    # ── Print setup for all sheets ──
    for ws_item in wb.worksheets:
        ws_item.page_setup.orientation = 'landscape'
        ws_item.page_setup.fitToWidth = 1
        ws_item.page_setup.fitToHeight = 0

    # Write to memory buffer
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    filename = f"Arena_Report_{label}.xlsx"
    return Response(
        output.getvalue(),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )

@app.route('/api/reaction-roles')
@api_auth_required
def api_reaction_roles():
    filepath = os.path.join(DATA_DIR, "reaction_roles.json")
    return jsonify(load_json_file(filepath, {}))

@app.route('/api/reaction-roles', methods=['POST'])
@api_auth_required
@api_perm_required('reaction_roles.manage')
def api_save_reaction_roles():
    data = request.json
    filepath = os.path.join(DATA_DIR, "reaction_roles.json")
    save_json_file(filepath, data)
    return jsonify({"success": True, "message": "Reaction roles saved"})

# ============ Roster Management API ============

ROSTERS_FILE = os.path.join(DATA_DIR, "rosters.json")
TEAMS_FILE = os.path.join(DATA_DIR, "teams.json")

def load_rosters():
    return load_json_file(ROSTERS_FILE, {"players": []})

def save_rosters(data):
    save_json_file(ROSTERS_FILE, data)

def load_teams():
    return load_json_file(TEAMS_FILE, {"teams": []})

def save_teams(data):
    save_json_file(TEAMS_FILE, data)

# Audit Log Configuration
AUDIT_LOG_FILE = os.path.join(DATA_DIR, "roster_audit_log.json")

def add_audit_log(action_type, target_id, details, user_name=None):
    """Add an entry to the roster audit log"""
    audit_log = load_json_file(AUDIT_LOG_FILE, {"logs": []})
    
    entry = {
        "id": f"log_{datetime.now().strftime('%Y%m%d%H%M%S')}_{len(audit_log.get('logs', []))}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action_type,
        "target_id": str(target_id) if target_id else None,
        "details": details,
        "performed_by": user_name or session.get('user_name', 'Dashboard Admin')
    }
    
    logs = audit_log.get("logs", [])
    logs.insert(0, entry)  # Add to beginning
    
    # Keep only last 500 entries
    audit_log["logs"] = logs[:500]
    save_json_file(AUDIT_LOG_FILE, audit_log)
    
    return entry

@app.route('/api/rosters')
@api_auth_required
def api_rosters():
    """Get all roster data including players, teams, and pending registrations"""
    rosters = load_rosters()
    teams = load_teams()
    
    # Load pending varsity registrations
    pending = []
    if os.path.exists(VARSITY_REG_DIR):
        for fname in os.listdir(VARSITY_REG_DIR):
            if fname.endswith("_varsity.json"):
                discord_id = fname.split("_")[0]
                filepath = os.path.join(VARSITY_REG_DIR, fname)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        records = json.load(f)
                    # Get the latest pending registration
                    for record in reversed(records):
                        if record.get("status", "").lower() == "pending":
                            record["discord_id"] = discord_id
                            # Transform attachments to proper URLs
                            if record.get('data'):
                                record['data']['attachments'] = transform_attachments_to_urls(record.get('data', {}))
                            pending.append(record)
                            break
                except:
                    pass
    
    # Enrich player data with Discord info from members cache
    members_cache = load_json_file(MEMBERS_CACHE_FILE, [])
    # Handle both list format and dict format
    if isinstance(members_cache, dict):
        members_list = members_cache.get("members", [])
    else:
        members_list = members_cache
    members_map = {str(m.get("id")): m for m in members_list}
    
    for player in rosters.get("players", []):
        member = members_map.get(str(player.get("discord_id")))
        if member:
            player["discord_username"] = member.get("username") or member.get("name")
            player["avatar"] = member.get("avatar")
    
    # Also enrich pending registrations with Discord info
    for reg in pending:
        member = members_map.get(str(reg.get("discord_id")))
        if member:
            reg["discord_username"] = member.get("username") or member.get("name")
            reg["avatar"] = member.get("avatar")
    
    return jsonify({
        "players": rosters.get("players", []),
        "teams": teams.get("teams", []),
        "pending": pending
    })

@app.route('/api/rosters/player', methods=['POST'])
@api_auth_required
@api_perm_required('rosters.manage_players')
def api_add_player():
    """Add a new player to the roster"""
    data = request.json
    discord_id = data.get("discord_id")
    
    if not discord_id:
        return jsonify({"error": "Discord ID is required"}), 400
    
    rosters = load_rosters()
    players = rosters.get("players", [])
    
    # Check if player already exists
    existing = next((p for p in players if str(p.get("discord_id")) == str(discord_id)), None)
    is_update = existing is not None
    
    if existing:
        # Update existing player
        existing.update({
            "full_name": data.get("full_name", existing.get("full_name")),
            "player_type": data.get("player_type", existing.get("player_type")),
            "game": data.get("game", existing.get("game")),
            "ign": data.get("ign", existing.get("ign")),
            "rank": data.get("rank", existing.get("rank")),
            "tracker": data.get("tracker", existing.get("tracker")),
            "is_captain": data.get("is_captain", existing.get("is_captain", False)),
            "team_id": data.get("team_id", existing.get("team_id")),
            "status": data.get("status", existing.get("status", "active")),
            "role": data.get("role", existing.get("role")),
            "secondary_role": data.get("secondary_role", existing.get("secondary_role")),
            "updated_at": datetime.now(timezone.utc).isoformat()
        })
    else:
        # Add new player
        players.append({
            "discord_id": str(discord_id),
            "full_name": data.get("full_name"),
            "player_type": data.get("player_type", "varsity"),
            "game": data.get("game"),
            "ign": data.get("ign"),
            "rank": data.get("rank"),
            "tracker": data.get("tracker"),
            "is_captain": data.get("is_captain", False),
            "team_id": data.get("team_id"),
            "purdue_email": data.get("purdue_email"),
            "personal_email": data.get("personal_email"),
            "status": data.get("status", "active"),
            "role": data.get("role"),
            "secondary_role": data.get("secondary_role"),
            "stats": {
                "matches_played": 0,
                "wins": 0,
                "losses": 0,
                "mvp_count": 0
            },
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        })
    
    rosters["players"] = players
    save_rosters(rosters)
    
    # Audit log
    player_name = data.get("full_name") or discord_id
    if is_update:
        add_audit_log("player_updated", discord_id, f"Updated player: {player_name}")
    else:
        add_audit_log("player_added", discord_id, f"Added player: {player_name}")
    
    return jsonify({"success": True, "message": "Player added/updated"})

@app.route('/api/rosters/player', methods=['DELETE'])
@api_auth_required
@api_perm_required('rosters.manage_players')
def api_remove_player():
    """Remove a player from the roster"""
    data = request.json
    discord_id = data.get("discord_id")
    
    if not discord_id:
        return jsonify({"error": "Discord ID is required"}), 400
    
    rosters = load_rosters()
    players = rosters.get("players", [])
    
    # Get player name for audit log
    removed_player = next((p for p in players if str(p.get("discord_id")) == str(discord_id)), None)
    player_name = removed_player.get("full_name") if removed_player else discord_id
    
    rosters["players"] = [p for p in players if str(p.get("discord_id")) != str(discord_id)]
    save_rosters(rosters)
    
    add_audit_log("player_removed", discord_id, f"Removed player: {player_name}")
    
    return jsonify({"success": True, "message": "Player removed"})

@app.route('/api/rosters/team', methods=['POST'])
@api_auth_required
@api_perm_required('rosters.manage_teams')
def api_create_team():
    """Create a new team"""
    data = request.json
    
    if not data.get("name"):
        return jsonify({"error": "Team name is required"}), 400
    
    teams_data = load_teams()
    teams = teams_data.get("teams", [])
    
    # Generate ID
    team_id = f"team_{len(teams) + 1}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    teams.append({
        "id": team_id,
        "name": data.get("name"),
        "game": data.get("game"),
        "type": data.get("type", "varsity"),
        "color": data.get("color", "#d4af37"),
        "description": data.get("description"),
        "created_at": datetime.now(timezone.utc).isoformat()
    })
    
    teams_data["teams"] = teams
    save_teams(teams_data)
    
    add_audit_log("team_created", team_id, f"Created team: {data.get('name')}")
    
    return jsonify({"success": True, "message": "Team created", "team_id": team_id})

@app.route('/api/rosters/team/update', methods=['POST'])
@api_auth_required
@api_perm_required('rosters.manage_teams')
def api_update_team():
    """Update an existing team"""
    data = request.json
    team_id = data.get("team_id")
    
    if not team_id:
        return jsonify({"error": "Team ID is required"}), 400
    
    teams_data = load_teams()
    teams = teams_data.get("teams", [])
    
    team_found = False
    team_name = team_id
    for team in teams:
        if team.get("id") == team_id:
            team_name = team.get("name", team_id)
            if data.get("name"):
                team["name"] = data.get("name")
                team_name = data.get("name")
            if data.get("game"):
                team["game"] = data.get("game")
            if data.get("type"):
                team["type"] = data.get("type")
            if data.get("color"):
                team["color"] = data.get("color")
            if data.get("description") is not None:
                team["description"] = data.get("description")
            team["updated_at"] = datetime.now(timezone.utc).isoformat()
            team_found = True
            break
    
    if not team_found:
        return jsonify({"error": "Team not found"}), 404
    
    teams_data["teams"] = teams
    save_teams(teams_data)
    
    add_audit_log("team_updated", team_id, f"Updated team: {team_name}")
    
    return jsonify({"success": True, "message": "Team updated"})

@app.route('/api/rosters/teams/reorder', methods=['POST'])
@api_auth_required
@api_perm_required('rosters.manage_teams')
def api_reorder_teams():
    """Reorder teams based on drag-and-drop"""
    data = request.json
    team_order = data.get("team_order", [])
    
    if not team_order:
        return jsonify({"error": "Team order is required"}), 400
    
    teams_data = load_teams()
    teams = teams_data.get("teams", [])
    
    # Create a map of teams by ID
    teams_map = {t.get("id"): t for t in teams}
    
    # Reorder teams based on the provided order
    reordered_teams = []
    for team_id in team_order:
        if team_id in teams_map:
            reordered_teams.append(teams_map[team_id])
    
    # Add any teams that weren't in the order list (just in case)
    for team in teams:
        if team not in reordered_teams:
            reordered_teams.append(team)
    
    teams_data["teams"] = reordered_teams
    save_teams(teams_data)
    
    add_audit_log("teams_reordered", None, f"Reordered {len(reordered_teams)} teams")
    
    return jsonify({"success": True, "message": "Team order saved"})

@app.route('/api/rosters/team', methods=['DELETE'])
@api_auth_required
@api_perm_required('rosters.manage_teams')
def api_delete_team():
    """Delete a team"""
    data = request.json
    team_id = data.get("team_id")
    
    if not team_id:
        return jsonify({"error": "Team ID is required"}), 400
    
    teams_data = load_teams()
    teams = teams_data.get("teams", [])
    
    # Get team name for audit log
    deleted_team = next((t for t in teams if t.get("id") == team_id), None)
    team_name = deleted_team.get("name") if deleted_team else team_id
    
    teams_data["teams"] = [t for t in teams if t.get("id") != team_id]
    save_teams(teams_data)
    
    # Remove team_id from all players
    rosters = load_rosters()
    for player in rosters.get("players", []):
        if player.get("team_id") == team_id:
            player["team_id"] = None
    save_rosters(rosters)
    
    add_audit_log("team_deleted", team_id, f"Deleted team: {team_name}")
    
    return jsonify({"success": True, "message": "Team deleted"})

@app.route('/api/rosters/send-registration', methods=['POST'])
@api_auth_required
@api_perm_required('rosters.registrations')
def api_send_varsity_registration():
    """Send varsity registration to a Discord user"""
    data = request.json
    user_id = data.get("user_id")
    player_type = data.get("player_type", "varsity")
    note = data.get("note", "")
    
    if not user_id:
        return jsonify({"error": "User ID is required"}), 400
    
    # Generate a unique job ID for tracking
    import uuid
    job_id = f"reg_{user_id}_{uuid.uuid4().hex[:8]}"
    
    # Queue notification to bot to send registration (thread-safe)
    queue_file = os.path.join(DATA_DIR, "discord_notification_queue.json")
    safe_queue_append(queue_file, {
        "type": "send_varsity_registration",
        "user_id": user_id,
        "player_type": player_type,
        "job_id": job_id,
        "note": note,
        "status": "pending",
        "dm_status": "pending",
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    
    return jsonify({
        "success": True, 
        "message": "Registration queued",
        "job_id": job_id
    })

@app.route('/api/rosters/registration-status/<job_id>', methods=['GET'])
@api_auth_required
def api_check_registration_status(job_id):
    """Check the status of a registration DM"""
    queue_file = os.path.join(DATA_DIR, "discord_notification_queue.json")
    queue = load_json_file(queue_file, [])
    
    # Find the notification with this job_id
    for notif in queue:
        if notif.get("job_id") == job_id:
            return jsonify({
                "success": True,
                "status": notif.get("status", "pending"),
                "dm_status": notif.get("dm_status", "pending"),
                "dm_error": notif.get("dm_error"),
                "dm_username": notif.get("dm_username"),
                "dm_team": notif.get("dm_team"),
                "timestamp": notif.get("timestamp")
            })
    
    # Job not found - could mean it was cleaned up after being processed
    return jsonify({
        "success": True,
        "status": "not_found",
        "dm_status": "unknown",
        "dm_error": None
    })

@app.route('/api/rosters/approve', methods=['POST'])
@api_auth_required
@api_perm_required('rosters.registrations')
def api_approve_registration():
    """Approve a pending varsity registration"""
    data = request.json
    discord_id = data.get("discord_id")
    
    if not discord_id:
        return jsonify({"error": "Discord ID is required"}), 400
    
    # Update registration status
    record_path = os.path.join(VARSITY_REG_DIR, f"{discord_id}_varsity.json")
    if not os.path.exists(record_path):
        return jsonify({"error": "Registration not found"}), 404
    
    try:
        with open(record_path, 'r', encoding='utf-8') as f:
            records = json.load(f)
        
        # Find and update the pending registration
        player_data = None
        for record in reversed(records):
            if record.get("status", "").lower() == "pending":
                record["status"] = "Approved"
                record["moderated_at"] = datetime.now(timezone.utc).isoformat()
                record["moderated_by"] = {"name": "Dashboard Admin"}
                player_data = record.get("data", {})
                break
        
        safe_json_dump(records, record_path, indent=2)
        
        # Add to roster
        if player_data:
            rosters = load_rosters()
            players = rosters.get("players", [])
            
            # Check if player already exists (use user_id from URL parameter)
            existing = next((p for p in players if str(p.get("discord_id")) == str(discord_id)), None)
            if not existing:
                players.append({
                    "discord_id": str(discord_id),
                    "full_name": player_data.get("Full Name"),
                    "player_type": player_data.get("player_type", "varsity"),
                    "game": player_data.get("Primary Game Title"),
                    "ign": player_data.get("IGN"),
                    "rank": player_data.get("Current Rank in Game"),
                    "role": player_data.get("Primary Role"),
                    "tracker": player_data.get("Tracker Link"),
                    "purdue_email": player_data.get("Purdue Email"),
                    "personal_email": player_data.get("Personal Email"),
                    "is_captain": False,
                    "team_id": None,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat()
                })
                rosters["players"] = players
                save_rosters(rosters)
        
        # Queue notification to bot to DM user and assign role (thread-safe)
        queue_file = os.path.join(DATA_DIR, "discord_notification_queue.json")
        safe_queue_append(queue_file, {
            "type": "varsity_approved",
            "user_id": discord_id,
            "player_type": player_data.get("player_type", "varsity") if player_data else "varsity",
            "assign_role": True,
            "status": "pending",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        
        # Add live notification
        player_name = player_data.get("Full Name", f"User {discord_id}") if player_data else f"User {discord_id}"
        add_live_notification(
            "registration",
            "Registration Approved",
            f"{player_name} has been approved for {player_data.get('player_type', 'varsity').upper() if player_data else 'Varsity'}",
            link='/rosters',
            target_id=discord_id
        )
        
        return jsonify({"success": True, "message": "Registration approved"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/rosters/deny', methods=['POST'])
@api_auth_required
@api_perm_required('rosters.registrations')
def api_deny_registration():
    """Deny a pending varsity registration"""
    data = request.json
    discord_id = data.get("discord_id")
    reason = data.get("reason", "No reason provided")
    
    if not discord_id:
        return jsonify({"error": "Discord ID is required"}), 400
    
    # Update registration status
    record_path = os.path.join(VARSITY_REG_DIR, f"{discord_id}_varsity.json")
    if not os.path.exists(record_path):
        return jsonify({"error": "Registration not found"}), 404
    
    try:
        with open(record_path, 'r', encoding='utf-8') as f:
            records = json.load(f)
        
        for record in reversed(records):
            if record.get("status", "").lower() == "pending":
                record["status"] = "Denied"
                record["moderated_at"] = datetime.now(timezone.utc).isoformat()
                record["moderated_by"] = {"name": "Dashboard Admin"}
                record["moderation_note"] = reason
                break
        
        safe_json_dump(records, record_path, indent=2)
        
        # Queue notification to bot (thread-safe)
        queue_file = os.path.join(DATA_DIR, "discord_notification_queue.json")
        safe_queue_append(queue_file, {
            "type": "varsity_denied",
            "user_id": discord_id,
            "reason": reason,
            "status": "pending",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        
        return jsonify({"success": True, "message": "Registration denied"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/rosters/captain', methods=['POST'])
@api_auth_required
@api_perm_required('rosters.manage_players')
def api_set_captain():
    """Set or remove captain status for a player"""
    data = request.json
    discord_id = data.get("discord_id")
    is_captain = data.get("is_captain", False)
    
    if not discord_id:
        return jsonify({"error": "Discord ID is required"}), 400
    
    rosters = load_rosters()
    for player in rosters.get("players", []):
        if str(player.get("discord_id")) == str(discord_id):
            player["is_captain"] = is_captain
            player["updated_at"] = datetime.now(timezone.utc).isoformat()
            break
    
    save_rosters(rosters)
    return jsonify({"success": True, "message": "Captain status updated"})

@app.route('/api/rosters/assign-team', methods=['POST'])
@api_auth_required
@api_perm_required('rosters.manage_players')
def api_assign_team():
    """Assign a player to a team (supports multiple teams) and queue role sync"""
    data = request.json
    discord_id = data.get("discord_id")
    team_id = data.get("team_id")
    action = data.get("action", "add")  # 'add', 'remove', or 'set' (replace all)
    player_type = data.get("player_type", "varsity")
    
    if not discord_id:
        return jsonify({"error": "Discord ID is required"}), 400
    
    rosters = load_rosters()
    
    # Get team info FIRST (before modifying anything) - teams are stored separately
    teams_data = load_teams()
    team = next((t for t in teams_data.get("teams", []) if t.get("id") == team_id), None) if team_id else None
    team_name = team.get("name", "Unknown Team") if team else "Unknown Team"
    team_game = team.get("game", "") if team else ""
    team_type = team.get("type", "varsity") if team else player_type
    
    player_found = False
    
    for player in rosters.get("players", []):
        if str(player.get("discord_id")) == str(discord_id):
            # Migrate old team_id to team_ids if needed
            if "team_ids" not in player:
                old_team_id = player.get("team_id")
                player["team_ids"] = [old_team_id] if old_team_id else []
            
            if action == "add" and team_id:
                # Add to team (if not already on it)
                if team_id not in player["team_ids"]:
                    player["team_ids"].append(team_id)
            elif action == "remove" and team_id:
                # Remove from specific team
                if team_id in player["team_ids"]:
                    player["team_ids"].remove(team_id)
            elif action == "set":
                # Replace all teams with this one (or clear if team_id is None)
                player["team_ids"] = [team_id] if team_id else []
            
            # Keep team_id for backward compatibility (use first team)
            player["team_id"] = player["team_ids"][0] if player["team_ids"] else None
            player["player_type"] = team_type if team else player_type
            # Update game from team so role sync works correctly
            if team_game:
                player["game"] = team_game
            player["updated_at"] = datetime.now(timezone.utc).isoformat()
            player_found = True
            break
    
    # If player doesn't exist in roster, add them
    if not player_found:
        new_player = {
            "discord_id": str(discord_id),
            "team_ids": [team_id] if team_id else [],
            "team_id": team_id,  # backward compatibility
            "player_type": team_type if team else player_type,
            "is_captain": False,
            "added_at": datetime.now(timezone.utc).isoformat()
        }
        # Set game from team so role sync works
        if team_game:
            new_player["game"] = team_game
        rosters.setdefault("players", []).append(new_player)
    
    save_rosters(rosters)
    
    # Log the action
    action_text = "added to" if action == "add" else ("removed from" if action == "remove" else "assigned to")
    add_audit_log("team_assignment", discord_id, f"{action_text.capitalize()} team {team_id} ({team_name})" if team_id else "Removed from team")
    
    # Queue role sync for the bot to handle
    if team_id and action != "remove":
        queue_file = os.path.join(DATA_DIR, "discord_notification_queue.json")
        safe_queue_append(queue_file, {
            "type": "sync_team_roles",
            "discord_id": discord_id,
            "team_id": team_id,
            "player_type": team_type,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        
        # Add live notification for team assignment
        add_live_notification(
            "team",
            "Player Added to Team",
            f"User {discord_id} {action_text} {team_name}",
            link='/rosters',
            target_id=discord_id
        )
    
    return jsonify({"success": True, "message": f"Player {action_text} {team_name}. Roles will be synced shortly."})

# ============ Audit Log API Endpoints ============

@app.route('/api/rosters/audit-log')
@api_auth_required
def api_get_audit_log():
    """Get the roster audit log with optional filtering"""
    audit_log = load_json_file(AUDIT_LOG_FILE, {"logs": []})
    
    # Optional filters
    action_filter = request.args.get('action')
    target_filter = request.args.get('target')
    limit = int(request.args.get('limit', 100))
    
    logs = audit_log.get("logs", [])
    
    if action_filter:
        logs = [l for l in logs if l.get("action") == action_filter]
    if target_filter:
        logs = [l for l in logs if str(l.get("target_id")) == str(target_filter)]
    
    return jsonify({
        "logs": logs[:limit],
        "total": len(audit_log.get("logs", []))
    })

# ============ Player Status API Endpoints ============

@app.route('/api/rosters/player/status', methods=['POST'])
@api_auth_required
@api_perm_required('rosters.manage_players')
def api_update_player_status():
    """Update player status (active/inactive/bench/injured)"""
    data = request.json
    discord_id = data.get("discord_id")
    status = data.get("status", "active")
    availability = data.get("availability")
    notes = data.get("notes")
    
    if not discord_id:
        return jsonify({"error": "Discord ID is required"}), 400
    
    valid_statuses = ["active", "inactive", "bench", "injured", "leave"]
    if status not in valid_statuses:
        return jsonify({"error": f"Invalid status. Must be one of: {', '.join(valid_statuses)}"}), 400
    
    rosters = load_rosters()
    player_found = False
    
    for player in rosters.get("players", []):
        if str(player.get("discord_id")) == str(discord_id):
            old_status = player.get("status", "active")
            player["status"] = status
            if availability is not None:
                player["availability"] = availability
            if notes is not None:
                player["status_notes"] = notes
            player["status_updated_at"] = datetime.now(timezone.utc).isoformat()
            player["updated_at"] = datetime.now(timezone.utc).isoformat()
            player_found = True
            
            # Log the change
            add_audit_log("status_change", discord_id, f"Status changed from {old_status} to {status}")
            break
    
    if not player_found:
        return jsonify({"error": "Player not found"}), 404
    
    save_rosters(rosters)
    return jsonify({"success": True, "message": "Player status updated"})

# ============ Bulk Actions API Endpoints ============

@app.route('/api/rosters/bulk/status', methods=['POST'])
@api_auth_required
@api_perm_required('rosters.bulk_actions')
def api_bulk_update_status():
    """Bulk update status for multiple players"""
    data = request.json
    player_ids = data.get("player_ids", [])
    status = data.get("status")
    
    if not player_ids:
        return jsonify({"error": "No players selected"}), 400
    if not status:
        return jsonify({"error": "Status is required"}), 400
    
    rosters = load_rosters()
    updated_count = 0
    
    for player in rosters.get("players", []):
        if str(player.get("discord_id")) in [str(p) for p in player_ids]:
            player["status"] = status
            player["status_updated_at"] = datetime.now(timezone.utc).isoformat()
            player["updated_at"] = datetime.now(timezone.utc).isoformat()
            updated_count += 1
    
    save_rosters(rosters)
    add_audit_log("bulk_status_change", None, f"Changed status to {status} for {updated_count} players")
    
    return jsonify({"success": True, "message": f"Updated {updated_count} players", "count": updated_count})

@app.route('/api/rosters/bulk/type', methods=['POST'])
@api_auth_required
@api_perm_required('rosters.bulk_actions')
def api_bulk_update_type():
    """Bulk update player type for multiple players"""
    data = request.json
    player_ids = data.get("player_ids", [])
    player_type = data.get("player_type")
    
    if not player_ids:
        return jsonify({"error": "No players selected"}), 400
    if not player_type:
        return jsonify({"error": "Player type is required"}), 400
    
    rosters = load_rosters()
    updated_count = 0
    
    for player in rosters.get("players", []):
        if str(player.get("discord_id")) in [str(p) for p in player_ids]:
            player["player_type"] = player_type
            player["updated_at"] = datetime.now(timezone.utc).isoformat()
            updated_count += 1
    
    save_rosters(rosters)
    add_audit_log("bulk_type_change", None, f"Changed type to {player_type} for {updated_count} players")
    
    return jsonify({"success": True, "message": f"Updated {updated_count} players", "count": updated_count})

@app.route('/api/rosters/bulk/team', methods=['POST'])
@api_auth_required
@api_perm_required('rosters.bulk_actions')
def api_bulk_assign_team():
    """Bulk assign players to a team (supports multi-team)"""
    data = request.json
    player_ids = data.get("player_ids", [])
    team_id = data.get("team_id")  # Can be null to remove from team
    action = data.get("action", "add")  # 'add', 'remove', or 'set'
    
    if not player_ids:
        return jsonify({"error": "No players selected"}), 400
    
    rosters = load_rosters()
    updated_count = 0
    
    for player in rosters.get("players", []):
        if str(player.get("discord_id")) in [str(p) for p in player_ids]:
            # Migrate old team_id to team_ids if needed
            if "team_ids" not in player:
                old_team_id = player.get("team_id")
                player["team_ids"] = [old_team_id] if old_team_id else []
            
            if action == "add" and team_id:
                if team_id not in player["team_ids"]:
                    player["team_ids"].append(team_id)
            elif action == "remove" and team_id:
                if team_id in player["team_ids"]:
                    player["team_ids"].remove(team_id)
            elif action == "set":
                player["team_ids"] = [team_id] if team_id else []
            
            # Keep team_id for backward compatibility
            player["team_id"] = player["team_ids"][0] if player["team_ids"] else None
            player["updated_at"] = datetime.now(timezone.utc).isoformat()
            updated_count += 1
    
    save_rosters(rosters)
    
    teams_data = load_teams()
    team_name = "no team"
    if team_id:
        team = next((t for t in teams_data.get("teams", []) if t.get("id") == team_id), None)
        team_name = team.get("name", team_id) if team else team_id
    
    action_text = "added to" if action == "add" else ("removed from" if action == "remove" else "assigned to")
    add_audit_log("bulk_team_assignment", None, f"{action_text.capitalize()} {updated_count} players to {team_name}")
    
    return jsonify({"success": True, "message": f"Updated {updated_count} players", "count": updated_count})

@app.route('/api/rosters/bulk/delete', methods=['POST'])
@api_auth_required
@api_perm_required('rosters.bulk_actions')
def api_bulk_delete_players():
    """Bulk delete multiple players from roster"""
    data = request.json
    player_ids = data.get("player_ids", [])
    
    if not player_ids:
        return jsonify({"error": "No players selected"}), 400
    
    rosters = load_rosters()
    original_count = len(rosters.get("players", []))
    rosters["players"] = [p for p in rosters.get("players", []) if str(p.get("discord_id")) not in [str(pid) for pid in player_ids]]
    deleted_count = original_count - len(rosters.get("players", []))
    
    save_rosters(rosters)
    add_audit_log("bulk_delete", None, f"Deleted {deleted_count} players from roster")
    
    return jsonify({"success": True, "message": f"Deleted {deleted_count} players", "count": deleted_count})

# ============ Match History & Player Stats API ============

MATCH_HISTORY_FILE = os.path.join(DATA_DIR, "match_history.json")

def load_match_history():
    return load_json_file(MATCH_HISTORY_FILE, {"matches": []})

def save_match_history(data):
    save_json_file(MATCH_HISTORY_FILE, data)

@app.route('/api/rosters/matches', methods=['GET'])
@api_auth_required
def api_get_matches():
    """Get match history with optional filtering"""
    team_id = request.args.get('team_id')
    player_id = request.args.get('player_id')
    game = request.args.get('game')
    limit = int(request.args.get('limit', 50))
    
    match_history = load_match_history()
    matches = match_history.get("matches", [])
    
    # Apply filters
    if team_id:
        matches = [m for m in matches if m.get("team_id") == team_id]
    if player_id:
        matches = [m for m in matches if player_id in [str(p.get("discord_id")) for p in m.get("players", [])]]
    if game:
        matches = [m for m in matches if m.get("game", "").lower() == game.lower()]
    
    # Sort by date descending
    matches.sort(key=lambda x: x.get("date", ""), reverse=True)
    
    return jsonify({
        "matches": matches[:limit],
        "total": len(matches)
    })

@app.route('/api/rosters/matches', methods=['POST'])
@api_auth_required
@api_perm_required('rosters.manage_matches')
def api_log_match():
    """Log a new match result"""
    data = request.json
    
    if not data.get("team_id"):
        return jsonify({"error": "Team ID is required"}), 400
    if not data.get("result"):
        return jsonify({"error": "Match result is required"}), 400
    
    match_history = load_match_history()
    matches = match_history.get("matches", [])
    
    # Generate match ID
    match_id = f"match_{datetime.now().strftime('%Y%m%d%H%M%S')}_{len(matches)}"
    
    # Get team info
    teams_data = load_teams()
    team = next((t for t in teams_data.get("teams", []) if t.get("id") == data.get("team_id")), None)
    team_name = team.get("name") if team else "Unknown Team"
    game = data.get("game") or (team.get("game") if team else "")
    
    # Build match record
    match_record = {
        "id": match_id,
        "team_id": data.get("team_id"),
        "team_name": team_name,
        "game": game,
        "opponent": data.get("opponent", "Unknown"),
        "result": data.get("result"),  # win, loss, draw
        "score": data.get("score", ""),  # e.g., "3-2"
        "map": data.get("map", ""),
        "tournament": data.get("tournament", ""),
        "notes": data.get("notes", ""),
        "date": data.get("date") or datetime.now(timezone.utc).isoformat(),
        "players": data.get("players", []),  # List of player participation with stats
        "mvp_id": data.get("mvp_id"),
        "logged_by": session.get('user_name', 'Dashboard Admin'),
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    matches.append(match_record)
    match_history["matches"] = matches
    save_match_history(match_history)
    
    # Update player stats
    rosters = load_rosters()
    players = rosters.get("players", [])
    
    for player_data in data.get("players", []):
        player_id = str(player_data.get("discord_id"))
        player = next((p for p in players if str(p.get("discord_id")) == player_id), None)
        
        if player:
            # Initialize stats if not present
            if "stats" not in player:
                player["stats"] = {
                    "matches_played": 0,
                    "wins": 0,
                    "losses": 0,
                    "draws": 0,
                    "mvp_count": 0
                }
            
            player["stats"]["matches_played"] = player["stats"].get("matches_played", 0) + 1
            
            if data.get("result") == "win":
                player["stats"]["wins"] = player["stats"].get("wins", 0) + 1
            elif data.get("result") == "loss":
                player["stats"]["losses"] = player["stats"].get("losses", 0) + 1
            else:
                player["stats"]["draws"] = player["stats"].get("draws", 0) + 1
            
            # Track MVP
            if str(data.get("mvp_id")) == player_id:
                player["stats"]["mvp_count"] = player["stats"].get("mvp_count", 0) + 1
            
            # Update game-specific stats if provided
            if player_data.get("kills") is not None:
                game_stats = player.get("game_stats", {})
                game_stats[game] = game_stats.get(game, {"kills": 0, "deaths": 0, "assists": 0})
                game_stats[game]["kills"] = game_stats[game].get("kills", 0) + int(player_data.get("kills", 0))
                game_stats[game]["deaths"] = game_stats[game].get("deaths", 0) + int(player_data.get("deaths", 0))
                game_stats[game]["assists"] = game_stats[game].get("assists", 0) + int(player_data.get("assists", 0))
                player["game_stats"] = game_stats
            
            player["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    save_rosters(rosters)
    add_audit_log("match_logged", match_id, f"Logged match: {team_name} vs {data.get('opponent')} - {data.get('result')}")
    
    return jsonify({"success": True, "message": "Match logged successfully", "match_id": match_id})

@app.route('/api/rosters/matches/<match_id>', methods=['DELETE'])
@api_auth_required
@api_perm_required('rosters.manage_matches')
def api_delete_match(match_id):
    """Delete a match from history"""
    match_history = load_match_history()
    matches = match_history.get("matches", [])
    
    match = next((m for m in matches if m.get("id") == match_id), None)
    if not match:
        return jsonify({"error": "Match not found"}), 404
    
    match_history["matches"] = [m for m in matches if m.get("id") != match_id]
    save_match_history(match_history)
    
    add_audit_log("match_deleted", match_id, f"Deleted match: {match.get('team_name')} vs {match.get('opponent')}")
    
    return jsonify({"success": True, "message": "Match deleted"})

@app.route('/api/rosters/player/<player_id>/stats')
@api_auth_required
def api_get_player_stats(player_id):
    """Get detailed stats for a specific player"""
    rosters = load_rosters()
    player = next((p for p in rosters.get("players", []) if str(p.get("discord_id")) == str(player_id)), None)
    
    if not player:
        return jsonify({"error": "Player not found"}), 404
    
    # Get match history for this player
    match_history = load_match_history()
    player_matches = [
        m for m in match_history.get("matches", [])
        if str(player_id) in [str(p.get("discord_id")) for p in m.get("players", [])]
    ]
    
    # Calculate additional stats
    stats = player.get("stats", {})
    total_matches = stats.get("matches_played", 0)
    wins = stats.get("wins", 0)
    
    win_rate = (wins / total_matches * 100) if total_matches > 0 else 0
    
    # Get recent form (last 5 matches)
    recent_matches = sorted(player_matches, key=lambda x: x.get("date", ""), reverse=True)[:5]
    recent_form = [m.get("result", "")[0].upper() if m.get("result") else "?" for m in recent_matches]
    
    # Get game-specific stats
    game_stats = player.get("game_stats", {})
    
    return jsonify({
        "player": player,
        "stats": {
            **stats,
            "win_rate": round(win_rate, 1),
            "recent_form": recent_form
        },
        "game_stats": game_stats,
        "recent_matches": recent_matches[:10],
        "total_matches_logged": len(player_matches)
    })

@app.route('/api/rosters/leaderboard')
@api_auth_required
def api_get_leaderboard():
    """Get player leaderboard based on various stats"""
    sort_by = request.args.get('sort', 'wins')  # wins, matches_played, win_rate, mvp_count
    game = request.args.get('game')
    team_id = request.args.get('team_id')
    limit = int(request.args.get('limit', 20))
    
    rosters = load_rosters()
    players = rosters.get("players", [])
    
    # Filter
    if game:
        players = [p for p in players if p.get("game", "").lower() == game.lower()]
    if team_id:
        players = [p for p in players if p.get("team_id") == team_id]
    
    # Calculate win rate for sorting
    for player in players:
        stats = player.get("stats", {})
        total = stats.get("matches_played", 0)
        wins = stats.get("wins", 0)
        player["_win_rate"] = (wins / total * 100) if total > 0 else 0
    
    # Sort
    sort_key_map = {
        "wins": lambda p: p.get("stats", {}).get("wins", 0),
        "matches_played": lambda p: p.get("stats", {}).get("matches_played", 0),
        "win_rate": lambda p: p.get("_win_rate", 0),
        "mvp_count": lambda p: p.get("stats", {}).get("mvp_count", 0)
    }
    
    sort_key = sort_key_map.get(sort_by, sort_key_map["wins"])
    players.sort(key=sort_key, reverse=True)
    
    # Clean up temp field
    for player in players:
        player.pop("_win_rate", None)
    
    return jsonify({
        "leaderboard": players[:limit],
        "sort_by": sort_by
    })

# ============ Sync Roles API ============

# ============ Job Progress Tracking API ============

@app.route('/api/jobs/progress/<job_id>')
@api_auth_required
def api_job_progress(job_id):
    """Get the current progress of a background job"""
    progress_data = load_json_file(JOB_PROGRESS_FILE, {})
    job = progress_data.get(job_id)
    
    if not job:
        return jsonify({"error": "Job not found", "status": "not_found"}), 404
    
    return jsonify(job)

@app.route('/api/jobs/progress')
@api_auth_required
def api_all_jobs_progress():
    """Get progress for all active jobs"""
    progress_data = load_json_file(JOB_PROGRESS_FILE, {})
    
    # Filter to only active/recent jobs (last 5 minutes)
    now = datetime.now(timezone.utc)
    active_jobs = {}
    for job_id, job in progress_data.items():
        try:
            job_time = datetime.fromisoformat(job.get('updated_at', job.get('started_at', '')).replace('Z', '+00:00'))
            if (now - job_time).total_seconds() < 300:  # 5 minutes
                active_jobs[job_id] = job
        except:
            pass
    
    return jsonify(active_jobs)

@app.route('/api/jobs/cleanup', methods=['POST'])
@api_auth_required
def api_cleanup_jobs():
    """Clean up old completed jobs"""
    progress_data = load_json_file(JOB_PROGRESS_FILE, {})
    now = datetime.now(timezone.utc)
    
    # Remove jobs older than 10 minutes that are completed
    cleaned = 0
    for job_id in list(progress_data.keys()):
        job = progress_data[job_id]
        try:
            job_time = datetime.fromisoformat(job.get('updated_at', job.get('started_at', '')).replace('Z', '+00:00'))
            is_old = (now - job_time).total_seconds() > 600  # 10 minutes
            is_done = job.get('status') in ('completed', 'failed')
            if is_old and is_done:
                del progress_data[job_id]
                cleaned += 1
        except:
            pass
    
    if cleaned > 0:
        save_json_file(JOB_PROGRESS_FILE, progress_data)
    
    return jsonify({"cleaned": cleaned})

@app.route('/api/rosters/sync-roles/preview', methods=['POST'])
@api_auth_required
@api_perm_required('rosters.sync_roles')
def api_sync_roles_preview():
    """Preview role sync changes without executing them"""
    data = request.json
    game_filter = data.get('game', 'all')
    type_filter = data.get('type', 'all')  # varsity, jv, or all
    
    # Load rosters, teams, and role settings
    rosters = load_rosters()
    teams_data = load_teams()
    teams = teams_data.get("teams", [])
    teams_by_id = {t.get("id"): t for t in teams}
    
    role_settings = load_json_file(TEAM_ROLE_SETTINGS_FILE, {
        "mapping": {},
        "varsity_role_id": None
    })
    
    players = rosters.get("players", [])
    role_mapping = role_settings.get("mapping", {})
    general_varsity_role = role_settings.get("varsity_role_id")  # This is now the general roster role for ALL players
    
    to_add = []
    to_remove = []
    
    # Build expected role assignments from roster
    expected_roles = {}  # user_id -> set of role_ids
    
    for player in players:
        user_id = str(player.get("discord_id"))
        if not user_id:
            continue
        
        # Get game from the player's assigned TEAM
        team_id = player.get("team_id")
        team = teams_by_id.get(team_id) if team_id else None
        
        # Skip players not assigned to any team
        if not team_id or not team:
            continue
        
        # Use team's game and type
        game = team.get("game", "")
        player_type = team.get("type", player.get("player_type", "")).lower()
        username = player.get("discord_name", player.get("name", user_id))
        team_name = team.get("name", "Unknown Team")
        
        # Apply filters based on team's game and type
        if game_filter != 'all' and game.lower() != game_filter.lower():
            continue
        if type_filter != 'all' and player_type != type_filter.lower():
            continue
        
        if user_id not in expected_roles:
            expected_roles[user_id] = {"roles": set(), "username": username}
        
        # Case-insensitive lookup for game roles
        game_roles = {}
        for mapping_game, roles in role_mapping.items():
            if mapping_game.lower() == game.lower():
                game_roles = roles
                break
        
        if player_type == "varsity" and game_roles.get("varsity"):
            expected_roles[user_id]["roles"].add(game_roles["varsity"])
            to_add.append({
                "user_id": user_id,
                "username": username,
                "role_id": game_roles["varsity"],
                "role_name": f"{game} Varsity",
                "game": game,
                "team_name": team_name,
                "type": "Varsity"
            })
        elif player_type == "jv" and game_roles.get("jv"):
            expected_roles[user_id]["roles"].add(game_roles["jv"])
            to_add.append({
                "user_id": user_id,
                "username": username,
                "role_id": game_roles["jv"],
                "role_name": f"{game} JV",
                "game": game,
                "team_name": team_name,
                "type": "JV"
            })
        
        # ALL roster players get the general roster role (regardless of varsity/jv)
        if general_varsity_role:
            expected_roles[user_id]["roles"].add(general_varsity_role)
            to_add.append({
                "user_id": user_id,
                "username": username,
                "role_id": general_varsity_role,
                "role_name": "Esports Team",
                "game": game,
                "team_name": team_name,
                "type": "Roster (General)"
            })
    
    # Note: The actual check for which users have roles and which don't 
    # would require Discord API access. For now, we show what WOULD be synced.
    # The bot will handle the actual Discord role checks during execution.
    
    return jsonify({
        "success": True,
        "to_add": to_add,
        "to_remove": [],  # Bot will determine this based on current Discord roles
        "message": "Preview generated. Execute sync to apply changes via Discord bot."
    })

@app.route('/api/rosters/sync-roles/execute', methods=['POST'])
@api_auth_required
@api_perm_required('rosters.sync_roles')
def api_sync_roles_execute():
    """Queue a role sync command for the Discord bot to execute"""
    import uuid
    
    data = request.json
    game_filter = data.get('game', 'all')
    type_filter = data.get('type', 'all')
    allow_removal = data.get('allow_removal', False)  # Must explicitly opt-in to role removal
    
    # Generate unique job ID
    job_id = f"sync_{uuid.uuid4().hex[:12]}"
    
    # Load rosters and teams for processing
    rosters = load_rosters()
    teams_data = load_teams()
    teams = teams_data.get("teams", [])
    
    # Build team lookup by ID
    teams_by_id = {t.get("id"): t for t in teams}
    
    role_settings = load_json_file(TEAM_ROLE_SETTINGS_FILE, {
        "mapping": {},
        "varsity_role_id": None,
        "captain_role_id": None
    })
    
    players = rosters.get("players", [])
    role_mapping = role_settings.get("mapping", {})
    general_varsity_role = role_settings.get("varsity_role_id")  # This is now the general roster role for ALL players
    captain_role_id = role_settings.get("captain_role_id")  # Role for team captains
    
    # Build sync data with job_id for progress tracking
    sync_data = {
        "type": "bulk_sync_team_roles",
        "job_id": job_id,  # For progress tracking
        "status": "pending",  # CRITICAL: Must be 'pending' for bot to process
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "game_filter": game_filter,
        "type_filter": type_filter,
        "players": [],
        "role_mapping": role_mapping,
        "general_varsity_role": general_varsity_role,  # This is now the general roster role for ALL players
        "captain_role_id": captain_role_id,  # Role for team captains
        "allow_removal": allow_removal  # Only remove roles if explicitly confirmed by user
    }
    
    for player in players:
        user_id = str(player.get("discord_id"))
        if not user_id:
            continue
        
        # Get game from the player's assigned TEAM, not from player record
        team_id = player.get("team_id")
        team = teams_by_id.get(team_id) if team_id else None
        
        # Use team's game if available, fall back to player's game field
        game = team.get("game", "") if team else player.get("game", "")
        
        # Use team's type if available, fall back to player's type
        player_type = (team.get("type", "") if team else player.get("player_type", "")).lower()
        if not player_type:
            player_type = player.get("player_type", "").lower()
        
        # Skip players not assigned to any team
        if not team_id:
            print(f"[SYNC] Skipping player {user_id} - not assigned to any team")
            continue
        
        # Apply filters based on team's game and type
        if game_filter != 'all' and game.lower() != game_filter.lower():
            continue
        if type_filter != 'all' and player_type != type_filter.lower():
            continue
        
        player_roles = []
        
        # Case-insensitive lookup for game roles
        game_roles = {}
        for mapping_game, roles in role_mapping.items():
            if mapping_game.lower() == game.lower():
                game_roles = roles
                break
        
        # Add game-specific role based on player type
        if player_type == "varsity":
            if game_roles.get("varsity"):
                player_roles.append(game_roles["varsity"])
        elif player_type == "jv":
            if game_roles.get("jv"):
                player_roles.append(game_roles["jv"])
        
        # ALL roster players get the general roster role (regardless of varsity/jv)
        if general_varsity_role:
            player_roles.append(general_varsity_role)
        
        # Captains get the captain role
        is_captain = player.get("is_captain", False)
        if is_captain and captain_role_id:
            player_roles.append(captain_role_id)
        
        if player_roles:
            sync_data["players"].append({
                "user_id": user_id,
                "username": player.get("discord_name", player.get("name")),
                "game": game,
                "team_name": team.get("name", "Unknown") if team else "Unknown",
                "player_type": player_type,
                "is_captain": is_captain,
                "expected_roles": player_roles
            })
        else:
            print(f"[SYNC] Warning: Player {user_id} on team {team.get('name') if team else 'Unknown'} (game: {game}, type: {player_type}) has no matching role mapping")
    
    # Queue for bot to process (thread-safe)
    queue_file = os.path.join(DATA_DIR, "discord_notification_queue.json")
    safe_queue_append(queue_file, sync_data)
    
    # Initialize job progress tracking (thread-safe via RLock)
    progress_data = load_json_file(JOB_PROGRESS_FILE, {})
    progress_data[job_id] = {
        "job_id": job_id,
        "type": "role_sync",
        "status": "queued",
        "game_filter": game_filter,
        "type_filter": type_filter,
        "total_players": len(sync_data["players"]),
        "total_operations": 0,  # Will be calculated by bot (adds + removes)
        "completed_operations": 0,
        "added_count": 0,
        "removed_count": 0,
        "skipped_count": 0,
        "errors": [],
        "current_step": "Waiting for bot to start processing...",
        "current_player": None,
        "rate_limit_cooldown": False,
        "rate_limit_wait_until": None,
        "queued_at": datetime.now(timezone.utc).isoformat(),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None
    }
    save_json_file(JOB_PROGRESS_FILE, progress_data)
    
    # Log the action
    add_audit_log("role_sync_queued", None, f"Role sync queued for {len(sync_data['players'])} players (game: {game_filter}, type: {type_filter})")
    
    return jsonify({
        "success": True,
        "job_id": job_id,
        "message": f"Role sync queued for {len(sync_data['players'])} players",
        "player_count": len(sync_data["players"]),
        "roles_added": len(sync_data["players"]),  # Estimated
        "roles_removed": 0  # Bot will handle removal
    })

# ============ Team Announcements & Notifications API ============

ANNOUNCEMENTS_FILE = os.path.join(DATA_DIR, "team_announcements.json")
NOTIFICATION_SETTINGS_FILE = os.path.join(DATA_DIR, "notification_settings.json")

def load_announcements():
    return load_json_file(ANNOUNCEMENTS_FILE, {"announcements": []})

def save_announcements(data):
    save_json_file(ANNOUNCEMENTS_FILE, data)

def load_notification_settings():
    return load_json_file(NOTIFICATION_SETTINGS_FILE, {
        "discord_webhook_url": "",
        "roster_change_notifications": True,
        "match_notifications": True,
        "announcement_notifications": True
    })

def save_notification_settings(data):
    save_json_file(NOTIFICATION_SETTINGS_FILE, data)

@app.route('/api/rosters/announcements', methods=['GET'])
@api_auth_required
def api_get_announcements():
    """Get team announcements"""
    team_id = request.args.get('team_id')
    limit = int(request.args.get('limit', 20))
    
    announcements = load_announcements()
    items = announcements.get("announcements", [])
    
    if team_id:
        items = [a for a in items if a.get("team_id") == team_id or a.get("team_id") == "all"]
    
    # Sort by date descending
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    
    return jsonify({
        "announcements": items[:limit],
        "total": len(items)
    })

@app.route('/api/rosters/announcements', methods=['POST'])
@api_auth_required
@api_perm_required('rosters.announcements')
def api_create_announcement():
    """Create a team announcement and send notifications"""
    data = request.json
    
    if not data.get("title"):
        return jsonify({"error": "Title is required"}), 400
    if not data.get("message"):
        return jsonify({"error": "Message is required"}), 400
    
    announcements = load_announcements()
    items = announcements.get("announcements", [])
    
    announcement_id = f"ann_{datetime.now().strftime('%Y%m%d%H%M%S')}_{len(items)}"
    
    announcement = {
        "id": announcement_id,
        "title": data.get("title"),
        "message": data.get("message"),
        "team_id": data.get("team_id", "all"),
        "priority": data.get("priority", "normal"),
        "category": data.get("category", "general"),
        "image_url": data.get("image_url"),
        "link_text": data.get("link_text"),
        "link_url": data.get("link_url"),
        "created_by": session.get('user_name', 'Dashboard Admin'),
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    items.append(announcement)
    announcements["announcements"] = items
    save_announcements(announcements)
    
    # Queue Discord notifications
    notification_settings = load_notification_settings()
    
    if notification_settings.get("announcement_notifications"):
        # Queue notification for Discord bot to send (thread-safe)
        queue_file = os.path.join(DATA_DIR, "discord_notification_queue.json")
        
        # Use provided player_ids if available, otherwise calculate from team_id
        player_ids = data.get("player_ids")
        if not player_ids:
            rosters = load_rosters()
            players_to_notify = rosters.get("players", [])
            
            if data.get("team_id") and data.get("team_id") != "all":
                players_to_notify = [p for p in players_to_notify if p.get("team_id") == data.get("team_id")]
            
            player_ids = [p.get("discord_id") for p in players_to_notify]
        
        # Add to notification queue with status tracking and all options
        safe_queue_append(queue_file, {
            "type": "team_announcement",
            "status": "pending",
            "announcement_id": announcement_id,
            "title": data.get("title"),
            "message": data.get("message"),
            "priority": data.get("priority", "normal"),
            "category": data.get("category", "general"),
            "team_id": data.get("team_id", "all"),
            "player_ids": player_ids,
            "image_url": data.get("image_url"),
            "link_text": data.get("link_text"),
            "link_url": data.get("link_url"),
            "send_discord_dm": data.get("send_discord_dm", False),
            "send_webhook": data.get("send_webhook", True),
            "pin_message": data.get("pin_message", False),
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
    
    add_audit_log("announcement_created", announcement_id, f"Created announcement: {data.get('title')}")
    
    return jsonify({"success": True, "message": "Announcement created", "announcement_id": announcement_id})

@app.route('/api/rosters/announcements/<announcement_id>', methods=['DELETE'])
@api_auth_required
@api_perm_required('rosters.announcements')
def api_delete_announcement(announcement_id):
    """Delete an announcement"""
    announcements = load_announcements()
    items = announcements.get("announcements", [])
    
    announcement = next((a for a in items if a.get("id") == announcement_id), None)
    if not announcement:
        return jsonify({"error": "Announcement not found"}), 404
    
    announcements["announcements"] = [a for a in items if a.get("id") != announcement_id]
    save_announcements(announcements)
    
    add_audit_log("announcement_deleted", announcement_id, f"Deleted announcement: {announcement.get('title')}")
    
    return jsonify({"success": True, "message": "Announcement deleted"})

@app.route('/api/rosters/notification-settings', methods=['GET'])
@api_auth_required
def api_get_notification_settings():
    """Get notification settings"""
    return jsonify(load_notification_settings())

@app.route('/api/rosters/notification-settings', methods=['POST'])
@api_auth_required
def api_update_notification_settings():
    """Update notification settings"""
    data = request.json
    settings = load_notification_settings()
    
    if "discord_webhook_url" in data:
        settings["discord_webhook_url"] = data["discord_webhook_url"]
    if "roster_change_notifications" in data:
        settings["roster_change_notifications"] = data["roster_change_notifications"]
    if "match_notifications" in data:
        settings["match_notifications"] = data["match_notifications"]
    if "announcement_notifications" in data:
        settings["announcement_notifications"] = data["announcement_notifications"]
    
    save_notification_settings(settings)
    add_audit_log("settings_updated", None, "Updated notification settings")
    
    return jsonify({"success": True, "message": "Settings updated"})

@app.route('/api/rosters/send-webhook', methods=['POST'])
@api_auth_required
def api_send_webhook():
    """Send a Discord webhook notification immediately"""
    import requests as http_requests
    
    data = request.json
    settings = load_notification_settings()
    
    webhook_url = data.get("webhook_url") or settings.get("discord_webhook_url")
    
    if not webhook_url:
        return jsonify({"error": "No webhook URL configured"}), 400
    
    # Build Discord embed
    embed = {
        "title": data.get("title", "Team Announcement"),
        "description": data.get("message", ""),
        "color": data.get("color", 0xD4AF37),  # Gold color
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "footer": {
            "text": "PNW eSports Team Management"
        }
    }
    
    if data.get("team_name"):
        embed["author"] = {"name": data.get("team_name")}
    
    payload = {
        "embeds": [embed],
        "username": "PNW eSports Bot"
    }
    
    try:
        response = http_requests.post(webhook_url, json=payload, timeout=10)
        if response.status_code in [200, 204]:
            return jsonify({"success": True, "message": "Webhook sent successfully"})
        else:
            return jsonify({"error": f"Webhook failed: {response.status_code}"}), 500
    except Exception as e:
        return jsonify({"error": f"Webhook error: {str(e)}"}), 500

@app.route('/api/rosters/dm-players', methods=['POST'])
@api_auth_required
@api_perm_required('rosters.dm_players')
def api_dm_players():
    """Queue Discord DM to selected players"""
    data = request.json
    player_ids = data.get("player_ids", [])
    message = data.get("message")
    title = data.get("title", "Team Message")
    
    if not player_ids:
        return jsonify({"error": "No players selected"}), 400
    if not message:
        return jsonify({"error": "Message is required"}), 400
    
    # Queue DM for bot to send (thread-safe)
    queue_file = os.path.join(DATA_DIR, "discord_notification_queue.json")
    safe_queue_append(queue_file, {
        "type": "bulk_dm",
        "player_ids": player_ids,
        "title": title,
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    add_audit_log("dm_queued", None, f"Queued DM to {len(player_ids)} players")
    
    return jsonify({"success": True, "message": f"DM queued for {len(player_ids)} players"})

# ============ CSV Export/Import API Endpoints ============

@app.route('/api/rosters/export/csv')
@api_auth_required
@api_perm_required('rosters.import_export')
def api_export_rosters_csv():
    """Export roster data as CSV"""
    export_type = request.args.get('type', 'players')  # 'players' or 'teams'
    
    if export_type == 'players':
        rosters = load_rosters()
        teams_data = load_teams()
        teams_map = {t.get("id"): t.get("name") for t in teams_data.get("teams", [])}
        
        # Build a map of academic info from varsity registration files
        academic_map = {}  # discord_id -> {hometown, major, year_in_school}
        if os.path.exists(VARSITY_REG_DIR):
            for fname in os.listdir(VARSITY_REG_DIR):
                if fname.endswith("_varsity.json"):
                    uid = fname.replace("_varsity.json", "")
                    try:
                        with open(os.path.join(VARSITY_REG_DIR, fname), 'r', encoding='utf-8') as f:
                            records = json.load(f)
                        if isinstance(records, list):
                            # Use latest approved registration, fallback to latest overall
                            approved = [r for r in records if r.get("status", "").lower() == "approved"]
                            reg = approved[-1] if approved else records[-1]
                        else:
                            reg = records
                        d = reg.get("data", {})
                        academic_map[uid] = {
                            "hometown": d.get("Home Town/City (State)", ""),
                            "major": d.get("Major", ""),
                            "year_in_school": d.get("Year in School", "")
                        }
                    except:
                        pass
        
        # Build CSV
        headers = ["Discord ID", "Full Name", "Player Type", "Status", "Game", "IGN", "Rank", 
                   "Role", "Secondary Role", "Team", "Is Captain", "Purdue Email", "Personal Email", "Tracker", 
                   "Hometown", "Major", "Year in School",
                   "Availability", "Status Notes", "Created At", "Updated At"]
        
        rows = [headers]
        for player in rosters.get("players", []):
            team_name = teams_map.get(player.get("team_id"), "")
            acad = academic_map.get(str(player.get("discord_id", "")), {})
            rows.append([
                player.get("discord_id", ""),
                player.get("full_name", ""),
                player.get("player_type", ""),
                player.get("status", "active"),
                player.get("game", ""),
                player.get("ign", ""),
                player.get("rank", ""),
                player.get("role", ""),
                player.get("secondary_role", ""),
                team_name,
                "Yes" if player.get("is_captain") else "No",
                player.get("purdue_email", ""),
                player.get("personal_email", ""),
                player.get("tracker", ""),
                acad.get("hometown", ""),
                acad.get("major", ""),
                acad.get("year_in_school", ""),
                player.get("availability", ""),
                player.get("status_notes", ""),
                player.get("created_at", ""),
                player.get("updated_at", "")
            ])
        
        # Convert to CSV string
        import io
        import csv
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerows(rows)
        csv_content = output.getvalue()
        
        add_audit_log("export", None, f"Exported {len(rows) - 1} players to CSV")
        
        from flask import Response
        return Response(
            csv_content,
            mimetype='text/csv',
            headers={"Content-Disposition": f"attachment;filename=roster_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"}
        )
    
    elif export_type == 'teams':
        teams_data = load_teams()
        rosters = load_rosters()
        
        # Count players per team
        team_player_counts = {}
        for player in rosters.get("players", []):
            tid = player.get("team_id")
            if tid:
                team_player_counts[tid] = team_player_counts.get(tid, 0) + 1
        
        headers = ["Team ID", "Team Name", "Game", "Type", "Color", "Player Count", "Description", "Created At"]
        
        rows = [headers]
        for team in teams_data.get("teams", []):
            rows.append([
                team.get("id", ""),
                team.get("name", ""),
                team.get("game", ""),
                team.get("type", ""),
                team.get("color", ""),
                team_player_counts.get(team.get("id"), 0),
                team.get("description", ""),
                team.get("created_at", "")
            ])
        
        import io
        import csv
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerows(rows)
        csv_content = output.getvalue()
        
        add_audit_log("export", None, f"Exported {len(rows) - 1} teams to CSV")
        
        from flask import Response
        return Response(
            csv_content,
            mimetype='text/csv',
            headers={"Content-Disposition": f"attachment;filename=teams_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"}
        )
    
    return jsonify({"error": "Invalid export type"}), 400

@app.route('/api/rosters/import/csv', methods=['POST'])
@api_auth_required
@api_perm_required('rosters.import_export')
def api_import_rosters_csv():
    """Import roster data from CSV"""
    import io
    import csv
    
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400
    
    if not file.filename.endswith('.csv'):
        return jsonify({"error": "File must be a CSV"}), 400
    
    import_type = request.form.get('type', 'players')
    mode = request.form.get('mode', 'merge')  # 'merge' or 'replace'
    
    try:
        content = file.read().decode('utf-8')
        reader = csv.DictReader(io.StringIO(content))
        
        if import_type == 'players':
            rosters = load_rosters() if mode == 'merge' else {"players": []}
            existing_ids = {str(p.get("discord_id")) for p in rosters.get("players", [])}
            
            imported_count = 0
            updated_count = 0
            
            for row in reader:
                discord_id = row.get("Discord ID", "").strip()
                if not discord_id:
                    continue
                
                player_data = {
                    "discord_id": discord_id,
                    "full_name": row.get("Full Name", ""),
                    "player_type": row.get("Player Type", "varsity").lower(),
                    "status": row.get("Status", "active").lower(),
                    "game": row.get("Game", ""),
                    "ign": row.get("IGN", ""),
                    "rank": row.get("Rank", ""),
                    "is_captain": row.get("Is Captain", "").lower() in ["yes", "true", "1"],
                    "purdue_email": row.get("Purdue Email", ""),
                    "personal_email": row.get("Personal Email", ""),
                    "tracker": row.get("Tracker", ""),
                    "availability": row.get("Availability", ""),
                    "status_notes": row.get("Status Notes", ""),
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }
                
                if discord_id in existing_ids:
                    # Update existing
                    for player in rosters.get("players", []):
                        if str(player.get("discord_id")) == discord_id:
                            player.update(player_data)
                            updated_count += 1
                            break
                else:
                    # Add new
                    player_data["created_at"] = datetime.now(timezone.utc).isoformat()
                    rosters.setdefault("players", []).append(player_data)
                    existing_ids.add(discord_id)
                    imported_count += 1
            
            save_rosters(rosters)
            add_audit_log("import", None, f"Imported {imported_count} new players, updated {updated_count} existing (mode: {mode})")
            
            return jsonify({
                "success": True,
                "message": f"Imported {imported_count} new players, updated {updated_count} existing",
                "imported": imported_count,
                "updated": updated_count
            })
        
        elif import_type == 'teams':
            teams_data = load_teams() if mode == 'merge' else {"teams": []}
            existing_ids = {t.get("id") for t in teams_data.get("teams", [])}
            
            imported_count = 0
            
            for row in reader:
                team_name = row.get("Team Name", "").strip()
                if not team_name:
                    continue
                
                team_id = row.get("Team ID", "").strip()
                if not team_id:
                    team_id = f"team_{len(teams_data.get('teams', [])) + 1}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                
                if team_id in existing_ids:
                    continue  # Skip existing teams
                
                teams_data.setdefault("teams", []).append({
                    "id": team_id,
                    "name": team_name,
                    "game": row.get("Game", ""),
                    "type": row.get("Type", "varsity").lower(),
                    "color": row.get("Color", "#d4af37"),
                    "description": row.get("Description", ""),
                    "created_at": datetime.now(timezone.utc).isoformat()
                })
                existing_ids.add(team_id)
                imported_count += 1
            
            save_teams(teams_data)
            add_audit_log("import", None, f"Imported {imported_count} teams (mode: {mode})")
            
            return jsonify({
                "success": True,
                "message": f"Imported {imported_count} teams",
                "imported": imported_count
            })
        
        return jsonify({"error": "Invalid import type"}), 400
        
    except Exception as e:
        return jsonify({"error": f"Import failed: {str(e)}"}), 500

# ============ VC Generators API ============

def load_vc_generators():
    """Load VC generator configuration"""
    return load_json_file(VC_GENERATORS_FILE, {"normal": [], "tryout": []})

def save_vc_generators(data):
    """Save VC generator configuration"""
    save_json_file(VC_GENERATORS_FILE, data)

def load_vc_live_cache():
    """Load live VC cache (populated by bot)"""
    return load_json_file(VC_LIVE_CACHE_FILE, {
        "generators": {"normal": [], "tryout": []},
        "active_vcs": [],
        "stats": {"total_users": 0, "active_vcs": 0, "normal_generators": 0, "tryout_generators": 0},
        "last_updated": None
    })

@app.route('/api/vc-generators')
@api_auth_required
def api_get_vc_generators():
    """Get VC generator configuration (raw IDs)"""
    generators = load_vc_generators()
    return jsonify(generators)

@app.route('/api/vc-generators/live')
@api_auth_required
def api_get_vc_generators_live():
    """Get live VC data including active channels and members"""
    cache = load_vc_live_cache()
    return jsonify(cache)

@app.route('/api/vc-generators/kick', methods=['POST'])
@api_auth_required
@api_perm_required('vc.kick_users')
def api_vc_kick_user():
    """Queue a kick user from VC action"""
    data = request.json
    user_id = data.get('user_id')
    channel_id = data.get('channel_id')
    reason = data.get('reason', 'Kicked by dashboard')
    
    if not user_id or not channel_id:
        return jsonify({"success": False, "error": "User ID and Channel ID required"}), 400
    
    queue_discord_notification({
        'type': 'vc_kick_user',
        'user_id': str(user_id),
        'channel_id': str(channel_id),
        'reason': reason,
        'moderator': get_moderator_name(),
        'moderator_id': get_moderator_id()
    })
    
    log_activity(
        action="vc_kick",
        category="voice",
        details=f"Queued kick user {user_id} from VC {channel_id}: {reason}",
        target_id=user_id,
        success=True
    )
    
    return jsonify({"success": True})

@app.route('/api/vc-generators/move', methods=['POST'])
@api_auth_required
@api_perm_required('vc.move_users')
def api_vc_move_user():
    """Queue a move user to another VC action"""
    data = request.json
    user_id = data.get('user_id')
    target_channel_id = data.get('target_channel_id')
    
    if not user_id or not target_channel_id:
        return jsonify({"success": False, "error": "User ID and Target Channel ID required"}), 400
    
    queue_discord_notification({
        'type': 'vc_move_user',
        'user_id': str(user_id),
        'target_channel_id': str(target_channel_id),
        'moderator': get_moderator_name(),
        'moderator_id': get_moderator_id()
    })
    
    log_activity(
        action="vc_move",
        category="voice",
        details=f"Queued move user {user_id} to VC {target_channel_id}",
        target_id=user_id,
        success=True
    )
    
    return jsonify({"success": True})

@app.route('/api/vc-generators/lock', methods=['POST'])
@api_auth_required
@api_perm_required('vc.manage_channels')
def api_vc_lock():
    """Queue a lock/unlock VC action"""
    data = request.json
    channel_id = data.get('channel_id')
    lock = data.get('lock', True)
    
    if not channel_id:
        return jsonify({"success": False, "error": "Channel ID required"}), 400
    
    queue_discord_notification({
        'type': 'vc_lock',
        'channel_id': str(channel_id),
        'lock': lock,
        'moderator': get_moderator_name(),
        'moderator_id': get_moderator_id()
    })
    
    log_activity(
        action="vc_lock" if lock else "vc_unlock",
        category="voice",
        details=f"Queued {'lock' if lock else 'unlock'} VC {channel_id}",
        target_id=channel_id,
        success=True
    )
    
    return jsonify({"success": True})

@app.route('/api/vc-generators/limit', methods=['POST'])
@api_auth_required
@api_perm_required('vc.manage_channels')
def api_vc_set_limit():
    """Queue a set user limit action"""
    data = request.json
    channel_id = data.get('channel_id')
    limit = data.get('limit', 0)
    
    if not channel_id:
        return jsonify({"success": False, "error": "Channel ID required"}), 400
    
    queue_discord_notification({
        'type': 'vc_set_limit',
        'channel_id': str(channel_id),
        'limit': int(limit),
        'moderator': get_moderator_name(),
        'moderator_id': get_moderator_id()
    })
    
    log_activity(
        action="vc_limit",
        category="voice",
        details=f"Queued set VC {channel_id} limit to {limit}",
        target_id=channel_id,
        success=True
    )
    
    return jsonify({"success": True})

@app.route('/api/vc-generators/delete', methods=['POST'])
@api_auth_required
@api_perm_required('vc.manage_channels')
def api_vc_delete():
    """Queue a delete VC action"""
    data = request.json
    channel_id = data.get('channel_id')
    
    if not channel_id:
        return jsonify({"success": False, "error": "Channel ID required"}), 400
    
    queue_discord_notification({
        'type': 'vc_delete',
        'channel_id': str(channel_id),
        'moderator': get_moderator_name(),
        'moderator_id': get_moderator_id()
    })
    
    log_activity(
        action="vc_delete",
        category="voice",
        details=f"Queued delete VC {channel_id}",
        target_id=channel_id,
        success=True
    )
    
    return jsonify({"success": True})

@app.route('/api/vc-generators/rename', methods=['POST'])
@api_auth_required
@api_perm_required('vc.manage_channels')
def api_vc_rename():
    """Queue a rename VC action"""
    data = request.json
    channel_id = data.get('channel_id')
    new_name = data.get('name')
    
    if not channel_id or not new_name:
        return jsonify({"success": False, "error": "Channel ID and new name required"}), 400
    
    queue_discord_notification({
        'type': 'vc_rename',
        'channel_id': str(channel_id),
        'name': new_name,
        'moderator': get_moderator_name(),
        'moderator_id': get_moderator_id()
    })
    
    log_activity(
        action="vc_rename",
        category="voice",
        details=f"Queued rename VC {channel_id} to '{new_name}'",
        target_id=channel_id,
        success=True
    )
    
    return jsonify({"success": True})

@app.route('/api/vc-generators/hide', methods=['POST'])
@api_auth_required
@api_perm_required('vc.manage_channels')
def api_vc_hide():
    """Queue a hide/unhide VC action"""
    data = request.json
    channel_id = data.get('channel_id')
    hide = data.get('hide', True)
    
    if not channel_id:
        return jsonify({"success": False, "error": "Channel ID required"}), 400
    
    queue_discord_notification({
        'type': 'vc_hide',
        'channel_id': str(channel_id),
        'hide': hide,
        'moderator': get_moderator_name(),
        'moderator_id': get_moderator_id()
    })
    
    log_activity(
        action="vc_hide" if hide else "vc_unhide",
        category="voice",
        details=f"Queued {'hide' if hide else 'unhide'} VC {channel_id}",
        target_id=channel_id,
        success=True
    )
    
    return jsonify({"success": True})

@app.route('/api/vc-generators/remove', methods=['POST'])
@api_auth_required
@api_perm_required('vc.manage_generators')
def api_remove_generator():
    """Remove a channel from VC generators (doesn't delete the channel)"""
    data = request.json
    channel_id = data.get('channel_id')
    gen_type = data.get('type', 'normal')
    
    if not channel_id:
        return jsonify({"success": False, "error": "Channel ID required"}), 400
    
    generators = load_vc_generators()
    
    try:
        channel_id_int = int(channel_id)
        if gen_type == 'normal' and channel_id_int in generators.get('normal', []):
            generators['normal'].remove(channel_id_int)
        elif gen_type == 'tryout' and channel_id_int in generators.get('tryout', []):
            generators['tryout'].remove(channel_id_int)
        else:
            return jsonify({"success": False, "error": "Generator not found"}), 404
        
        save_vc_generators(generators)
        
        log_activity(
            action="vc_generator_remove",
            category="admin",
            details=f"Removed {gen_type} VC generator {channel_id}",
            success=True
        )
        
        return jsonify({"success": True})
    except ValueError:
        return jsonify({"success": False, "error": "Invalid channel ID"}), 400

@app.route('/api/vc-generators/add', methods=['POST'])
@api_auth_required
@api_perm_required('vc.manage_generators')
def api_add_generator():
    """Add a channel as a VC generator"""
    data = request.json
    channel_id = data.get('channel_id')
    gen_type = data.get('type', 'normal')
    
    if not channel_id:
        return jsonify({"success": False, "error": "Channel ID required"}), 400
    
    generators = load_vc_generators()
    
    try:
        channel_id_int = int(channel_id)
        if gen_type == 'normal':
            if channel_id_int not in generators.get('normal', []):
                generators.setdefault('normal', []).append(channel_id_int)
        elif gen_type == 'tryout':
            if channel_id_int not in generators.get('tryout', []):
                generators.setdefault('tryout', []).append(channel_id_int)
        
        save_vc_generators(generators)
        
        log_activity(
            action="vc_generator_add",
            category="admin",
            details=f"Added {gen_type} VC generator {channel_id}",
            success=True
        )
        
        return jsonify({"success": True})
    except ValueError:
        return jsonify({"success": False, "error": "Invalid channel ID"}), 400

# ============ Moderation Templates API ============

def load_moderation_templates():
    """Load moderation templates from file"""
    return load_json_file(MODERATION_TEMPLATES_FILE, {"templates": [], "categories": [], "custom_templates": []})

def save_moderation_templates(data):
    """Save moderation templates to file"""
    save_json_file(MODERATION_TEMPLATES_FILE, data)

@app.route('/api/moderation/templates')
@api_auth_required
def api_get_templates():
    """Get all moderation reason templates"""
    templates_data = load_moderation_templates()
    
    # Combine built-in and custom templates
    all_templates = templates_data.get("templates", []) + templates_data.get("custom_templates", [])
    
    # Optional filtering
    category = request.args.get('category')
    action = request.args.get('action')
    
    if category:
        all_templates = [t for t in all_templates if t.get('category', '').lower() == category.lower()]
    if action:
        all_templates = [t for t in all_templates if t.get('suggested_action') == action]
    
    return jsonify({
        "templates": all_templates,
        "categories": templates_data.get("categories", [])
    })

@app.route('/api/moderation/templates', methods=['POST'])
@api_auth_required
@api_perm_required('moderation.templates')
def api_create_template():
    """Create a custom moderation template"""
    data = request.json
    
    if not data.get('name') or not data.get('reason'):
        return jsonify({"error": "Name and reason are required"}), 400
    
    templates_data = load_moderation_templates()
    
    # Generate unique ID
    import uuid
    template_id = f"custom_{uuid.uuid4().hex[:8]}"
    
    new_template = {
        "id": template_id,
        "name": data.get('name'),
        "category": data.get('category', 'Custom'),
        "reason": data.get('reason'),
        "severity": data.get('severity', 'warning'),
        "suggested_action": data.get('suggested_action', 'warn'),
        "color": data.get('color', '#6b7280'),
        "is_custom": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": get_moderator_name()
    }
    
    templates_data.setdefault("custom_templates", []).append(new_template)
    save_moderation_templates(templates_data)
    
    log_activity(
        action="template_created",
        category="admin",
        details=f"Created moderation template: {new_template['name']}",
        success=True
    )
    
    return jsonify({"success": True, "template": new_template})

@app.route('/api/moderation/templates/<template_id>', methods=['PUT'])
@api_auth_required
@api_perm_required('moderation.templates')
def api_update_template(template_id):
    """Update a custom moderation template"""
    data = request.json
    templates_data = load_moderation_templates()
    
    # Only allow editing custom templates
    for i, template in enumerate(templates_data.get("custom_templates", [])):
        if template.get("id") == template_id:
            templates_data["custom_templates"][i].update({
                "name": data.get('name', template.get('name')),
                "category": data.get('category', template.get('category')),
                "reason": data.get('reason', template.get('reason')),
                "severity": data.get('severity', template.get('severity')),
                "suggested_action": data.get('suggested_action', template.get('suggested_action')),
                "color": data.get('color', template.get('color')),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "updated_by": get_moderator_name()
            })
            save_moderation_templates(templates_data)
            return jsonify({"success": True, "template": templates_data["custom_templates"][i]})
    
    return jsonify({"error": "Template not found or cannot be edited"}), 404

@app.route('/api/moderation/templates/<template_id>', methods=['DELETE'])
@api_auth_required
@api_perm_required('moderation.templates')
def api_delete_template(template_id):
    """Delete a custom moderation template"""
    templates_data = load_moderation_templates()
    
    # Only allow deleting custom templates
    original_count = len(templates_data.get("custom_templates", []))
    templates_data["custom_templates"] = [
        t for t in templates_data.get("custom_templates", []) 
        if t.get("id") != template_id
    ]
    
    if len(templates_data["custom_templates"]) < original_count:
        save_moderation_templates(templates_data)
        log_activity(
            action="template_deleted",
            category="admin",
            details=f"Deleted moderation template: {template_id}",
            success=True
        )
        return jsonify({"success": True})
    
    return jsonify({"error": "Template not found or cannot be deleted"}), 404

# ============ Watchlist API ============

def load_watchlist():
    """Load watchlist from file"""
    return load_json_file(WATCHLIST_FILE, {"watched_users": [], "settings": {}})

def save_watchlist(data):
    """Save watchlist to file"""
    save_json_file(WATCHLIST_FILE, data)

def is_user_watched(user_id):
    """Check if a user is on the watchlist"""
    watchlist = load_watchlist()
    return any(str(u.get('user_id')) == str(user_id) for u in watchlist.get('watched_users', []))

def get_watched_user(user_id):
    """Get watchlist entry for a user"""
    watchlist = load_watchlist()
    for user in watchlist.get('watched_users', []):
        if str(user.get('user_id')) == str(user_id):
            return user
    return None

@app.route('/api/watchlist')
@api_auth_required
def api_get_watchlist():
    """Get all watched users"""
    watchlist = load_watchlist()
    watched_users = watchlist.get('watched_users', [])
    
    # Enrich with member data
    members = load_json_file(MEMBERS_CACHE_FILE, [])
    members_dict = {str(m.get('id')): m for m in members}
    
    enriched_users = []
    for watched in watched_users:
        user_id = str(watched.get('user_id'))
        member = members_dict.get(user_id, {})
        enriched_users.append({
            **watched,
            "username": member.get('name') or member.get('username') or 'Unknown',
            "display_name": member.get('display_name') or member.get('name') or 'Unknown',
            "avatar": member.get('avatar') or member.get('avatar_url'),
            "in_server": user_id in members_dict
        })
    
    return jsonify({
        "watched_users": enriched_users,
        "settings": watchlist.get('settings', {}),
        "total": len(enriched_users)
    })

@app.route('/api/watchlist/check/<user_id>')
@api_auth_required
def api_check_watchlist(user_id):
    """Check if a specific user is on the watchlist"""
    watched = get_watched_user(user_id)
    return jsonify({
        "is_watched": watched is not None,
        "watchlist_entry": watched
    })

@app.route('/api/watchlist', methods=['POST'])
@api_auth_required
@api_perm_required('moderation.watchlist')
def api_add_to_watchlist():
    """Add a user to the watchlist"""
    data = request.json
    user_id = data.get('user_id')
    reason = data.get('reason', 'No reason provided')
    notes = data.get('notes', '')
    alert_level = data.get('alert_level', 'normal')  # low, normal, high
    
    if not user_id:
        return jsonify({"error": "User ID is required"}), 400
    
    watchlist = load_watchlist()
    
    # Check if already watched
    if is_user_watched(user_id):
        return jsonify({"error": "User is already on the watchlist"}), 400
    
    # Get user info from members cache
    members = load_json_file(MEMBERS_CACHE_FILE, [])
    member = next((m for m in members if str(m.get('id')) == str(user_id)), None)
    
    watch_entry = {
        "user_id": str(user_id),
        "username": member.get('name') if member else None,
        "reason": reason,
        "notes": notes,
        "alert_level": alert_level,
        "added_at": datetime.now(timezone.utc).isoformat(),
        "added_by": get_moderator_name(),
        "added_by_id": get_moderator_id(),
        "activity_count": 0,
        "last_activity": None
    }
    
    watchlist.setdefault('watched_users', []).append(watch_entry)
    save_watchlist(watchlist)
    
    # Add to user's record file so it shows up when searching
    record_file = os.path.join(USER_RECORDS_DIR, f"{user_id}_record.json")
    records = load_json_file(record_file, [])
    
    records.append({
        "user_id": str(user_id),
        "type": "Watch",
        "reason": reason,
        "notes": notes,
        "alert_level": alert_level,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "moderator": get_moderator_name(),
        "moderator_id": get_moderator_id(),
        "source": "website"
    })
    
    save_json_file(record_file, records)
    
    # Log activity
    log_activity(
        action="watchlist_add",
        category="moderation",
        details=f"Added to watchlist: {reason}",
        target_id=user_id,
        target_name=member.get('display_name') if member else None,
        success=True
    )
    
    # Add live notification with moderator name
    moderator_name = get_moderator_name()
    target_name = member.get('display_name') if member else user_id
    add_live_notification(
        'info',
        'User Added to Watchlist',
        f"{target_name} added by {moderator_name} - {reason[:50]}",
        link='/moderation',
        target_id=user_id
    )
    
    return jsonify({"success": True, "entry": watch_entry})

@app.route('/api/watchlist/<user_id>', methods=['PUT'])
@api_auth_required
@api_perm_required('moderation.watchlist')
def api_update_watchlist(user_id):
    """Update a watchlist entry"""
    data = request.json
    watchlist = load_watchlist()
    
    for i, watched in enumerate(watchlist.get('watched_users', [])):
        if str(watched.get('user_id')) == str(user_id):
            watchlist['watched_users'][i].update({
                "reason": data.get('reason', watched.get('reason')),
                "notes": data.get('notes', watched.get('notes')),
                "alert_level": data.get('alert_level', watched.get('alert_level')),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "updated_by": get_moderator_name()
            })
            save_watchlist(watchlist)
            return jsonify({"success": True, "entry": watchlist['watched_users'][i]})
    
    return jsonify({"error": "User not found on watchlist"}), 404

@app.route('/api/watchlist/<user_id>', methods=['DELETE'])
@api_auth_required
@api_perm_required('moderation.watchlist')
def api_remove_from_watchlist(user_id):
    """Remove a user from the watchlist"""
    watchlist = load_watchlist()
    
    original_count = len(watchlist.get('watched_users', []))
    
    # Get user info before removing
    removed_user = None
    for u in watchlist.get('watched_users', []):
        if str(u.get('user_id')) == str(user_id):
            removed_user = u
            break
    
    watchlist['watched_users'] = [
        u for u in watchlist.get('watched_users', [])
        if str(u.get('user_id')) != str(user_id)
    ]
    
    if len(watchlist['watched_users']) < original_count:
        save_watchlist(watchlist)
        
        # Handle user's record file
        record_file = os.path.join(USER_RECORDS_DIR, f"{user_id}_record.json")
        if os.path.exists(record_file):
            records = load_json_file(record_file, [])
            # Filter out Watch records
            records = [r for r in records if r.get('type') != 'Watch']
            
            if records:
                # User has other records, keep them
                save_json_file(record_file, records)
            else:
                # No other records, delete the file entirely
                try:
                    os.remove(record_file)
                except:
                    pass
        
        # Log activity
        log_activity(
            action="watchlist_remove",
            category="moderation",
            details=f"Removed from watchlist",
            target_id=user_id,
            target_name=removed_user.get('username') if removed_user else None,
            success=True
        )
        
        return jsonify({"success": True})
    
    return jsonify({"error": "User not found on watchlist"}), 404

@app.route('/api/watchlist/settings', methods=['PUT'])
@api_auth_required
@api_perm_required('moderation.watchlist')
def api_update_watchlist_settings():
    """Update watchlist alert settings"""
    data = request.json
    watchlist = load_watchlist()
    
    watchlist['settings'] = {
        "alert_on_join": data.get('alert_on_join', True),
        "alert_on_message": data.get('alert_on_message', True),
        "alert_on_voice_join": data.get('alert_on_voice_join', True),
        "alert_on_role_change": data.get('alert_on_role_change', False),
        "alert_channel_id": data.get('alert_channel_id'),
        "dm_alerts_to": data.get('dm_alerts_to', [])
    }
    
    save_watchlist(watchlist)
    return jsonify({"success": True, "settings": watchlist['settings']})

@app.route('/api/watchlist/<user_id>/activity', methods=['POST'])
@api_auth_required
def api_log_watchlist_activity(user_id):
    """Log activity for a watched user (called by bot)"""
    data = request.json
    activity_type = data.get('type', 'unknown')
    details = data.get('details', '')
    
    watchlist = load_watchlist()
    
    for i, watched in enumerate(watchlist.get('watched_users', [])):
        if str(watched.get('user_id')) == str(user_id):
            watchlist['watched_users'][i]['activity_count'] = watched.get('activity_count', 0) + 1
            watchlist['watched_users'][i]['last_activity'] = datetime.now(timezone.utc).isoformat()
            watchlist['watched_users'][i].setdefault('activity_log', []).insert(0, {
                "type": activity_type,
                "details": details,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            # Keep only last 50 activity entries
            watchlist['watched_users'][i]['activity_log'] = watchlist['watched_users'][i]['activity_log'][:50]
            save_watchlist(watchlist)
            return jsonify({"success": True})
    
    return jsonify({"error": "User not on watchlist"}), 404

# ============ Members API ============

@app.route('/api/members')
@api_auth_required
def api_members():
    """Get all members from the members cache file"""
    members = load_json_file(MEMBERS_CACHE_FILE, [])
    return jsonify(members)

@app.route('/api/members/<user_id>')
@api_auth_required
def api_member_detail(user_id):
    """Get detailed info for a specific member"""
    members = load_json_file(MEMBERS_CACHE_FILE, [])
    member = next((m for m in members if str(m.get('id')) == str(user_id)), None)
    
    if not member:
        return jsonify({"error": "Member not found"}), 404
    
    # Get user's moderation records
    records = load_json_file(os.path.join(USER_RECORDS_DIR, f"{user_id}_record.json"), [])
    
    # Get guest time if applicable
    guest_time = load_json_file(os.path.join(GUEST_TIMES_DIR, f"{user_id}_guest_time.json"), None)
    
    # Get varsity registration if applicable
    varsity_reg = load_json_file(os.path.join(VARSITY_REG_DIR, f"{user_id}_varsity.json"), None)
    
    # Get watchlist status
    watchlist_entry = get_watched_user(user_id)
    
    return jsonify({
        "member": member,
        "records": records,
        "guest_time": guest_time,
        "varsity_registration": varsity_reg,
        "watchlist": watchlist_entry
    })

@app.route('/api/members/<user_id>/action', methods=['POST'])
@api_auth_required
def api_member_action(user_id):
    """Queue a moderation action for a member (requires bot to process)"""
    data = request.json
    action = data.get('action')  # kick, ban, timeout, warn

    # Check granular permission based on action type
    perm_map = {'kick': 'members.kick', 'ban': 'members.ban', 'timeout': 'members.timeout',
                'unban': 'members.ban', 'warn': 'members.warn'}
    required_perm = perm_map.get(action)
    if required_perm and not has_perm(required_perm):
        return jsonify({"error": "Permission denied"}), 403

    reason = data.get('reason', 'No reason provided')
    duration = data.get('duration')  # For timeout, in minutes
    
    if action not in ['kick', 'ban', 'timeout', 'unban', 'warn']:
        return jsonify({"success": False, "message": "Invalid action"})
    
    # Get the moderator info
    moderator_name = get_moderator_name()
    moderator_id = get_moderator_id()
    
    # Get target member name for logging
    members = load_json_file(MEMBERS_CACHE_FILE, [])
    target_member = next((m for m in members if str(m.get('id')) == str(user_id)), None)
    target_name = target_member.get('display_name') or target_member.get('name') if target_member else f"User {user_id}"
    
    # Handle warnings differently - they don't need bot processing
    if action == 'warn':
        # Add warning directly to user's record
        record_file = os.path.join(USER_RECORDS_DIR, f"{user_id}_record.json")
        records = load_json_file(record_file, [])
        
        records.append({
            "user_id": str(user_id),
            "type": "Warning",
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "moderator": moderator_name,
            "moderator_id": moderator_id,
            "source": "website"
        })
        
        save_json_file(record_file, records)
        
        # Log the activity
        log_activity(
            action="warn",
            category="moderation",
            details=f"Warned user: {reason}",
            target_id=user_id,
            target_name=target_name,
            success=True
        )
        
        # Add live notification
        add_live_notification(
            'warning',
            'Member Warned',
            f"{target_name} - {reason[:50]}{'...' if len(reason) > 50 else ''}",
            link='/moderation',
            target_id=user_id
        )
        
        # Queue Discord DM notification
        queue_discord_notification({
            "type": "warn_user",
            "user_id": user_id,
            "reason": reason,
            "moderator": moderator_name
        })
        
        return jsonify({
            "success": True, 
            "message": f"Warning issued to {target_name} and added to their record."
        })
    
    # For other actions, queue for bot processing (thread-safe)
    queue_file = os.path.join(DATA_DIR, "moderation_queue.json")
    safe_queue_append(queue_file, {
        "user_id": user_id,
        "action": action,
        "reason": reason,
        "duration": duration,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
        "moderator": moderator_name,
        "moderator_id": moderator_id,
        "source": "website"
    })
    
    # Log the activity
    action_past_tense = {
        'kick': 'kicked',
        'ban': 'banned',
        'timeout': 'timed out',
        'unban': 'unbanned'
    }
    log_activity(
        action=action,
        category="moderation",
        details=f"{action_past_tense.get(action, action)} user: {reason}" + (f" (Duration: {duration} min)" if duration else ""),
        target_id=user_id,
        target_name=target_name,
        success=True
    )
    
    # Add live notification for moderation action
    action_titles = {
        'kick': 'Member Kicked',
        'ban': 'Member Banned',
        'timeout': 'Member Timed Out',
        'unban': 'Member Unbanned'
    }
    action_types = {
        'kick': 'kick',
        'ban': 'ban',
        'timeout': 'warning',
        'unban': 'info'
    }
    add_live_notification(
        action_types.get(action, 'info'),
        action_titles.get(action, 'Moderation Action'),
        f"{target_name} - {reason[:50]}{'...' if len(reason) > 50 else ''}",
        link='/moderation',
        target_id=user_id
    )
    
    return jsonify({
        "success": True, 
        "message": f"Action '{action}' queued for {target_name}. The bot will process this action."
    })

@app.route('/api/members/<user_id>/send-varsity-registration', methods=['POST'])
@api_auth_required
@api_perm_required('varsity.send_registration')
def api_member_send_varsity_registration(user_id):
    """Queue a varsity registration to be sent to a user via Discord DM"""
    data = request.json
    player_type = data.get('player_type', 'varsity')
    
    if player_type not in ['varsity', 'jv', 'sub_varsity', 'sub_jv']:
        return jsonify({"success": False, "message": "Invalid player type"})
    
    # Generate a unique job ID for tracking
    import uuid
    job_id = f"reg_{user_id}_{uuid.uuid4().hex[:8]}"
    
    # Queue the varsity registration request for the bot to send (thread-safe)
    notification_queue_file = os.path.join(DATA_DIR, "discord_notification_queue.json")
    safe_queue_append(notification_queue_file, {
        "type": "send_varsity_registration",
        "user_id": user_id,
        "player_type": player_type,
        "job_id": job_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
        "dm_status": "pending"
    })
    
    player_type_names = {
        'varsity': 'Varsity',
        'jv': 'JV',
        'sub_varsity': 'Varsity Substitute',
        'sub_jv': 'JV Substitute'
    }
    
    return jsonify({
        "success": True,
        "message": f"{player_type_names.get(player_type, player_type)} registration will be sent to the user shortly.",
        "job_id": job_id
    })

# ============ Varsity Registrations API ============

@app.route('/api/varsity-registrations')
@api_auth_required
def api_varsity_registrations():
    """Get all varsity registrations"""
    registrations = []
    
    if os.path.exists(VARSITY_REG_DIR):
        for fname in os.listdir(VARSITY_REG_DIR):
            if fname.endswith("_varsity.json"):
                user_id = fname.replace("_varsity.json", "")
                filepath = os.path.join(VARSITY_REG_DIR, fname)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        # Handle both list and dict formats
                        if isinstance(data, list):
                            for idx, reg in enumerate(data):
                                # Transform attachments to proper URLs
                                if reg.get('data'):
                                    reg['data']['attachments'] = transform_attachments_to_urls(reg.get('data', {}))
                                registrations.append({
                                    "user_id": user_id,
                                    "file": fname,
                                    "index": idx,
                                    **reg
                                })
                        else:
                            # Transform attachments to proper URLs
                            if data.get('data'):
                                data['data']['attachments'] = transform_attachments_to_urls(data.get('data', {}))
                            registrations.append({
                                "user_id": user_id,
                                "file": fname,
                                "index": 0,
                                **data
                            })
                except Exception as e:
                    print(f"Error reading {fname}: {e}")
    
    # Sort by timestamp descending
    registrations.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    return jsonify(registrations)

@app.route('/api/varsity-registrations/<user_id>')
@api_auth_required
def api_varsity_registration_detail(user_id):
    """Get detailed varsity registration for a user"""
    filepath = os.path.join(VARSITY_REG_DIR, f"{user_id}_varsity.json")
    if os.path.exists(filepath):
        data = load_json_file(filepath)
        # Transform to list format and fix attachments
        registrations = data if isinstance(data, list) else [data]
        for reg in registrations:
            if reg.get('data'):
                reg['data']['attachments'] = transform_attachments_to_urls(reg.get('data', {}))
        return jsonify({"user_id": user_id, "registrations": registrations})
    return jsonify({"error": "Registration not found"}), 404

@app.route('/api/varsity-registrations/<user_id>', methods=['DELETE'])
@api_auth_required
@api_perm_required('varsity.delete')
def api_delete_varsity_registration(user_id):
    """Delete all varsity registrations for a user"""
    filepath = os.path.join(VARSITY_REG_DIR, f"{user_id}_varsity.json")
    if os.path.exists(filepath):
        # First, delete any associated schedule images
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, list):
                for entry in data:
                    attachments = entry.get('data', {}).get('attachments', [])
                    delete_schedule_images(attachments)
        except Exception as e:
            print(f"Error cleaning up images for {user_id}: {e}")
        # Now delete the registration file
        os.remove(filepath)
        return jsonify({"success": True, "message": f"Deleted varsity registration for {user_id}"})
    return jsonify({"success": False, "message": "Registration not found"})

@app.route('/api/varsity-registrations/<user_id>/entry/<int:index>', methods=['DELETE'])
@api_auth_required
@api_perm_required('varsity.delete')
def api_delete_varsity_entry(user_id, index):
    """Delete a specific entry from a user's varsity registrations"""

    filepath = os.path.join(VARSITY_REG_DIR, f"{user_id}_varsity.json")
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if isinstance(data, list) and 0 <= index < len(data):
                # Delete associated schedule images before removing entry
                entry = data[index]
                attachments = entry.get('data', {}).get('attachments', [])
                delete_schedule_images(attachments)
                
                data.pop(index)
                
                if len(data) == 0:
                    # Delete file if no entries left
                    os.remove(filepath)
                else:
                    safe_json_dump(data, filepath, indent=2)
                
                return jsonify({"success": True, "message": "Entry deleted"})
            else:
                return jsonify({"success": False, "message": "Invalid index"})
        except Exception as e:
            return jsonify({"success": False, "message": str(e)})
    return jsonify({"success": False, "message": "Registration not found"})

@app.route('/api/varsity-registrations/<user_id>/entry/<int:index>/status', methods=['POST'])
@api_auth_required
@api_perm_required('varsity.approve')
def api_update_varsity_status(user_id, index):
    """Update the status of a varsity registration entry"""
    filepath = os.path.join(VARSITY_REG_DIR, f"{user_id}_varsity.json")
    if os.path.exists(filepath):
        try:
            data = request.json
            new_status = data.get('status')
            note = data.get('note', '')
            
            with open(filepath, 'r', encoding='utf-8') as f:
                registrations = json.load(f)
            
            if isinstance(registrations, list) and 0 <= index < len(registrations):
                registrations[index]['status'] = new_status
                registrations[index]['moderation_note'] = note
                registrations[index]['moderated_at'] = datetime.now(timezone.utc).isoformat()
                registrations[index]['moderated_by'] = {'id': 'dashboard', 'name': 'Dashboard Admin'}
                
                safe_json_dump(registrations, filepath, indent=2)
                
                return jsonify({"success": True, "message": f"Status updated to {new_status}"})
            else:
                return jsonify({"success": False, "message": "Invalid index"})
        except Exception as e:
            return jsonify({"success": False, "message": str(e)})
    return jsonify({"success": False, "message": "Registration not found"})

@app.route('/api/varsity-registrations/<user_id>/entry/<int:index>/approve', methods=['POST'])
@api_auth_required
@api_perm_required('varsity.approve')
def api_approve_varsity(user_id, index):
    """Approve a varsity registration and queue Discord notification"""
    filepath = os.path.join(VARSITY_REG_DIR, f"{user_id}_varsity.json")
    if not os.path.exists(filepath):
        return jsonify({"success": False, "message": "Registration not found"})
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            registrations = json.load(f)
        
        if not isinstance(registrations, list) or index < 0 or index >= len(registrations):
            return jsonify({"success": False, "message": "Invalid index"})
        
        # Check if already processed
        current_status = registrations[index].get('status', 'Pending').lower()
        if current_status in ('approved', 'denied'):
            return jsonify({"success": False, "message": f"Registration already {current_status}"})
        
        # Get player data before updating status
        player_data = registrations[index].get('data', {})
        
        # Update status
        registrations[index]['status'] = 'Approved'
        registrations[index]['moderated_at'] = datetime.now(timezone.utc).isoformat()
        registrations[index]['moderated_by'] = {'id': 'dashboard', 'name': 'Dashboard Admin'}
        
        safe_json_dump(registrations, filepath, indent=2)
        
        # Add player to rosters.json
        if player_data:
            rosters = load_rosters()
            players = rosters.get("players", [])
            
            # Check if player already exists (use user_id from URL parameter)
            existing = next((p for p in players if str(p.get("discord_id")) == str(user_id)), None)
            if not existing:
                # Get Discord username from members cache
                members_cache = load_json_file(MEMBERS_CACHE_FILE, [])
                if isinstance(members_cache, dict):
                    members_list = members_cache.get("members", [])
                else:
                    members_list = members_cache
                member = next((m for m in members_list if str(m.get("id")) == str(user_id)), None)
                discord_username = member.get("username") or member.get("name") if member else None
                
                players.append({
                    "discord_id": str(user_id),
                    "full_name": player_data.get("Full Name"),
                    "discord_username": discord_username,
                    "player_type": player_data.get("player_type", "varsity"),
                    "game": player_data.get("Primary Game Title"),
                    "ign": player_data.get("IGN"),
                    "rank": player_data.get("Current Rank in Game"),
                    "role": player_data.get("Primary Role"),
                    "tracker": player_data.get("Tracker Link"),
                    "purdue_email": player_data.get("Purdue Email"),
                    "personal_email": player_data.get("Personal Email"),
                    "is_captain": False,
                    "team_id": None,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat()
                })
                rosters["players"] = players
                save_rosters(rosters)
        
        # Queue Discord notification (thread-safe)
        notification_queue_file = os.path.join(DATA_DIR, "discord_notification_queue.json")
        safe_queue_append(notification_queue_file, {
            "type": "varsity_approved",
            "user_id": user_id,
            "player_type": player_data.get("player_type", "varsity") if player_data else "varsity",
            "assign_role": True,
            "status": "pending",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        
        return jsonify({"success": True, "message": "Registration approved successfully"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/varsity-registrations/<user_id>/entry/<int:index>/deny', methods=['POST'])
@api_auth_required
@api_perm_required('varsity.deny')
def api_deny_varsity(user_id, index):
    """Deny a varsity registration with reason and queue Discord notification"""
    filepath = os.path.join(VARSITY_REG_DIR, f"{user_id}_varsity.json")
    if not os.path.exists(filepath):
        return jsonify({"success": False, "message": "Registration not found"})
    
    try:
        req_data = request.json or {}
        reason = req_data.get('reason', 'Declined by admin')
        
        with open(filepath, 'r', encoding='utf-8') as f:
            registrations = json.load(f)
        
        if not isinstance(registrations, list) or index < 0 or index >= len(registrations):
            return jsonify({"success": False, "message": "Invalid index"})
        
        # Check if already processed
        current_status = registrations[index].get('status', 'Pending').lower()
        if current_status in ('approved', 'denied'):
            return jsonify({"success": False, "message": f"Registration already {current_status}"})
        
        # Update status
        registrations[index]['status'] = 'Denied'
        registrations[index]['moderation_note'] = reason
        registrations[index]['moderated_at'] = datetime.now(timezone.utc).isoformat()
        registrations[index]['moderated_by'] = {'id': 'dashboard', 'name': 'Dashboard Admin'}
        
        safe_json_dump(registrations, filepath, indent=2)
        
        # Queue Discord notification (thread-safe)
        notification_queue_file = os.path.join(DATA_DIR, "discord_notification_queue.json")
        safe_queue_append(notification_queue_file, {
            "type": "varsity_denied",
            "user_id": user_id,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "pending"
        })
        
        return jsonify({"success": True, "message": "Registration denied successfully"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

# ============ EQUIPMENT MANAGEMENT ============

EQUIPMENT_FILE = os.path.join(DATA_DIR, "equipment.json")  # legacy, replaced by equipment.db

# ============ DISCORD CHANNELS API ============

@app.route('/api/discord/channels')
@api_auth_required
def api_get_discord_channels():
    """Get all text channels from Discord for announcement selection"""
    try:
        # Load members cache to get guild info, or use a channels cache
        channels_cache_file = os.path.join(DATA_DIR, "channels_cache.json")
        
        if os.path.exists(channels_cache_file):
            with open(channels_cache_file, 'r', encoding='utf-8') as f:
                channels = json.load(f)
            return jsonify({"channels": channels})
        
        # Fallback - return empty or suggest manual setup
        return jsonify({
            "channels": [],
            "message": "Channel cache not available. Channels will be loaded when bot syncs."
        })
    except Exception as e:
        return jsonify({"error": str(e), "channels": []}), 500

# ============ EQUIPMENT API (SQLite) ============
from equipment_db import (
    init_equipment_db, get_all_items, get_item, add_item, update_item, delete_item as db_delete_item,
    checkout_item, checkin_item, report_item, get_all_reports, resolve_report,
    get_activity_log, get_full_export, get_active_checkouts, get_all_checkouts,
    create_qr_code, get_qr_code, get_qr_codes_for_item, get_all_qr_codes, delete_qr_code,
)
init_equipment_db()


def _get_username():
    user = session.get('discord_user') or session.get('dashboard_user') or {}
    return user.get('global_name') or user.get('display_name') or user.get('username') or 'Unknown'


@app.route('/api/equipment')
@api_auth_required
def api_get_equipment():
    """Get all equipment inventory"""
    items = get_all_items()
    reports = get_all_reports()
    checkouts = get_active_checkouts()
    resp = jsonify({"items": items, "reports": reports, "active_checkouts": checkouts})
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return resp


@app.route('/api/equipment', methods=['POST'])
@api_auth_required
@api_perm_required('equipment.manage')
def api_add_equipment():
    """Add a new equipment item"""
    req = request.json
    if not req:
        return jsonify({"success": False, "message": "Invalid request"}), 400
    name = (req.get("name") or "").strip()
    if not name:
        return jsonify({"success": False, "message": "Item name is required"}), 400
    try:
        expected_qty = int(req.get("expected_quantity") or 0)
        current_qty = int(req.get("current_quantity") or 0)
    except (ValueError, TypeError):
        return jsonify({"success": False, "message": "Quantities must be numbers"}), 400
    item = add_item(name, req.get("category", "other"), expected_qty, current_qty, req.get("notes", ""), _get_username())
    return jsonify({"success": True, "item": item})


@app.route('/api/equipment/<item_id>', methods=['PUT'])
@api_auth_required
@api_perm_required('equipment.manage')
def api_update_equipment(item_id):
    """Update an equipment item"""
    req = request.json
    if not req:
        return jsonify({"success": False, "message": "Invalid request"}), 400
    try:
        expected_qty = int(req.get("expected_quantity") or 0)
        current_qty = int(req.get("current_quantity") or 0)
    except (ValueError, TypeError):
        return jsonify({"success": False, "message": "Quantities must be numbers"}), 400
    item = update_item(item_id, (req.get("name") or "").strip(), req.get("category", "other"), expected_qty, current_qty, req.get("notes", ""), _get_username())
    if not item:
        return jsonify({"success": False, "message": "Item not found"}), 404
    return jsonify({"success": True, "item": item})


@app.route('/api/equipment/<item_id>', methods=['DELETE'])
@api_auth_required
@api_perm_required('equipment.manage')
def api_delete_equipment(item_id):
    """Remove an equipment item"""
    if db_delete_item(item_id, _get_username()):
        return jsonify({"success": True})
    return jsonify({"success": False, "message": "Item not found"}), 404


@app.route('/api/equipment/<item_id>/checkout', methods=['POST'])
@api_auth_required
@api_perm_required('equipment.checkout')
def api_checkout_equipment(item_id):
    """Check out equipment"""
    req = request.json or {}
    try:
        quantity = int(req.get("quantity") or 1)
    except (ValueError, TypeError):
        return jsonify({"success": False, "message": "Invalid quantity"}), 400
    checked_out_to = (req.get("checked_out_to") or "").strip()
    if not checked_out_to:
        return jsonify({"success": False, "message": "Name of person is required"}), 400
    person_id = (req.get("person_id") or "").strip()
    if not person_id:
        return jsonify({"success": False, "message": "ID number is required"}), 400
    id_type = req.get("id_type", "")
    purpose = req.get("purpose", "")
    item, err = checkout_item(item_id, quantity, checked_out_to, req.get("notes", ""), _get_username(), person_id, id_type, purpose)
    if err:
        code = 404 if err == "Item not found" else 400
        return jsonify({"success": False, "message": err}), code
    return jsonify({"success": True, "item": item})


@app.route('/api/equipment/<item_id>/checkin', methods=['POST'])
@api_auth_required
@api_perm_required('equipment.checkin')
def api_checkin_equipment(item_id):
    """Check in equipment"""
    req = request.json or {}
    try:
        quantity = int(req.get("quantity") or 1)
    except (ValueError, TypeError):
        return jsonify({"success": False, "message": "Invalid quantity"}), 400
    checkout_id = req.get("checkout_id", "")
    condition = req.get("condition", "good")
    item, err = checkin_item(item_id, quantity, req.get("notes", ""), _get_username(), checkout_id, condition)
    if err:
        code = 404 if err == "Item not found" else 400
        return jsonify({"success": False, "message": err}), code
    return jsonify({"success": True, "item": item})


@app.route('/api/equipment/<item_id>/report', methods=['POST'])
@api_auth_required
@api_perm_required('equipment.reports')
def api_report_equipment(item_id):
    """Report equipment as missing or stolen"""
    req = request.json or {}
    try:
        quantity = int(req.get("quantity") or 1)
    except (ValueError, TypeError):
        return jsonify({"success": False, "message": "Invalid quantity"}), 400
    report, item, err = report_item(item_id, req.get("type", "missing"), quantity, req.get("notes", ""), _get_username())
    if err:
        return jsonify({"success": False, "message": err}), 404
    return jsonify({"success": True, "report": report, "item": item})


@app.route('/api/equipment/reports/<report_id>/resolve', methods=['POST'])
@api_auth_required
@api_perm_required('equipment.reports')
def api_resolve_report(report_id):
    """Resolve a missing/stolen report"""
    req = request.json or {}
    if resolve_report(report_id, req.get("resolution", ""), req.get("recovered", False), _get_username()):
        return jsonify({"success": True})
    return jsonify({"success": False, "message": "Report not found"}), 404


@app.route('/api/equipment/history')
@api_auth_required
def api_equipment_history():
    """Get equipment activity log"""
    log = get_activity_log(200)
    resp = jsonify({"history": log})
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return resp


@app.route('/api/equipment/export')
@api_auth_required
@api_perm_required('equipment.export')
def api_export_equipment():
    """Export equipment inventory to CSV for Excel"""
    export = get_full_export()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(["Item Name", "Category", "Expected Qty", "Current Qty", "Checked Out", "Missing", "Status", "Notes"])
    for item in export["items"]:
        if item["missing"] > 0:
            status = "Has Missing/Stolen"
        elif item["checked_out"] > 0:
            status = "Partially Checked Out"
        elif item["current_quantity"] >= item["expected_quantity"]:
            status = "All Accounted For"
        else:
            status = "Low Stock"
        writer.writerow([item["name"], item["category"].title(), item["expected_quantity"], item["current_quantity"], item["checked_out"], item["missing"], status, item.get("notes", "")])

    writer.writerow([])
    writer.writerow(["--- Active Checkouts ---"])
    writer.writerow(["Item", "Qty", "Checked Out To", "ID Type", "Person ID", "Purpose", "Checked Out By", "Checked Out At", "Status", "Notes"])
    for co in export.get("checkouts", []):
        writer.writerow([co["item_name"], co["quantity"], co["checked_out_to"], co.get("id_type", ""), co.get("person_id", ""), co.get("purpose", ""), co["checked_out_by"], co["checked_out_at"][:19].replace("T", " "), co["status"], co.get("notes", "")])

    writer.writerow([])
    writer.writerow(["--- Reports ---"])
    writer.writerow(["Item", "Type", "Quantity", "Reported By", "Date", "Notes", "Resolved"])
    for r in export["reports"]:
        writer.writerow([r["item_name"], r["type"].title(), r["quantity"], r["reported_by"], r["timestamp"][:10], r.get("notes", ""), "Yes" if r.get("resolved") else "No"])

    writer.writerow([])
    writer.writerow(["--- Activity Log ---"])
    writer.writerow(["Item", "Action", "Performed By", "Date/Time", "Details"])
    for entry in export["log"]:
        writer.writerow([entry.get("item_name", ""), entry.get("action", "").replace("_", " ").title(), entry.get("performed_by", ""), entry.get("timestamp", "")[:19].replace("T", " "), entry.get("details", entry.get("notes", ""))])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=equipment_inventory_{datetime.now().strftime("%Y%m%d")}.csv'}
    )


# ============ QR CODE MANAGEMENT ============

import qrcode
from io import BytesIO
import base64

@app.route('/api/equipment/<item_id>/qrcode', methods=['POST'])
@api_auth_required
@api_perm_required('equipment.manage')
def api_create_equipment_qr(item_id):
    """Generate a persistent QR code for an equipment item."""
    item = get_item(item_id)
    if not item:
        return jsonify({"error": "Item not found"}), 404
    qr = create_qr_code(item_id, _get_username())
    return jsonify(qr), 201


@app.route('/api/equipment/<item_id>/qrcodes')
@api_auth_required
def api_get_equipment_qrcodes(item_id):
    """Get all QR codes for an equipment item."""
    codes = get_qr_codes_for_item(item_id)
    return jsonify(codes)


@app.route('/api/equipment/qrcodes')
@api_auth_required
def api_get_all_qrcodes():
    """Get all QR codes across all equipment."""
    codes = get_all_qr_codes()
    return jsonify(codes)


@app.route('/api/equipment/qrcode/<qr_id>', methods=['DELETE'])
@api_auth_required
@api_perm_required('equipment.manage')
def api_delete_equipment_qr(qr_id):
    """Delete a QR code (permanently deactivates it)."""
    qr = get_qr_code(qr_id)
    if not qr:
        return jsonify({"error": "QR code not found"}), 404
    delete_qr_code(qr_id)
    return jsonify({"success": True})


@app.route('/api/equipment/qrcode/<qr_id>/image')
@api_auth_required
def api_get_qr_image(qr_id):
    """Generate and return a QR code PNG image."""
    qr = get_qr_code(qr_id)
    if not qr:
        return jsonify({"error": "QR code not found"}), 404

    item = get_item(qr['item_id'])
    item_name = item['name'] if item else 'Unknown'

    # Build the checkout URL
    base_url = request.host_url.rstrip('/')
    checkout_url = f"{base_url}/onduty/equipment?checkout={qr['item_id']}&qr={qr_id}"

    img = qrcode.make(checkout_url, box_size=10, border=2)
    buf = BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)

    return Response(buf.getvalue(), mimetype='image/png',
                    headers={'Content-Disposition': f'inline; filename=qr_{item_name}_{qr_id}.png'})


@app.route('/api/equipment/qrcode/<qr_id>/data')
@api_auth_required
def api_get_qr_data(qr_id):
    """Get QR code image as base64 + metadata."""
    qr = get_qr_code(qr_id)
    if not qr:
        return jsonify({"error": "QR code not found"}), 404

    item = get_item(qr['item_id'])
    item_name = item['name'] if item else 'Unknown'

    base_url = request.host_url.rstrip('/')
    checkout_url = f"{base_url}/onduty/equipment?checkout={qr['item_id']}&qr={qr_id}"

    img = qrcode.make(checkout_url, box_size=10, border=2)
    buf = BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    b64 = base64.b64encode(buf.getvalue()).decode('utf-8')

    return jsonify({
        "id": qr_id,
        "item_id": qr['item_id'],
        "item_name": item_name,
        "url": checkout_url,
        "image_base64": b64,
        "created_at": qr['created_at'],
        "created_by": qr['created_by'],
    })


@app.route('/qr/<qr_id>')
def qr_redirect(qr_id):
    """Public QR redirect — validates the QR code then redirects to checkout page."""
    qr = get_qr_code(qr_id)
    if not qr:
        # QR was deleted — show a simple error
        return "<h2>This QR code is no longer active.</h2><p>It may have been deleted by an admin.</p>", 404

    return redirect(f"/onduty/equipment?checkout={qr['item_id']}&qr={qr_id}")


# ============ Live Notifications API ============

LIVE_NOTIFICATIONS_FILE = os.path.join(DATA_DIR, "live_notifications.json")

@app.route('/api/live-notifications')
@api_auth_required
def api_get_live_notifications():
    """Get live notifications for the dashboard bell"""
    notifications = load_json_file(LIVE_NOTIFICATIONS_FILE, {"notifications": [], "last_cleared": None})
    
    # Only return notifications from the last 24 hours
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    recent = [n for n in notifications.get("notifications", []) 
              if datetime.fromisoformat(n.get("timestamp", "2000-01-01T00:00:00+00:00").replace('Z', '+00:00')) > cutoff]
    
    return jsonify({
        "notifications": recent[:50],  # Limit to 50 most recent
        "count": len(recent)
    })

@app.route('/api/live-notifications/mark-read', methods=['POST'])
@api_auth_required
def api_mark_notifications_read():
    """Mark all notifications as read"""
    notifications = load_json_file(LIVE_NOTIFICATIONS_FILE, {"notifications": [], "last_cleared": None})
    for n in notifications.get("notifications", []):
        n["read"] = True
    save_json_file(LIVE_NOTIFICATIONS_FILE, notifications)
    return jsonify({"success": True})

@app.route('/api/live-notifications/clear', methods=['POST'])
@api_auth_required
def api_clear_notifications():
    """Clear all notifications"""
    save_json_file(LIVE_NOTIFICATIONS_FILE, {
        "notifications": [],
        "last_cleared": datetime.now(timezone.utc).isoformat()
    })
    return jsonify({"success": True})

def add_live_notification(notif_type, title, message, link=None, target_id=None):
    """Add a live notification that will appear in the dashboard bell"""
    notifications = load_json_file(LIVE_NOTIFICATIONS_FILE, {"notifications": [], "last_cleared": None})
    
    notification = {
        "id": f"notif_{datetime.now().strftime('%Y%m%d%H%M%S')}_{os.urandom(4).hex()}",
        "type": notif_type,  # registration, warning, kick, ban, team, info
        "title": title,
        "message": message,
        "link": link,
        "target_id": target_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "read": False
    }
    
    # Add to beginning of list
    notifications["notifications"].insert(0, notification)
    
    # Keep only last 100 notifications
    notifications["notifications"] = notifications["notifications"][:100]
    
    save_json_file(LIVE_NOTIFICATIONS_FILE, notifications)
    return notification

@app.route('/api/live-notifications/test', methods=['POST'])
@api_auth_required
def api_test_notification():
    """Send a test notification to verify the system works"""
    notif = add_live_notification(
        notif_type="info",
        title="Test Notification",
        message="This is a test notification to verify the bell system is working!",
        link="/dashboard"
    )
    return jsonify({"success": True, "notification": notif})

# ============ Security Headers ============

@app.after_request
def add_security_headers(response):
    """Add security and performance headers to all responses"""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    
    # Cache static assets aggressively
    if request.path.startswith('/static/'):
        response.headers['Cache-Control'] = 'public, max-age=86400'  # 24 hours
    # Short-lived cache for API data so pages feel instant on back-nav
    elif request.path.startswith('/api/') and request.method == 'GET':
        response.headers['Cache-Control'] = 'private, max-age=5'  # 5 seconds
    
    return response

# ============ Error Handlers ============

@app.errorhandler(400)
def bad_request(e):
    """Handle bad request errors"""
    if request.path.startswith('/api/'):
        return jsonify({"error": "Bad request", "message": str(e.description)}), 400
    return render_template('404.html'), 400

@app.errorhandler(404)
def not_found(e):
    """Handle not found errors"""
    if request.path.startswith('/api/'):
        return jsonify({"error": "Not found", "message": "The requested resource was not found"}), 404
    return render_template('404.html'), 404

@app.errorhandler(500)
def server_error(e):
    """Handle internal server errors with logging"""
    logger.error(f"Internal server error: {e}", exc_info=True)
    if request.path.startswith('/api/'):
        return jsonify({"error": "Internal server error", "message": "An unexpected error occurred"}), 500
    return render_template('404.html'), 500

@app.errorhandler(Exception)
def handle_exception(e):
    """Global exception handler"""
    logger.error(f"Unhandled exception: {e}", exc_info=True)
    if request.path.startswith('/api/'):
        return jsonify({"error": "Internal server error", "message": str(e)}), 500
    return render_template('404.html'), 500

# ============ Health Check Endpoint ============

@app.route('/health')
def health_check():
    """Health check endpoint for monitoring"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0"
    })

# ============ Main ============

if __name__ == '__main__':
    import sys
    
    # Check for production mode
    is_production = os.environ.get('FLASK_ENV') == 'production'
    debug_mode = os.environ.get('FLASK_DEBUG', 'true').lower() == 'true' and not is_production
    
    print("=" * 60)
    print("LionByteGG Web Dashboard")
    print("=" * 60)
    print(f"Mode: {'PRODUCTION' if is_production else 'DEVELOPMENT'}")
    print(f"Debug: {'Enabled' if debug_mode else 'Disabled'}")
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=5000, debug=debug_mode)
