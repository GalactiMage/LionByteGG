"""
Discord OAuth2 Configuration for LionByteGG Dashboard
"""
import os
from functools import wraps
from flask import session, redirect, url_for, jsonify, request

# ============ Discord OAuth2 Settings ============
# You'll need to create an application at https://discord.com/developers/applications

# Get these from Discord Developer Portal > Your App > OAuth2
DISCORD_CLIENT_ID = os.environ.get('DISCORD_CLIENT_ID', 'YOUR_CLIENT_ID_HERE')
DISCORD_CLIENT_SECRET = os.environ.get('DISCORD_CLIENT_SECRET', 'YOUR_CLIENT_SECRET_HERE')
DISCORD_REDIRECT_URI = os.environ.get('DISCORD_REDIRECT_URI', 'http://localhost:5000/auth/callback')

# Bot token for fetching guild member data (same as your bot token)
# This is used to get member roles from the Discord API
DISCORD_BOT_TOKEN = os.environ.get('DISCORD_BOT_TOKEN', '')

# Your Discord Guild/Server ID (PNW Esports)
GUILD_ID = 728274695673348140

# Discord API endpoints
DISCORD_API_BASE = "https://discord.com/api/v10"
DISCORD_AUTH_URL = "https://discord.com/api/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"

# OAuth2 scopes we need
OAUTH_SCOPES = ["identify", "guilds", "guilds.members.read"]

# ============ Role-Based Permission System ============
# Map Discord role IDs to dashboard permission levels

class PermissionLevel:
    """Permission levels for dashboard access"""
    NONE = 0        # No access
    VIEWER = 1      # Can view basic info
    WORKER = 2      # Student workers - limited access
    MODERATOR = 3   # Moderators - moderation tools
    ADMIN = 4       # Admins - most features
    DIRECTOR = 5    # Directors - full access including settings
    OWNER = 6       # Server owner - everything

# Map role IDs to permission levels
# Update these with your actual Discord role IDs
ROLE_PERMISSIONS = {
    # Directors / Leadership
    "1234567890123456789": PermissionLevel.DIRECTOR,  # Replace with actual Director role ID
    "745068163313434716": PermissionLevel.ADMIN,       # Student role (example)
    
    # Moderators
    "MOD_ROLE_ID_HERE": PermissionLevel.MODERATOR,
    
    # Student Workers
    "WORKER_ROLE_ID_HERE": PermissionLevel.WORKER,
    
    # Default for server members
    "default_member": PermissionLevel.VIEWER,
}

# Specific user overrides (Discord user IDs)
USER_PERMISSION_OVERRIDES = {
    # "USER_ID": PermissionLevel.OWNER,  # Server owner
}

# ============ Feature Permissions ============
# What each permission level can access

FEATURE_PERMISSIONS = {
    # Dashboard sections
    "view_dashboard": PermissionLevel.VIEWER,
    "view_members": PermissionLevel.VIEWER,
    "view_analytics": PermissionLevel.WORKER,
    
    # Moderation
    "view_moderation": PermissionLevel.MODERATOR,
    "kick_users": PermissionLevel.MODERATOR,
    "ban_users": PermissionLevel.ADMIN,
    "timeout_users": PermissionLevel.MODERATOR,
    "manage_warnings": PermissionLevel.MODERATOR,
    
    # Tickets
    "view_tickets": PermissionLevel.WORKER,
    "close_tickets": PermissionLevel.WORKER,
    "manage_ticket_blacklist": PermissionLevel.MODERATOR,
    
    # Teams / Varsity
    "view_teams": PermissionLevel.VIEWER,
    "manage_teams": PermissionLevel.ADMIN,
    "manage_players": PermissionLevel.ADMIN,
    "send_varsity_registration": PermissionLevel.ADMIN,
    
    # Voice Channels
    "view_voice_channels": PermissionLevel.VIEWER,
    "manage_voice_channels": PermissionLevel.MODERATOR,
    
    # Worker On Duty
    "view_equipment": PermissionLevel.WORKER,
    "manage_equipment": PermissionLevel.MODERATOR,
    "manage_inventory": PermissionLevel.DIRECTOR,
    
    # Bot Control
    "view_bot_status": PermissionLevel.VIEWER,
    "restart_bot": PermissionLevel.DIRECTOR,
    "stop_bot": PermissionLevel.OWNER,
    
    # Settings
    "view_settings": PermissionLevel.ADMIN,
    "manage_settings": PermissionLevel.DIRECTOR,
    "manage_flagged_words": PermissionLevel.ADMIN,
    "manage_reaction_roles": PermissionLevel.ADMIN,
}

# ============ Helper Functions ============

def get_user_permission_level(user_data):
    """
    Calculate the highest permission level for a user based on their roles.
    
    Args:
        user_data: Dict containing user info including roles
        
    Returns:
        int: The highest PermissionLevel the user has
    """
    if not user_data:
        return PermissionLevel.NONE
    
    user_id = str(user_data.get('id', ''))
    
    # Check for user-specific override first
    if user_id in USER_PERMISSION_OVERRIDES:
        return USER_PERMISSION_OVERRIDES[user_id]
    
    # Check if user is guild owner
    if user_data.get('is_owner', False):
        return PermissionLevel.OWNER
    
    # Get highest permission from roles
    highest_level = PermissionLevel.NONE
    user_roles = user_data.get('roles', [])
    
    for role_id in user_roles:
        role_id_str = str(role_id)
        if role_id_str in ROLE_PERMISSIONS:
            level = ROLE_PERMISSIONS[role_id_str]
            if level > highest_level:
                highest_level = level
    
    # If user is a guild member but no specific role matched, give default member access
    if highest_level == PermissionLevel.NONE and user_data.get('is_member', False):
        highest_level = ROLE_PERMISSIONS.get('default_member', PermissionLevel.VIEWER)
    
    return highest_level

def has_permission(user_data, feature):
    """
    Check if a user has permission for a specific feature.
    
    Args:
        user_data: Dict containing user info
        feature: String name of the feature to check
        
    Returns:
        bool: True if user has permission
    """
    required_level = FEATURE_PERMISSIONS.get(feature, PermissionLevel.OWNER)
    user_level = get_user_permission_level(user_data)
    return user_level >= required_level

def get_user_features(user_data):
    """
    Get list of all features a user has access to.
    
    Args:
        user_data: Dict containing user info
        
    Returns:
        list: Feature names the user can access
    """
    user_level = get_user_permission_level(user_data)
    return [
        feature for feature, required_level in FEATURE_PERMISSIONS.items()
        if user_level >= required_level
    ]

# ============ Decorators ============

def oauth_login_required(f):
    """Decorator to require Discord OAuth login"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('discord_user'):
            return redirect(url_for('discord_login'))
        return f(*args, **kwargs)
    return decorated_function

def permission_required(feature):
    """Decorator to require specific permission for a route"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user_data = session.get('discord_user')
            if not user_data:
                return redirect(url_for('discord_login'))
            
            if not has_permission(user_data, feature):
                # For API endpoints, return JSON error
                if request.path.startswith('/api/'):
                    return jsonify({
                        "error": "Permission denied",
                        "required_feature": feature,
                        "message": "You don't have permission to access this feature."
                    }), 403
                # For pages, redirect to dashboard with error
                return redirect(url_for('dashboard', error='permission_denied'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def api_permission_required(feature):
    """Decorator for API endpoints requiring specific permission"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user_data = session.get('discord_user')
            
            # Also allow legacy security code auth for backwards compatibility
            auth_token = request.headers.get('Authorization')
            from utils.constants import SECURITY_CODE
            if auth_token == f"Bearer {SECURITY_CODE}":
                return f(*args, **kwargs)
            
            if not user_data:
                return jsonify({"error": "Not authenticated"}), 401
            
            if not has_permission(user_data, feature):
                return jsonify({
                    "error": "Permission denied",
                    "required_feature": feature
                }), 403
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# ============ Permission Level Names ============

PERMISSION_LEVEL_NAMES = {
    PermissionLevel.NONE: "No Access",
    PermissionLevel.VIEWER: "Viewer",
    PermissionLevel.WORKER: "Student Worker",
    PermissionLevel.MODERATOR: "Moderator",
    PermissionLevel.ADMIN: "Admin",
    PermissionLevel.DIRECTOR: "Director",
    PermissionLevel.OWNER: "Owner",
}

def get_permission_level_name(level):
    """Get human-readable name for permission level"""
    return PERMISSION_LEVEL_NAMES.get(level, "Unknown")
