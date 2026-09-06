"""
LionByteGG Web Dashboard API
A comprehensive Flask API for managing the Discord bot through a web interface.
Features Discord OAuth2 authentication with role-based permissions.
"""

from flask import Flask, render_template, request, jsonify, redirect, url_for, session, send_from_directory, send_file, Response
from flask_cors import CORS
from functools import wraps
import os
import sys
import json
import uuid
import copy
from datetime import datetime, timezone, timedelta
import hashlib
import secrets
import requests
import tempfile
import threading
import time
import csv
from collections import defaultdict
import io
from cryptography.fernet import Fernet

# Add parent directory imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Add web directory for local imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.constants import (
    GUILD_ID, STUDENT_ROLE_ID, GUEST_ROLE_ID, SECURITY_CODE,
    USER_RECORDS_DIR, GUEST_TIMES_DIR, VARSITY_REG_DIR, SCHEDULE_IMAGES_DIR, LOG_CHANNEL_NAME
)
from utils.safe_json import safe_json_dump, safe_json_load, safe_queue_append as _safe_queue_append
from utils import db as user_db
from utils.automod_sync import sync_automod

DISCORD_BOT_TOKEN = os.environ.get('DISCORD_BOT_TOKEN', '')

# Initialize the SQLite user-records DB on startup
user_db.init_db()

# Import auth database
import auth_db
# Encrypted SQLite store for arena sign-ins
import arena_db
import puid_db

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
    perms = get_user_perms() if (session.get('dashboard_user') or (session.get('authenticated') and session.get('legacy_login'))) else []
    resolved = set(auth_db.resolve_perm(p) for p in perms)
    return dict(user_perms=perms, has_perm=lambda p: auth_db.resolve_perm(p) in resolved,
                is_captain=False, account_role='captain')

# Configuration
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
FLAGGED_WORDS_PATH = os.path.join(DATA_DIR, "flagged_words.json")
BOT_STATUS_FILE = os.path.join(DATA_DIR, "bot_status.json")
MEMBERS_CACHE_FILE = os.path.join(DATA_DIR, "members_cache.json")
ROLES_CACHE_FILE = os.path.join(DATA_DIR, "roles_cache.json")

# Unique per-process id, regenerated every time the server starts. Kiosks poll
# this and auto-reload the moment it changes, so a server restart/redeploy
# never leaves a kiosk stuck on a stale page needing a manual refresh.
SERVER_BOOT_ID = uuid.uuid4().hex
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
    """Decorator to require authentication (dashboard user or legacy)"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check for dashboard user (new auth system)
        if session.get('dashboard_user'):
            return f(*args, **kwargs)
        # Check for legacy authentication
        if session.get('authenticated') and session.get('legacy_login'):
            return f(*args, **kwargs)
        return redirect(url_for('login'))
    return decorated_function

def api_auth_required(f):
    """Decorator for API endpoints (supports dashboard user, legacy session, and token)"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
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
        # Legacy login gets admin access (they had the security code)
        if session.get('authenticated') and session.get('legacy_login'):
            return f(*args, **kwargs)
        return jsonify({"error": "Admin access required"}), 403
    return decorated_function

def _is_full_access_user():
    """Check if the current user has full unrestricted access (dashboard admin or legacy login)."""
    user = session.get('dashboard_user')
    if user and user.get('is_admin'):
        return True
    if session.get('authenticated') and session.get('legacy_login'):
        return True
    return False

def _perm_keys(permission_key):
    """Normalize a permission_key argument (str or iterable of str) to a list."""
    if isinstance(permission_key, (list, tuple, set)):
        return list(permission_key)
    return [permission_key]

def page_permission_required(permission_key):
    """Decorator factory to require a specific page permission (or any of a list of permissions)"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Discord OAuth users and legacy users get full access
            if _is_full_access_user():
                return f(*args, **kwargs)
            # Dashboard users need at least one of the specified permissions (resolved via alias)
            resolved_required = set(auth_db.resolve_perm(k) for k in _perm_keys(permission_key))
            resolved_held = set(auth_db.resolve_perm(p) for p in get_user_perms())
            if resolved_required & resolved_held:
                return f(*args, **kwargs)
            return redirect(url_for('smart_landing'))
        return decorated_function
    return decorator

def has_perm(permission_key):
    """Check if current user has a specific permission. Discord/legacy users always have all perms."""
    if _is_full_access_user():
        return True
    resolved = auth_db.resolve_perm(permission_key)
    return resolved in set(auth_db.resolve_perm(p) for p in get_user_perms())

def get_user_perms():
    """Effective permission set for the current session. Discord/legacy users get everything."""
    if _is_full_access_user():
        return auth_db.ALL_PERMISSIONS
    return list(session.get('dashboard_permissions', []))

def api_perm_required(permission_key):
    """Decorator factory for API endpoints requiring a specific action permission (or any of a list)"""
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
            # Dashboard users need at least one of the specified permissions (resolved via alias)
            resolved_required = set(auth_db.resolve_perm(k) for k in _perm_keys(permission_key))
            resolved_held = set(auth_db.resolve_perm(p) for p in get_user_perms())
            if resolved_required & resolved_held:
                return f(*args, **kwargs)
            return jsonify({"error": "Permission denied"}), 403
        return decorated_function
    return decorator

# ============ Helper Functions ============

# Discord API request timeout (seconds) - prevents hanging when Discord is slow/down
DISCORD_API_TIMEOUT = 10

def load_json_file(filepath, default=None):
    """Load JSON file using the shared thread-safe implementation."""
    return safe_json_load(filepath, default)

def save_json_file(filepath, data):
    """Save JSON file using the shared thread-safe implementation."""
    safe_json_dump(data, filepath, indent=2)

def safe_queue_append(filepath, item):
    """Thread-safe append to a JSON list file."""
    _safe_queue_append(filepath, item)

def load_flagged_words():
    return load_json_file(FLAGGED_WORDS_PATH, {"bannable": [], "kickable": [], "warning": []})

def save_flagged_words(words):
    save_json_file(FLAGGED_WORDS_PATH, words)

def _sync_automod_bg(flagged_words: dict):
    """Run AutoMod sync in a background thread so the API response isn't delayed."""
    def _run():
        try:
            result = sync_automod(DISCORD_BOT_TOKEN, GUILD_ID, flagged_words)
            logger.info(f"[AutoMod Sync] Result: {result}")
        except Exception as exc:
            logger.error(f"[AutoMod Sync] Unexpected error: {exc}")
    threading.Thread(target=_run, daemon=True).start()

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
    return user_db.get_all_records()

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
        
        dashboard_user = session.get('dashboard_user')
        if dashboard_user:
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
    dashboard_user = session.get('dashboard_user')
    if dashboard_user:
        return dashboard_user.get('display_name') or dashboard_user.get('username')
    elif session.get('legacy_login'):
        return session.get('user_name', 'Admin')
    return 'Dashboard Admin'

def get_moderator_id():
    """Get the current moderator's ID from session"""
    dashboard_user = session.get('dashboard_user')
    if dashboard_user:
        return dashboard_user.get('id')
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
            data = load_json_file(BOT_STATUS_FILE, {})
            if data:
                # Check if status is recent (within last 2 minutes)
                last_update = data.get('last_update', '')
                if last_update:
                    update_time = datetime.fromisoformat(last_update.replace('Z', '+00:00'))
                    now = datetime.now(timezone.utc)
                    if (now - update_time).total_seconds() < 120:
                        return data
        except (json.JSONDecodeError, ValueError, OSError) as e:
            print(f"[ERROR] Failed to read bot status file: {e}")
    
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
    if (session.get('authenticated') and session.get('legacy_login')) or session.get('dashboard_user'):
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
    # If already logged in, redirect to dashboard
    if session.get('dashboard_user') or (session.get('authenticated') and session.get('legacy_login')):
        return redirect(url_for('smart_landing'))
    
    error = request.args.get('error')
    error_messages = {
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
        return render_template('login.html', error="Invalid username or password")
    
    return render_template('login.html', 
                         error=error_messages.get(error))

@app.route('/logout')
def logout():
    dashboard_user = session.get('dashboard_user')
    user_name = None
    user_id = None
    
    if dashboard_user:
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

# ============ Auth API Endpoints ============

@app.route('/api/auth/user')
def get_current_user():
    """API endpoint to get current logged-in user info"""
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
                'is_admin': True
            }
        })
    return jsonify({'authenticated': False}), 401

@app.route('/api/auth/permissions')
def get_user_permissions():
    """API endpoint to get current user's permissions"""
    dashboard_user = session.get('dashboard_user')
    if dashboard_user:
        return jsonify({
            'permissions': session.get('dashboard_permissions', []),
            'is_admin': dashboard_user.get('is_admin', False)
        })
    if session.get('authenticated') and session.get('legacy_login'):
        return jsonify({
            'is_admin': True,
            'legacy_login': True
        })
    return jsonify({'authenticated': False}), 401

@app.route('/api/auth/check-feature/<feature>')
def check_feature_permission(feature):
    """API endpoint to check if user has permission for a feature"""
    if _is_full_access_user():
        return jsonify({'has_permission': True, 'feature': feature})
    dashboard_user = session.get('dashboard_user')
    if dashboard_user:
        return jsonify({'has_permission': has_perm(feature), 'feature': feature})
    return jsonify({'has_permission': False, 'authenticated': False}), 401

# ============ Admin Panel Routes ============

@app.route('/admin')
@login_required
def admin_panel():
    # Check admin access for page route (redirect instead of JSON 403)
    user = session.get('dashboard_user')
    is_admin = (
        (user and user.get('is_admin')) or
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
    """Redirect to the first accessible page in the first section the user has access to.
    Section-aware so a custom group (e.g. Student Worker + Captain) that has section.lionbyte
    but not page.dashboard specifically still lands inside LionByteGG instead of bouncing to
    a different section entirely."""
    # Full-access users go to main dashboard
    if _is_full_access_user():
        return redirect(url_for('dashboard'))
    # Use the unioned permission set (group perms + captain/coach baseline, if applicable)
    perms = set(auth_db.resolve_perm(p) for p in get_user_perms())
    # (section_perm, [(page_perm, url), ...]) — first section the user can access wins; within
    # that section, the first page permission they actually hold wins (not just the dashboard).
    section_fallbacks = [
        ('section.lionbyte', [
            ('page.dashboard', '/dashboard'),
            ('page.rosters', '/rosters'),
            ('page.members', '/members'),
            ('page.varsity', '/varsity'),
            ('page.analytics', '/analytics'),
            ('page.users', '/users'),
            ('page.moderation', '/moderation'),
            ('page.tickets', '/tickets'),
            ('page.reaction_roles', '/reaction-roles'),
            ('page.vc_system', '/vc-system'),
            ('page.logs', '/logs'),
            ('page.settings', '/settings'),
        ]),
        ('section.boilercraft', [
            ('page.boilercraft', '/boilercraft/dashboard'),
            ('page.boilercraft_faq', '/boilercraft/faq'),
        ]),
        ('section.lionshift', [
            ('page.shift_dashboard', '/lionshift/dashboard'),
            ('page.shift_schedules', '/lionshift/schedules'),
            ('page.shift_workers', '/lionshift/workers'),
            ('page.shift_offers', '/lionshift/offers'),
            ('page.shift_trades', '/lionshift/trades'),
            ('page.shift_timeoff', '/lionshift/timeoff'),
            ('page.shift_logs', '/lionshift/logs'),
        ]),
        ('section.lionbeats', [
            ('page.music_dashboard', '/music/dashboard'),
            ('page.music_features', '/music/features'),
        ]),
        ('section.arena', [
            ('page.arena_live', '/arena/live'),
            ('page.arena_students', '/arena/students'),
            ('page.arena_reports', '/arena/reports'),
            ('page.arena_logs', '/arena/logs'),
            ('page.arena_controls', '/arena/controls'),
            ('page.arena_inventory', '/arena/inventory'),
            ('page.arena_sessions', '/arena/sessions'),
        ]),
    ]
    for section_perm, pages in section_fallbacks:
        if section_perm in perms:
            for page_perm, url in pages:
                if page_perm in perms:
                    return redirect(url)
    if 'admin.panel' in perms:
        return redirect('/admin')
    # No sections or pages accessible — show an error
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

# ============ ARENA INVENTORY (moved from the retired "Worker On Duty" app) ============

@app.route('/arena/inventory')
@login_required
@page_permission_required('page.arena_inventory')
def arena_inventory():
    return render_template('onduty.html', active_tab='equipment', arena_mode=True)

# Old On-Duty inventory URLs now live under Arena Staff.
@app.route('/onduty/dashboard')
@app.route('/onduty/equipment')
@login_required
def onduty_inventory_redirect():
    return redirect('/arena/inventory')

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

# ============ LionShiftGG Dashboard ============

LIONSHIFT_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "LionShiftGG")
LIONSHIFT_SCHEDULES = os.path.join(LIONSHIFT_DATA_DIR, "schedules.json")
LIONSHIFT_SHIFT_BOARD = os.path.join(LIONSHIFT_DATA_DIR, "shift_board.json")
LIONSHIFT_SHIFT_LOGS = os.path.join(LIONSHIFT_DATA_DIR, "shift_logs.json")
LIONSHIFT_TRADES = os.path.join(LIONSHIFT_DATA_DIR, "trades.json")
LIONSHIFT_TIMEOFF = os.path.join(LIONSHIFT_DATA_DIR, "timeoff_requests.json")
LIONSHIFT_WORKERS = os.path.join(LIONSHIFT_DATA_DIR, "workers_cache.json")
LIONSHIFT_SETTINGS = os.path.join(LIONSHIFT_DATA_DIR, "settings.json")
LIONSHIFT_AVAILABILITY = os.path.join(LIONSHIFT_DATA_DIR, "worker_availability.json")
LIONSHIFT_SHIFT_DUTIES = os.path.join(LIONSHIFT_DATA_DIR, "shift_duties.json")

def load_shift_schedules():
    return load_json_file(LIONSHIFT_SCHEDULES, [])

def load_shift_board():
    return load_json_file(LIONSHIFT_SHIFT_BOARD, {"shift_board": {}, "shift_counter": 0})

def load_shift_logs():
    return load_json_file(LIONSHIFT_SHIFT_LOGS, [])

def load_shift_trades():
    return load_json_file(LIONSHIFT_TRADES, [])

def load_shift_timeoff():
    return load_json_file(LIONSHIFT_TIMEOFF, [])

def load_shift_workers():
    return load_json_file(LIONSHIFT_WORKERS, [])

def load_shift_settings():
    return load_json_file(LIONSHIFT_SETTINGS, {})

def load_shift_availability():
    return load_json_file(LIONSHIFT_AVAILABILITY, {})


# -- Rooms / locations (configurable; shared with the bot) --------------
LIONSHIFT_ROOMS = os.path.join(LIONSHIFT_DATA_DIR, "rooms.json")

_ROOM_DEFAULTS = [
    {"id": "pc", "name": "PC Room", "emoji": "\U0001f5a5\ufe0f", "color": "#3b82f6", "order": 0},
    {"id": "console", "name": "Console Room", "emoji": "\U0001f3ae", "color": "#a855f7", "order": 1},
]


def load_shift_rooms():
    """Configurable arena rooms. Seeds a default PC + Console on first use."""
    rooms = load_json_file(LIONSHIFT_ROOMS, None)
    if not rooms or not isinstance(rooms, list):
        rooms = [dict(r) for r in _ROOM_DEFAULTS]
        save_json_file(LIONSHIFT_ROOMS, rooms)
    rooms.sort(key=lambda r: r.get("order", 0))
    return rooms


def default_room_id():
    rooms = load_shift_rooms()
    return rooms[0]["id"] if rooms else "pc"


_ROLE_KEYS = ("opener", "mid", "closer")
_ROLE_GREETINGS = {
    "opener": "\U0001f305 You're the Opener today! Here's what you need to take care of:",
    "mid": "\u2600\ufe0f You're the Mid-Shift worker today! Here's what you need to take care of:",
    "closer": "\U0001f319 You're the Closer tonight! Here's what you need to take care of:",
}


def _blank_room_duties():
    return {role: {"greeting": _ROLE_GREETINGS[role], "tasks": []} for role in _ROLE_KEYS}


def load_room_duties():
    """Return shift duties keyed by room id -> role -> {greeting, tasks}.

    Migrates the legacy flat {opener,mid,closer} format (single implicit room)
    into the first room the first time it is read, so old checklists are kept.
    """
    raw = load_json_file(LIONSHIFT_SHIFT_DUTIES, None)
    rooms = load_shift_rooms()
    room_ids = [r["id"] for r in rooms]
    out = {}
    legacy = isinstance(raw, dict) and any(k in raw for k in _ROLE_KEYS)
    for rid in room_ids:
        if isinstance(raw, dict) and isinstance(raw.get(rid), dict) and any(k in raw[rid] for k in _ROLE_KEYS):
            src = raw[rid]
        elif legacy and rid == room_ids[0]:
            src = raw  # migrate the old single checklist onto the first room
        else:
            src = None
        room = _blank_room_duties()
        if isinstance(src, dict):
            for role in _ROLE_KEYS:
                rd = src.get(role) or {}
                if isinstance(rd, dict):
                    room[role]["greeting"] = str(rd.get("greeting") or _ROLE_GREETINGS[role])
                    room[role]["tasks"] = rd.get("tasks") or []
        out[rid] = room
    return out


@app.route('/lionshift')
@app.route('/lionshift/')
@app.route('/lionshift/dashboard')
@app.route('/lionshift/calendar')
@login_required
@page_permission_required('page.shift_dashboard')
def lionshift_dashboard():
    return render_template('lionshift.html', active_tab='calendar')


@app.route('/lionshift/schedules')
@login_required
@page_permission_required('page.shift_schedules')
def lionshift_schedules():
    return render_template('lionshift.html', active_tab='schedules')


@app.route('/lionshift/workers')
@login_required
@page_permission_required('page.shift_workers')
def lionshift_workers():
    return render_template('lionshift.html', active_tab='workers')


@app.route('/lionshift/activity')
@app.route('/lionshift/offers')
@login_required
@page_permission_required('page.shift_offers')
def lionshift_activity():
    return render_template('lionshift.html', active_tab='activity')


@app.route('/lionshift/trades')
@login_required
@page_permission_required('page.shift_trades')
def lionshift_trades():
    return render_template('lionshift.html', active_tab='activity')


@app.route('/lionshift/timeoff')
@login_required
@page_permission_required('page.shift_timeoff')
def lionshift_timeoff():
    return render_template('lionshift.html', active_tab='activity')


@app.route('/lionshift/logs')
@login_required
@page_permission_required('page.shift_logs')
def lionshift_logs():
    return render_template('lionshift.html', active_tab='logs')



@app.route('/lionshift/tasks')
@login_required
@page_permission_required('page.shift_dashboard')
def lionshift_tasks():
    return render_template('lionshift.html', active_tab='tasks')

@app.route('/lionshift/bot-settings')
@login_required
@page_permission_required('page.shift_dashboard')
def lionshift_bot_settings():
    return render_template('lionshift.html', active_tab='bot-settings')

# ── LionShift API Endpoints ─────────────────────────────────────────────

@app.route('/api/lionshift/stats')
@api_auth_required
def api_lionshift_stats():
    """Quick stats for shift dashboard."""
    schedules = load_shift_schedules()
    board = load_shift_board()
    workers = load_shift_workers()
    trades = load_shift_trades()
    timeoff = load_shift_timeoff()
    logs = load_shift_logs()

    offers = board.get("shift_board", {})
    open_offers = sum(1 for o in offers.values() if not o.get("taken_by"))
    taken_offers = sum(1 for o in offers.values() if o.get("taken_by"))
    pending_trades = sum(1 for t in trades if t.get("status", "").lower() == "pending")
    pending_timeoff = sum(1 for t in timeoff if t.get("status", "").lower() == "pending")
    clocked_in = sum(1 for w in workers if w.get("clocked_in"))

    return jsonify({
        "success": True,
        "schedule_count": len(schedules),
        "worker_count": len(workers),
        "clocked_in": clocked_in,
        "open_offers": open_offers,
        "taken_offers": taken_offers,
        "pending_trades": pending_trades,
        "pending_timeoff": pending_timeoff,
        "log_count": len(logs),
    })


@app.route('/api/lionshift/schedules')
@api_auth_required
def api_lionshift_schedules():
    return jsonify({"success": True, "schedules": load_shift_schedules()})


@app.route('/api/lionshift/workers')
@api_auth_required
def api_lionshift_workers():
    return jsonify({"success": True, "workers": load_shift_workers()})


@app.route('/api/lionshift/offers')
@api_auth_required
def api_lionshift_offers():
    board = load_shift_board()
    offers = []
    for offer_id, offer in board.get("shift_board", {}).items():
        offer["id"] = offer_id
        offers.append(offer)
    # Also include taken_shifts history for the web
    taken = board.get("taken_shifts", [])
    return jsonify({"success": True, "offers": offers, "taken_shifts": taken})


@app.route('/api/lionshift/trades')
@api_auth_required
def api_lionshift_trades():
    return jsonify({"success": True, "trades": load_shift_trades()})


@app.route('/api/lionshift/timeoff')
@api_auth_required
def api_lionshift_timeoff():
    return jsonify({"success": True, "requests": load_shift_timeoff()})


@app.route('/api/lionshift/logs')
@api_auth_required
def api_lionshift_logs():
    logs = load_shift_logs()
    # Return newest-first, limit to 100
    return jsonify({"success": True, "logs": list(reversed(logs))[:100]})


# -- LionShift Schedule Creator ------------------------------------------

LIONSHIFT_NOTIFICATION_QUEUE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "LionByteGG", "data", "lionshift_notification_queue.json")

@app.route('/lionshift/schedule-creator')
@login_required
@page_permission_required('page.shift_schedules')
def lionshift_schedule_creator():
    return redirect(url_for('lionshift_schedules'))


@app.route('/api/lionshift/schedules', methods=['POST'])
@api_auth_required
def api_lionshift_schedule_create():
    """Create a new schedule (draft or published)."""
    if not has_perm('schedules.manage'):
        return jsonify({"success": False, "message": "Permission denied"}), 403
    data = request.json
    if not data:
        return jsonify({"success": False, "message": "No data provided"}), 400

    name = (data.get('name') or '').strip()
    start_date = (data.get('start_date') or '').strip()
    end_date = (data.get('end_date') or '').strip()

    if not name or not start_date or not end_date:
        return jsonify({"success": False, "message": "Name, start date, and end date are required"}), 400

    schedule_link = (data.get('schedule_link') or '').strip()
    allow_offers = data.get('allow_offers', True)
    status = data.get('status', 'draft')  # 'draft' or 'published'
    shifts = data.get('shifts', [])
    announce_at = data.get('announce_at')  # ISO datetime string or null
    custom_message = (data.get('custom_message') or '').strip()
    _shift_defaults = load_shift_settings()
    notify_workers = data.get('notify_workers', _shift_defaults.get('dm_new_schedule', True))

    if status not in ('draft', 'published'):
        status = 'draft'

    moderator = get_moderator_name()
    now = datetime.now(timezone.utc).isoformat()

    schedule = {
        "name": name,
        "start_date": start_date,
        "end_date": end_date,
        "schedule_link": schedule_link,
        "allow_offers": bool(allow_offers),
        "status": status,
        "shifts": shifts,
        "announce_at": announce_at,
        "custom_message": custom_message,
        "notify_workers": bool(notify_workers),
        "created_at": now,
        "created_by": moderator,
    }

    schedules = load_shift_schedules()
    schedules.append(schedule)
    save_json_file(LIONSHIFT_SCHEDULES, schedules)

    # If published immediately, queue announcement
    if status == 'published' and not announce_at:
        _queue_schedule_announcement(schedule, custom_message, notify_workers)

    return jsonify({"success": True, "message": f"Schedule '{name}' {'published' if status == 'published' else 'saved as draft'}.", "index": len(schedules) - 1})


@app.route('/api/lionshift/schedules/<int:index>', methods=['PUT'])
@api_auth_required
def api_lionshift_schedule_update(index):
    """Update an existing schedule."""
    if not has_perm('schedules.manage'):
        return jsonify({"success": False, "message": "Permission denied"}), 403
    data = request.json
    if not data:
        return jsonify({"success": False, "message": "No data provided"}), 400

    schedules = load_shift_schedules()
    if index < 0 or index >= len(schedules):
        return jsonify({"success": False, "message": "Schedule not found"}), 404

    schedule = schedules[index]
    old_status = schedule.get('status', 'published')

    for field in ('name', 'start_date', 'end_date', 'schedule_link', 'custom_message'):
        if field in data:
            schedule[field] = (data[field] or '').strip() if isinstance(data[field], str) else data[field]

    if 'allow_offers' in data:
        schedule['allow_offers'] = bool(data['allow_offers'])
    if 'shifts' in data:
        schedule['shifts'] = data['shifts']
    if 'status' in data and data['status'] in ('draft', 'published'):
        schedule['status'] = data['status']
    if 'announce_at' in data:
        schedule['announce_at'] = data['announce_at']
    if 'notify_workers' in data:
        schedule['notify_workers'] = bool(data['notify_workers'])

    schedule['updated_at'] = datetime.now(timezone.utc).isoformat()
    schedule['updated_by'] = get_moderator_name()

    schedules[index] = schedule
    save_json_file(LIONSHIFT_SCHEDULES, schedules)

    # If just changed from draft to published, announce
    if old_status == 'draft' and schedule.get('status') == 'published' and not schedule.get('announce_at'):
        _queue_schedule_announcement(schedule, schedule.get('custom_message', ''), schedule.get('notify_workers', False))

    return jsonify({"success": True, "message": f"Schedule '{schedule.get('name', '')}' updated."})


@app.route('/api/lionshift/schedules/<int:index>', methods=['DELETE'])
@api_auth_required
def api_lionshift_schedule_delete(index):
    """Delete a schedule."""
    if not has_perm('schedules.manage'):
        return jsonify({"success": False, "message": "Permission denied"}), 403
    schedules = load_shift_schedules()
    if index < 0 or index >= len(schedules):
        return jsonify({"success": False, "message": "Schedule not found"}), 404

    removed = schedules.pop(index)
    save_json_file(LIONSHIFT_SCHEDULES, schedules)
    return jsonify({"success": True, "message": f"Schedule '{removed.get('name', '')}' deleted."})


@app.route('/api/lionshift/schedules/<int:index>/publish', methods=['POST'])
@api_auth_required
def api_lionshift_schedule_publish(index):
    """Publish a draft schedule and optionally announce it."""
    if not has_perm('schedules.manage'):
        return jsonify({"success": False, "message": "Permission denied"}), 403
    data = request.json or {}
    schedules = load_shift_schedules()
    if index < 0 or index >= len(schedules):
        return jsonify({"success": False, "message": "Schedule not found"}), 404

    schedule = schedules[index]
    schedule['status'] = 'published'
    schedule['updated_at'] = datetime.now(timezone.utc).isoformat()
    schedule['updated_by'] = get_moderator_name()

    custom_message = data.get('custom_message', schedule.get('custom_message', ''))
    notify_workers = data.get('notify_workers', schedule.get('notify_workers', False))
    announce_at = data.get('announce_at')

    if announce_at:
        schedule['announce_at'] = announce_at
    else:
        # Announce immediately
        _queue_schedule_announcement(schedule, custom_message, notify_workers)

    schedules[index] = schedule
    save_json_file(LIONSHIFT_SCHEDULES, schedules)
    return jsonify({"success": True, "message": f"Schedule '{schedule.get('name', '')}' published!"})


@app.route('/api/lionshift/schedules/<int:index>/announce', methods=['POST'])
@api_auth_required
def api_lionshift_schedule_announce(index):
    """Manually announce a published schedule."""
    if not has_perm('schedules.manage'):
        return jsonify({"success": False, "message": "Permission denied"}), 403
    data = request.json or {}
    schedules = load_shift_schedules()
    if index < 0 or index >= len(schedules):
        return jsonify({"success": False, "message": "Schedule not found"}), 404

    schedule = schedules[index]
    custom_message = data.get('custom_message', schedule.get('custom_message', ''))
    notify_workers = data.get('notify_workers', schedule.get('notify_workers', False))

    _queue_schedule_announcement(schedule, custom_message, notify_workers)
    return jsonify({"success": True, "message": f"Announcement queued for '{schedule.get('name', '')}'!"})


@app.route('/api/lionshift/dm-workers', methods=['POST'])
@api_auth_required
def api_lionshift_dm_workers():
    """Queue DM notifications to workers."""
    data = request.json
    if not data:
        return jsonify({"success": False, "message": "No data provided"}), 400

    worker_ids = data.get('worker_ids', [])
    message = (data.get('message') or '').strip()

    if not message:
        return jsonify({"success": False, "message": "Message is required"}), 400

    if not worker_ids:
        wk = load_shift_workers()
        worker_ids = [w.get('discord_id') or w.get('id') for w in wk if w.get('discord_id') or w.get('id')]

    safe_queue_append(LIONSHIFT_NOTIFICATION_QUEUE, {
        "type": "dm_workers",
        "status": "pending",
        "worker_ids": worker_ids,
        "message": message,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": get_moderator_name(),
    })

    return jsonify({"success": True, "message": f"DM queued for {len(worker_ids)} worker(s)."})


# -- Worker Hours Calculation ------------------------------------------

@app.route('/api/lionshift/worker-hours')
@api_auth_required
def api_lionshift_worker_hours():
    """Calculate hours for all workers from schedules (primary) and shift logs (if available)."""
    schedules = load_shift_schedules()
    logs = load_shift_logs()
    workers = load_shift_workers()

    worker_map = {w.get('id') or w.get('discord_id'): w for w in workers}

    now = datetime.now(timezone.utc)
    week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # -- 1. Calculate SCHEDULED hours from schedules.json --------------
    sched_data = defaultdict(lambda: {"total_s": 0, "week_s": 0, "month_s": 0, "count": 0, "name": "Unknown"})
    for schedule in schedules:
        for shift in schedule.get("shifts", []):
            wid = str(shift.get("worker_id", "") or "")
            if not wid:
                continue
            date_str = shift.get("date", "")
            start_str = shift.get("start", "")
            end_str = shift.get("end", "")
            if not (date_str and start_str and end_str):
                continue
            try:
                start_dt = datetime.fromisoformat(f"{date_str}T{start_str}:00").replace(tzinfo=timezone.utc)
                end_dt = datetime.fromisoformat(f"{date_str}T{end_str}:00").replace(tzinfo=timezone.utc)
                diff = (end_dt - start_dt).total_seconds()
                if diff <= 0:
                    continue
                sched_data[wid]["total_s"] += diff
                sched_data[wid]["count"] += 1
                sched_data[wid]["name"] = shift.get("worker_name") or worker_map.get(wid, {}).get("name", "Unknown")
                if start_dt >= week_start:
                    sched_data[wid]["week_s"] += diff
                if start_dt >= month_start:
                    sched_data[wid]["month_s"] += diff
            except Exception:
                continue

    # -- 2. Calculate LOGGED hours from shift_logs.json (clock in/out) --
    user_logs = defaultdict(list)
    for log in sorted(logs, key=lambda x: x.get('timestamp', '')):
        uid = str(log.get('user_id', ''))
        if uid:
            user_logs[uid].append(log)

    logged_data = {}
    for uid, ulogs in user_logs.items():
        total_s = week_s = month_s = shift_count = 0
        active_start = None
        for entry in ulogs:
            ts_str = entry.get('timestamp', '')
            if entry.get('action') == 'start':
                try:
                    active_start = datetime.fromisoformat(ts_str)
                    if active_start.tzinfo is None:
                        active_start = active_start.replace(tzinfo=timezone.utc)
                except Exception:
                    active_start = None
            elif entry.get('action') == 'end' and active_start:
                try:
                    end_time = datetime.fromisoformat(ts_str)
                    if end_time.tzinfo is None:
                        end_time = end_time.replace(tzinfo=timezone.utc)
                    diff = (end_time - active_start).total_seconds()
                    if 0 < diff < 86400:
                        total_s += diff
                        shift_count += 1
                        if active_start >= week_start:
                            week_s += diff
                        if active_start >= month_start:
                            month_s += diff
                except Exception:
                    pass
                active_start = None
        logged_data[uid] = {"total_s": total_s, "week_s": week_s, "month_s": month_s, "count": shift_count}

    # -- 3. Merge: prefer logged hours if they exist, else use scheduled -
    all_ids = set(sched_data.keys()) | set(logged_data.keys()) | set(worker_map.keys())
    results = []
    for uid in all_ids:
        s = sched_data.get(uid, {})
        l = logged_data.get(uid, {})
        w = worker_map.get(uid, {})
        name = s.get("name") or w.get("name", "Unknown")
        has_logs = l.get("count", 0) > 0
        if has_logs:
            total_h = round(l["total_s"] / 3600, 2)
            week_h = round(l["week_s"] / 3600, 2)
            month_h = round(l["month_s"] / 3600, 2)
            count = l["count"]
            source = "logged"
        else:
            total_h = round(s.get("total_s", 0) / 3600, 2)
            week_h = round(s.get("week_s", 0) / 3600, 2)
            month_h = round(s.get("month_s", 0) / 3600, 2)
            count = s.get("count", 0)
            source = "scheduled"
        results.append({
            "user_id": uid,
            "name": name,
            "total_hours": total_h,
            "week_hours": week_h,
            "month_hours": month_h,
            "shift_count": count,
            "is_clocked_in": w.get("clocked_in", False),
            "source": source
        })

    results.sort(key=lambda x: x["total_hours"], reverse=True)
    return jsonify({"success": True, "hours": results})


# -- Worker Availability CRUD ------------------------------------------

@app.route('/api/lionshift/availability')
@api_auth_required
def api_lionshift_availability():
    """Get all worker availability."""
    return jsonify({"success": True, "availability": load_shift_availability()})


@app.route('/api/lionshift/availability/<worker_id>', methods=['GET', 'PUT', 'DELETE'])
@api_auth_required
def api_lionshift_worker_availability(worker_id):
    """Get, update, or delete a worker's availability."""
    avail = load_shift_availability()
    
    if request.method == 'GET':
        return jsonify({"success": True, "availability": avail.get(worker_id, {})})
    
    if request.method == 'DELETE':
        if worker_id in avail:
            del avail[worker_id]
            save_json_file(LIONSHIFT_AVAILABILITY, avail)
            return jsonify({"success": True, "message": "Availability deleted."})
        return jsonify({"success": False, "message": "Worker availability not found."}), 404
    
    # PUT — update availability
    data = request.json
    if not data:
        return jsonify({"success": False, "message": "No data provided"}), 400
    
    # Expected format: { "monday": [{"start": "09:00", "end": "14:00"}], "tuesday": [...], ... }
    avail[worker_id] = {
        "slots": data.get('slots', {}),
        "notes": (data.get('notes') or '').strip(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "updated_by": get_moderator_name()
    }
    save_json_file(LIONSHIFT_AVAILABILITY, avail)
    return jsonify({"success": True, "message": "Availability updated."})



# -- Bot Settings API --

# -- Rooms / locations CRUD ---------------------------------------------

@app.route('/api/lionshift/rooms', methods=['GET'])
@api_auth_required
def api_lionshift_rooms_get():
    return jsonify({"success": True, "rooms": load_shift_rooms()})


@app.route('/api/lionshift/rooms', methods=['POST'])
@api_auth_required
def api_lionshift_rooms_post():
    """Replace the full rooms list (managers configure/add/rename/remove rooms)."""
    if not has_perm('schedules.manage'):
        return jsonify({"success": False, "message": "Permission denied"}), 403
    import re as _re
    data = request.json or {}
    raw = data.get('rooms', [])
    if not isinstance(raw, list) or not raw:
        return jsonify({"success": False, "message": "At least one room is required"}), 400
    rooms, seen = [], set()
    for i, r in enumerate(raw):
        if not isinstance(r, dict):
            continue
        name = str(r.get('name', '')).strip()[:40]
        if not name:
            continue
        rid = _re.sub(r'[^a-z0-9_-]+', '-', str(r.get('id', '')).strip().lower()).strip('-')
        if not rid:
            rid = _re.sub(r'[^a-z0-9_-]+', '-', name.lower()).strip('-') or f'room{i}'
        base, n = rid, 2
        while rid in seen:
            rid = f'{base}-{n}'; n += 1
        seen.add(rid)
        color = str(r.get('color', '') or '').strip()
        if not _re.match(r'^#[0-9a-fA-F]{6}$', color):
            color = '#3b82f6'
        rooms.append({'id': rid, 'name': name, 'emoji': str(r.get('emoji', '') or '').strip()[:8],
                      'color': color, 'order': i})
    if not rooms:
        return jsonify({"success": False, "message": "At least one valid room is required"}), 400
    save_json_file(LIONSHIFT_ROOMS, rooms)
    return jsonify({"success": True, "rooms": rooms, "message": "Rooms saved."})


# -- Shift Duties CRUD (per room + role) --------------------------------

@app.route('/api/lionshift/shift-duties', methods=['GET'])
@api_auth_required
def api_lionshift_shift_duties_get():
    return jsonify({"success": True, "duties": load_room_duties(), "rooms": load_shift_rooms()})


@app.route('/api/lionshift/shift-duties', methods=['POST'])
@api_auth_required
def api_lionshift_shift_duties_post():
    if not has_perm('schedules.manage'):
        return jsonify({"success": False, "message": "Permission denied"}), 403
    data = request.json or {}
    incoming = data.get('duties', data)  # accept {duties:{room:{role}}} or bare {room:{role}}
    out = {}
    for rid in [r['id'] for r in load_shift_rooms()]:
        room_in = incoming.get(rid, {}) if isinstance(incoming, dict) else {}
        room_out = {}
        for role in _ROLE_KEYS:
            role_data = room_in.get(role, {}) if isinstance(room_in, dict) else {}
            greeting = str((role_data or {}).get('greeting', '')).strip()[:500] or _ROLE_GREETINGS[role]
            raw_tasks = (role_data or {}).get('tasks', []) if isinstance(role_data, dict) else []
            tasks = []
            for t in raw_tasks:
                if isinstance(t, str):
                    text = t.strip()[:200]
                    if text:
                        tasks.append({'text': text, 'show_on': 'both', 'required': False})
                elif isinstance(t, dict):
                    text = str(t.get('text', '')).strip()[:200]
                    if not text:
                        continue
                    show_on = t.get('show_on', 'both')
                    if show_on not in ('start', 'end', 'both'):
                        show_on = 'both'
                    tasks.append({'text': text, 'show_on': show_on, 'required': bool(t.get('required', False))})
            room_out[role] = {'greeting': greeting, 'tasks': tasks[:30]}
        out[rid] = room_out
    save_json_file(LIONSHIFT_SHIFT_DUTIES, out)
    return jsonify({"success": True, "message": "Shift duties saved."})


@app.route('/api/lionshift/bot-settings', methods=['GET'])
@api_auth_required
def api_lionshift_bot_settings_get():
    settings = load_shift_settings()
    return jsonify({
        "success": True,
        "dm_shift_reminders": settings.get("dm_shift_reminders", True),
        "dm_late_alerts": settings.get("dm_late_alerts", True),
        "reminder_minutes_before": int(settings.get("reminder_minutes_before", 60)),
        "late_alert_minutes": int(settings.get("late_alert_minutes", 10)),
        "dm_new_schedule": settings.get("dm_new_schedule", True),
        "allow_shift_trading": settings.get("allow_shift_trading", True),
    })


@app.route('/api/lionshift/bot-settings', methods=['POST'])
@api_auth_required
def api_lionshift_bot_settings_post():
    data = request.json or {}
    settings = load_shift_settings()
    changed = []
    # Boolean toggles
    for key in ("dm_shift_reminders", "dm_late_alerts", "dm_new_schedule", "allow_shift_trading"):
        if key in data:
            settings[key] = bool(data[key])
            changed.append(key)
    # Integer timing values — validated to reasonable ranges
    if "reminder_minutes_before" in data:
        val = int(data["reminder_minutes_before"])
        if not (5 <= val <= 480):
            return jsonify({"success": False, "message": "reminder_minutes_before must be between 5 and 480"}), 400
        settings["reminder_minutes_before"] = val
        changed.append("reminder_minutes_before")
    if "late_alert_minutes" in data:
        val = int(data["late_alert_minutes"])
        if not (1 <= val <= 60):
            return jsonify({"success": False, "message": "late_alert_minutes must be between 1 and 60"}), 400
        settings["late_alert_minutes"] = val
        changed.append("late_alert_minutes")
    if not changed:
        return jsonify({"success": False, "message": "No valid settings provided"}), 400
    settings["updated_by"] = get_moderator_name()
    save_json_file(LIONSHIFT_SETTINGS, settings)
    return jsonify({"success": True, "message": "Bot settings saved."})


# -- Approve/Decline Trades & TimeOff from Web --------------------------

@app.route('/api/lionshift/trades/<trade_id>/approve', methods=['POST'])
@api_auth_required
def api_lionshift_trade_approve(trade_id):
    """Approve a trade from the web dashboard."""
    trades = load_shift_trades()
    found = False
    for trade in trades:
        if str(trade.get('id')) == str(trade_id):
            trade['status'] = 'approved'
            trade['updated_at'] = datetime.now(timezone.utc).isoformat()
            trade['updated_by'] = get_moderator_name()
            found = True
            break
    if not found:
        return jsonify({"success": False, "message": "Trade not found"}), 404
    save_json_file(LIONSHIFT_TRADES, trades)
    
    # Queue DM notifications to both parties
    requester_id = trade.get('requester_id')
    target_id = trade.get('target_id')
    shift_info = f"{trade.get('shift_type','?').title()} on {trade.get('date','?')} ({trade.get('start','?')}–{trade.get('end','?')})"
    requester_msg = f"Your shift trade (ID #{trade_id}) for **{shift_info}** has been **approved** by {get_moderator_name()}. {trade.get('target_name','Your trade partner')} will now cover that shift."
    target_msg = f"Your shift trade (ID #{trade_id}) has been **approved** by {get_moderator_name()}. You are now covering **{shift_info}**."
    for wid, dm_msg in [(requester_id, requester_msg), (target_id, target_msg)]:
        if wid:
            safe_queue_append(LIONSHIFT_NOTIFICATION_QUEUE, {
                "type": "dm_workers",
                "status": "pending",
                "worker_ids": [str(wid)],
                "message": dm_msg,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "created_by": get_moderator_name()
            })
    
    return jsonify({"success": True, "message": "Trade approved. Workers will be notified."})


@app.route('/api/lionshift/trades/<trade_id>/decline', methods=['POST'])
@api_auth_required
def api_lionshift_trade_decline(trade_id):
    """Decline a trade from the web dashboard."""
    data = request.json or {}
    reason = (data.get('reason') or 'Declined from dashboard').strip()
    
    trades = load_shift_trades()
    found = False
    for trade in trades:
        if str(trade.get('id')) == str(trade_id):
            trade['status'] = 'declined'
            trade['decline_reason'] = reason
            trade['updated_at'] = datetime.now(timezone.utc).isoformat()
            trade['updated_by'] = get_moderator_name()
            found = True
            break
    if not found:
        return jsonify({"success": False, "message": "Trade not found"}), 404
    save_json_file(LIONSHIFT_TRADES, trades)
    
    # DM both parties
    requester_id = trade.get('requester_id')
    target_id = trade.get('target_id')
    msg = f"Your shift trade (ID #{trade_id}) has been **declined** by {get_moderator_name()}.\n**Reason:** {reason}"
    for wid in [requester_id, target_id]:
        if wid:
            safe_queue_append(LIONSHIFT_NOTIFICATION_QUEUE, {
                "type": "dm_workers",
                "status": "pending",
                "worker_ids": [str(wid)],
                "message": msg,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "created_by": get_moderator_name()
            })
    
    return jsonify({"success": True, "message": "Trade declined. Workers will be notified."})


@app.route('/api/lionshift/timeoff/<request_id>/approve', methods=['POST'])
@api_auth_required
def api_lionshift_timeoff_approve(request_id):
    """Approve a time-off request from the web dashboard."""
    requests_list = load_shift_timeoff()
    found = False
    req = None
    for r in requests_list:
        if str(r.get('id')) == str(request_id):
            r['status'] = 'approved'
            r['approved_at'] = datetime.now(timezone.utc).isoformat()
            r['approved_by'] = get_moderator_name()
            found = True
            req = r
            break
    if not found:
        return jsonify({"success": False, "message": "Request not found"}), 404
    save_json_file(LIONSHIFT_TIMEOFF, requests_list)
    
    # DM the worker
    if req and req.get('user_id'):
        msg = f"Your time-off request ({req.get('from_date')} to {req.get('to_date')}) has been **approved** by {get_moderator_name()}."
        safe_queue_append(LIONSHIFT_NOTIFICATION_QUEUE, {
            "type": "dm_workers",
            "status": "pending",
            "worker_ids": [str(req['user_id'])],
            "message": msg,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "created_by": get_moderator_name()
        })
    
    return jsonify({"success": True, "message": "Time-off request approved."})


@app.route('/api/lionshift/timeoff/<request_id>/decline', methods=['POST'])
@api_auth_required
def api_lionshift_timeoff_decline(request_id):
    """Decline a time-off request from the web dashboard."""
    data = request.json or {}
    reason = (data.get('reason') or 'Declined from dashboard').strip()
    
    requests_list = load_shift_timeoff()
    found = False
    req = None
    for r in requests_list:
        if str(r.get('id')) == str(request_id):
            r['status'] = 'declined'
            r['declined_at'] = datetime.now(timezone.utc).isoformat()
            r['decline_reason'] = reason
            r['declined_by'] = get_moderator_name()
            found = True
            req = r
            break
    if not found:
        return jsonify({"success": False, "message": "Request not found"}), 404
    save_json_file(LIONSHIFT_TIMEOFF, requests_list)
    
    # DM the worker
    if req and req.get('user_id'):
        msg = f"Your time-off request ({req.get('from_date')} to {req.get('to_date')}) has been **declined**.\n**Reason:** {reason}"
        safe_queue_append(LIONSHIFT_NOTIFICATION_QUEUE, {
            "type": "dm_workers",
            "status": "pending",
            "worker_ids": [str(req['user_id'])],
            "message": msg,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "created_by": get_moderator_name()
        })
    
    return jsonify({"success": True, "message": "Time-off request declined."})


def _queue_schedule_announcement(schedule, custom_message='', notify_workers=False):
    """Queue a schedule announcement for the LionShift bot to process."""
    settings = load_shift_settings()
    channel_id = settings.get('announcement_channel_id') or settings.get('schedule_announcement_channel_id', '')
    if not channel_id:
        return

    # Build shift summary for richer Discord embed
    shifts = schedule.get('shifts', [])
    _rooms_by_id = {r['id']: r for r in load_shift_rooms()}
    shift_summary = {}
    for s in shifts:
        day = s.get('date', 'Unknown')
        if day not in shift_summary:
            shift_summary[day] = []
        worker = s.get('worker_name') or 'Unassigned'
        _room = _rooms_by_id.get(s.get('room'))
        _room_sfx = f" | {_room['name']}" if _room else ""
        shift_summary[day].append(f"{(s.get('type') or '?').title()}: {s.get('start','?')}-{s.get('end','?')} ({worker}){_room_sfx}")

    safe_queue_append(LIONSHIFT_NOTIFICATION_QUEUE, {
        "type": "schedule_announcement",
        "status": "pending",
        "channel_id": str(channel_id),
        "schedule": {
            "name": schedule.get("name", ""),
            "start_date": schedule.get("start_date", ""),
            "end_date": schedule.get("end_date", ""),
            "schedule_link": schedule.get("schedule_link", ""),
            "allow_offers": schedule.get("allow_offers", True),
            "created_by": schedule.get("created_by", "Dashboard Admin"),
            "shift_count": len(shifts),
            "shift_summary": shift_summary,
        },
        "custom_message": custom_message,
        "notify_workers": notify_workers,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


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
    # Legacy admin gets full boilercraft access
    if session.get('legacy_login'):
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

    dashboard_user = session.get('dashboard_user', {}).get('username') or 'Dashboard'
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
    
    # Get verification data from SQLite database
    import sqlite3
    verification = None
    if os.path.exists(BOILERCRAFT_DB_PATH):
        try:
            conn = sqlite3.connect(BOILERCRAFT_DB_PATH)
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT discord_id, minecraft_username, minecraft_uuid, first_name, email, phone, campus, verified_at FROM verified_users WHERE discord_id = ?",
                (int(user_id),)
            )
            row = cursor.fetchone()
            if row:
                verification = {
                    "discord_id": str(row["discord_id"]),
                    "minecraft_username": row["minecraft_username"],
                    "minecraft_uuid": row["minecraft_uuid"],
                    "first_name": row["first_name"],
                    "email": row["email"],
                    "phone": row["phone"],
                    "campus": row["campus"],
                    "verified_at": row["verified_at"],
                }
            conn.close()
        except Exception:
            pass
    
    return jsonify({
        "member": member,
        "records": records,
        "verification": verification
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
            "type": "Violation",
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "moderator": moderator_name,
            "moderator_id": moderator_id,
            "source": "website"
        })
        
        save_json_file(record_file, records)
        
        return jsonify({
            "success": True,
            "message": f"Violation issued to {target_name} and added to their record."
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
            activity_data['updated_by'] = get_moderator_name()
            
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
            'requested_by': get_moderator_name()
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
            'requested_by': get_moderator_name()
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
                        regs = load_json_file(filepath, [])
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
    
    stats["total_violations"] = sum(len([r for r in records if r.get("type") in ("Warning", "Violation")]) 
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
                        violations = len([r for r in records if r.get('type') in ('Warning', 'Violation')])
                        automod_flags = len([r for r in records if r.get('type') == 'AutoMod Flag'])
                        kicks = len([r for r in records if r.get('type') == 'Kick'])
                        bans = len([r for r in records if r.get('type') == 'Ban'])
                        results.append({
                            "type": "user_record",
                            "id": user_id,
                            "record_count": len(records),
                            "violations": violations,
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
    total_violations = sum(len([r for r in records if r.get("type") in ("Warning", "Violation")]) 
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
            "total_violations": total_violations,
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
                _sync_automod_bg(words)
                return jsonify({"success": True, "message": f"Added '{word}' to {category}"})
        
        elif action == 'remove' and category in words and word:
            if word.lower() in words[category]:
                words[category].remove(word.lower())
                save_flagged_words(words)
                _sync_automod_bg(words)
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
            "violation_count": len([r for r in user_records if r.get("type") in ("Warning", "Violation")]),
            "automod_count": len([r for r in user_records if r.get("type") == "AutoMod Flag"]),
            "kick_count": len([r for r in user_records if r.get("type") == "Kick"]),
            "ban_count": len([r for r in user_records if r.get("type") == "Ban"])
        })
    
    return jsonify(formatted)

@app.route('/api/user-records/<user_id>')
@api_auth_required
def api_user_record(user_id):
    records = user_db.get_records(user_id)
    return jsonify({"user_id": user_id, "records": records})

@app.route('/api/user-records/<user_id>/clear', methods=['POST'])
@api_auth_required
@api_perm_required('moderation.user_records')
def api_clear_user_record(user_id):
    user_db.clear_records(user_id)
    return jsonify({"success": True, "message": f"Cleared records for user {user_id}"})

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
    
    # Add record to DB
    user_db.add_record(
        user_id=str(user_id),
        type_="Violation",
        reason=reason,
        moderator=moderator,
        source="website"
    )
    
    # Queue notification to bot to DM the user
    queue_discord_notification({
        "type": "warn_user",
        "user_id": str(user_id),
        "reason": reason,
        "moderator": moderator
    })
    
    return jsonify({"success": True, "message": f"Violation issued to user {user_id}"})

@app.route('/api/user-records/<user_id>/remove-warning', methods=['POST'])
@api_auth_required
@api_perm_required('moderation.user_records')
def api_remove_warning(user_id):
    """Remove a specific warning from a user's record"""
    data = request.get_json()
    violation_index = data.get('index')
    
    if violation_index is None:
        return jsonify({"success": False, "message": "Violation index is required"})
    
    removed = user_db.remove_warning_by_index(user_id, violation_index)
    if removed is None:
        return jsonify({"success": False, "message": "Invalid violation index"})
    
    return jsonify({
        "success": True,
        "message": f"Removed violation: {removed.get('reason', 'No reason')}"
    })

@app.route('/api/user-records/<user_id>/remove-record', methods=['POST'])
@api_auth_required
@api_perm_required('moderation.user_records')
def api_remove_record(user_id):
    """Remove a specific record (any type) from a user's record by index"""
    data = request.get_json()
    record_index = data.get('index')
    
    if record_index is None:
        return jsonify({"success": False, "message": "Record index is required"})
    
    removed = user_db.remove_record_by_index(user_id, record_index)
    if removed is None:
        return jsonify({"success": False, "message": "Invalid record index"})
    
    return jsonify({
        "success": True,
        "message": f"Removed {removed.get('type', 'record')}: {removed.get('reason', 'No reason')}"
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
                "violations": 0,
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
        records = user_db.get_records(user_id)
        profile["records"] = records
        
        # Calculate stats from records
        for record in records:
            record_type = record.get('type', '').lower()
            if record_type in ('warning', 'violation'):
                profile["stats"]["violations"] += 1
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
        
        user_db.add_record(
            user_id=user_id,
            type_=note_type,
            reason=note_content,
            moderator="Dashboard Admin",
            source="website"
        )
        
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
            "jv_role_id": None,
            "coach_role_id": None
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
            "coach_role_id": data.get("coach_role_id"),
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

# -- GGLeap daily API-usage meter --------------------------------------------
# Counts every real request we make to GGLeap so staff can see how close we are
# to the plan's daily cap. Persisted so it survives restarts; rolls over on the
# UTC date (GGLeap's quota resets daily).
GGLEAP_DAILY_LIMIT = 10000
_GGLEAP_USAGE_FILE = os.path.join(DATA_DIR, "ggleap_usage.json")
_ggleap_usage_lock = threading.Lock()
_ggleap_usage = {"date": "", "total": 0, "by_kind": {}}

def _ggleap_usage_today():
    """Current UTC date key for the usage meter."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def _ggleap_count(kind="get-all", n=1):
    """Record n GGLeap API request(s) of a given kind toward today's usage."""
    with _ggleap_usage_lock:
        today = _ggleap_usage_today()
        if _ggleap_usage.get("date") != today:
            _ggleap_usage["date"] = today
            _ggleap_usage["total"] = 0
            _ggleap_usage["by_kind"] = {}
        _ggleap_usage["total"] += n
        _ggleap_usage["by_kind"][kind] = _ggleap_usage["by_kind"].get(kind, 0) + n
        try:
            save_json_file(_GGLEAP_USAGE_FILE, _ggleap_usage)
        except Exception:
            pass

def _ggleap_usage_load():
    """Load the persisted usage meter at startup (ignore if it's from a past day)."""
    global _ggleap_usage
    try:
        saved = load_json_file(_GGLEAP_USAGE_FILE, None)
        if isinstance(saved, dict) and saved.get("date") == _ggleap_usage_today():
            _ggleap_usage = {"date": saved["date"], "total": int(saved.get("total", 0)),
                             "by_kind": dict(saved.get("by_kind", {}))}
    except Exception:
        pass

_ggleap_usage_load()

def _ggleap_is_paused():
    """Master kill-switch: when True the server makes NO GGLeap calls at all
    (status, locks, auth). Toggled via the arena config `ggleap_paused`."""
    try:
        return bool(load_arena_config().get("ggleap_paused", False))
    except Exception:
        return False

def get_ggleap_jwt():
    """Refresh JWT token for GGLeap status API"""
    global ggleap_jwt_token
    try:
        import requests
        _ggleap_count("auth")
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
        _ggleap_count("auth")
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

# -- Shared GGLeap machines cache (protects the 10k/day API budget) ----------
# Every consumer (kiosk status, the lock loop, lock-status, bulk actions) goes
# through _ggleap_get_machines() so we make at most ONE real machines/get-all per
# cache window no matter how many callers/kiosks. The window widens when the arena
# is closed since nobody's using the kiosks then.
_ggleap_machines_cache = {"machines": None, "fetched_at": 0, "error": None}
_ggleap_status_cache = {"data": None, "raw_at": -1}

def _ggleap_cache_ttl():
    """Seconds between real get-all calls: short while open (kiosks live), long
    when closed. Keeps daily usage far under GGLeap's 10k/day budget."""
    try:
        return 8 if _arena_is_open_now(load_arena_config()) else 120
    except Exception:
        return 20

def _pc_manager_max_age():
    """Refresh window for the staff PC Manager tab's auto-poll: a flat 15s
    regardless of arena open/closed status. Worst case (this tab left open and
    visible 24 hours a day, every day) is ~5,760 calls/day — under 58% of the
    10,000/day budget, with no reliance on the circuit breaker below. The
    manual Refresh button still bypasses this instantly regardless."""
    return 15

# Hard circuit-breaker: no matter how many tabs are polling or how often staff
# hit the manual force-refresh, once today's usage crosses 85% of the 10k/day
# cap every cache window (including forced ones) gets floored to 60s so the
# remaining budget can't be exhausted by a busy day.
_GGLEAP_DAILY_BUDGET = 10000
_GGLEAP_SAFETY_FLOOR_PCT = 0.85
_GGLEAP_SAFETY_MAX_AGE = 60

def _ggleap_budget_guard(max_age):
    """Raise (never lower) the requested max_age once today's usage is within
    the safety margin of the daily budget."""
    with _ggleap_usage_lock:
        used_today = _ggleap_usage.get("total", 0) if _ggleap_usage.get("date") == _ggleap_usage_today() else 0
    if used_today >= _GGLEAP_DAILY_BUDGET * _GGLEAP_SAFETY_FLOOR_PCT:
        return max(max_age, _GGLEAP_SAFETY_MAX_AGE)
    return max_age

def _ggleap_get_machines(max_age=None, force=False):
    """One shared machines/get-all, server-cached. Returns (machines, error).
    On any error (e.g. 429) the last good list is served stale so the kiosks never
    flash '0 machines' and the lock loop keeps its state."""
    global ggleap_jwt_token
    import time as _t, requests as _req
    if _ggleap_is_paused():
        return (_ggleap_machines_cache["machines"] or []), "GGLeap paused"
    if max_age is None:
        max_age = _ggleap_cache_ttl()
    max_age = _ggleap_budget_guard(max_age)
    now = _t.time()
    cached = _ggleap_machines_cache["machines"]
    # Throttle by last ATTEMPT (success or failure) so a 429 outage backs off to the
    # same cadence instead of hammering every loop tick.
    if not force and (now - _ggleap_machines_cache["fetched_at"]) < max_age:
        return (cached or []), _ggleap_machines_cache["error"]
    if not ggleap_jwt_token:
        get_ggleap_jwt()
    if not ggleap_jwt_token:
        _ggleap_machines_cache["fetched_at"] = now
        _ggleap_machines_cache["error"] = "Failed to authenticate with GGLeap API"
        return (cached or []), _ggleap_machines_cache["error"]
    hdrs = {"Accept": "application/json", "Authorization": f"Bearer {ggleap_jwt_token}"}
    try:
        _ggleap_count("get-all")
        r = _req.get(f"{GGLEAP_BASE_URL}/machines/get-all", headers=hdrs, timeout=15)
        if r.status_code == 401:
            get_ggleap_jwt()
            hdrs["Authorization"] = f"Bearer {ggleap_jwt_token}"
            _ggleap_count("get-all")
            r = _req.get(f"{GGLEAP_BASE_URL}/machines/get-all", headers=hdrs, timeout=15)
        r.raise_for_status()
        machines = (r.json() or {}).get("Machines", [])
        _ggleap_machines_cache["machines"] = machines
        _ggleap_machines_cache["fetched_at"] = now
        _ggleap_machines_cache["error"] = None
        return machines, None
    except _req.exceptions.RequestException as e:
        _ggleap_machines_cache["fetched_at"] = now  # back off retries during an outage
        _ggleap_machines_cache["error"] = str(e)
        return (cached or []), f"Failed to connect to GGLeap API: {str(e)}"

def _ggleap_patch_machine_lock(machine_uuid, lock, message=None):
    """Optimistically update the cached machine's lock fields after a successful
    set-screen-lock so the lock loop reads a consistent state without an extra fetch."""
    for m in (_ggleap_machines_cache["machines"] or []):
        if m.get("Uuid") == machine_uuid:
            m["IsLocked"] = bool(lock)
            m["LockedByAdmin"] = bool(lock)
            m["AdminLockMessage"] = message if lock else None
            break

def _fetch_ggleap_status(max_age=None):
    """Live PC status for the kiosk display, derived from the shared machines
    cache. The transform (and session tracking) only re-runs when the underlying
    get-all actually refreshed. `max_age` lets a specific caller (e.g. the staff
    PC Manager tab) ask for a tighter refresh window than the default kiosk/public
    cadence — it still flows through the ONE shared _ggleap_get_machines() cache,
    so it never adds a second independent polling loop or extra API calls beyond
    whatever the shortest currently-requested window needs."""
    machines, error = _ggleap_get_machines(max_age=max_age)

    # Reuse the last transform unless the raw data changed since we built it.
    if _ggleap_status_cache["data"] is not None and _ggleap_status_cache["raw_at"] == _ggleap_machines_cache["fetched_at"]:
        return _ggleap_status_cache["data"]

    if not machines and error:
        return {
            "error": error,
            "pcs": [], "available": 0, "in_use": 0, "offline": 0,
            "last_updated": datetime.now(timezone.utc).isoformat()
        }

    pcs = []
    available = 0
    in_use = 0
    offline = 0

    for device in machines:
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

        pcs.append({
            "uuid": device.get("Uuid"),
            "name": format_pc_name(name),
            "status": status,
            "state": state,
            "user_uuid": device.get("UserUuid"),
            "has_guest": device.get("HasGuest", False),
            "locked": bool(device.get("IsLocked")) and bool(device.get("LockedByAdmin")),
            "open_windows": [w.get("Title", "") for w in device.get("OpenedWindows", []) if w.get("Title")],
            "last_state_update": device.get("LastStateUpdate"),
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
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }
    if error:
        result["error"] = error  # serving slightly stale data
    _ggleap_status_cache["data"] = result
    _ggleap_status_cache["raw_at"] = _ggleap_machines_cache["fetched_at"]
    return result

@app.route('/api/ggleap/status')
@api_auth_required
def api_ggleap_status():
    """Get live PC status from GGLeap API (server-cached)."""
    return jsonify(_fetch_ggleap_status())


# -- Kiosk PC picker + booking (public — used by the arena kiosks) ----------

def _pc_area(name):
    """Group label for the kiosk PC picker, derived from the machine name."""
    m = re.match(r"Island\s+(\d+)", name or "", re.IGNORECASE)
    if m:
        return f"Island {m.group(1)}"
    if re.match(r"Stage", name or "", re.IGNORECASE):
        return "Stage"
    return "Other"


@app.route('/api/arena/pcs')
def api_arena_pcs_public():
    """Public: live PC availability for the kiosk attract screen + picker.
    Read-only, server-cached. Overlays kiosk-side reservation holds so a
    just-picked PC shows 'reserved' until the guest logs in or the hold lapses.
    Stage (varsity-only) stations are returned in a separate `stage` array so the
    guest picker can show them as locked, and the varsity picker can select them."""
    data = _fetch_ggleap_status()
    pcs = []
    stage = []
    available = in_use = offline = 0
    for p in data.get("pcs", []):
        name = p.get("name", "")
        uid = p.get("uuid")
        status = p.get("status")       # available | in-use | offline
        if status == "in-use":
            _pc_clear_hold(uid)        # they arrived & logged in — hold is done
        elif status == "available" and _pc_hold_active(uid):
            status = "reserved"        # held for an arriving guest
        entry = {"uuid": uid, "name": name, "status": status, "area": _pc_area(name)}
        if _is_varsity_pc(name):
            stage.append(entry)        # varsity-only — kept out of the guest counts
            continue
        if status == "available":
            available += 1
        elif status == "in-use":
            in_use += 1
        elif status == "offline":
            offline += 1
        pcs.append(entry)
    return jsonify({
        "available": available,
        "in_use": in_use,
        "offline": offline,
        "total": len(pcs),
        "pcs": pcs,
        "stage": stage,
        "error": data.get("error"),
        "last_updated": data.get("last_updated"),
    })


# Kiosk-side PC reservations: when a guest signs in for a PC we "hold" it for a
# few minutes so nobody else can pick it while they walk over. The kiosk is in
# full control — GGLeap is never told to book/lock. If they don't log in within
# the hold window the PC frees again; once they log in (GGLeap State =
# UserLoggedIn) it shows occupied for as long as they stay, then frees on logout.
KIOSK_HOLD_MINUTES = 10
_arena_pc_holds = {}   # machine_uuid -> {"name", "email", "kiosk_id", "until"}

def _pc_hold_active(machine_uuid):
    import time as _t
    h = _arena_pc_holds.get(machine_uuid)
    if not h:
        return None
    if _t.time() > h.get("until", 0):
        _arena_pc_holds.pop(machine_uuid, None)
        return None
    return h

def _pc_set_hold(machine_uuid, name, email, kiosk_id):
    import time as _t
    minutes = KIOSK_HOLD_MINUTES
    try:
        minutes = max(1, min(120, int(load_arena_config().get("pc_hold_minutes", KIOSK_HOLD_MINUTES))))
    except (ValueError, TypeError):
        pass
    _arena_pc_holds[machine_uuid] = {
        "name": name, "email": email, "kiosk_id": kiosk_id,
        "until": _t.time() + minutes * 60,
    }

def _pc_clear_hold(machine_uuid):
    _arena_pc_holds.pop(machine_uuid, None)


# Who is on / reserved each PC (for the Active Sessions tab). Unlike a hold, this
# is NOT cleared when the guest logs in — it persists through their session so the
# Sessions tab can name them. Cleared on logout/cancel or when the slot frees.
_arena_pc_occupants = {}   # machine_uuid -> {"name","email","kiosk_id","reserved_at","varsity"}

def _arena_set_occupant(machine_uuid, name, email, kiosk_id, varsity=False):
    _arena_pc_occupants[machine_uuid] = {
        "name": name, "email": email, "kiosk_id": kiosk_id,
        "reserved_at": datetime.now().isoformat(timespec="seconds"),
        "varsity": bool(varsity),
    }

def _arena_clear_occupant(machine_uuid):
    _arena_pc_occupants.pop(machine_uuid, None)


# -- GGLeap screen lock/unlock (kiosk gating) -------------------------------
KIOSK_PC_LOCK_MESSAGE = "Must be checked in on Kiosk to use system"
KIOSK_VARSITY_LOCK_MESSAGE = "Varsity Members must check in on the Kiosk"

def _is_island_pc(name):
    return bool(re.match(r"\s*island", name or "", re.IGNORECASE))

def _is_varsity_pc(name):
    """Stage machines are the varsity-only stations."""
    return bool(re.match(r"\s*stage", name or "", re.IGNORECASE))

def _is_kiosk_pc(name):
    """Machines the kiosk lock loop manages: Island (guest) + Stage (varsity)."""
    return _is_island_pc(name) or _is_varsity_pc(name)

def _pc_lock_message(name):
    """The on-screen lock message for a managed PC (varsity wording for Stage)."""
    return KIOSK_VARSITY_LOCK_MESSAGE if _is_varsity_pc(name) else KIOSK_PC_LOCK_MESSAGE

# GGLeap is rate-limited (~20 write req/min on our plan). Serialize + space out
# all screen-lock writes so a full-room lock/unlock never trips a 429.
_ggleap_write_lock = threading.Lock()
_ggleap_last_write = [0.0]
_GGLEAP_WRITE_INTERVAL = 4.5  # seconds between screen-lock writes (~13/min)

def _ggleap_throttle_write():
    """Block until at least _GGLEAP_WRITE_INTERVAL has passed since the last write."""
    with _ggleap_write_lock:
        wait = _GGLEAP_WRITE_INTERVAL - (time.time() - _ggleap_last_write[0])
        if wait > 0:
            time.sleep(wait)
        _ggleap_last_write[0] = time.time()

def _ggleap_set_screen_lock(machine_uuid, lock, message=None):
    """Lock/unlock a single PC's screen via GGLeap. Returns (ok, error).
    Locking blanks the screen with an optional message; unlocking clears it."""
    global ggleap_jwt_token
    import requests as _req
    if not machine_uuid:
        return False, "no machine"
    if _ggleap_is_paused():
        return False, "GGLeap paused"
    if not ggleap_jwt_token:
        get_ggleap_jwt()
    if not ggleap_jwt_token:
        return False, "GGLeap auth failed"
    body = {"LockScreen": bool(lock), "Message": message, "MachineUuid": machine_uuid}
    hdrs = {"Accept": "application/json", "Content-Type": "application/json",
            "Authorization": f"Bearer {ggleap_jwt_token}"}
    _ggleap_throttle_write()
    try:
        _ggleap_count("set-lock")
        r = _req.post(f"{GGLEAP_BASE_URL}/machines/set-screen-lock", headers=hdrs, json=body, timeout=20)
        if r.status_code == 401:
            get_ggleap_jwt()
            hdrs["Authorization"] = f"Bearer {ggleap_jwt_token}"
            _ggleap_throttle_write()
            _ggleap_count("set-lock")
            r = _req.post(f"{GGLEAP_BASE_URL}/machines/set-screen-lock", headers=hdrs, json=body, timeout=20)
        if r.status_code == 204 or r.ok:
            _ggleap_patch_machine_lock(machine_uuid, lock, message)
            return True, None
        return False, f"GGLeap {r.status_code}: {(r.text or '')[:150]}"
    except _req.exceptions.RequestException as e:
        return False, str(e)

# Cancel Session force-restarts the PC via GGLeap's execute-action endpoint —
# a restart ends the session and logs the student out.
GGLEAP_EXECUTE_ACTION_PATH = "/machines/execute-action"

def _ggleap_reboot_machine(machine_uuid):
    """Restart a single PC via GGLeap (ends the session / logs the user out). Returns (ok, error)."""
    global ggleap_jwt_token
    import requests as _req
    if not machine_uuid:
        return False, "no machine"
    if _ggleap_is_paused():
        return False, "GGLeap paused"
    if not ggleap_jwt_token:
        get_ggleap_jwt()
    if not ggleap_jwt_token:
        return False, "GGLeap auth failed"
    body = {"Action": "Restart", "Reason": "SessionEnded", "MachineUuid": machine_uuid, "EndOfSession": True}
    hdrs = {"Accept": "application/json", "Content-Type": "application/json",
            "Authorization": f"Bearer {ggleap_jwt_token}"}
    _ggleap_throttle_write()
    try:
        _ggleap_count("reboot")
        r = _req.post(f"{GGLEAP_BASE_URL}{GGLEAP_EXECUTE_ACTION_PATH}", headers=hdrs, json=body, timeout=20)
        if r.status_code == 401:
            get_ggleap_jwt()
            hdrs["Authorization"] = f"Bearer {ggleap_jwt_token}"
            _ggleap_throttle_write()
            _ggleap_count("reboot")
            r = _req.post(f"{GGLEAP_BASE_URL}{GGLEAP_EXECUTE_ACTION_PATH}", headers=hdrs, json=body, timeout=20)
        if r.status_code == 204 or r.ok:
            return True, None
        return False, f"GGLeap {r.status_code}: {(r.text or '')[:150]}"
    except _req.exceptions.RequestException as e:
        return False, str(e)

def _ggleap_shutdown_machine(machine_uuid):
    """Power off a single PC via GGLeap. Returns (ok, error). Used for stations
    stuck in Admin Mode, where the only sane remote actions are restart/shutdown."""
    global ggleap_jwt_token
    import requests as _req
    if not machine_uuid:
        return False, "no machine"
    if _ggleap_is_paused():
        return False, "GGLeap paused"
    if not ggleap_jwt_token:
        get_ggleap_jwt()
    if not ggleap_jwt_token:
        return False, "GGLeap auth failed"
    body = {"Action": "Shutdown", "Reason": "AdminRequested", "MachineUuid": machine_uuid, "EndOfSession": True}
    hdrs = {"Accept": "application/json", "Content-Type": "application/json",
            "Authorization": f"Bearer {ggleap_jwt_token}"}
    _ggleap_throttle_write()
    try:
        _ggleap_count("shutdown")
        r = _req.post(f"{GGLEAP_BASE_URL}{GGLEAP_EXECUTE_ACTION_PATH}", headers=hdrs, json=body, timeout=20)
        if r.status_code == 401:
            get_ggleap_jwt()
            hdrs["Authorization"] = f"Bearer {ggleap_jwt_token}"
            _ggleap_throttle_write()
            _ggleap_count("shutdown")
            r = _req.post(f"{GGLEAP_BASE_URL}{GGLEAP_EXECUTE_ACTION_PATH}", headers=hdrs, json=body, timeout=20)
        if r.status_code == 204 or r.ok:
            return True, None
        return False, f"GGLeap {r.status_code}: {(r.text or '')[:150]}"
    except _req.exceptions.RequestException as e:
        return False, str(e)

# PC-lock reconcile state (per process). While the feature is on, an idle Island
# PC that is unlocked gets locked with the check-in message. We remember which PCs
# WE locked; if such a PC later shows up unlocked without having rebooted, a human
# (a worker via GGLeap, or the kiosk check-in) unlocked it — so we leave it alone
# until it reboots. A reboot (a down/boot state) resets that memory so the PC
# re-locks the moment it powers back on.
_pc_prev_state = {}        # machine_uuid -> last observed GGLeap State
_pc_we_locked = set()      # uuids we locked this power session
_pc_human_unlocked = set() # uuids a worker unlocked — don't re-lock until reboot
_pc_kiosk_unlocked = set() # uuids the kiosk check-in unlocked — re-lock if held slot lapses with no login (no-show)
_pc_session_ended = {}     # uuid -> ts: session cancelled/restarting — hide from Active Sessions until it reboots
_PC_SESSION_ENDED_TTL = 300  # safety: stop hiding after 5 min even if GGLeap still reports in-use
_ARENA_SESSION_STATES = {"UserLoggedIn", "UserLoggingIn"}  # states that mean a real student is actually on the PC
_arena_system_events = []  # ephemeral live-feed events (e.g. admin unlocks) — shown in Live Feed only, never persisted

def _arena_push_system_event(rec):
    """Record a transient Live-Feed event (not a real sign-in). Kept in memory,
    capped, and auto-dropped when it ages out of the current day."""
    _arena_system_events.append(rec)
    today = datetime.now().strftime("%Y-%m-%d")
    _arena_system_events[:] = [e for e in _arena_system_events
                               if (e.get("signed_in_at", "")[:10] == today)][-60:]

_PC_DOWN_STATES = {"Off", "StartingUp", "Restarting", "ShuttingDown"}

def _reconcile_pc_locks():
    """Keep idle Island PCs locked behind the kiosk gate while the feature is on:
    lock any unlocked idle PC, but never re-lock one a worker or the kiosk
    deliberately unlocked (until it reboots). When the feature is off, clear our
    admin locks so PCs work normally."""
    cfg = load_arena_config()
    enabled = bool(cfg.get("pc_lock_enabled", False))
    devices, error = _ggleap_get_machines()
    if error and not devices:
        return  # transient (e.g. 429) and no cached data yet — try again next cycle
    for d in devices:
        if d.get("GgRockVm"):
            continue
        name = d.get("Name", "")
        uuid = d.get("Uuid")
        if not uuid or not _is_kiosk_pc(name):
            continue
        state = d.get("State")
        is_locked = bool(d.get("IsLocked"))
        by_admin = bool(d.get("LockedByAdmin"))
        _pc_prev_state[uuid] = state

        if not enabled:
            # Feature off — undo any lock we placed so PCs work normally.
            _pc_we_locked.discard(uuid)
            _pc_human_unlocked.discard(uuid)
            _pc_kiosk_unlocked.discard(uuid)
            if is_locked and by_admin:
                ok, err = _ggleap_set_screen_lock(uuid, False)
                if not ok:
                    logger.warning(f"[PCLOCK] unlock(disable) {name} failed: {err}")
            continue

        if state in _PC_DOWN_STATES:
            # Rebooting/off — forget this power session so it re-locks on next boot.
            # Also release any kiosk hold: a student who reserved this machine and
            # then it restarted must be free to pick the same or another station
            # right away (don't make them wait out the 10-minute hold).
            _pc_we_locked.discard(uuid)
            _pc_human_unlocked.discard(uuid)
            _pc_kiosk_unlocked.discard(uuid)
            _pc_clear_hold(uuid)
            continue

        if state != "ReadyForUser":
            continue  # in a session / transitioning — leave it

        # --- idle & available (ReadyForUser) ---
        if uuid in _pc_human_unlocked:
            continue  # a worker unlocked it — respect that until it reboots

        if uuid in _pc_kiosk_unlocked:
            # Unlocked for a kiosk check-in. Keep it open while the hold is live;
            # once the slot lapses and it's still sitting idle & unlocked, the guest
            # never logged in (no-show) — re-lock it behind the kiosk gate.
            if _pc_hold_active(uuid):
                continue
            if not is_locked:
                ok, err = _ggleap_set_screen_lock(uuid, True, _pc_lock_message(name))
                if ok:
                    _pc_kiosk_unlocked.discard(uuid)
                    _pc_we_locked.add(uuid)
                else:
                    logger.warning(f"[PCLOCK] no-show re-lock {name} failed: {err}")
            else:
                _pc_kiosk_unlocked.discard(uuid)
                _pc_we_locked.add(uuid)
            continue

        if is_locked:
            _pc_we_locked.add(uuid)  # locked already — remember it's ours to manage
            continue

        if uuid in _pc_we_locked:
            # We locked it earlier but it's unlocked now with no reboot seen — a
            # worker unlocked it. Respect that and stop re-locking until it reboots.
            _pc_we_locked.discard(uuid)
            _pc_human_unlocked.add(uuid)
            continue

        # Idle, unlocked, and not unlocked by a human — lock it behind the kiosk gate.
        ok, err = _ggleap_set_screen_lock(uuid, True, _pc_lock_message(name))
        if ok:
            _pc_we_locked.add(uuid)
        else:
            logger.warning(f"[PCLOCK] lock {name} failed: {err}")  # retried next cycle

_pc_lock_thread_started = False

def _start_pc_lock_thread():
    """Start the background PC-lock reconcile loop once per process."""
    global _pc_lock_thread_started
    if _pc_lock_thread_started:
        return
    _pc_lock_thread_started = True

    def _worker():
        import time as _t
        _t.sleep(6)  # let the app settle before the first pass
        while True:
            try:
                _reconcile_pc_locks()
            except Exception as e:
                logger.warning(f"[PCLOCK] loop error: {e}")
            _t.sleep(7)

    threading.Thread(target=_worker, daemon=True).start()


@app.route('/api/arena/kiosk/book', methods=['POST'])
def api_arena_kiosk_book():
    """Public: a guest picked a PC and signed in. Hold that PC at the kiosk for
    KIOSK_HOLD_MINUTES so nobody else grabs it while they walk over, and record
    the arena check-in. Play time is unlimited — the PC frees when they log out."""
    cfg = load_arena_config()
    data = request.get_json(silent=True) or {}
    kid = _clean_str(data.get("kioskId") or data.get("kiosk_id") or "kiosk-1", 40)
    kcfg = _arena_kiosk_cfg(cfg, kid)
    machine_uuid = _clean_str(data.get("machineUuid") or data.get("machine_uuid"), 60)

    first = _clean_str(data.get("firstName") or data.get("first_name"), 60)
    last = _clean_str(data.get("lastName") or data.get("last_name"), 60)
    name = _clean_str(data.get("name"), 120) or (first + " " + last).strip()
    email = _clean_str(data.get("email"), 120).lower()

    if not machine_uuid:
        return jsonify({"success": False, "error": "Please select a PC first."}), 400
    if not name:
        return jsonify({"success": False, "error": "Please enter your full name."}), 400
    if cfg.get("require_email", True):
        domains = [d.lower().lstrip("@") for d in (cfg.get("email_domains") or [])]
        if not email or (domains and not any(email.endswith("@" + d) for d in domains)):
            allowed = " or ".join("@" + d for d in domains) if domains else "a valid email"
            return jsonify({"success": False, "error": f"Please use {allowed}."}), 400

    guard_ok, guard_msg = _signin_guard(cfg, email, name, kid, is_pc=True)
    if not guard_ok:
        return jsonify({"success": False, "error": guard_msg, "blocked": True}), 403

    # Confirm the machine is still free and not already held by someone else.
    status = _fetch_ggleap_status()
    machine = next((p for p in status.get("pcs", []) if p.get("uuid") == machine_uuid), None)
    if not machine:
        return jsonify({"success": False, "error": "That PC is no longer listed. Please pick another."}), 404
    if machine.get("status") != "available":
        return jsonify({"success": False, "error": "That PC was just taken. Please pick another."}), 409
    if _pc_hold_active(machine_uuid):
        return jsonify({"success": False, "error": "That PC was just reserved. Please pick another."}), 409

    machine_name = machine.get("name", "your PC")
    prior = arena_db.find_recent_guest(email) if email else None
    returning = bool(prior)
    # Kiosk-only reservation — no GGLeap booking/lock. Just hold it locally so
    # nobody else can pick it while the guest walks over; the hold auto-expires.
    _pc_set_hold(machine_uuid, name, email, kid)
    _arena_set_occupant(machine_uuid, name, email, kid)
    # Unlock the screen so the guest can log in. The lock loop won't re-lock it
    # (it only locks on power-on), so this unlock persists for their session.
    if load_arena_config().get("pc_lock_enabled", False):
        # Track as a kiosk unlock: the loop keeps it open while the hold is live,
        # then re-locks it if the guest never logs in (no-show).
        _pc_we_locked.discard(machine_uuid)
        _pc_human_unlocked.discard(machine_uuid)
        _pc_kiosk_unlocked.add(machine_uuid)
        ok, err = _ggleap_set_screen_lock(machine_uuid, False)
        if not ok:
            logger.warning(f"[PCLOCK] checkin unlock {machine_name} failed: {err}")
    record = {
        "id": uuid.uuid4().hex,
        "name": name,
        "first_name": first,
        "last_name": last,
        "email": email,
        "kiosk_id": kid,
        "kiosk_label": kcfg.get("label"),
        "room": _clean_str(data.get("room"), 60) or kcfg.get("room", ""),
        "accepted_rules": True,
        "reason": f"PC Session — {machine_name}",
        "pc_session": True,
        "machine": machine_name,
        "machine_uuid": machine_uuid,
        "signed_in_at": datetime.now().isoformat(timespec="seconds"),
    }
    arena_db.add_signin(record)
    log_activity("arena_pc_reserve", "arena",
                 f"{name} reserved {machine_name} via {kcfg.get('label') or kid}")
    record["returning"] = returning
    return jsonify({
        "success": True,
        "record": record,
        "returning": returning,
        "machine_name": machine_name,
        "hold_minutes": max(1, min(120, int(load_arena_config().get("pc_hold_minutes", KIOSK_HOLD_MINUTES)))),
    })


def _arena_active_sessions():
    """Build the Active Sessions list for Nova: every kiosk-managed PC that is
    currently reserved (held, walking over) or in use (logged in), with who's on
    it and how long. Combines GGLeap live state, kiosk holds, and occupant info."""
    import time as _t
    status = _fetch_ggleap_status()
    usage = _load_arena_usage()
    active_sessions = usage.get("active_sessions", {}) or {}
    try:
        hold_minutes = max(1, min(120, int(load_arena_config().get("pc_hold_minutes", KIOSK_HOLD_MINUTES))))
    except (ValueError, TypeError):
        hold_minutes = KIOSK_HOLD_MINUTES
    out = []
    for p in status.get("pcs", []):
        uid = p.get("uuid")
        name = p.get("name", "")
        st = p.get("status")          # available | in-use | offline
        state = p.get("state", "")    # raw GGLeap state
        hold = _pc_hold_active(uid)
        occ = _arena_pc_occupants.get(uid)

        # A machine only counts as an ACTIVE session when a real user is on it.
        # States like AdminMode / Restarting / StartingUp / ShuttingDown report as
        # "in-use" for booking purposes but are NOT student sessions.
        is_session = state in _ARENA_SESSION_STATES

        # Session was just cancelled/restarted — hide it until the machine actually
        # reboots and frees up (GGLeap can still report the user for a moment).
        ended_at = _pc_session_ended.get(uid)
        if ended_at is not None:
            if not is_session or (_t.time() - ended_at) > _PC_SESSION_ENDED_TTL:
                _pc_session_ended.pop(uid, None)  # reboot done (or timed out) — stop hiding
            else:
                if occ:
                    _arena_clear_occupant(uid)
                continue

        if is_session:
            sess_status = "active"    # a real user is logged in and playing
        elif hold:
            sess_status = "reserved"  # held for an arriving guest
        else:
            if occ:                   # freed up — drop stale occupant record
                _arena_clear_occupant(uid)
            continue

        who_name = who_email = ""
        varsity = False
        if hold:
            who_name = hold.get("name", "") or who_name
            who_email = hold.get("email", "") or who_email
        if occ:
            who_name = who_name or occ.get("name", "")
            who_email = who_email or occ.get("email", "")
            varsity = bool(occ.get("varsity"))

        started_at = None
        if sess_status == "active":
            sess = active_sessions.get(name)
            if sess and sess.get("start_time"):
                started_at = sess["start_time"]
            elif occ and occ.get("reserved_at"):
                started_at = occ["reserved_at"]
        else:  # reserved
            until = hold.get("until", _t.time()) if hold else _t.time()
            started_at = datetime.fromtimestamp(until - hold_minutes * 60).isoformat(timespec="seconds")

        hold_until = None
        if hold:
            hold_until = datetime.fromtimestamp(hold.get("until", _t.time())).isoformat(timespec="seconds")

        out.append({
            "uuid": uid,
            "machine": name,
            "status": sess_status,          # active | reserved
            "name": who_name,
            "email": who_email,
            "varsity": varsity,
            "started_at": started_at,
            "hold_until": hold_until,
        })

    def _skey(s):
        m = re.match(r"Island (\d+) S(\d+)", s["machine"], re.IGNORECASE)
        if m:
            return (0, int(m.group(1)), int(m.group(2)))
        m = re.match(r"Stage S(\d+)", s["machine"], re.IGNORECASE)
        if m:
            return (1, 0, int(m.group(1)))
        return (2, 999, 999)
    out.sort(key=_skey)
    return out


@app.route('/api/arena/sessions')
@api_perm_required('page.arena_sessions')
def api_arena_sessions():
    """Active PC sessions + full room map for the Nova PC Manager tab.
    Uses `_pc_manager_max_age()` — a flat 15s regardless of arena open/closed
    status. It still shares the ONE global GGLeap cache, so this can only
    *shorten* the effective refresh cadence while someone's actively viewing
    this tab; it never spins up a separate polling loop. Worst case (this tab
    left open and visible 24/7) stays under 58% of the daily budget by design —
    the circuit breaker (`_ggleap_budget_guard`) is only an extra backstop for
    the unexpected, not something normal use relies on.

    ?force=1 (the manual Refresh button only) bypasses the window entirely for
    that one request — a human can't click faster than the browser-side cooldown
    lets them, so this stays budget-safe while giving staff a true "check right
    now" after physically restarting a machine, instead of waiting out the window."""
    forced = request.args.get('force') in ('1', 'true', 'yes')
    sessions = _arena_active_sessions()
    sess_by_uid = {s["uuid"]: s for s in sessions}
    status = _fetch_ggleap_status(max_age=0 if forced else _pc_manager_max_age())
    machines = []
    for p in status.get("pcs", []):
        uid = p.get("uuid")
        name = p.get("name", "")
        s = sess_by_uid.get(uid)
        m = re.match(r"^(Island\s+\d+|Stage)\s+S(\d+)", name, re.IGNORECASE)
        area = m.group(1).title() if m else "Other"
        seat = m.group(2) if m else name
        if s:
            seat_status = s["status"]              # active | reserved
        elif p.get("status") == "available":
            seat_status = "available"
        elif p.get("status") == "offline":
            seat_status = "offline"
        else:
            seat_status = "maint"                  # in-use but no real session (AdminMode, restarting…)
        _is_unlocked = (uid in _pc_kiosk_unlocked or uid in _pc_human_unlocked)
        entry = {
            "uuid": uid,
            "machine": name,
            "area": area,
            "seat": seat,
            "seat_status": seat_status,
            "locked": (not _is_unlocked) and (bool(p.get("locked")) or uid in _pc_we_locked),
            "unlocked": _is_unlocked,
            "unlocked_by": ("kiosk" if uid in _pc_kiosk_unlocked else ("staff" if uid in _pc_human_unlocked else None)),
            "varsity": bool(s["varsity"]) if s else bool(re.match(r"Stage", name, re.IGNORECASE)),
            "state": p.get("state"),
            "admin_mode": p.get("state") == "AdminMode",
            "last_state_update": p.get("last_state_update"),
            "has_guest": bool(p.get("has_guest")),
        }
        if s:
            entry.update({
                "name": s.get("name", ""),
                "email": s.get("email", ""),
                "started_at": s.get("started_at"),
                "hold_until": s.get("hold_until"),
            })
        machines.append(entry)
    return jsonify({
        "success": True,
        "sessions": sessions,
        "machines": machines,
        "active": sum(1 for s in sessions if s["status"] == "active"),
        "reserved": sum(1 for s in sessions if s["status"] == "reserved"),
        "available": sum(1 for m in machines if m["seat_status"] == "available"),
        "offline": sum(1 for m in machines if m["seat_status"] == "offline"),
    })


@app.route('/api/arena/sessions/<uid>/cancel', methods=['POST'])
@api_perm_required('arena.manage')
def api_arena_session_cancel(uid):
    """Cancel a PC session. If the student is logged in ? force-restart the machine.
    If it's only reserved/unlocked (not logged in yet) ? re-lock it. Either way the
    station frees up so another machine can be selected."""
    status = _fetch_ggleap_status()
    machine = next((p for p in status.get("pcs", []) if p.get("uuid") == uid), None)
    if not machine:
        return jsonify({"success": False, "error": "That station is no longer listed."}), 404
    name = machine.get("name", "the station")
    st = machine.get("status")

    if st == "in-use":
        # Logged in — force a restart to end their session.
        ok, err = _ggleap_reboot_machine(uid)
        action = "restarted" if ok else "restart_failed"
        if not ok:
            # Best-effort fallback so the station is at least gated again.
            _ggleap_set_screen_lock(uid, True, _pc_lock_message(name))
        if ok:
            # Drop it from Active Sessions right away — it's rebooting, not active.
            _pc_session_ended[uid] = time.time()
    else:
        # Unlocked/reserved but nobody logged in — just re-lock it.
        ok, err = _ggleap_set_screen_lock(uid, True, _pc_lock_message(name))
        action = "locked" if ok else "lock_failed"
        if ok:
            _pc_we_locked.add(uid)

    _pc_clear_hold(uid)
    _pc_kiosk_unlocked.discard(uid)
    _pc_human_unlocked.discard(uid)
    _arena_clear_occupant(uid)
    log_activity("arena_session_cancel", "arena",
                 f"{_arena_staff_name()} cancelled session on {name} ({action})")
    if not ok:
        detail = " GGLeap could not restart the machine." if action == "restart_failed" else " GGLeap could not lock the machine."
        return jsonify({"success": False, "error": (err or "GGLeap error") + detail, "action": action}), 502
    return jsonify({"success": True, "action": action, "machine": name})


@app.route('/api/arena/sessions/<uid>/power', methods=['POST'])
@api_perm_required('arena.manage')
def api_arena_session_power(uid):
    """Restart or shut down a station stuck in Admin Mode — the only remote
    actions available there since there's no student session to manage."""
    data = request.get_json(silent=True) or {}
    action = data.get("action")
    if action not in ("restart", "shutdown"):
        return jsonify({"success": False, "error": "Invalid action"}), 400
    status = _fetch_ggleap_status()
    machine = next((p for p in status.get("pcs", []) if p.get("uuid") == uid), None)
    if not machine:
        return jsonify({"success": False, "error": "That station is no longer listed."}), 404
    name = machine.get("name", "the station")
    ok, err = _ggleap_reboot_machine(uid) if action == "restart" else _ggleap_shutdown_machine(uid)
    if ok:
        _pc_session_ended[uid] = time.time()
        _pc_clear_hold(uid)
        _pc_we_locked.discard(uid)
        _pc_kiosk_unlocked.discard(uid)
        _pc_human_unlocked.discard(uid)
    log_activity("arena_session_power", "arena", f"{_arena_staff_name()} {action}ed {name} (Admin Mode)")
    if not ok:
        return jsonify({"success": False, "error": (err or "GGLeap error") + f" Could not {action} the machine."}), 502
    return jsonify({"success": True, "action": action, "machine": name})


@app.route('/api/arena/sessions/<uid>/unlock', methods=['POST'])
@api_perm_required('arena.manage')
def api_arena_session_unlock(uid):
    """Remotely unlock a single station from the Sessions map (no check-in)."""
    status = _fetch_ggleap_status()
    machine = next((p for p in status.get("pcs", []) if p.get("uuid") == uid), None)
    if not machine:
        return jsonify({"success": False, "error": "That station is no longer listed."}), 404
    name = machine.get("name", "the station")
    _pc_we_locked.discard(uid)
    _pc_human_unlocked.add(uid)   # a staff member unlocked — don't auto re-lock until it reboots
    _pc_kiosk_unlocked.add(uid)
    _pc_session_ended.pop(uid, None)
    ok, err = _ggleap_set_screen_lock(uid, False)
    if not ok:
        return jsonify({"success": False, "error": (err or "GGLeap error") + " Could not unlock the machine."}), 502
    log_activity("arena_session_unlock", "arena", f"{_arena_staff_name()} unlocked {name}")
    return jsonify({"success": True, "machine": name})


@app.route('/api/arena/sessions/<uid>/lock', methods=['POST'])
@api_perm_required('arena.manage')
def api_arena_session_lock(uid):
    """Re-lock a single station from the Sessions map (e.g. after an admin unlock)."""
    status = _fetch_ggleap_status()
    machine = next((p for p in status.get("pcs", []) if p.get("uuid") == uid), None)
    if not machine:
        return jsonify({"success": False, "error": "That station is no longer listed."}), 404
    name = machine.get("name", "the station")
    _pc_kiosk_unlocked.discard(uid)
    _pc_human_unlocked.discard(uid)
    _pc_clear_hold(uid)
    _arena_clear_occupant(uid)
    ok, err = _ggleap_set_screen_lock(uid, True, _pc_lock_message(name))
    if not ok:
        return jsonify({"success": False, "error": (err or "GGLeap error") + " Could not lock the machine."}), 502
    _pc_we_locked.add(uid)
    log_activity("arena_session_lock", "arena", f"{_arena_staff_name()} locked {name}")
    return jsonify({"success": True, "machine": name})


@app.route('/api/arena/sessions/<uid>/checkin', methods=['POST'])
@api_perm_required('arena.manage')
def api_arena_session_checkin(uid):
    """Staff check-in on a specific station from the Sessions map. Bypasses the
    varsity roster check (trusted staff action), unlocks the machine, records a
    sign-in (appears in the live feed), and marks the station occupied."""
    cfg = load_arena_config()
    data = request.get_json(silent=True) or {}
    status = _fetch_ggleap_status()
    machine = next((p for p in status.get("pcs", []) if p.get("uuid") == uid), None)
    if not machine:
        return jsonify({"success": False, "error": "That station is no longer listed."}), 404
    name_m = machine.get("name", "the station")

    first = _clean_str(data.get("firstName") or data.get("first_name"), 60)
    last = _clean_str(data.get("lastName") or data.get("last_name"), 60)
    name = _clean_str(data.get("name"), 120) or (first + " " + last).strip()
    if not name:
        return jsonify({"success": False, "error": "Please enter the student's full name."}), 400
    email = _clean_str(data.get("email"), 120).lower()

    # Attribute to the PC kiosk if there is one, else the first kiosk.
    kid = next((k for k, kc in cfg.get("kiosks", {}).items() if kc.get("type") == "pc"), None) \
        or next(iter(cfg.get("kiosks", {})), "kiosk-1")
    kcfg = _arena_kiosk_cfg(cfg, kid)
    staff_name = _arena_staff_name()

    # Unlock + reserve the station for this person.
    _pc_set_hold(uid, name, email, kid)
    _arena_set_occupant(uid, name, email, kid, varsity=False)
    _pc_we_locked.discard(uid)
    _pc_human_unlocked.discard(uid)
    _pc_kiosk_unlocked.add(uid)
    _pc_session_ended.pop(uid, None)
    ok, uerr = _ggleap_set_screen_lock(uid, False)
    if not ok:
        logger.warning(f"[SESSION CHECKIN] unlock {name_m} failed: {uerr}")

    prior = arena_db.find_recent_guest(email) if email else None
    returning = bool(prior)
    record = {
        "id": uuid.uuid4().hex, "name": name,
        "first_name": first, "last_name": last, "email": email,
        "kiosk_id": kid, "kiosk_label": kcfg.get("label"),
        "room": name_m,
        "accepted_rules": True, "manual": True, "kind": "staff",
        "reason": "Staff Check-In — " + name_m,
        "machine": name_m, "machine_uuid": uid,
        "checked_in_by": staff_name,
        "signed_in_at": datetime.now().isoformat(timespec="seconds"),
    }
    arena_db.add_signin(record)
    log_activity("arena_session_checkin", "arena", f"{staff_name} checked in {name} on {name_m}")
    record["returning"] = returning
    return jsonify({"success": True, "record": record, "returning": returning,
                    "machine_name": name_m, "unlocked": ok})


# -- Varsity after-hours check-in ------------------------------------------
_VARSITY_DM = (
    "?? **Your Machine is Ready — {machine}**\n\n"
    "Your after-hours Arena session is now **active under privilege of policy**.\n\n"
    "After-hours play is a privilege reserved for approved varsity members. Any misuse "
    "of after-hours access may result in this privilege being revoked by any means "
    "necessary. Please use after-hours play respectfully and represent PNW Esports with integrity.\n\n"
    "— PNW Esports Arena"
)


def _arena_norm_name(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _arena_find_varsity(first, last, email):
    """Match a kiosk varsity login against the roster. Returns (player, error_code).
    A player qualifies if their Purdue email matches, they're a varsity-type player,
    active, and the first/last name they entered appears in their roster full name."""
    email = (email or "").strip().lower()
    first = _arena_norm_name(first)
    last = _arena_norm_name(last)
    if not email:
        return None, "email_required"
    try:
        players = load_rosters().get("players", [])
    except Exception:
        players = []
    match = None
    for p in players:
        pe = (p.get("purdue_email") or "").strip().lower()
        if pe and pe == email:
            match = p
            break
    if not match:
        return None, "not_found"
    ptype = (match.get("player_type") or "").lower()
    if "varsity" not in ptype:
        return None, "not_varsity"
    if (match.get("status") or "active").lower() != "active":
        return None, "inactive"
    tokens = set(_arena_norm_name(match.get("full_name")).split())
    if (first and first not in tokens) or (last and last not in tokens):
        return None, "name_mismatch"
    return match, None


def _arena_varsity_by_email(email):
    """Return the active varsity roster player for an email, or None."""
    email = (email or "").strip().lower()
    if not email:
        return None
    try:
        players = load_rosters().get("players", [])
    except Exception:
        players = []
    for p in players:
        pe = (p.get("purdue_email") or "").strip().lower()
        if pe and pe == email and "varsity" in (p.get("player_type") or "").lower() \
                and (p.get("status") or "active").lower() == "active":
            return p
    return None


@app.route('/api/arena/puid-scan', methods=['POST'])
@api_auth_required
def api_arena_puid_scan():
    """Demo kiosk: identify a scanned PUID. The PUID is never echoed back."""
    cfg = load_arena_config()
    data = request.get_json(silent=True) or {}
    kid = _clean_str(data.get("kioskId") or data.get("kiosk_id") or "kiosk-demo", 40)
    raw = data.get("puid", "")
    if not puid_db.is_valid_puid(raw):
        return jsonify({"success": False, "error": "That card didn't scan correctly — please try again."}), 400
    kcfg = _arena_kiosk_cfg(cfg, kid)
    arena_open = _arena_is_open_now(cfg, kcfg)
    profile = puid_db.lookup(raw)
    known = bool(profile)
    varsity = bool(_arena_varsity_by_email(profile.get("email"))) if known else False

    if arena_open:
        if known:
            puid_db.touch(raw)
            return jsonify({"success": True, "known": True, "arena_open": True, "allowed": True,
                            "reason": "ok", "varsity": varsity, "name": profile.get("name"),
                            "first_name": profile.get("first_name"), "email": profile.get("email")})
        return jsonify({"success": True, "known": False, "arena_open": True, "allowed": True,
                        "reason": "register", "varsity": False})

    # Arena is closed — only approved varsity members get in.
    if known and varsity:
        puid_db.touch(raw)
        return jsonify({"success": True, "known": True, "arena_open": False, "allowed": True,
                        "reason": "varsity_after_hours", "varsity": True, "name": profile.get("name"),
                        "first_name": profile.get("first_name"), "email": profile.get("email")})
    return jsonify({"success": True, "known": known, "arena_open": False, "allowed": False,
                    "reason": "closed_students", "varsity": False,
                    "name": profile.get("name") if known else "",
                    "first_name": profile.get("first_name") if known else ""})


@app.route('/api/arena/puid-register', methods=['POST'])
@api_auth_required
def api_arena_puid_register():
    """Demo kiosk: first-time student registration, linked to a PUID (encrypted)."""
    cfg = load_arena_config()
    data = request.get_json(silent=True) or {}
    raw = data.get("puid", "")
    if not puid_db.is_valid_puid(raw):
        return jsonify({"success": False, "error": "That card didn't scan correctly — please try again."}), 400
    first = _clean_str(data.get("firstName") or data.get("first_name"), 60)
    last = _clean_str(data.get("lastName") or data.get("last_name"), 60)
    name = _clean_str(data.get("name"), 120) or (first + " " + last).strip()
    if not first or not last:
        return jsonify({"success": False, "error": "Please enter your first and last name."}), 400
    email = _clean_str(data.get("email"), 120).lower()
    if cfg.get("require_email", True):
        domains = [d.lower().lstrip("@") for d in (cfg.get("email_domains") or [])]
        if not email or (domains and not any(email.endswith("@" + d) for d in domains)):
            allowed = " or ".join("@" + d for d in domains) if domains else "a valid email"
            return jsonify({"success": False, "error": f"Please use {allowed}."}), 400
    puid_db.register(raw, first_name=first, last_name=last, name=name, email=email)
    varsity = bool(_arena_varsity_by_email(email))
    return jsonify({"success": True, "name": name, "first_name": first, "email": email, "varsity": varsity})


@app.route('/api/arena/varsity-checkin', methods=['POST'])
def api_arena_varsity_checkin():
    """Public: an approved varsity member checks in for after-hours play. Works
    regardless of open hours. On a PC kiosk they also pick a station to unlock."""
    cfg = load_arena_config()
    if not cfg.get("varsity_checkin", False):
        return jsonify({"success": False, "error": "Varsity Check-In is not available right now."}), 403
    data = request.get_json(silent=True) or {}
    kid = _clean_str(data.get("kioskId") or data.get("kiosk_id") or "kiosk-1", 40)
    kcfg = _arena_kiosk_cfg(cfg, kid)
    first = _clean_str(data.get("firstName") or data.get("first_name"), 60)
    last = _clean_str(data.get("lastName") or data.get("last_name"), 60)
    email = _clean_str(data.get("email"), 120).lower()
    machine_uuid = _clean_str(data.get("machineUuid") or data.get("machine_uuid"), 60)

    if not first or not last:
        return jsonify({"success": False, "error": "Please enter your first and last name."}), 400
    if not email:
        return jsonify({"success": False, "error": "Please enter your Purdue email."}), 400

    player, err = _arena_find_varsity(first, last, email)
    if not player:
        msg = ("We couldn't match your details to an approved varsity roster entry. "
               "Double-check your first name, last name, and Purdue email exactly as they "
               "appear on your roster — if it still doesn't work, contact your coach to fix your roster info.")
        return jsonify({"success": False, "error": msg, "mismatch": True, "reason": err}), 403

    name = player.get("full_name") or (first + " " + last).strip()

    # Validate-only: PC kiosk checks the roster match before showing the station
    # picker. No sign-in is recorded and no DM is sent until the final check-in.
    if data.get("validate"):
        return jsonify({"success": True, "validated": True, "name": name, "first_name": first})

    machine_name = None
    if machine_uuid:
        status = _fetch_ggleap_status()
        machine = next((p for p in status.get("pcs", []) if p.get("uuid") == machine_uuid), None)
        if not machine:
            return jsonify({"success": False, "error": "That station is no longer listed. Please pick another."}), 404
        if machine.get("status") != "available" or _pc_hold_active(machine_uuid):
            return jsonify({"success": False, "error": "That station was just taken. Please pick another."}), 409
        machine_name = machine.get("name", "your station")
        _pc_set_hold(machine_uuid, name, email, kid)
        _arena_set_occupant(machine_uuid, name, email, kid, varsity=True)
        _pc_we_locked.discard(machine_uuid)
        _pc_human_unlocked.discard(machine_uuid)
        _pc_kiosk_unlocked.add(machine_uuid)
        ok, uerr = _ggleap_set_screen_lock(machine_uuid, False)
        if not ok:
            logger.warning(f"[VARSITY] unlock {machine_name} failed: {uerr}")

    prior = arena_db.find_recent_guest(email)
    returning = bool(prior)
    record = {
        "id": uuid.uuid4().hex, "name": name,
        "first_name": first, "last_name": last, "email": email,
        "kiosk_id": kid, "kiosk_label": kcfg.get("label"),
        "room": machine_name or kcfg.get("room", ""),
        "accepted_rules": True, "kind": "varsity",
        "reason": ("Varsity After-Hours — " + machine_name) if machine_name else "Varsity After-Hours",
        "machine": machine_name, "machine_uuid": machine_uuid or None,
        "signed_in_at": datetime.now().isoformat(timespec="seconds"),
    }
    arena_db.add_signin(record)
    log_activity("arena_varsity_checkin", "arena",
                 f"Varsity check-in: {name}" + (f" on {machine_name}" if machine_name else ""))

    dmed = False
    discord_id = str(player.get("discord_id") or "").strip()
    if discord_id:
        try:
            queue_discord_notification({
                "type": "send_dm",
                "user_id": discord_id,
                "message": _VARSITY_DM.format(machine=machine_name or "a station"),
                "silent": True,  # varsity check-ins are frequent — don't spam staff with "DM Delivered"
            })
            dmed = True
        except Exception as e:
            logger.warning(f"[VARSITY] DM queue failed: {e}")

    record["returning"] = returning
    return jsonify({
        "success": True,
        "record": record,
        "returning": returning,
        "name": name,
        "first_name": first,
        "machine_name": machine_name,
        "dmed": dmed,
        "hold_minutes": max(1, min(120, int(cfg.get("pc_hold_minutes", KIOSK_HOLD_MINUTES)))),
    })

@app.route('/api/ggleap/games')
@api_auth_required
def api_ggleap_games():
    """Get available games and apps from GGLeap"""
    global ggleap_games_jwt_token
    import requests

    if _ggleap_is_paused():
        return jsonify({"error": "GGLeap paused", "games": [], "apps": []})

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
        _ggleap_count("games")
        
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
                _ggleap_count("games")
        
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

# PII fields that must be encrypted at rest in rosters.json
PLAYER_PII_FIELDS = [
    'purdue_email', 'personal_email', 'puid', 'phone', 'hometown',
    'year_in_school', 'gpa', 'major', 'jersey_details', 'additional_notes',
    'schedule_images'
]

ROSTER_ENCRYPT_KEY_FILE = os.path.join(DATA_DIR, ".roster_encrypt_key")
_roster_fernet = None

def get_roster_fernet():
    """Load or generate the Fernet encryption key for roster PII."""
    global _roster_fernet
    if _roster_fernet is not None:
        return _roster_fernet
    if not os.path.exists(ROSTER_ENCRYPT_KEY_FILE):
        key = Fernet.generate_key()
        os.makedirs(os.path.dirname(ROSTER_ENCRYPT_KEY_FILE), exist_ok=True)
        with open(ROSTER_ENCRYPT_KEY_FILE, 'wb') as f:
            f.write(key)
    else:
        with open(ROSTER_ENCRYPT_KEY_FILE, 'rb') as f:
            key = f.read().strip()
    _roster_fernet = Fernet(key)
    return _roster_fernet

def encrypt_player_pii(pii_dict):
    """Encrypt a dict of PII fields to a Fernet token string."""
    f = get_roster_fernet()
    return f.encrypt(json.dumps(pii_dict, ensure_ascii=False).encode()).decode()

def decrypt_player_pii(token):
    """Decrypt a Fernet token string back to a PII fields dict."""
    try:
        f = get_roster_fernet()
        return json.loads(f.decrypt(token.encode()))
    except Exception:
        return {}

def load_rosters():
    data = load_json_file(ROSTERS_FILE, {"players": []})
    for player in data.get("players", []):
        if "encrypted_pii" in player:
            pii = decrypt_player_pii(player.pop("encrypted_pii"))
            player.update(pii)
    return data

def save_rosters(data):
    export = copy.deepcopy(data)
    for player in export.get("players", []):
        pii = {}
        for field in PLAYER_PII_FIELDS:
            if field in player:
                pii[field] = player.pop(field)
        if pii:
            player["encrypted_pii"] = encrypt_player_pii(pii)
    save_json_file(ROSTERS_FILE, export)

def migrate_rosters_pii():
    """One-time migration: encrypt any existing plaintext PII in rosters.json."""
    try:
        raw = load_json_file(ROSTERS_FILE, {"players": []})
        needs_migration = any(
            any(f in p for f in PLAYER_PII_FIELDS)
            for p in raw.get("players", [])
        )
        if needs_migration:
            # load_rosters() decrypts existing encrypted_pii, save_rosters() re-encrypts everything
            save_rosters(load_rosters())
            print("[Roster] PII migration complete — plaintext fields encrypted.")
    except Exception as e:
        print(f"[Roster] PII migration error: {e}")

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
@api_perm_required('page.rosters')
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
                    records = load_json_file(filepath, [])
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
    
    players_out = rosters.get("players", [])
    teams_out = teams.get("teams", [])
    
    return jsonify({
        "players": players_out,
        "teams": teams_out,
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
            "purdue_email": data.get("purdue_email", existing.get("purdue_email")),
            "personal_email": data.get("personal_email", existing.get("personal_email")),
            "status": data.get("status", existing.get("status", "active")),
            "role": data.get("role", existing.get("role")),
            "secondary_role": data.get("secondary_role", existing.get("secondary_role")),
            "coach_title": data.get("coach_title", existing.get("coach_title")),
            "phone": data.get("phone", existing.get("phone")),
            "notes": data.get("notes", existing.get("notes")),
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
            "coach_title": data.get("coach_title"),
            "phone": data.get("phone"),
            "notes": data.get("notes"),
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
        records = load_json_file(record_path, [])
        
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
                    "coach_title": player_data.get("Coach Title") or ("Head Coach" if player_data.get("player_type") == "coach" else None),
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
        records = load_json_file(record_path, [])
        
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
            # Coaches keep their own type — they don't inherit the team's varsity/jv tier
            is_coach = player.get("player_type") == "coach" or player_type == "coach"
            if is_coach:
                player["player_type"] = "coach"
            else:
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
            "player_type": "coach" if player_type == "coach" else (team_type if team else player_type),
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
            "player_type": "coach" if player_type == "coach" else team_type,
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

# ============ Captains Management API Endpoints (admin-only) ============

@app.route('/api/rosters/coaches', methods=['GET'])
@api_auth_required
@api_perm_required('rosters.manage')
def api_get_coaches():
    """Get all coach roster entries. Coaches are admin-managed only — marking a
    player as Coach just tags their roster record so Discord role sync applies
    the Coach role; there is no separate website login for them."""
    rosters = load_rosters()
    teams = load_teams()
    team_names = {t.get("id"): t.get("name") for t in teams.get("teams", [])}
    
    coach_players = [p for p in rosters.get("players", []) if (p.get("player_type") or "").lower() == "coach"]
    
    result = []
    for player in coach_players:
        discord_id = str(player.get("discord_id"))
        team_ids = player.get("team_ids") or ([player["team_id"]] if player.get("team_id") else [])
        result.append({
            "discord_id": discord_id,
            "full_name": player.get("full_name"),
            "coach_title": player.get("coach_title"),
            "player_team_ids": team_ids,
            "player_team_names": [team_names.get(tid, tid) for tid in team_ids],
        })
    
    return jsonify({"coaches": result})

@app.route('/api/rosters/captains', methods=['GET'])
@api_auth_required
@api_perm_required('rosters.manage')
def api_get_captains():
    """Get all players marked as captain. Captains are admin-managed only —
    marking a player as Captain just tags their roster record so Discord role
    sync applies the Captain role; there is no separate website login for them."""
    rosters = load_rosters()
    teams = load_teams()
    team_names = {t.get("id"): t.get("name") for t in teams.get("teams", [])}
    
    captain_players = [p for p in rosters.get("players", []) if p.get("is_captain")]
    
    result = []
    for player in captain_players:
        discord_id = str(player.get("discord_id"))
        team_ids = player.get("team_ids") or ([player["team_id"]] if player.get("team_id") else [])
        result.append({
            "discord_id": discord_id,
            "full_name": player.get("full_name"),
            "game": player.get("game"),
            "player_team_ids": team_ids,
            "player_team_names": [team_names.get(tid, tid) for tid in team_ids],
        })
    
    return jsonify({"captains": result})

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
        "varsity_role_id": None,
        "coach_role_id": None
    })
    
    players = rosters.get("players", [])
    role_mapping = role_settings.get("mapping", {})
    general_varsity_role = role_settings.get("varsity_role_id")  # This is now the general roster role for ALL players
    coach_role_id = role_settings.get("coach_role_id")
    
    to_add = []
    to_remove = []
    
    # Build expected role assignments from roster
    expected_roles = {}  # user_id -> set of role_ids
    
    for player in players:
        user_id = str(player.get("discord_id"))
        if not user_id:
            continue
        
        is_coach = (player.get("player_type") or "").lower() == "coach"
        
        # A player can be on multiple teams — sync roles for every team they're on,
        # not just the first (team_id is kept only for backward compatibility).
        player_team_ids = player.get("team_ids") or ([player["team_id"]] if player.get("team_id") else [])
        if not player_team_ids:
            continue
        
        for team_id in player_team_ids:
            team = teams_by_id.get(team_id)
            if not team:
                continue
            
            # Use team's game and type (coaches keep their own type — they don't
            # inherit the team's varsity/jv competitive tier)
            game = team.get("game", "")
            player_type = "coach" if is_coach else team.get("type", player.get("player_type", "")).lower()
            username = player.get("discord_name", player.get("name", user_id))
            team_name = team.get("name", "Unknown Team")
            
            # Apply filters based on team's game and type
            if game_filter != 'all' and game.lower() != game_filter.lower():
                continue
            if type_filter != 'all' and player_type != type_filter.lower():
                continue
            
            if user_id not in expected_roles:
                expected_roles[user_id] = {"roles": set(), "username": username}
            
            if is_coach:
                if coach_role_id:
                    expected_roles[user_id]["roles"].add(coach_role_id)
                    to_add.append({
                        "user_id": user_id,
                        "username": username,
                        "role_id": coach_role_id,
                        "role_name": f"{game} Coach" if game else "Coach",
                        "game": game,
                        "team_name": team_name,
                        "type": "Coach"
                    })
            else:
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
            
            # ALL roster players (including coaches) get the general roster role
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
        "captain_role_id": None,
        "coach_role_id": None
    })
    
    players = rosters.get("players", [])
    role_mapping = role_settings.get("mapping", {})
    general_varsity_role = role_settings.get("varsity_role_id")  # This is now the general roster role for ALL players
    captain_role_id = role_settings.get("captain_role_id")  # Role for team captains
    coach_role_id = role_settings.get("coach_role_id")  # Role for coaches
    
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
        "coach_role_id": coach_role_id,  # Role for coaches
        "allow_removal": allow_removal  # Only remove roles if explicitly confirmed by user
    }
    
    for player in players:
        user_id = str(player.get("discord_id"))
        if not user_id:
            continue
        
        is_coach = (player.get("player_type") or "").lower() == "coach"
        
        # A player can be on multiple teams — collect roles for every team they're
        # on, not just the first (team_id is kept only for backward compatibility).
        player_team_ids = player.get("team_ids") or ([player["team_id"]] if player.get("team_id") else [])
        if not player_team_ids:
            print(f"[SYNC] Skipping player {user_id} - not assigned to any team")
            continue
        
        player_roles = set()
        matched_games = []
        matched_team_names = []
        matched_type = "coach" if is_coach else None
        
        for team_id in player_team_ids:
            team = teams_by_id.get(team_id)
            if not team:
                continue
            
            game = team.get("game", "") if team else player.get("game", "")
            player_type = "coach" if is_coach else (team.get("type", "") or player.get("player_type", "")).lower()
            
            # Apply filters based on team's game and type
            if game_filter != 'all' and game.lower() != game_filter.lower():
                continue
            if type_filter != 'all' and player_type != type_filter.lower():
                continue
            
            matched_games.append(game)
            matched_team_names.append(team.get("name", "Unknown"))
            if not is_coach:
                matched_type = player_type
            
            if is_coach:
                if coach_role_id:
                    player_roles.add(coach_role_id)
            else:
                # Case-insensitive lookup for game roles
                game_roles = {}
                for mapping_game, roles in role_mapping.items():
                    if mapping_game.lower() == game.lower():
                        game_roles = roles
                        break
                
                if player_type == "varsity" and game_roles.get("varsity"):
                    player_roles.add(game_roles["varsity"])
                elif player_type == "jv" and game_roles.get("jv"):
                    player_roles.add(game_roles["jv"])
            
            # ALL roster players (including coaches) get the general roster role
            if general_varsity_role:
                player_roles.add(general_varsity_role)
        
        if not matched_team_names:
            continue  # no team matched the game/type filters
        
        # Captains get the captain role
        is_captain = player.get("is_captain", False)
        if is_captain and captain_role_id:
            player_roles.add(captain_role_id)
        
        if player_roles:
            sync_data["players"].append({
                "user_id": user_id,
                "username": player.get("full_name") or player.get("discord_username") or "Unknown",
                "game": matched_games[0] if matched_games else "",
                "team_name": ", ".join(matched_team_names),
                "player_type": matched_type or (player.get("player_type") or "").lower(),
                "is_captain": is_captain,
                "expected_roles": list(player_roles)
            })
        else:
            print(f"[SYNC] Warning: Player {user_id} on team(s) {', '.join(matched_team_names)} has no matching role mapping")
    
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
                        records = load_json_file(os.path.join(VARSITY_REG_DIR, fname), [])
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
                acad.get("hometown", "") or player.get("hometown", ""),
                acad.get("major", "") or player.get("major", ""),
                acad.get("year_in_school", "") or player.get("year_in_school", ""),
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
    
    # Add to user's record so it shows up when searching
    user_db.add_record(
        user_id=str(user_id),
        type_="Watch",
        reason=reason,
        moderator=get_moderator_name(),
        moderator_id=get_moderator_id(),
        source="website"
    )
    
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
        
        # Remove Watch records from the DB
        user_db.remove_watch_records(user_id)
        
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
@api_perm_required('page.members')
def api_members():
    """Get all members from the members cache file"""
    members = load_json_file(MEMBERS_CACHE_FILE, [])
    return jsonify(members)

@app.route('/api/members/<user_id>')
@api_auth_required
@api_perm_required('page.members')
def api_member_detail(user_id):
    """Get detailed info for a specific member"""
    members = load_json_file(MEMBERS_CACHE_FILE, [])
    member = next((m for m in members if str(m.get('id')) == str(user_id)), None)
    
    if not member:
        return jsonify({"error": "Member not found"}), 404
    
    # Get user's moderation records
    records = user_db.get_records(user_id)
    
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
        # Add violation directly to DB
        user_db.add_record(
            user_id=str(user_id),
            type_="Violation",
            reason=reason,
            moderator=moderator_name,
            moderator_id=moderator_id,
            source="website"
        )
        
        # Log the activity
        log_activity(
            action="warn",
            category="moderation",
            details=f"Issued violation: {reason}",
            target_id=user_id,
            target_name=target_name,
            success=True
        )
        
        # Add live notification
        add_live_notification(
            'warning',
            'Member Violation Issued',
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
            "message": f"Violation issued to {target_name} and added to their record."
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
@api_perm_required('page.varsity')
def api_varsity_registrations():
    """Get all varsity registrations"""
    registrations = []
    
    if os.path.exists(VARSITY_REG_DIR):
        for fname in os.listdir(VARSITY_REG_DIR):
            if fname.endswith("_varsity.json"):
                user_id = fname.replace("_varsity.json", "")
                filepath = os.path.join(VARSITY_REG_DIR, fname)
                try:
                    data = load_json_file(filepath, [])
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
@api_perm_required('page.varsity')
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
            data = load_json_file(filepath, [])
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
            data = load_json_file(filepath, [])
            
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

@app.route('/api/varsity-registrations/all', methods=['DELETE'])
@api_auth_required
@api_perm_required('varsity.delete')
def api_delete_all_varsity_registrations():
    """Delete ALL varsity registrations (semester reset)"""
    if not os.path.exists(VARSITY_REG_DIR):
        return jsonify({"success": True, "deleted": 0, "message": "No registrations directory found"})

    deleted = 0
    errors = []
    for fname in os.listdir(VARSITY_REG_DIR):
        if not fname.endswith("_varsity.json"):
            continue
        filepath = os.path.join(VARSITY_REG_DIR, fname)
        try:
            data = load_json_file(filepath, [])
            # Clean up associated schedule images
            entries = data if isinstance(data, list) else [data]
            for entry in entries:
                attachments = entry.get('data', {}).get('attachments', [])
                delete_schedule_images(attachments)
            os.remove(filepath)
            deleted += 1
        except Exception as e:
            errors.append(f"{fname}: {e}")

    msg = f"Deleted {deleted} registration file(s)"
    if errors:
        msg += f" with {len(errors)} error(s)"
    return jsonify({"success": True, "deleted": deleted, "errors": errors, "message": msg})

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
            
            registrations = load_json_file(filepath, [])
            
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
        registrations = load_json_file(filepath, [])
        
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
                    "secondary_role": None,
                    "tracker": player_data.get("Tracker Link"),
                    # PII — encrypted at rest by save_rosters()
                    "purdue_email": player_data.get("Purdue Email"),
                    "personal_email": player_data.get("Personal Email"),
                    "puid": player_data.get("PUID"),
                    "phone": player_data.get("Phone Number"),
                    "hometown": player_data.get("Home Town/City (State)"),
                    "year_in_school": player_data.get("Year in School"),
                    "gpa": player_data.get("GPA"),
                    "major": player_data.get("Major"),
                    "jersey_details": player_data.get("Jersey Details"),
                    "additional_notes": player_data.get("Anything Else"),
                    "schedule_images": player_data.get("attachments_cdn", player_data.get("attachments", [])),
                    "is_captain": False,
                    "team_id": None,
                    "status": "active",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat()
                })
                rosters["players"] = players
                save_rosters(rosters)
            else:
                # Update existing player's data in case they re-registered with new info
                existing.update({
                    "full_name": player_data.get("Full Name", existing.get("full_name")),
                    "game": player_data.get("Primary Game Title", existing.get("game")),
                    "ign": player_data.get("IGN", existing.get("ign")),
                    "rank": player_data.get("Current Rank in Game", existing.get("rank")),
                    "role": player_data.get("Primary Role", existing.get("role")),
                    "tracker": player_data.get("Tracker Link", existing.get("tracker")),
                    "player_type": player_data.get("player_type", existing.get("player_type", "varsity")),
                    "purdue_email": player_data.get("Purdue Email", existing.get("purdue_email")),
                    "personal_email": player_data.get("Personal Email", existing.get("personal_email")),
                    "puid": player_data.get("PUID", existing.get("puid")),
                    "phone": player_data.get("Phone Number", existing.get("phone")),
                    "hometown": player_data.get("Home Town/City (State)", existing.get("hometown")),
                    "year_in_school": player_data.get("Year in School", existing.get("year_in_school")),
                    "gpa": player_data.get("GPA", existing.get("gpa")),
                    "major": player_data.get("Major", existing.get("major")),
                    "jersey_details": player_data.get("Jersey Details", existing.get("jersey_details")),
                    "additional_notes": player_data.get("Anything Else", existing.get("additional_notes")),
                    "schedule_images": player_data.get("attachments_cdn", player_data.get("attachments", existing.get("schedule_images", []))),
                    "updated_at": datetime.now(timezone.utc).isoformat()
                })
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
        
        registrations = load_json_file(filepath, [])
        
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
            channels = load_json_file(channels_cache_file, [])
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
    user = session.get('dashboard_user') or {}
    return user.get('display_name') or user.get('username') or 'Unknown'


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

# ============ Arena Staff — iPad Kiosk Sign-in System ============

ARENA_SIGNINS_FILE = os.path.join(DATA_DIR, "arena_signins.json")
ARENA_CONFIG_FILE = os.path.join(DATA_DIR, "arena_kiosk_config.json")
ARENA_STATE_FILE = os.path.join(DATA_DIR, "arena_kiosk_state.json")

# Per-kiosk defaults. closed_days uses JS weekday convention (0=Sun … 6=Sat).
# "type": "pc" = GGLeap PC-picker flow (arena_kiosk1.html); "console" = simple visiting/play flow (arena_kiosk2.html).
DEFAULT_ARENA_KIOSKS = {
    "kiosk-1": {"label": "Kiosk 1", "room": "Main Room (PCs)", "enabled": True, "bypass": False, "type": "pc"},
    "kiosk-2": {"label": "Kiosk 2", "room": "Console Room", "enabled": True, "bypass": False, "type": "console"},
    "kiosk-demo": {"label": "Demo Kiosk", "room": "Testing (PCs)", "enabled": True, "bypass": False,
                    "type": "pc", "scan": True, "admin_only": True, "demo": True},
}

DEFAULT_ARENA_CONFIG = {
    "open": True,
    "arena_name": "PNW Esports Arena",
    "welcome_title": "Welcome to the Esports Arena",
    "welcome_sub": "Sign in below before entering.",
    "rules_text": "I agree to follow all Arena Rules and Regulations.",
    "email_domains": ["purdue.edu", "pnw.edu"],
    "require_email": True,
    "staff_passcode": "1234",
    "max_attempts": 5,
    "open_hour": 9,
    "close_hour": 17,
    "closed_days": [6],
    "closing_soon_minutes": 15,
    "pc_lock_enabled": False,
    "pc_hold_minutes": 10,
    "ggleap_paused": False,
    "varsity_checkin": False,
    "signin_guard": {
        "enabled": True,
        "cooldown_minutes": 0,
        "max_per_day": 0,
        "max_active_pc": 1,
        "ban_message": "Please see the front desk to check in.",
    },
    "day_hours": [
        {"open": True,  "start": "09:00", "end": "17:00"},   # Sun (0)
        {"open": True,  "start": "09:00", "end": "17:00"},   # Mon (1)
        {"open": True,  "start": "09:00", "end": "17:00"},   # Tue (2)
        {"open": True,  "start": "09:00", "end": "17:00"},   # Wed (3)
        {"open": True,  "start": "09:00", "end": "17:00"},   # Thu (4)
        {"open": True,  "start": "09:00", "end": "17:00"},   # Fri (5)
        {"open": False, "start": "09:00", "end": "17:00"},   # Sat (6)
    ],
    "announcement": {"enabled": False, "text": "", "color": "#CFB991", "scroll": True},
    "kiosks": DEFAULT_ARENA_KIOSKS,
}


def load_arena_config():
    """Load kiosk config deep-merged over defaults so new keys always exist."""
    cfg = load_json_file(ARENA_CONFIG_FILE, {}) or {}
    merged = copy.deepcopy(DEFAULT_ARENA_CONFIG)
    for k, v in cfg.items():
        if k == "kiosks" and isinstance(v, dict):
            for kid, kv in v.items():
                base = dict(merged["kiosks"].get(kid, {"label": kid, "room": "", "enabled": True, "bypass": False}))
                base.update(kv or {})
                merged["kiosks"][kid] = base
        else:
            merged[k] = v
    merged["day_hours"] = _arena_build_day_hours(merged, had_day_hours=("day_hours" in cfg))
    return merged


def save_arena_config(cfg):
    # Watch/ban list lives in the encrypted DB, never in this JSON.
    cfg.pop("watchlist", None)
    save_json_file(ARENA_CONFIG_FILE, cfg)


def load_arena_signins():
    # Backed by the encrypted SQLite store (arena_db); returns decrypted records.
    return arena_db.get_all()


def save_arena_signins(records):
    # Used by the retention prune path; per-sign-in writes use arena_db.add_signin().
    arena_db.replace_all(records)


def load_arena_state():
    """Kiosk runtime state (heartbeat last-seen), separate from settings."""
    return load_json_file(ARENA_STATE_FILE, {}) or {}


def save_arena_state(state):
    save_json_file(ARENA_STATE_FILE, state)


def _arena_kiosk_online(state, kid):
    """A kiosk counts as online if it polled within the last 40 seconds."""
    ls = (state.get(kid) or {}).get("last_seen")
    if not ls:
        return False, None
    try:
        t = datetime.fromisoformat(ls)
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - t).total_seconds() < 40, ls
    except Exception:
        return False, ls


def _arena_kiosk_cfg(cfg, kid):
    """Return a per-kiosk config dict (merged with defaults for that kiosk)."""
    kiosks = cfg.get("kiosks") or {}
    merged = dict(DEFAULT_ARENA_KIOSKS.get(kid, {"label": kid, "room": "", "enabled": True, "bypass": False, "type": "console"}))
    merged.update(kiosks.get(kid) or {})
    return merged


def _arena_kiosk_list(cfg):
    """All kiosks with their merged config, in order — for management UIs."""
    return [{"id": kid, **_arena_kiosk_cfg(cfg, kid)} for kid in (cfg.get("kiosks") or {})]


ARENA_DAY_COUNT = 7


def _norm_hhmm(value, default="09:00"):
    """Coerce any value to a clean 'HH:MM' 24-hour string."""
    try:
        parts = str(value).split(":")
        h = max(0, min(23, int(parts[0])))
        m = max(0, min(59, int(parts[1]) if len(parts) > 1 else 0))
        return f"{h:02d}:{m:02d}"
    except (ValueError, TypeError, IndexError):
        return default


def _parse_hhmm(value, default=0.0):
    """'HH:MM' -> float hours (e.g. '09:30' -> 9.5)."""
    try:
        parts = str(value).split(":")
        return max(0.0, min(24.0, int(parts[0]) + (int(parts[1]) if len(parts) > 1 else 0) / 60.0))
    except (ValueError, TypeError, IndexError):
        return default


def _fmt_hhmm(value):
    """'HH:MM' (or a numeric hour) -> a friendly '9:30 AM'."""
    if isinstance(value, (int, float)):
        h = int(value)
        m = int(round((value - h) * 60))
    else:
        try:
            parts = str(value).split(":")
            h = int(parts[0])
            m = int(parts[1]) if len(parts) > 1 else 0
        except (ValueError, TypeError, IndexError):
            h, m = 9, 0
    ap = "AM" if (h % 24) < 12 else "PM"
    return f"{(h % 12) or 12}:{m:02d} {ap}"


def _arena_build_day_hours(cfg, had_day_hours):
    """Return a normalized 7-entry day_hours list (JS weekday 0=Sun..6=Sat).
    Migrates from legacy open_hour/close_hour/closed_days when no per-day data."""
    src = cfg.get("day_hours") if had_day_hours else None
    closed = set(cfg.get("closed_days") or [])
    oh, ch = cfg.get("open_hour", 9), cfg.get("close_hour", 17)
    out = []
    for i in range(ARENA_DAY_COUNT):
        if isinstance(src, list) and i < len(src) and isinstance(src[i], dict):
            e = src[i]
            out.append({
                "open": bool(e.get("open", True)),
                "start": _norm_hhmm(e.get("start"), "09:00"),
                "end": _norm_hhmm(e.get("end"), "17:00"),
            })
        else:
            out.append({
                "open": i not in closed,
                "start": _norm_hhmm(f"{int(oh):02d}:00", "09:00"),
                "end": _norm_hhmm(f"{int(ch):02d}:00", "17:00"),
            })
    return out


def _arena_today_entry(cfg, now=None):
    """Return (today's day_hours entry, js_weekday)."""
    now = now or datetime.now()
    js_day = (now.weekday() + 1) % 7  # Python Mon=0..Sun=6 -> JS Sun=0..Sat=6
    hours = cfg.get("day_hours")
    if not (isinstance(hours, list) and len(hours) == ARENA_DAY_COUNT):
        hours = _arena_build_day_hours(cfg, had_day_hours=False)
    return hours[js_day], js_day


def _arena_is_open_now(cfg, kcfg=None):
    """Server-authoritative open state. A kiosk with bypass ON is forced open
    regardless of the master switch or the per-day schedule."""
    if kcfg and kcfg.get("bypass"):
        return True
    if not cfg.get("open", True):
        return False
    now = datetime.now()
    entry, _ = _arena_today_entry(cfg, now)
    if not entry.get("open", True):
        return False
    h = now.hour + now.minute / 60.0
    return _parse_hhmm(entry.get("start"), 0.0) <= h < _parse_hhmm(entry.get("end"), 24.0)


def _arena_closing_soon(cfg, kcfg=None, now=None):
    """True if the arena is open but within `closing_soon_minutes` of today's close.
    Used to restrict the kiosk to 'visiting' sign-ins as closing approaches."""
    if not _arena_is_open_now(cfg, kcfg):
        return False
    try:
        mins = int(cfg.get("closing_soon_minutes", 15) or 0)
    except (ValueError, TypeError):
        mins = 15
    if mins <= 0:
        return False
    now = now or datetime.now()
    entry, _ = _arena_today_entry(cfg, now)
    if not entry.get("open", True):
        return False
    end_h = _parse_hhmm(entry.get("end"), 24.0)
    now_h = now.hour + now.minute / 60.0
    return (end_h - now_h) <= (mins / 60.0)


def _arena_fmt_hour(h):
    h = int(h) % 24
    ap = "AM" if h < 12 else "PM"
    d = h % 12 or 12
    return f"{d}:00 {ap}"


def _arena_hours_label(cfg):
    entry, _ = _arena_today_entry(cfg)
    if not entry.get("open", True):
        return "Closed today"
    return f"{_fmt_hhmm(entry.get('start'))} – {_fmt_hhmm(entry.get('end'))}"


def _arena_closed_message(cfg):
    now = datetime.now()
    entry, _ = _arena_today_entry(cfg, now)
    if not entry.get("open", True):
        return "The arena is closed today."
    h = now.hour + now.minute / 60.0
    if h < _parse_hhmm(entry.get("start"), 0.0):
        return f"The arena opens at {_fmt_hhmm(entry.get('start'))}."
    return f"Today's hours: {_fmt_hhmm(entry.get('start'))} – {_fmt_hhmm(entry.get('end'))}."


def _arena_hours_summary(cfg):
    """Compact weekly schedule, grouping consecutive days with identical hours,
    e.g. 'Mon–Fri 9:00 AM – 5:00 PM · Sat–Sun Closed'."""
    days = cfg.get("day_hours")
    if not (isinstance(days, list) and len(days) == ARENA_DAY_COUNT):
        days = _arena_build_day_hours(cfg, had_day_hours=False)
    names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

    def label(e):
        if not e.get("open", True):
            return "Closed"
        return f"{_fmt_hhmm(e.get('start'))} – {_fmt_hhmm(e.get('end'))}"

    groups = []
    for i, e in enumerate(days):
        lbl = label(e)
        if groups and groups[-1][2] == lbl:
            groups[-1][1] = i
        else:
            groups.append([i, i, lbl])
    parts = []
    for a, b, lbl in groups:
        d = names[a] if a == b else f"{names[a]}\u2013{names[b]}"
        parts.append(f"{d} {lbl}")
    return " \u00b7 ".join(parts)


def _arena_schedule(cfg):
    """Full weekly schedule for the kiosk closed screen: one entry per day,
    today flagged, hours formatted or 'Closed'."""
    days = cfg.get("day_hours")
    if not (isinstance(days, list) and len(days) == ARENA_DAY_COUNT):
        days = _arena_build_day_hours(cfg, had_day_hours=False)
    names = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    today = (datetime.now().weekday() + 1) % 7
    out = []
    for i, e in enumerate(days):
        is_open = bool(e.get("open", True))
        hours = f"{_fmt_hhmm(e.get('start'))} \u2013 {_fmt_hhmm(e.get('end'))}" if is_open else "Closed"
        out.append({"day": names[i], "hours": hours, "open": is_open, "today": i == today})
    return out


def _valid_hex_color(c):
    return isinstance(c, str) and len(c) == 7 and c[0] == "#" and all(ch in "0123456789abcdefABCDEF" for ch in c[1:])


def _arena_announcement(cfg):
    """Normalized announcement banner config exposed to kiosks."""
    a = cfg.get("announcement") or {}
    color = a.get("color", "#CFB991")
    if not _valid_hex_color(color):
        color = "#CFB991"
    color2 = a.get("color2", "#4C6EDC")
    if not _valid_hex_color(color2):
        color2 = "#4C6EDC"
    mode = a.get("mode", "solid")
    if mode not in ("solid", "gradient", "cycle"):
        mode = "solid"
    size = a.get("size", "normal")
    if size not in ("normal", "large"):
        size = "normal"
    try:
        speed = int(a.get("speed", 5))
    except (TypeError, ValueError):
        speed = 5
    speed = max(1, min(10, speed))
    return {
        "enabled": bool(a.get("enabled")),
        "text": _clean_str(a.get("text", ""), 200),
        "color": color,
        "color2": color2,
        "mode": mode,
        "scroll": a.get("scroll", True) is not False,
        "speed": speed,
        "size": size,
        "pulse": bool(a.get("pulse")),
        "uppercase": a.get("uppercase", True) is not False,
    }


def _arena_kiosk_public(cfg, kid):
    """Public config a kiosk needs to render — never includes the passcode."""
    kcfg = _arena_kiosk_cfg(cfg, kid)
    return {
        "kiosk_id": kid,
        "label": kcfg.get("label"),
        "room": kcfg.get("room"),
        "type": kcfg.get("type", "console"),
        "enabled": kcfg.get("enabled", True),
        "bypass": kcfg.get("bypass", False),
        "arena_name": cfg.get("arena_name"),
        "welcome_title": cfg.get("welcome_title"),
        "welcome_sub": cfg.get("welcome_sub"),
        "rules_text": cfg.get("rules_text"),
        "email_domains": cfg.get("email_domains", []),
        "require_email": cfg.get("require_email", True),
        "max_attempts": cfg.get("max_attempts", 5),
        "open": _arena_is_open_now(cfg, kcfg),
        "closing_soon": _arena_closing_soon(cfg, kcfg),
        "closing_soon_minutes": int(cfg.get("closing_soon_minutes", 15) or 0),
        "closed_message": _arena_closed_message(cfg),
        "hours_label": _arena_hours_label(cfg),
        "hours_summary": _arena_hours_summary(cfg),
        "schedule": _arena_schedule(cfg),
        "announcement": _arena_announcement(cfg),
        "reload_token": kcfg.get("reload_token", 0),
        "unlock_token": kcfg.get("unlock_token", 0),
        "boot_id": SERVER_BOOT_ID,
        "varsity_checkin": bool(cfg.get("varsity_checkin", False)),
        "scan": bool(kcfg.get("scan", False)),
        "demo": bool(kcfg.get("demo", False)),
        "admin_only": bool(kcfg.get("admin_only", False)),
    }


def _clean_str(value, max_len=120):
    """Trim and length-limit a user-provided string."""
    if not isinstance(value, str):
        value = "" if value is None else str(value)
    return value.strip()[:max_len]


def _arena_check_passcode(cfg, entered):
    real = str(cfg.get("staff_passcode", "") or "")
    entered = _clean_str(entered, 12)
    return bool(real) and secrets.compare_digest(entered, real)


# Arena entry logs are retained this many days, then auto-pruned for storage.
ARENA_LOG_RETENTION_DAYS = 30


def _arena_parse_dt(s):
    """Parse an entry timestamp to a local-naive datetime (handles old UTC records)."""
    if not s:
        return None
    try:
        t = datetime.fromisoformat(s)
        if t.tzinfo is not None:
            t = t.astimezone().replace(tzinfo=None)
        return t
    except Exception:
        return None


def _arena_prune_signins(records):
    """Drop entry records older than the retention window. Returns (kept, changed)."""
    cutoff = datetime.now() - timedelta(days=ARENA_LOG_RETENTION_DAYS)
    kept = []
    changed = False
    for r in records:
        t = _arena_parse_dt(r.get("signed_in_at", ""))
        if t is not None and t < cutoff:
            changed = True
            continue
        kept.append(r)
    return kept, changed


def _arena_today_records(records):
    """Entries whose local date is today (drives the live feed; resets at midnight)."""
    today = datetime.now().strftime("%Y-%m-%d")
    out = []
    for r in records:
        t = _arena_parse_dt(r.get("signed_in_at", ""))
        if t is not None and t.strftime("%Y-%m-%d") == today:
            out.append(r)
    return out


def _arena_live_cutoff(cfg):
    """Datetime after which sign-ins appear on the live feed.
    The later of today's local midnight and the last manual 'clear live feed' time."""
    now = datetime.now()
    cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
    cleared = _arena_parse_dt(cfg.get("live_cleared_at", "") or "")
    if cleared and cleared > cutoff:
        cutoff = cleared
    return cutoff


def _arena_live_records(records, cfg):
    """Today's entries that are newer than the last live-feed clear (the current session)."""
    cutoff = _arena_live_cutoff(cfg)
    out = []
    for r in records:
        t = _arena_parse_dt(r.get("signed_in_at", ""))
        if t is not None and t >= cutoff:
            out.append(r)
    return out


def _arena_mark_returning(subset, all_records):
    """Flag each record in `subset` as returning if that email appears in the full
    history on an earlier day (i.e. they've visited before, not just today)."""
    earliest = {}
    for r in all_records:
        em = (r.get("email") or "").strip().lower()
        if not em:
            continue
        day = (r.get("signed_in_at") or "")[:10]
        if not day:
            continue
        if em not in earliest or day < earliest[em]:
            earliest[em] = day
    for r in subset:
        em = (r.get("email") or "").strip().lower()
        if not em:
            continue
        rday = (r.get("signed_in_at") or "")[:10]
        r["returning"] = bool(earliest.get(em) and earliest[em] < rday)


# -- Arena staff pages -----------------------------------------------------

@app.route('/arena')
@app.route('/arena/')
@app.route('/arena/live')
@login_required
@page_permission_required(['page.arena_live', 'page.arena_logs', 'page.arena_controls'])
def arena_live():
    return render_template('arena.html', active_tab='live')


@app.route('/arena/logs')
@login_required
@page_permission_required('page.arena_logs')
def arena_logs():
    return render_template('arena.html', active_tab='logs')


@app.route('/arena/sessions')
@login_required
@page_permission_required('page.arena_sessions')
def arena_sessions():
    return render_template('arena.html', active_tab='sessions')


@app.route('/arena/controls')
@login_required
@page_permission_required('page.arena_controls')
def arena_controls():
    return render_template('arena.html', active_tab='controls')


@app.route('/arena/activity')
@login_required
@page_permission_required('page.arena_logs')
def arena_activity():
    return render_template('arena.html', active_tab='activity')


@app.route('/arena/students')
@login_required
@page_permission_required('page.arena_students')
def arena_students():
    return render_template('arena.html', active_tab='students')


@app.route('/arena/reports')
@login_required
@page_permission_required('page.arena_reports')
def arena_reports():
    return render_template('arena.html', active_tab='reports')


@app.route('/arena/kiosk')
def arena_kiosk():
    """Public kiosk picker — choose which kiosk this device is. Admin-only kiosks
    (e.g. the Demo Kiosk) are hidden from non-admins."""
    cfg = load_arena_config()
    is_admin = _is_full_access_user()
    kiosks = []
    for i, kid in enumerate(cfg.get("kiosks", {}).keys()):
        kc = _arena_kiosk_cfg(cfg, kid)
        if kc.get("admin_only") and not is_admin:
            continue
        kiosks.append({"id": kid, **kc, "num": i + 1})
    return render_template('arena_kiosk.html', kiosks=kiosks, arena_name=cfg.get("arena_name"))


def _arena_normalize_kid(kid):
    """Accept '1'/'2' (legacy), 'demo', or a full 'kiosk-3' id ? canonical 'kiosk-N'."""
    kid = str(kid or "").strip().lower()
    if kid.isdigit():
        return "kiosk-" + kid
    if kid and not kid.startswith("kiosk-"):
        return "kiosk-" + kid
    return kid


@app.route('/arena/kiosk/<kid>')
def arena_kiosk_device(kid):
    """Public fullscreen sign-in kiosk for any room. The template is chosen by the
    kiosk's type: 'pc' ? GGLeap station picker, anything else ? simple visiting flow."""
    cfg = load_arena_config()
    kid = _arena_normalize_kid(kid)
    if kid not in cfg.get("kiosks", {}):
        return ("Kiosk not found", 404)
    kcfg = _arena_kiosk_cfg(cfg, kid)
    # Admin-only kiosks (e.g. the Demo/Test kiosk) require a Nova admin session.
    if kcfg.get("admin_only") and not _is_full_access_user():
        return redirect(url_for('login', next=request.path))
    template = 'arena_kiosk1.html' if kcfg.get("type") == "pc" else 'arena_kiosk2.html'
    return render_template(template, kiosk=_arena_kiosk_public(cfg, kid))


# -- Arena API — staff endpoints -------------------------------------------

@app.route('/api/arena/stats')
@api_auth_required
def api_arena_stats():
    cfg = load_arena_config()
    records = load_arena_signins()
    records, pruned = _arena_prune_signins(records)
    if pruned:
        save_arena_signins(records)
    today_recs = _arena_live_records(records, cfg)
    # Current calendar week to date (weeks start Sunday), not a rolling 7 days.
    _now = datetime.now()
    _week_start = (_now - timedelta(days=(_now.weekday() + 1) % 7)).replace(hour=0, minute=0, second=0, microsecond=0)
    week_count = sum(1 for r in records
                     if (_arena_parse_dt(r.get("signed_in_at", "")) or datetime.min) >= _week_start)
    by_kiosk = {}
    last_signin = {}
    for r in today_recs:
        by_kiosk[r.get("kiosk_id", "?")] = by_kiosk.get(r.get("kiosk_id", "?"), 0) + 1
    for r in records:
        kid = r.get("kiosk_id", "?")
        si = r.get("signed_in_at", "")
        if si > last_signin.get(kid, ""):
            last_signin[kid] = si
    state = load_arena_state()
    kiosks = []
    for kid in cfg.get("kiosks", {}):
        kcfg = _arena_kiosk_cfg(cfg, kid)
        online, last_seen = _arena_kiosk_online(state, kid)
        kiosks.append({
            "id": kid, "label": kcfg.get("label"), "room": kcfg.get("room"),
            "enabled": kcfg.get("enabled", True), "bypass": kcfg.get("bypass", False),
            "open": _arena_is_open_now(cfg, kcfg), "today": by_kiosk.get(kid, 0),
            "online": online, "last_seen": last_seen, "last_signin": last_signin.get(kid),
            "locked": bool((state.get(kid) or {}).get("locked")),
        })
    return jsonify({
        "success": True,
        "today_count": len(today_recs),
        "week_count": week_count,
        "total_count": len(records),
        "arena_open": _arena_is_open_now(cfg),
        "hours_label": _arena_hours_label(cfg),
        "kiosks": kiosks,
    })


@app.route('/api/arena/active')
@api_auth_required
def api_arena_active():
    """Today's arena entries (live feed) — resets automatically at local midnight."""
    cfg = load_arena_config()
    records = load_arena_signins()
    records, pruned = _arena_prune_signins(records)
    if pruned:
        save_arena_signins(records)
    today = _arena_live_records(records, cfg)
    today.sort(key=lambda r: r.get("signed_in_at", ""), reverse=True)
    _arena_mark_returning(today, records)
    # Merge transient system events (admin unlocks) newer than the last live clear.
    cutoff = _arena_live_cutoff(cfg)
    sys_events = [e for e in _arena_system_events
                  if (_arena_parse_dt(e.get("signed_in_at", "")) or datetime.min) >= cutoff]
    if sys_events:
        merged = today + sys_events
        merged.sort(key=lambda r: r.get("signed_in_at", ""), reverse=True)
        today = merged
    return jsonify({"success": True, "active": today})


@app.route('/api/arena/active/clear', methods=['POST'])
@api_perm_required('page.arena_live')
def api_arena_active_clear():
    """Clear the live feed (resets the visible board for a fresh session).
    Non-destructive: entries remain in the Sign-in Logs / history."""
    cfg = load_arena_config()
    cfg["live_cleared_at"] = datetime.now().isoformat(timespec="seconds")
    save_arena_config(cfg)
    return jsonify({"success": True, "cleared_at": cfg["live_cleared_at"]})


def _arena_filter_logs(records, args):
    """Filter entry records by search text, kiosk, and date range."""
    query = _clean_str(args.get('q', ''), 80).lower()
    kiosk = _clean_str(args.get('kiosk', ''), 40)
    dfrom = _clean_str(args.get('from', ''), 10)      # YYYY-MM-DD
    dto = _clean_str(args.get('to', ''), 10)
    out = []
    for r in records:
        if query and query not in (r.get("name", "") + " " + r.get("email", "") + " "
                                   + r.get("kiosk_label", "") + " " + r.get("room", "")).lower():
            continue
        if kiosk and r.get("kiosk_id") != kiosk:
            continue
        day = (r.get("signed_in_at", "") or "")[:10]
        if dfrom and day and day < dfrom:
            continue
        if dto and day and day > dto:
            continue
        out.append(r)
    return out


@app.route('/api/arena/logs')
@api_auth_required
def api_arena_logs():
    """Filtered arena entry history with a summary, newest first."""
    records = load_arena_signins()
    records, pruned = _arena_prune_signins(records)
    if pruned:
        save_arena_signins(records)
    filtered = _arena_filter_logs(records, request.args)
    unique = len({(r.get('email') or r.get('name', '')).lower() for r in filtered})
    logs = list(reversed(filtered))[:2000]
    _arena_mark_returning(logs, records)
    return jsonify({
        "success": True,
        "logs": logs,
        "summary": {"total": len(filtered), "unique": unique, "all_time": len(records),
                    "retention_days": ARENA_LOG_RETENTION_DAYS},
    })


@app.route('/api/arena/logs/export')
@api_auth_required
def api_arena_logs_export():
    """Download filtered arena entry history as CSV."""
    records = load_arena_signins()
    filtered = list(reversed(_arena_filter_logs(records, request.args)))
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Name", "First", "Last", "Email", "Kiosk", "Room", "Entered", "Reason", "Checked In By", "Accepted Rules"])
    for r in filtered:
        writer.writerow([
            r.get("name", ""), r.get("first_name", ""), r.get("last_name", ""), r.get("email", ""),
            r.get("kiosk_label", ""), r.get("room", ""), r.get("signed_in_at", ""),
            r.get("reason", ""), r.get("checked_in_by", ""),
            "yes" if r.get("accepted_rules") else "no",
        ])
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    return Response(output.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=arena_entries_{stamp}.csv"})


def _entry_kind(r):
    """Classify a sign-in as guest / varsity / staff for reporting."""
    k = (r.get("kind") or "").lower()
    if k in ("guest", "varsity", "staff"):
        return k
    reason = (r.get("reason") or "").lower()
    if "varsity" in reason:
        return "varsity"
    if r.get("manual") or r.get("checked_in_by"):
        return "staff"
    return "guest"


def _rec_machine(r):
    """The station a sign-in used. Prefers the explicit machine field, else falls
    back to the room when it looks like a station name (older records stored the
    station in `room`)."""
    m = (r.get("machine") or "").strip()
    if m:
        return m
    room = (r.get("room") or "").strip()
    if re.match(r"(Island\s+\d+\s+S\d+|Stage\s+S\d+)$", room, re.IGNORECASE):
        return room
    return ""


def _arena_build_analytics(records):
    """Aggregate entry records into chart-ready buckets plus headline stats."""
    from collections import Counter
    day_counts, hour_counts, weekday_counts, kiosk_counts = Counter(), Counter(), Counter(), Counter()
    type_counts = Counter()
    heat = [[0] * 24 for _ in range(7)]
    visitors = {}
    machines = {}
    emails = set()
    accepted = 0
    for r in records:
        dt = _arena_parse_dt(r.get("signed_in_at", ""))
        if not dt:
            continue
        si = r.get("signed_in_at", "")
        kind = _entry_kind(r)
        type_counts[kind] += 1
        day_counts[dt.strftime("%Y-%m-%d")] += 1
        hour_counts[dt.hour] += 1
        wd = (dt.weekday() + 1) % 7                       # -> JS weekday (0=Sun)
        weekday_counts[wd] += 1
        heat[wd][dt.hour] += 1
        kiosk_counts[r.get("kiosk_label") or r.get("kiosk_id") or "Unknown"] += 1
        key = (r.get("email") or r.get("name", "")).strip().lower()
        emails.add(key)
        v = visitors.setdefault(key, {"name": r.get("name", ""), "email": r.get("email", ""),
                                      "count": 0, "first": "", "last": "",
                                      "guest": 0, "varsity": 0, "staff": 0, "machines": Counter()})
        v["count"] += 1
        v[kind] += 1
        if not v["name"] and r.get("name"):
            v["name"] = r.get("name")
        if si > v["last"]:
            v["last"] = si
        if si and (not v["first"] or si < v["first"]):
            v["first"] = si
        mn = _rec_machine(r)
        if mn:
            v["machines"][mn] += 1
            mc = machines.setdefault(mn, {"machine": mn, "count": 0, "users": set(),
                                          "guest": 0, "varsity": 0, "staff": 0, "last": ""})
            mc["count"] += 1
            mc[kind] += 1
            if key:
                mc["users"].add(key)
            if si > mc["last"]:
                mc["last"] = si
        if r.get("accepted_rules"):
            accepted += 1

    by_day = []
    if day_counts:
        d0 = datetime.strptime(min(day_counts), "%Y-%m-%d").date()
        d1 = datetime.strptime(max(day_counts), "%Y-%m-%d").date()
        cur = d0
        while cur <= d1:
            k = cur.strftime("%Y-%m-%d")
            by_day.append({"date": k, "count": day_counts.get(k, 0)})
            cur += timedelta(days=1)

    by_hour = [{"hour": h, "count": hour_counts.get(h, 0)} for h in range(24)]
    wk = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    by_weekday = [{"day": wk[i], "count": weekday_counts.get(i, 0)} for i in range(7)]
    by_kiosk = [{"label": k, "count": v} for k, v in sorted(kiosk_counts.items(), key=lambda x: -x[1])]

    def _mkey(name):
        m = re.match(r"Island (\d+) S(\d+)", name, re.IGNORECASE)
        if m:
            return (0, int(m.group(1)), int(m.group(2)))
        m = re.match(r"Stage S(\d+)", name, re.IGNORECASE)
        if m:
            return (1, 0, int(m.group(1)))
        return (2, 999, 999)
    by_machine = [{"machine": mc["machine"], "count": mc["count"], "unique": len(mc["users"]),
                   "guest": mc["guest"], "varsity": mc["varsity"], "staff": mc["staff"], "last": mc["last"]}
                  for mc in sorted(machines.values(), key=lambda x: _mkey(x["machine"]))]
    by_type = {"guest": type_counts.get("guest", 0), "varsity": type_counts.get("varsity", 0),
               "staff": type_counts.get("staff", 0)}

    total = sum(day_counts.values())
    busiest_day = max(by_day, key=lambda x: x["count"]) if by_day else {"date": None, "count": 0}
    peak_hour = max(by_hour, key=lambda x: x["count"]) if total else {"hour": None, "count": 0}
    active_days = sum(1 for d in by_day if d["count"] > 0)

    peak_slot = {"day": None, "hour": None, "count": 0}
    hmax = 0
    for d in range(7):
        for h in range(24):
            c = heat[d][h]
            if c > peak_slot["count"]:
                peak_slot = {"day": wk[d], "hour": h, "count": c}
            if c > hmax:
                hmax = c
    bwd = max(range(7), key=lambda i: weekday_counts.get(i, 0)) if weekday_counts else None
    busiest_weekday = {"day": wk[bwd], "count": weekday_counts.get(bwd, 0)} if bwd is not None else {"day": None, "count": 0}

    def _vis_out(v, n=60):
        top = sorted(visitors.values(), key=lambda x: -x["count"])[:n]
        out = []
        for x in top:
            fav = x["machines"].most_common(1)[0][0] if x["machines"] else ""
            out.append({"name": x["name"], "email": x["email"], "count": x["count"],
                        "first": x["first"], "last": x["last"], "guest": x["guest"],
                        "varsity": x["varsity"], "staff": x["staff"], "favorite": fav})
        return out
    students = _vis_out(visitors, 60)
    top_visitors = students[:8]

    return {
        "totals": {
            "total": total,
            "unique": len(emails),
            "active_days": active_days,
            "avg_per_day": round(total / active_days, 1) if active_days else 0,
            "busiest_day": busiest_day,
            "peak_hour": peak_hour,
            "peak_slot": peak_slot,
            "busiest_weekday": busiest_weekday,
            "accept_rate": round(accepted / total * 100) if total else 0,
        },
        "by_day": by_day,
        "by_hour": by_hour,
        "by_weekday": by_weekday,
        "by_kiosk": by_kiosk,
        "by_machine": by_machine,
        "by_type": by_type,
        "students": students,
        "heatmap": heat,
        "heatmap_max": hmax,
        "top_visitors": top_visitors,
    }


@app.route('/api/arena/analytics')
@api_auth_required
def api_arena_analytics():
    """Aggregated sign-in analytics for the Activity tab (respects log filters)."""
    records = load_arena_signins()
    records, pruned = _arena_prune_signins(records)
    if pruned:
        save_arena_signins(records)
    filtered = _arena_filter_logs(records, request.args)
    cfg = load_arena_config()
    kiosks = [{"id": kid, "label": _arena_kiosk_cfg(cfg, kid).get("label") or kid}
              for kid in cfg.get("kiosks", {})]
    data = _arena_build_analytics(filtered)

    dfrom = _clean_str(request.args.get('from', ''), 10)
    dto = _clean_str(request.args.get('to', ''), 10)
    kiosk = _clean_str(request.args.get('kiosk', ''), 40)

    # Trend vs the immediately-preceding period of equal length.
    trend = None
    if dfrom and dto:
        try:
            f = datetime.strptime(dfrom, "%Y-%m-%d").date()
            t = datetime.strptime(dto, "%Y-%m-%d").date()
            length = (t - f).days + 1
            pf, pt = f - timedelta(days=length), f - timedelta(days=1)
            prev = _arena_filter_logs(records, {"from": pf.isoformat(), "to": pt.isoformat(), "kiosk": kiosk})
            pv, cur = len(prev), data["totals"]["total"]
            pct = round((cur - pv) / pv * 100) if pv else (100 if cur else 0)
            trend = {"prev_total": pv, "pct": pct, "up": cur >= pv}
        except ValueError:
            trend = None
    data["trend"] = trend

    # New vs returning visitors (needs history before the window).
    cur_keys = {(r.get("email") or r.get("name", "")).strip().lower() for r in filtered}
    new_c = ret_c = 0
    if dfrom:
        seen_before = set()
        for r in records:
            if kiosk and r.get("kiosk_id") != kiosk:
                continue
            day = (r.get("signed_in_at", "") or "")[:10]
            if day and day < dfrom:
                seen_before.add((r.get("email") or r.get("name", "")).strip().lower())
        for k in cur_keys:
            if k in seen_before:
                ret_c += 1
            else:
                new_c += 1
    else:
        new_c = len(cur_keys)
    data["new_returning"] = {"new": new_c, "returning": ret_c}

    return jsonify({"success": True, "kiosks": kiosks, **data})


@app.route('/api/arena/analytics/replay')
@api_auth_required
def api_arena_analytics_replay():
    """Minute-resolution timeline for a single day so the Activity tab can
    'replay' how busy the arena got. Returns 5-minute buckets (count + running
    total), an hourly summary, and the ordered list of that day's sign-ins."""
    day = _clean_str(request.args.get('date', ''), 10)
    kiosk = _clean_str(request.args.get('kiosk', ''), 40)
    if not day:
        day = datetime.now().strftime("%Y-%m-%d")
    records = load_arena_signins()
    todays = []
    for r in records:
        si = r.get("signed_in_at", "") or ""
        if si[:10] != day:
            continue
        if kiosk and r.get("kiosk_id") != kiosk:
            continue
        todays.append(r)
    todays.sort(key=lambda r: r.get("signed_in_at", ""))

    STEP = 5                                   # minutes per bucket
    nb = (24 * 60) // STEP                      # 288 buckets
    buckets = [0] * nb
    hourly = [0] * 24
    events = []
    for r in todays:
        dt = _arena_parse_dt(r.get("signed_in_at", ""))
        if not dt:
            continue
        idx = (dt.hour * 60 + dt.minute) // STEP
        if 0 <= idx < nb:
            buckets[idx] += 1
        hourly[dt.hour] += 1
        events.append({
            "t": dt.strftime("%H:%M"),
            "hm": dt.hour * 60 + dt.minute,
            "name": r.get("name", "") or "Guest",
            "email": r.get("email", ""),
            "machine": _rec_machine(r),
            "kind": _entry_kind(r),
        })
    cumulative = []
    run = 0
    for i, c in enumerate(buckets):
        run += c
        cumulative.append({"m": i * STEP, "t": f"{(i * STEP) // 60:02d}:{(i * STEP) % 60:02d}",
                           "count": c, "total": run})
    peak_bucket = max(range(nb), key=lambda i: buckets[i]) if todays else 0
    return jsonify({
        "success": True,
        "date": day,
        "step": STEP,
        "total": len(todays),
        "buckets": cumulative,
        "hourly": [{"hour": h, "count": hourly[h]} for h in range(24)],
        "events": events,
        "peak": {"m": peak_bucket * STEP, "count": buckets[peak_bucket] if todays else 0},
    })


@app.route('/api/arena/machine-history')
@api_auth_required
def api_arena_machine_history():
    """Full sign-in history for one station within the current filter range."""
    machine = _clean_str(request.args.get('machine', ''), 60)
    records = load_arena_signins()
    filtered = _arena_filter_logs(records, request.args)   # respects from/to/kiosk
    want = machine.strip().lower()
    rows = [r for r in filtered if _rec_machine(r).lower() == want]
    rows.sort(key=lambda r: r.get("signed_in_at", ""), reverse=True)
    users = {(r.get("email") or r.get("name", "")).strip().lower() for r in rows}
    history = [{
        "name": r.get("name", "") or "Guest",
        "email": r.get("email", ""),
        "kind": _entry_kind(r),
        "signed_in_at": r.get("signed_in_at", ""),
        "kiosk_label": r.get("kiosk_label", ""),
        "reason": r.get("reason", ""),
    } for r in rows[:500]]
    return jsonify({"success": True, "machine": machine, "count": len(rows),
                    "unique": len(users), "history": history})


@app.route('/api/arena/analytics/export')
@api_auth_required
def api_arena_analytics_export():
    """Download a professional, filterable Excel activity report."""
    records = load_arena_signins()
    filtered = _arena_filter_logs(records, request.args)
    rows = sorted(filtered, key=lambda r: r.get("signed_in_at", ""))
    stats = _arena_build_analytics(filtered)
    dfrom = _clean_str(request.args.get('from', ''), 10)
    dto = _clean_str(request.args.get('to', ''), 10)
    kiosk_id = _clean_str(request.args.get('kiosk', ''), 40)
    cfg = load_arena_config()
    kiosk_label = (_arena_kiosk_cfg(cfg, kiosk_id).get("label") or kiosk_id) if kiosk_id else "All kiosks"
    arena_name = cfg.get("arena_name", "PNW Esports Arena")

    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.chart import BarChart, LineChart, PieChart, Reference
        from openpyxl.chart.label import DataLabelList
    except ImportError:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Name", "Email", "Kiosk", "Room", "Entered", "Accepted Rules"])
        for r in rows:
            writer.writerow([r.get("name", ""), r.get("email", ""), r.get("kiosk_label", ""),
                             r.get("room", ""), r.get("signed_in_at", ""),
                             "yes" if r.get("accepted_rules") else "no"])
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        return Response(output.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename=arena_activity_{stamp}.csv"})

    TEAL, TEAL_DARK, INK, MUTE = "06B6D4", "0E7490", "0F172A", "64748B"
    NAVY, NAVY2 = "0B1B2B", "12293D"          # dark header band
    GOLD, GOLD_DK = "CFB991", "9A7B2E"         # Purdue-gold accent
    STRIPE, LIGHT, GREEN = "F3F6F9", "E2E8F0", "10B981"
    WHITE = "FFFFFF"
    title_font = Font(bold=True, color=WHITE, size=20, name="Segoe UI Semibold")
    brand_font = Font(bold=True, color=GOLD, size=11, name="Segoe UI Semibold")
    sub_font = Font(color="C7D2DA", size=10, name="Segoe UI")
    meta_font = Font(color=MUTE, size=10, italic=True, name="Segoe UI")
    kpi_val_font = Font(bold=True, color=TEAL_DARK, size=26, name="Segoe UI")
    kpi_lbl_font = Font(bold=True, color=MUTE, size=9, name="Segoe UI")
    sec_font = Font(bold=True, color=INK, size=13, name="Segoe UI Semibold")
    hdr_font = Font(bold=True, color="FFFFFF", size=11, name="Segoe UI")
    cell_font = Font(color=INK, size=11, name="Segoe UI")
    hdr_fill = PatternFill("solid", fgColor=TEAL)
    title_fill = PatternFill("solid", fgColor=NAVY)
    band_fill2 = PatternFill("solid", fgColor=NAVY2)
    gold_fill = PatternFill("solid", fgColor=GOLD)
    stripe_fill = PatternFill("solid", fgColor=STRIPE)
    kpi_fill = PatternFill("solid", fgColor="ECFEFF")
    kpi_fill2 = PatternFill("solid", fgColor="F7F3E9")
    center = Alignment(horizontal="center", vertical="center")
    left = Alignment(horizontal="left", vertical="center")
    thin = Side(style="thin", color=LIGHT)
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    def section(ws, cell, text):
        ws[cell] = text
        ws[cell].font = sec_font

    def table(ws, top, left_col, headers, data, widths=None):
        """Write a styled table; returns (header_row, last_row)."""
        from openpyxl.utils import get_column_letter
        for j, h in enumerate(headers):
            c = ws.cell(row=top, column=left_col + j, value=h)
            c.font = hdr_font
            c.fill = hdr_fill
            c.alignment = center if j else left
            c.border = border
            if widths:
                ws.column_dimensions[get_column_letter(left_col + j)].width = widths[j]
        r = top
        for i, rowvals in enumerate(data):
            r = top + 1 + i
            for j, v in enumerate(rowvals):
                c = ws.cell(row=r, column=left_col + j, value=v)
                c.font = cell_font
                c.alignment = center if j else left
                c.border = border
                if i % 2:
                    c.fill = stripe_fill
        return top, r

    wb = Workbook()

    # -- Dashboard sheet --
    ov = wb.active
    ov.title = "Dashboard"
    ov.sheet_view.showGridLines = False

    # Navy header band (rows 1-4) with brand logo + title.
    for rr in range(1, 5):
        for cc in range(1, 9):
            ov.cell(row=rr, column=cc).fill = title_fill
    ov.row_dimensions[1].height = 10
    ov.row_dimensions[2].height = 30
    ov.row_dimensions[3].height = 20
    ov.row_dimensions[4].height = 12

    try:
        from openpyxl.drawing.image import Image as XLImage
        logo_path = os.path.join(app.root_path, "static", "images", "LionByteGGLogo.png")
        if os.path.exists(logo_path):
            _img = XLImage(logo_path)
            _ratio = 58 / float(_img.height or 58)
            _img.height = 58
            _img.width = int((_img.width or 58) * _ratio)
            ov.add_image(_img, "A1")
    except Exception as _e:
        logger.warning(f"[ARENA EXPORT] logo embed failed: {_e}")

    ov.merge_cells("C2:H2")
    ov["C2"] = f"{arena_name} · Activity Report"
    ov["C2"].font = title_font
    ov["C2"].alignment = Alignment(horizontal="left", vertical="center")
    ov.merge_cells("C3:H3")
    ov["C3"] = "LIONBYTEGG  ·  ARENA ANALYTICS"
    ov["C3"].font = brand_font
    ov["C3"].alignment = Alignment(horizontal="left", vertical="center")

    # Gold accent underline (row 5).
    for cc in range(1, 9):
        ov.cell(row=5, column=cc).fill = gold_fill
    ov.row_dimensions[5].height = 4

    rng = f"{dfrom or 'earliest'} ? {dto or 'today'}"
    ov.merge_cells("A6:H6")
    ov["A6"] = f"Range: {rng}    ·    Kiosk: {kiosk_label}    ·    Generated {datetime.now().strftime('%b %d, %Y %I:%M %p')}"
    ov["A6"].font = meta_font
    ov["A6"].alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ov.row_dimensions[6].height = 20

    _ps = stats["totals"].get("peak_slot", {})
    _bw = stats["totals"].get("busiest_weekday", {})
    ps_txt = f"{_ps['day']} {_fmt_hhmm(str(_ps['hour']) + ':00')}" if _ps.get("day") and _ps.get("hour") is not None else "—"
    ov.merge_cells("A7:H7")
    ov["A7"] = f"Key insights    ·    Peak slot: {ps_txt}    ·    Busiest weekday: {_bw.get('day') or '—'}    ·    Rules accepted: {stats['totals'].get('accept_rate', 0)}%"
    ov["A7"].font = Font(bold=True, color=TEAL_DARK, size=10, name="Segoe UI")
    ov["A7"].alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ov.row_dimensions[7].height = 18

    t = stats["totals"]
    bd = t["busiest_day"]
    ph = t["peak_hour"]
    bd_txt = (datetime.strptime(bd["date"], "%Y-%m-%d").strftime("%b %d") + f"  ({bd['count']})") if bd.get("date") else "—"
    ph_txt = (_fmt_hhmm(f"{ph['hour']}:00") + f"  ({ph['count']})") if ph.get("hour") is not None else "—"
    from collections import Counter as _Counter
    kind_counts = _Counter(_entry_kind(r) for r in rows)
    kpis = [
        ("TOTAL SIGN-INS", t["total"]),
        ("UNIQUE VISITORS", t["unique"]),
        ("AVG / ACTIVE DAY", t["avg_per_day"]),
        ("GUEST", kind_counts.get("guest", 0)),
        ("VARSITY", kind_counts.get("varsity", 0)),
        ("STAFF", kind_counts.get("staff", 0)),
        ("BUSIEST DAY", bd_txt),
        ("PEAK HOUR", ph_txt),
    ]
    from openpyxl.utils import get_column_letter
    for i, (lbl, val) in enumerate(kpis):
        col = 1 + i
        fill = kpi_fill if i % 2 == 0 else kpi_fill2
        vcolor = TEAL_DARK if i % 2 == 0 else GOLD_DK
        L = ov.cell(row=9, column=col, value=lbl)
        L.font = kpi_lbl_font
        L.fill = fill
        L.alignment = center
        L.border = border
        V = ov.cell(row=10, column=col, value=val)
        V.font = kpi_val_font if isinstance(val, (int, float)) else Font(bold=True, color=vcolor, size=13, name="Segoe UI")
        if isinstance(val, (int, float)):
            V.font = Font(bold=True, color=vcolor, size=26, name="Segoe UI")
        V.fill = fill
        V.alignment = center
        V.border = border
        ov.column_dimensions[get_column_letter(col)].width = 18
    ov.row_dimensions[9].height = 18
    ov.row_dimensions[10].height = 38

    section(ov, "A12", "Sign-ins by Day of Week")
    wk_top, wk_bot = table(ov, 13, 1, ["Day", "Sign-ins"],
                           [[d["day"], d["count"]] for d in stats["by_weekday"]], widths=[14, 12])
    chart = BarChart()
    chart.type = "col"
    chart.title = "Traffic by Day of Week"
    chart.style = 10
    chart.height, chart.width = 8, 14
    chart.legend = None
    data = Reference(ov, min_col=2, min_row=wk_top, max_row=wk_bot)
    cats = Reference(ov, min_col=1, min_row=wk_top + 1, max_row=wk_bot)
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(cats)
    ov.add_chart(chart, "D12")

    section(ov, "A23", "Sign-ins by Kiosk")
    k_top, k_bot = table(ov, 24, 1, ["Kiosk", "Sign-ins"],
                         [[k["label"], k["count"]] for k in stats["by_kiosk"]] or [["—", 0]], widths=[24, 12])
    if stats["by_kiosk"]:
        pie = PieChart()
        pie.title = "Share by Kiosk"
        pie.height, pie.width = 8, 12
        pdata = Reference(ov, min_col=2, min_row=k_top, max_row=k_bot)
        pcats = Reference(ov, min_col=1, min_row=k_top + 1, max_row=k_bot)
        pie.add_data(pdata, titles_from_data=True)
        pie.set_categories(pcats)
        pie.dataLabels = DataLabelList()
        pie.dataLabels.showPercent = True
        ov.add_chart(pie, "D23")

    # -- Daily sheet --
    dsh = wb.create_sheet("Daily")
    dsh.sheet_view.showGridLines = False
    section(dsh, "A1", "Daily Sign-ins")
    d_top, d_bot = table(dsh, 2, 1, ["Date", "Sign-ins"],
                         [[d["date"], d["count"]] for d in stats["by_day"]] or [["—", 0]], widths=[16, 12])
    dsh.auto_filter.ref = f"A2:B{d_bot}"
    dsh.freeze_panes = "A3"
    if stats["by_day"]:
        lc = LineChart()
        lc.title = "Sign-ins per Day"
        lc.style = 12
        lc.height, lc.width = 9, 22
        lc.legend = None
        data = Reference(dsh, min_col=2, min_row=d_top, max_row=d_bot)
        cats = Reference(dsh, min_col=1, min_row=d_top + 1, max_row=d_bot)
        lc.add_data(data, titles_from_data=True)
        lc.set_categories(cats)
        dsh.add_chart(lc, "D2")

    # -- Hourly sheet --
    hsh = wb.create_sheet("Hourly")
    hsh.sheet_view.showGridLines = False
    section(hsh, "A1", "Sign-ins by Hour of Day")
    h_top, h_bot = table(hsh, 2, 1, ["Hour", "Sign-ins"],
                         [[_fmt_hhmm(f"{d['hour']}:00"), d["count"]] for d in stats["by_hour"]], widths=[14, 12])
    bc = BarChart()
    bc.type = "col"
    bc.title = "Busiest Hours"
    bc.style = 11
    bc.height, bc.width = 9, 22
    bc.legend = None
    data = Reference(hsh, min_col=2, min_row=h_top, max_row=h_bot)
    cats = Reference(hsh, min_col=1, min_row=h_top + 1, max_row=h_bot)
    bc.add_data(data, titles_from_data=True)
    bc.set_categories(cats)
    hsh.add_chart(bc, "D2")

    # -- Check-Ins sheet (every sign-in, all fields, filterable) --
    esh = wb.create_sheet("Check-Ins")
    esh.sheet_view.showGridLines = False
    headers = ["#", "Date", "Time", "Weekday", "Name", "Email", "Type", "Machine", "Kiosk", "Room", "Reason", "Checked In By", "Rules"]
    widths = [5, 12, 10, 11, 22, 28, 10, 16, 16, 16, 26, 18, 8]
    detail = []
    for idx, r in enumerate(rows, 1):
        dt = _arena_parse_dt(r.get("signed_in_at", ""))
        detail.append([
            idx,
            dt.strftime("%Y-%m-%d") if dt else "",
            dt.strftime("%I:%M %p").lstrip("0") if dt else "",
            dt.strftime("%A") if dt else "",
            r.get("name", ""), r.get("email", ""),
            _entry_kind(r).title(),
            _rec_machine(r) or "—",
            r.get("kiosk_label", ""), r.get("room", ""),
            r.get("reason", ""), r.get("checked_in_by", ""),
            "Yes" if r.get("accepted_rules") else "No",
        ])
    e_top, e_bot = table(esh, 1, 1, headers, detail or [["", "", "", "", "No check-ins", "", "", "", "", "", "", "", ""]], widths=widths)
    esh.auto_filter.ref = f"A1:M{e_bot}"
    esh.freeze_panes = "B2"

    # -- Machines sheet (per-station activity) --
    mach = {}
    for r in rows:
        mname = _rec_machine(r)
        if not mname:
            continue
        m = mach.setdefault(mname, {"count": 0, "users": set(), "guest": 0, "varsity": 0, "staff": 0, "first": "", "last": ""})
        m["count"] += 1
        ukey = (r.get("email") or r.get("name", "")).strip().lower()
        if ukey:
            m["users"].add(ukey)
        m[_entry_kind(r)] += 1
        si = r.get("signed_in_at", "")
        if si:
            if not m["first"] or si < m["first"]:
                m["first"] = si
            if si > m["last"]:
                m["last"] = si

    def _mach_key(kv):
        name = kv[0]
        mm = re.match(r"Island (\d+) S(\d+)", name, re.IGNORECASE)
        if mm:
            return (0, int(mm.group(1)), int(mm.group(2)))
        mm = re.match(r"Stage S(\d+)", name, re.IGNORECASE)
        if mm:
            return (1, 0, int(mm.group(1)))
        return (2, 999, 999)
    mach_sorted = sorted(mach.items(), key=_mach_key)

    msh = wb.create_sheet("Machines")
    msh.sheet_view.showGridLines = False
    section(msh, "A1", "Station Activity")
    mheaders = ["Machine", "Sign-ins", "Unique Users", "Guest", "Varsity", "Staff", "First Used", "Last Used"]
    mdata = []
    for name, m in mach_sorted:
        fdt = _arena_parse_dt(m["first"])
        ldt = _arena_parse_dt(m["last"])
        mdata.append([name, m["count"], len(m["users"]), m["guest"], m["varsity"], m["staff"],
                      fdt.strftime("%Y-%m-%d") if fdt else "",
                      ldt.strftime("%Y-%m-%d %I:%M %p") if ldt else ""])
    m_top, m_bot = table(msh, 2, 1, mheaders, mdata or [["No station activity", 0, 0, 0, 0, 0, "", ""]],
                         widths=[16, 11, 13, 9, 9, 9, 14, 20])
    msh.auto_filter.ref = f"A2:H{m_bot}"
    msh.freeze_panes = "A3"
    if mach_sorted:
        # Busiest-station chart (sorted by count for the visual).
        busy = sorted(mach_sorted, key=lambda kv: -kv[1]["count"])[:15]
        cr = m_bot + 3
        msh.cell(row=cr, column=1, value="Chart data (busiest stations)").font = Font(italic=True, color=MUTE, size=9, name="Segoe UI")
        cdata_top = cr + 1
        for j, h in enumerate(["Machine", "Sign-ins"]):
            cc = msh.cell(row=cdata_top, column=1 + j, value=h)
            cc.font = hdr_font
            cc.fill = hdr_fill
            cc.alignment = center
        for i, (name, m) in enumerate(busy):
            msh.cell(row=cdata_top + 1 + i, column=1, value=name)
            msh.cell(row=cdata_top + 1 + i, column=2, value=m["count"])
        cbot = cdata_top + len(busy)
        mbar = BarChart()
        mbar.type = "bar"
        mbar.title = "Busiest Stations"
        mbar.style = 11
        mbar.height, mbar.width = 10, 20
        mbar.legend = None
        bdata = Reference(msh, min_col=2, min_row=cdata_top, max_row=cbot)
        bcats = Reference(msh, min_col=1, min_row=cdata_top + 1, max_row=cbot)
        mbar.add_data(bdata, titles_from_data=True)
        mbar.set_categories(bcats)
        msh.add_chart(mbar, "J2")

    # -- Students sheet (per-person activity leaderboard) --
    stud = {}
    for r in rows:
        key = (r.get("email") or r.get("name", "")).strip().lower()
        if not key:
            continue
        s = stud.setdefault(key, {"name": r.get("name", ""), "email": r.get("email", ""), "count": 0,
                                  "first": "", "last": "", "guest": 0, "varsity": 0, "staff": 0,
                                  "machines": _Counter(), "accepted": 0})
        s["count"] += 1
        if not s["name"] and r.get("name"):
            s["name"] = r.get("name")
        s[_entry_kind(r)] += 1
        _rm = _rec_machine(r)
        if _rm:
            s["machines"][_rm] += 1
        if r.get("accepted_rules"):
            s["accepted"] += 1
        si = r.get("signed_in_at", "")
        if si:
            if not s["first"] or si < s["first"]:
                s["first"] = si
            if si > s["last"]:
                s["last"] = si
    stud_sorted = sorted(stud.values(), key=lambda x: -x["count"])

    ssh = wb.create_sheet("Students")
    ssh.sheet_view.showGridLines = False
    section(ssh, "A1", "Student Activity")
    sheaders = ["Rank", "Name", "Email", "Visits", "Guest", "Varsity", "Staff", "Favorite Station", "First Seen", "Last Seen"]
    sdata = []
    for i, s in enumerate(stud_sorted, 1):
        fdt = _arena_parse_dt(s["first"])
        ldt = _arena_parse_dt(s["last"])
        fav = s["machines"].most_common(1)[0][0] if s["machines"] else "—"
        sdata.append([i, s["name"] or s["email"] or "Guest", s["email"], s["count"],
                      s["guest"], s["varsity"], s["staff"], fav,
                      fdt.strftime("%Y-%m-%d") if fdt else "",
                      ldt.strftime("%Y-%m-%d %I:%M %p") if ldt else ""])
    _st, s_bot = table(ssh, 2, 1, sheaders,
                       sdata or [["", "No students", "", 0, 0, 0, 0, "—", "", ""]],
                       widths=[7, 24, 28, 9, 9, 9, 9, 16, 14, 20])
    ssh.auto_filter.ref = f"A2:J{s_bot}"
    ssh.freeze_panes = "A3"

    # -- Heatmap sheet (day × hour, colour-scaled) --
    from openpyxl.formatting.rule import ColorScaleRule
    from openpyxl.utils import get_column_letter as _gcl
    hm = wb.create_sheet("Heatmap")
    hm.sheet_view.showGridLines = False
    section(hm, "A1", "Traffic Heatmap · Day × Hour")
    wknames = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    hm_top = 2
    for j, htext in enumerate(["Day"] + [_fmt_hhmm(f"{h}:00") for h in range(24)]):
        c = hm.cell(row=hm_top, column=1 + j, value=htext)
        c.font = hdr_font
        c.fill = hdr_fill
        c.alignment = center
        c.border = border
    heat = stats.get("heatmap", [[0] * 24 for _ in range(7)])
    for i in range(7):
        rr = hm_top + 1 + i
        dc = hm.cell(row=rr, column=1, value=wknames[i])
        dc.font = cell_font
        dc.alignment = left
        dc.border = border
        for h in range(24):
            cc = hm.cell(row=rr, column=2 + h, value=heat[i][h])
            cc.font = cell_font
            cc.alignment = center
            cc.border = border
    hm.conditional_formatting.add(
        f"B{hm_top + 1}:Y{hm_top + 7}",
        ColorScaleRule(start_type='num', start_value=0, start_color='FFFFFF',
                       mid_type='percentile', mid_value=55, mid_color='7DD3E8',
                       end_type='max', end_color='06B6D4'))
    hm.column_dimensions['A'].width = 12
    for h in range(24):
        hm.column_dimensions[_gcl(2 + h)].width = 5

    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    return Response(
        bio.getvalue(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=arena_activity_{stamp}.xlsx"},
    )


@app.route('/api/arena/config')
@api_auth_required
def api_arena_get_config():
    cfg = load_arena_config()
    cfg["watchlist"] = arena_db.watchlist_all()  # served from the encrypted DB, not the JSON
    return jsonify({"success": True, "config": cfg})


@app.route('/api/arena/config', methods=['POST'])
@api_perm_required('arena.manage')
def api_arena_save_config():
    data = request.get_json(silent=True) or {}
    cfg = load_arena_config()
    if "open" in data:
        cfg["open"] = bool(data["open"])
    if "arena_name" in data:
        cfg["arena_name"] = _clean_str(data["arena_name"], 60) or DEFAULT_ARENA_CONFIG["arena_name"]
    if "welcome_title" in data:
        cfg["welcome_title"] = _clean_str(data["welcome_title"], 80) or DEFAULT_ARENA_CONFIG["welcome_title"]
    if "welcome_sub" in data:
        cfg["welcome_sub"] = _clean_str(data["welcome_sub"], 160)
    if "rules_text" in data:
        cfg["rules_text"] = _clean_str(data["rules_text"], 200) or DEFAULT_ARENA_CONFIG["rules_text"]
    if "require_email" in data:
        cfg["require_email"] = bool(data["require_email"])
    if "staff_passcode" in data:
        pin = _clean_str(data["staff_passcode"], 12)
        if pin.isdigit() and 4 <= len(pin) <= 12:
            cfg["staff_passcode"] = pin
    if "max_attempts" in data:
        try:
            cfg["max_attempts"] = max(1, min(20, int(data["max_attempts"])))
        except (ValueError, TypeError):
            pass
    if "open_hour" in data:
        try:
            cfg["open_hour"] = max(0, min(23, int(data["open_hour"])))
        except (ValueError, TypeError):
            pass
    if "close_hour" in data:
        try:
            cfg["close_hour"] = max(1, min(24, int(data["close_hour"])))
        except (ValueError, TypeError):
            pass
    if "closing_soon_minutes" in data:
        try:
            cfg["closing_soon_minutes"] = max(0, min(120, int(data["closing_soon_minutes"])))
        except (ValueError, TypeError):
            pass
    if "pc_lock_enabled" in data:
        cfg["pc_lock_enabled"] = bool(data["pc_lock_enabled"])
    if "varsity_checkin" in data:
        cfg["varsity_checkin"] = bool(data["varsity_checkin"])
    if "pc_hold_minutes" in data:
        try:
            cfg["pc_hold_minutes"] = max(1, min(120, int(data["pc_hold_minutes"])))
        except (ValueError, TypeError):
            pass
    if "signin_guard" in data and isinstance(data["signin_guard"], dict):
        sg = dict(cfg.get("signin_guard") or {})
        d = data["signin_guard"]
        if "enabled" in d:
            sg["enabled"] = bool(d["enabled"])
        if "cooldown_minutes" in d:
            sg["cooldown_minutes"] = max(0, min(1440, _as_int(d["cooldown_minutes"], 0)))
        if "max_per_day" in d:
            sg["max_per_day"] = max(0, min(100, _as_int(d["max_per_day"], 0)))
        if "max_active_pc" in d:
            sg["max_active_pc"] = max(0, min(20, _as_int(d["max_active_pc"], 0)))
        if "ban_message" in d:
            sg["ban_message"] = _clean_str(d["ban_message"], 160)
        cfg["signin_guard"] = sg
    if "closed_days" in data and isinstance(data["closed_days"], list):
        cfg["closed_days"] = sorted({d for d in data["closed_days"] if isinstance(d, int) and 0 <= d <= 6})
    if "day_hours" in data and isinstance(data["day_hours"], list):
        cfg["day_hours"] = _arena_build_day_hours({"day_hours": data["day_hours"]}, had_day_hours=True)
    if "announcement" in data and isinstance(data["announcement"], dict):
        a = data["announcement"]
        cur = cfg.get("announcement") or {}
        color = _clean_str(a.get("color", cur.get("color", "#CFB991")), 7)
        if not _valid_hex_color(color):
            color = "#CFB991"
        color2 = _clean_str(a.get("color2", cur.get("color2", "#4C6EDC")), 7)
        if not _valid_hex_color(color2):
            color2 = "#4C6EDC"
        mode = a.get("mode", cur.get("mode", "solid"))
        if mode not in ("solid", "gradient", "cycle"):
            mode = "solid"
        size = a.get("size", cur.get("size", "normal"))
        if size not in ("normal", "large"):
            size = "normal"
        try:
            speed = int(a.get("speed", cur.get("speed", 5)))
        except (TypeError, ValueError):
            speed = 5
        speed = max(1, min(10, speed))
        cfg["announcement"] = {
            "enabled": bool(a.get("enabled")),
            "text": _clean_str(a.get("text", ""), 200),
            "color": color,
            "color2": color2,
            "mode": mode,
            "scroll": a.get("scroll", True) is not False,
            "speed": speed,
            "size": size,
            "pulse": bool(a.get("pulse")),
            "uppercase": a.get("uppercase", True) is not False,
        }
    if "email_domains" in data and isinstance(data["email_domains"], list):
        domains = [_clean_str(d, 40).lower().lstrip("@") for d in data["email_domains"] if _clean_str(d, 40)]
        cfg["email_domains"] = domains[:10]
    if "kiosks" in data and isinstance(data["kiosks"], dict):
        for kid, kv in data["kiosks"].items():
            if kid not in cfg.get("kiosks", {}):
                continue
            if not isinstance(kv, dict):
                continue
            k = cfg["kiosks"][kid]
            if "label" in kv:
                k["label"] = _clean_str(kv["label"], 40) or k.get("label", kid)
            if "room" in kv:
                k["room"] = _clean_str(kv["room"], 60)
            if "enabled" in kv:
                k["enabled"] = bool(kv["enabled"])
            if "bypass" in kv:
                k["bypass"] = bool(kv["bypass"])
    save_arena_config(cfg)
    log_activity("arena_settings", "settings", "Updated arena kiosk settings")
    return jsonify({"success": True, "config": cfg})


@app.route('/api/arena/kiosks', methods=['POST'])
@api_perm_required('arena.manage')
def api_arena_kiosk_add():
    """Add a new kiosk (unique id) for a room. type 'pc' = station picker, else simple."""
    data = request.get_json(silent=True) or {}
    label = _clean_str(data.get("label"), 40)
    room = _clean_str(data.get("room"), 60)
    ktype = "pc" if data.get("type") == "pc" else "console"
    if not room:
        return jsonify({"success": False, "error": "A room name is required."}), 400
    cfg = load_arena_config()
    kiosks = cfg.setdefault("kiosks", {})
    nums = [int(k.split("-")[1]) for k in kiosks
            if k.startswith("kiosk-") and k.split("-")[1].isdigit()]
    new_num = (max(nums) + 1) if nums else 1
    kid = f"kiosk-{new_num}"
    kiosks[kid] = {
        "label": label or f"Kiosk {new_num}",
        "room": room, "type": ktype, "enabled": True, "bypass": False,
    }
    save_arena_config(cfg)
    log_activity("arena_kiosk", "settings", f"Added kiosk {kid} ({room})")
    return jsonify({"success": True, "id": kid, "kiosks": _arena_kiosk_list(cfg)})


@app.route('/api/arena/kiosks/<kid>', methods=['DELETE'])
@api_perm_required('arena.manage')
def api_arena_kiosk_remove(kid):
    """Remove a kiosk (never the last one)."""
    kid = _arena_normalize_kid(kid)
    cfg = load_arena_config()
    kiosks = cfg.get("kiosks") or {}
    if kid not in kiosks:
        return jsonify({"success": False, "error": "Kiosk not found."}), 404
    if len(kiosks) <= 1:
        return jsonify({"success": False, "error": "At least one kiosk is required."}), 400
    kiosks.pop(kid, None)
    save_arena_config(cfg)
    log_activity("arena_kiosk", "settings", f"Removed kiosk {kid}")
    return jsonify({"success": True, "kiosks": _arena_kiosk_list(cfg)})


@app.route('/api/arena/watchlist/add', methods=['POST'])
@api_perm_required('arena.ban')
def api_arena_watchlist_add():
    """Add (or update) an email on the ban/watch list."""
    data = request.get_json(silent=True) or {}
    email = _norm_email(data.get("email"))
    if not email or "@" not in email:
        return jsonify({"success": False, "error": "A valid email is required."}), 400
    mode = "ban" if data.get("mode") == "ban" else "watch"
    reason = _clean_str(data.get("reason"), 120)
    _u = session.get('dashboard_user') or {}
    staff = _u.get('display_name') or _u.get('username') or 'Staff'
    arena_db.watchlist_set(email, mode, reason, staff)
    log_activity("arena_watchlist", "settings", f"{staff} {mode}-listed {email}")
    return jsonify({"success": True, "watchlist": arena_db.watchlist_all()})


@app.route('/api/arena/watchlist/remove', methods=['POST'])
@api_perm_required('arena.ban')
def api_arena_watchlist_remove():
    """Remove an email from the ban/watch list."""
    data = request.get_json(silent=True) or {}
    email = _norm_email(data.get("email"))
    arena_db.watchlist_remove(email)
    log_activity("arena_watchlist", "settings", f"Removed {email} from watch/ban list")
    return jsonify({"success": True, "watchlist": arena_db.watchlist_all()})


@app.route('/api/arena/signin-flags')
@api_perm_required('arena.manage')
def api_arena_signin_flags():
    """Recent sign-in flags (bans, watches, blocked attempts) for the Nova feed."""
    return jsonify({"success": True, "flags": _arena_recent_flags(60)})


@app.route('/api/arena/signin-flags/clear', methods=['POST'])
@api_perm_required('arena.manage')
def api_arena_signin_flags_clear():
    """Clear the sign-in flags feed."""
    arena_db.clear_flags()
    log_activity("arena_signin_flag", "arena", "Cleared sign-in flags feed")
    return jsonify({"success": True})


# -- Arena students (profiles + notes) -------------------------------------

def _arena_staff_name():
    _u = session.get('dashboard_user') or {}
    return _u.get('display_name') or _u.get('username') or 'Staff'


@app.route('/api/arena/students')
@api_perm_required('page.arena_students')
def api_arena_students():
    """Every distinct student from the sign-in history + note counts + flag status."""
    query = request.args.get("q", "")
    students = arena_db.list_students(query)
    watch = {(_norm_email(w.get("email"))): w.get("mode") for w in arena_db.watchlist_all()}
    for s in students:
        s["status"] = watch.get(_norm_email(s.get("email")), "")  # '', 'watch', or 'ban'
    return jsonify({"success": True, "students": students})


@app.route('/api/arena/student')
@api_perm_required('page.arena_students')
def api_arena_student():
    """Full profile for one student: visits, notes, incidents, watch/ban status, flags."""
    email = _norm_email(request.args.get("email"))
    if not email or "@" not in email:
        return jsonify({"success": False, "error": "A valid email is required."}), 400
    visits = arena_db.get_visits(email, limit=100)
    notes = arena_db.get_notes(email)
    incidents = arena_db.get_incidents_for(email)
    if not has_perm('arena.reports_all'):
        me = _arena_staff_name()
        incidents = [i for i in incidents if (i.get("author") or "") == me]
    w = _arena_watch_entry(None, email)
    flags = [f for f in _arena_recent_flags(200) if _norm_email(f.get("email")) == email]
    name = ""
    for v in visits:
        if v.get("name"):
            name = v["name"]
            break
    return jsonify({
        "success": True,
        "profile": {
            "email": email,
            "name": name,
            "visit_count": len(visits),
            "first_at": visits[-1]["signed_in_at"] if visits else None,
            "last_at": visits[0]["signed_in_at"] if visits else None,
            "status": (w.get("mode") if w else ""),
            "status_reason": (w.get("reason") if w else ""),
            "visits": visits,
            "notes": notes,
            "incidents": incidents,
            "flags": flags,
        },
    })


@app.route('/api/arena/student/note', methods=['POST'])
@api_perm_required('arena.notes')
def api_arena_student_note_add():
    data = request.get_json(silent=True) or {}
    email = _norm_email(data.get("email"))
    note = _clean_str(data.get("note"), 1000)
    if not email or "@" not in email:
        return jsonify({"success": False, "error": "A valid email is required."}), 400
    if not note:
        return jsonify({"success": False, "error": "Note text is required."}), 400
    name = _clean_str(data.get("name"), 120)
    ntype = _clean_str(data.get("type"), 30) or "general"
    nid = arena_db.add_note(email, name, note, ntype, _arena_staff_name())
    log_activity("arena_student_note", "arena", f"{_arena_staff_name()} noted {email}: {note[:60]}")
    return jsonify({"success": True, "id": nid, "notes": arena_db.get_notes(email)})


@app.route('/api/arena/student/note/<nid>', methods=['DELETE'])
@api_perm_required('arena.notes')
def api_arena_student_note_delete(nid):
    arena_db.delete_note(nid)
    return jsonify({"success": True})


@app.route('/api/arena/student', methods=['DELETE'])
@api_perm_required('arena.students_manage')
def api_arena_student_delete():
    """Delete a student's entire record (all sign-ins + notes)."""
    email = _norm_email(request.args.get("email"))
    if not email or "@" not in email:
        return jsonify({"success": False, "error": "A valid email is required."}), 400
    visits, notes = arena_db.delete_student(email)
    log_activity("arena_student_delete", "arena", f"{_arena_staff_name()} deleted {email} ({visits} visits, {notes} notes)")
    return jsonify({"success": True, "deleted_visits": visits, "deleted_notes": notes})


@app.route('/api/arena/student/edit', methods=['POST'])
@api_perm_required('arena.students_manage')
def api_arena_student_edit():
    """Edit a student's name and/or email across all their records + PUID entry."""
    data = request.get_json(silent=True) or {}
    email = _norm_email(data.get("email"))
    if not email or "@" not in email:
        return jsonify({"success": False, "error": "A valid email is required."}), 400
    new_name = _clean_str(data.get("name"), 120)
    new_email = _norm_email(data.get("new_email")) if data.get("new_email") else None
    if new_email and "@" not in new_email:
        return jsonify({"success": False, "error": "Enter a valid new email."}), 400
    if not new_name and not new_email:
        return jsonify({"success": False, "error": "Nothing to update."}), 400
    arena_db.update_student(email, new_name=new_name or None, new_email=new_email)
    try:
        puid_db.update_by_email(email, new_name=new_name or None, new_email=new_email)
    except Exception as e:
        logger.warning(f"[STUDENT EDIT] PUID sync failed: {e}")
    log_activity("arena_student_edit", "arena",
                 f"{_arena_staff_name()} edited student {email}" + (f" ? {new_email}" if new_email else ""))
    return jsonify({"success": True, "email": new_email or email, "name": new_name})


@app.route('/api/arena/student/reset', methods=['POST'])
@api_perm_required('arena.students_manage')
def api_arena_student_reset():
    """Reset a student's account: clears their saved PUID registration so they
    re-register on their next scan. Visit history is preserved."""
    data = request.get_json(silent=True) or {}
    email = _norm_email(data.get("email"))
    if not email or "@" not in email:
        return jsonify({"success": False, "error": "A valid email is required."}), 400
    removed = 0
    try:
        removed = puid_db.delete_by_email(email)
    except Exception as e:
        logger.warning(f"[STUDENT RESET] PUID delete failed: {e}")
    log_activity("arena_student_reset", "arena", f"{_arena_staff_name()} reset account for {email}")
    return jsonify({"success": True, "reset": bool(removed), "email": email})


# -- Arena incident reports ------------------------------------------------

def _arena_visible_incidents():
    """Incidents the current user may see: all if 'arena.reports_all', else only their own."""
    incidents = arena_db.list_incidents()
    if not has_perm('arena.reports_all'):
        me = _arena_staff_name()
        incidents = [i for i in incidents if (i.get("author") or "") == me]
    return incidents


def _arena_can_edit_incident(rid):
    """True if the user can resolve/delete this incident (owner or reports_all)."""
    if has_perm('arena.reports_all'):
        return True
    me = _arena_staff_name()
    return any(i.get("id") == rid and (i.get("author") or "") == me for i in arena_db.list_incidents())


@app.route('/api/arena/incidents')
@api_perm_required('page.arena_reports')
def api_arena_incidents():
    return jsonify({"success": True, "incidents": _arena_visible_incidents(),
                    "can_see_all": has_perm('arena.reports_all')})


@app.route('/api/arena/incidents', methods=['POST'])
@api_perm_required('arena.reports')
def api_arena_incident_create():
    data = request.get_json(silent=True) or {}
    title = _clean_str(data.get("title"), 140)
    desc = _clean_str(data.get("description"), 4000)
    if not title:
        return jsonify({"success": False, "error": "A title is required."}), 400
    itype = _clean_str(data.get("type"), 30) or "other"
    severity = data.get("severity") if data.get("severity") in ("low", "medium", "high") else "low"
    rid = arena_db.add_incident(
        title, itype, severity, desc, _arena_staff_name(),
        involved_name=_clean_str(data.get("involved_name"), 120),
        involved_email=_norm_email(data.get("involved_email")),
    )
    log_activity("arena_incident", "arena", f"{_arena_staff_name()} filed incident: {title}")
    return jsonify({"success": True, "id": rid, "incidents": _arena_visible_incidents()})


@app.route('/api/arena/incidents/<rid>/resolve', methods=['POST'])
@api_perm_required('arena.reports')
def api_arena_incident_resolve(rid):
    if not _arena_can_edit_incident(rid):
        return jsonify({"success": False, "error": "You can only manage your own reports."}), 403
    data = request.get_json(silent=True) or {}
    status = data.get("status") if data.get("status") in ("open", "resolved") else "resolved"
    arena_db.resolve_incident(rid, _arena_staff_name(), status)
    return jsonify({"success": True, "incidents": _arena_visible_incidents()})


@app.route('/api/arena/incidents/<rid>', methods=['DELETE'])
@api_perm_required('arena.reports')
def api_arena_incident_delete(rid):
    if not _arena_can_edit_incident(rid):
        return jsonify({"success": False, "error": "You can only delete your own reports."}), 403
    arena_db.delete_incident(rid)
    return jsonify({"success": True, "incidents": _arena_visible_incidents()})


@app.route('/api/arena/ggleap-usage')
@api_perm_required('arena.manage')
def api_arena_ggleap_usage():
    """Today's GGLeap API usage vs the daily cap (no GGLeap call — reads the local
    meter). Lets staff see how close we are to the limit."""
    with _ggleap_usage_lock:
        today = _ggleap_usage_today()
        if _ggleap_usage.get("date") != today:
            used, by_kind = 0, {}
        else:
            used, by_kind = int(_ggleap_usage.get("total", 0)), dict(_ggleap_usage.get("by_kind", {}))
    return jsonify({
        "success": True,
        "date": today,
        "used": used,
        "limit": GGLEAP_DAILY_LIMIT,
        "remaining": max(0, GGLEAP_DAILY_LIMIT - used),
        "pct": round(used / GGLEAP_DAILY_LIMIT * 100, 1) if GGLEAP_DAILY_LIMIT else 0,
        "by_kind": by_kind,
    })


def _pc_collect_lock_targets(lock):
    """Return [(uuid, name), ...] Island PCs to act on: for lock=True the idle
    unlocked ones; for lock=False every admin-locked one. ([] on API error)."""
    devices, error = _ggleap_get_machines()
    if error and not devices:
        return []
    out = []
    for d in devices:
        if d.get("GgRockVm"):
            continue
        name, uuid = d.get("Name", ""), d.get("Uuid")
        if not uuid or not _is_kiosk_pc(name):
            continue
        is_locked = bool(d.get("IsLocked"))
        if lock:
            if d.get("State") == "ReadyForUser" and not is_locked:
                out.append((uuid, name))
        else:
            if is_locked and bool(d.get("LockedByAdmin")):
                out.append((uuid, name))
    return out


def _pc_bulk_apply(items, lock):
    """Background: lock/unlock a batch of PCs (throttled) and keep the reconcile
    loop's memory in sync so its decision matches this manual override."""
    for uuid, name in items:
        ok, err = _ggleap_set_screen_lock(uuid, True, _pc_lock_message(name)) if lock \
            else _ggleap_set_screen_lock(uuid, False)
        if ok:
            if lock:
                _pc_human_unlocked.discard(uuid)
                _pc_we_locked.add(uuid)
            else:
                _pc_we_locked.discard(uuid)
                _pc_human_unlocked.add(uuid)  # stays unlocked until it reboots
        else:
            logger.warning(f"[PCLOCK] bulk {'lock' if lock else 'unlock'} {name} failed: {err}")


@app.route('/api/arena/pcs/lock-status')
@api_perm_required('arena.manage')
def api_arena_pcs_lock_status():
    """Lock overview for the Kiosk Manager: how many Island PCs are locked,
    idle-and-unlocked (lockable now), in use, or offline."""
    counts = {"locked": 0, "lockable": 0, "in_use": 0, "offline": 0, "total": 0, "enabled": bool(load_arena_config().get("pc_lock_enabled", False))}
    devices, error = _ggleap_get_machines()
    if error and not devices:
        return jsonify({"success": False, "error": error, **counts})
    for d in devices:
        if d.get("GgRockVm") or not _is_kiosk_pc(d.get("Name", "")):
            continue
        counts["total"] += 1
        state = d.get("State")
        if bool(d.get("IsLocked")):
            counts["locked"] += 1
        elif state == "Off":
            counts["offline"] += 1
        elif state == "ReadyForUser":
            counts["lockable"] += 1
        else:
            counts["in_use"] += 1
    return jsonify({"success": True, **counts})


@app.route('/api/arena/pcs/lock-all', methods=['POST'])
@api_perm_required('arena.manage')
def api_arena_pcs_lock_all():
    """Lock every idle, unlocked Island PC now (manual trigger). Runs in the
    background because calls are throttled to respect GGLeap's rate limit."""
    targets = _pc_collect_lock_targets(lock=True)
    if targets:
        threading.Thread(target=_pc_bulk_apply, args=(list(targets), True), daemon=True).start()
        log_activity("arena_pc_lock_all", "arena", f"Locking {len(targets)} idle PC(s)")
    return jsonify({"success": True, "count": len(targets)})


@app.route('/api/arena/pcs/unlock-all', methods=['POST'])
@api_perm_required('arena.manage')
def api_arena_pcs_unlock_all():
    """Unlock every admin-locked Island PC now (manual trigger). They stay
    unlocked until they reboot, even if the lock feature is on."""
    targets = _pc_collect_lock_targets(lock=False)
    if targets:
        threading.Thread(target=_pc_bulk_apply, args=(list(targets), False), daemon=True).start()
        log_activity("arena_pc_unlock_all", "arena", f"Unlocking {len(targets)} PC(s)")
    return jsonify({"success": True, "count": len(targets)})


@app.route('/api/arena/alerts')
@api_auth_required
def api_arena_alerts():
    """Lightweight per-kiosk lock/online status for fast alerting (no signin file read)."""
    cfg = load_arena_config()
    state = load_arena_state()
    kiosks = []
    for kid in cfg.get("kiosks", {}):
        kcfg = _arena_kiosk_cfg(cfg, kid)
        ks = state.get(kid) or {}
        online, last_seen = _arena_kiosk_online(state, kid)
        kiosks.append({
            "id": kid, "label": kcfg.get("label"), "room": kcfg.get("room"),
            "locked": bool(ks.get("locked")), "attempts": ks.get("attempts", 0),
            "max_attempts": cfg.get("max_attempts", 5),
            "online": online, "last_seen": last_seen,
        })
    open_reports = 0
    if has_perm('page.arena_reports'):
        open_reports = sum(1 for i in _arena_visible_incidents() if i.get("status") != "resolved")
    return jsonify({"success": True, "kiosks": kiosks, "flags": _arena_recent_flags(8, since_minutes=10),
                    "open_reports": open_reports})


# -- Arena API — public kiosk endpoints (no login) -------------------------

@app.route('/api/arena/kiosk/<kid>/config')
def api_arena_kiosk_config(kid):
    """Public per-kiosk display config (no passcode). Doubles as a heartbeat."""
    cfg = load_arena_config()
    state = load_arena_state()
    ks = state.setdefault(kid, {})
    ks["last_seen"] = datetime.now(timezone.utc).isoformat()
    # Kiosk reports its own lockout state so staff can see/unlock it remotely.
    if request.args.get("locked") is not None:
        reported_locked = request.args.get("locked") == "1"
        # Ignore a stale locked=1 from a kiosk that hasn't yet processed the latest
        # remote unlock (prevents the alert from re-appearing right after unlocking).
        try:
            kiosk_utok = int(request.args.get("utok", 0))
        except (ValueError, TypeError):
            kiosk_utok = 0
        server_utok = int(_arena_kiosk_cfg(cfg, kid).get("unlock_token", 0))
        if reported_locked and kiosk_utok < server_utok:
            reported_locked = False
        ks["locked"] = reported_locked
        try:
            ks["attempts"] = int(request.args.get("attempts", 0))
        except (ValueError, TypeError):
            ks["attempts"] = 0
    save_arena_state(state)
    return jsonify({"success": True, "config": _arena_kiosk_public(cfg, kid)})


@app.route('/api/arena/kiosk/<kid>/reload', methods=['POST'])
@api_perm_required('arena.manage')
def api_arena_kiosk_reload(kid):
    """Remotely tell a kiosk (or all) to reload — kiosks pick this up within seconds."""
    cfg = load_arena_config()
    targets = list(cfg.get("kiosks", {}).keys()) if kid == "all" else [kid]
    if kid != "all" and kid not in cfg.get("kiosks", {}):
        return jsonify({"success": False, "error": "Unknown kiosk"}), 404
    for t in targets:
        cfg["kiosks"][t]["reload_token"] = int(cfg["kiosks"][t].get("reload_token", 0)) + 1
    save_arena_config(cfg)
    return jsonify({"success": True})


@app.route('/api/arena/kiosk/<kid>/unlock', methods=['POST'])
@api_perm_required('arena.unlock')
def api_arena_kiosk_unlock(kid):
    """Remotely clear a kiosk's failed-attempt lockout so the visitor can retry."""
    cfg = load_arena_config()
    targets = list(cfg.get("kiosks", {}).keys()) if kid == "all" else [kid]
    if kid != "all" and kid not in cfg.get("kiosks", {}):
        return jsonify({"success": False, "error": "Unknown kiosk"}), 404
    for t in targets:
        cfg["kiosks"][t]["unlock_token"] = int(cfg["kiosks"][t].get("unlock_token", 0)) + 1
    save_arena_config(cfg)
    # Optimistically clear the reported lock state so the UI updates immediately.
    state = load_arena_state()
    for t in targets:
        if t in state:
            state[t]["locked"] = False
            state[t]["attempts"] = 0
    save_arena_state(state)
    return jsonify({"success": True})




@app.route('/api/arena/verify-pin', methods=['POST'])
def api_arena_verify_pin():
    """Public: verify the staff passcode for the on-kiosk admin panel."""
    cfg = load_arena_config()
    entered = (request.get_json(silent=True) or {}).get("pin", "")
    if _arena_check_passcode(cfg, entered):
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Incorrect passcode"}), 403


@app.route('/api/arena/kiosk-unlock', methods=['POST'])
def api_arena_kiosk_bypass_unlock():
    """PIN-gated (or staff): unlock a station from the on-kiosk 'Unlock System'
    map. Posts a 'System Unlocked · BYPASS ADMIN' event to the Live Feed."""
    cfg = load_arena_config()
    data = request.get_json(silent=True) or {}
    if not (_is_full_access_user() or has_perm('arena.manage')):
        if not _arena_check_passcode(cfg, data.get("pin", "")):
            return jsonify({"success": False, "error": "Incorrect passcode"}), 403
    uid = _clean_str(data.get("machineUuid") or data.get("machine_uuid"), 60)
    kid = _clean_str(data.get("kioskId") or data.get("kiosk_id") or "kiosk-1", 40)
    status = _fetch_ggleap_status()
    machine = next((p for p in status.get("pcs", []) if p.get("uuid") == uid), None)
    if not machine:
        return jsonify({"success": False, "error": "That station is no longer listed."}), 404
    name = machine.get("name", "the station")
    _pc_we_locked.discard(uid)
    _pc_human_unlocked.add(uid)
    _pc_kiosk_unlocked.add(uid)
    _pc_session_ended.pop(uid, None)
    ok, err = _ggleap_set_screen_lock(uid, False)
    if not ok:
        return jsonify({"success": False, "error": (err or "GGLeap error") + " Could not unlock the machine."}), 502
    kcfg = _arena_kiosk_cfg(cfg, kid)
    _arena_push_system_event({
        "id": uuid.uuid4().hex,
        "name": "System Unlocked",
        "email": "",
        "kiosk_id": kid, "kiosk_label": kcfg.get("label"),
        "room": name,
        "kind": "unlock",
        "system_event": True,
        "reason": "BYPASS ADMIN",
        "machine": name, "machine_uuid": uid,
        "signed_in_at": datetime.now().isoformat(timespec="seconds"),
    })
    log_activity("arena_kiosk_unlock", "arena", f"System Unlocked (BYPASS ADMIN): {name}")
    return jsonify({"success": True, "machine": name})


@app.route('/api/arena/kiosk/<kid>/bypass', methods=['POST'])
def api_arena_kiosk_bypass(kid):
    """Toggle a kiosk's arena-hours bypass. Staff session OR correct passcode."""
    cfg = load_arena_config()
    data = request.get_json(silent=True) or {}
    if not (_is_full_access_user() or has_perm('arena.manage')):
        if not _arena_check_passcode(cfg, data.get("pin", "")):
            return jsonify({"success": False, "error": "Incorrect passcode"}), 403
    if kid not in cfg.get("kiosks", {}):
        return jsonify({"success": False, "error": "Unknown kiosk"}), 404
    cfg["kiosks"][kid]["bypass"] = bool(data.get("value"))
    save_arena_config(cfg)
    kcfg = _arena_kiosk_cfg(cfg, kid)
    return jsonify({"success": True, "bypass": kcfg.get("bypass"), "open": _arena_is_open_now(cfg, kcfg)})


# -- Sign-in protection: rate/duplicate guards + ban/watch list + flags feed --
_ARENA_FLAGS_FILE = os.path.join(DATA_DIR, "arena_signin_flags.json")  # legacy — migrated to DB

def _as_int(v, d=0):
    try:
        return int(v)
    except (ValueError, TypeError):
        return d

def _norm_email(e):
    return (e or "").strip().lower()

def _arena_watch_entry(cfg, email):
    """Ban/watch entry for an email (read from the encrypted DB; cfg unused)."""
    return arena_db.watchlist_get(_norm_email(email))

def _arena_add_flag(kind, severity, email, name, kid, kcfg, reason):
    """Record a sign-in flag (ban / watch / blocked attempt) in the encrypted DB."""
    entry = arena_db.add_flag(kind, severity, _norm_email(email), name or "",
                              kid, (kcfg or {}).get("label") or kid, reason or "")
    try:
        log_activity("arena_signin_flag", "arena",
                     f"[{severity}] {kind}: {name} <{_norm_email(email)}> — {reason}")
    except Exception:
        pass
    return entry

def _arena_recent_flags(limit=60, since_minutes=None):
    return arena_db.recent_flags(limit, since_minutes)

def _signin_guard(cfg, email, name, kid, is_pc):
    """Enforce the ban/watch list + rate/duplicate limits. Returns (allowed, message).
    Bans, watches and blocked attempts are recorded as flags so staff see them in Nova."""
    kcfg = _arena_kiosk_cfg(cfg, kid)
    email = _norm_email(email)
    # Ban / watch list applies even when the numeric guards are turned off.
    w = _arena_watch_entry(cfg, email)
    if w:
        if (w.get("mode") or "watch") == "ban":
            _arena_add_flag("ban", "high", email, name, kid, kcfg, w.get("reason") or "Banned email attempted check-in")
            g = cfg.get("signin_guard") or {}
            return False, (g.get("ban_message") or "").strip() or "Please see the front desk to check in."
        _arena_add_flag("watch", "med", email, name, kid, kcfg, w.get("reason") or "Watch-listed guest checked in")
        # watched ? allowed, but the desk is alerted
    g = cfg.get("signin_guard") or {}
    if not g.get("enabled", True) or not email:
        return True, None
    now = datetime.now()
    records = load_arena_signins()
    mine = [r for r in records if _norm_email(r.get("email")) == email]
    cd = _as_int(g.get("cooldown_minutes"), 0)
    if cd > 0 and mine:
        last = max((_arena_parse_dt(r.get("signed_in_at", "")) or datetime.min) for r in mine)
        if last and (now - last).total_seconds() < cd * 60:
            _arena_add_flag("cooldown", "low", email, name, kid, kcfg, f"Re-check-in within {cd} min")
            return False, "You just checked in a moment ago — please wait a bit before signing in again."
    mx = _as_int(g.get("max_per_day"), 0)
    if mx > 0:
        today = now.strftime("%Y-%m-%d")
        cnt = sum(1 for r in mine if (r.get("signed_in_at") or "")[:10] == today)
        if cnt >= mx:
            _arena_add_flag("daily_cap", "low", email, name, kid, kcfg, f"Reached {mx} check-ins today")
            return False, "You've reached today's check-in limit. Please see the front desk."
    if is_pc:
        mxpc = _as_int(g.get("max_active_pc"), 0)
        if mxpc > 0:
            import time as _t
            nowts = _t.time()
            active = sum(1 for h in _arena_pc_holds.values()
                         if _norm_email(h.get("email")) == email and h.get("until", 0) > nowts)
            if active >= mxpc:
                _arena_add_flag("dup_pc", "med", email, name, kid, kcfg, "Already holds a station")
                return False, "You already have a station reserved — head to that one, or ask the front desk."
    return True, None


@app.route('/api/arena/signin', methods=['POST'])
def api_arena_signin():
    """Public: log a visitor entering the arena from a kiosk."""
    cfg = load_arena_config()
    data = request.get_json(silent=True) or {}
    kid = _clean_str(data.get("kioskId") or data.get("kiosk_id") or "kiosk-1", 40)
    kcfg = _arena_kiosk_cfg(cfg, kid)

    if not kcfg.get("enabled", True):
        return jsonify({"success": False, "error": "This kiosk is disabled."}), 403
    if not _arena_is_open_now(cfg, kcfg):
        return jsonify({"success": False, "error": _arena_closed_message(cfg)}), 403

    first = _clean_str(data.get("firstName") or data.get("first_name"), 60)
    last = _clean_str(data.get("lastName") or data.get("last_name"), 60)
    name = _clean_str(data.get("name"), 120) or (first + " " + last).strip()
    if not name:
        return jsonify({"success": False, "error": "Please enter your full name."}), 400

    email = _clean_str(data.get("email"), 120).lower()
    if cfg.get("require_email", True):
        domains = [d.lower().lstrip("@") for d in (cfg.get("email_domains") or [])]
        if not email or (domains and not any(email.endswith("@" + d) for d in domains)):
            allowed = " or ".join("@" + d for d in domains) if domains else "a valid email"
            return jsonify({"success": False, "error": f"Please use {allowed}."}), 400

    guard_ok, guard_msg = _signin_guard(cfg, email, name, kid, is_pc=False)
    if not guard_ok:
        return jsonify({"success": False, "error": guard_msg, "blocked": True}), 403

    records = load_arena_signins()
    records, _ = _arena_prune_signins(records)
    # Every kiosk sign-in creates its own entry (a person can enter more than once).

    prior = arena_db.find_recent_guest(email) if email else None
    returning = bool(prior)

    record = {
        "id": uuid.uuid4().hex,
        "name": name,
        "first_name": first,
        "last_name": last,
        "email": email,
        "kiosk_id": kid,
        "kiosk_label": kcfg.get("label"),
        "room": _clean_str(data.get("room"), 60) or kcfg.get("room", ""),
        "accepted_rules": bool(data.get("acceptedRules") or data.get("accepted_rules")),
        "reason": _clean_str(data.get("reason"), 60),
        "signed_in_at": datetime.now().isoformat(timespec="seconds"),
    }
    arena_db.add_signin(record)
    record["returning"] = returning
    return jsonify({"success": True, "record": record, "returning": returning})


@app.route('/api/arena/manual-signin', methods=['POST'])
@api_perm_required('page.arena_live')
def api_arena_manual_signin():
    """Staff fallback: check a visitor in from the dashboard when a kiosk is unavailable.
    Bypasses open-hours / kiosk-enabled / email-domain checks (trusted staff action)."""
    cfg = load_arena_config()
    data = request.get_json(silent=True) or {}
    kid = _clean_str(data.get("kioskId") or data.get("kiosk_id") or "kiosk-1", 40)
    if kid not in cfg.get("kiosks", {}):
        kid = next(iter(cfg.get("kiosks", {})), "kiosk-1")
    kcfg = _arena_kiosk_cfg(cfg, kid)

    first = _clean_str(data.get("firstName") or data.get("first_name"), 60)
    last = _clean_str(data.get("lastName") or data.get("last_name"), 60)
    name = _clean_str(data.get("name"), 120) or (first + " " + last).strip()
    if not name:
        return jsonify({"success": False, "error": "Please enter the visitor's full name."}), 400
    email = _clean_str(data.get("email"), 120).lower()
    reason = _clean_str(data.get("reason"), 200)
    _u = session.get('dashboard_user') or {}
    staff_name = _u.get('display_name') or _u.get('username') or 'Staff'

    records = load_arena_signins()
    records, _ = _arena_prune_signins(records)
    # Staff check-in is a deliberate action — always create a fresh entry so the same
    # person can be checked in again (e.g. they left and returned).

    record = {
        "id": uuid.uuid4().hex,
        "name": name,
        "first_name": first,
        "last_name": last,
        "email": email,
        "kiosk_id": kid,
        "kiosk_label": kcfg.get("label"),
        "room": _clean_str(data.get("room"), 60) or kcfg.get("room", ""),
        "accepted_rules": True,
        "manual": True,
        "reason": reason,
        "checked_in_by": staff_name,
        "signed_in_at": datetime.now().isoformat(timespec="seconds"),
    }
    arena_db.add_signin(record)
    log_activity("arena_manual_signin", "arena",
                 f"{staff_name} manually checked in {name}" + (f" — {reason}" if reason else ""))
    return jsonify({"success": True, "record": record})


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

# Migrate any existing plaintext PII to encrypted form on startup
migrate_rosters_pii()

# Initialize the encrypted arena sign-in database (migrates arena_signins.json once)
arena_db.init_arena_db(ARENA_SIGNINS_FILE)

# Initialize the secure (encrypted) PUID store
puid_db.init_puid_db()

# Ensure Student Workers can view + manage arena students (edit / reset / notes).
try:
    auth_db.ensure_group_permissions("Student Workers",
        ["section.arena", "page.arena_students", "arena.notes", "arena.students_manage"])
except Exception as _e:
    logger.warning(f"Could not grant arena student perms to Student Workers: {_e}")

# Sessions (PC room map) is its own permission, split out from page.arena_live. Student
# Workers, Supervisors, and Directors all need full view + control of PC sessions
# (lock/unlock/check-in/restart/shutdown), same as an admin.
try:
    for _grp in ("Student Workers", "Supervisors", "Directors"):
        auth_db.ensure_group_permissions(_grp, ["page.arena_sessions", "arena.manage"])
except Exception as _e:
    logger.warning(f"Could not grant page.arena_sessions/arena.manage: {_e}")


def _migrate_arena_json_to_db():
    """One-time move of the watch/ban list and sign-in flags from JSON into the
    encrypted DB, then delete the plaintext files."""
    # Watch/ban list (was stored inside arena_kiosk_config.json)
    try:
        raw = load_json_file(ARENA_CONFIG_FILE, {}) or {}
        wl = raw.get("watchlist")
        if isinstance(wl, list) and wl:
            arena_db.migrate_watchlist(wl)
        if "watchlist" in raw:
            raw.pop("watchlist", None)
            save_json_file(ARENA_CONFIG_FILE, raw)  # rewrite config without the PII list
    except Exception as e:
        logger.warning(f"[ARENA] watchlist migration skipped: {e}")
    # Sign-in flags (was arena_signin_flags.json)
    try:
        if os.path.exists(_ARENA_FLAGS_FILE):
            flags = load_json_file(_ARENA_FLAGS_FILE, []) or []
            if isinstance(flags, list) and flags and arena_db.recent_flags(1) == []:
                arena_db.migrate_flags(flags)
            os.replace(_ARENA_FLAGS_FILE, _ARENA_FLAGS_FILE + ".migrated")
    except Exception as e:
        logger.warning(f"[ARENA] flags migration skipped: {e}")


_migrate_arena_json_to_db()

# Start the background loop that keeps kiosk PCs locked/unlocked per check-ins.
_start_pc_lock_thread()

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
