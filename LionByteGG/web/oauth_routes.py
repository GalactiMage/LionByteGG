"""
Discord OAuth2 Authentication Routes for LionByteGG Dashboard
"""
import requests
from flask import Blueprint, redirect, request, session, url_for, jsonify
from urllib.parse import urlencode
import os

from .oauth_config import (
    DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, DISCORD_REDIRECT_URI,
    DISCORD_BOT_TOKEN, GUILD_ID, DISCORD_API_BASE, DISCORD_AUTH_URL,
    DISCORD_TOKEN_URL, OAUTH_SCOPES, get_user_permission_level,
    get_user_features, get_permission_level_name, PermissionLevel
)

# Create blueprint for OAuth routes
oauth_bp = Blueprint('oauth', __name__)

def get_oauth_url(state=None):
    """Generate Discord OAuth2 authorization URL"""
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
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    
    response = requests.post(DISCORD_TOKEN_URL, data=data, headers=headers)
    
    if response.status_code != 200:
        print(f"[OAUTH] Token exchange failed: {response.status_code} - {response.text}")
        return None
    
    return response.json()

def get_discord_user(access_token):
    """Fetch user information from Discord API"""
    headers = {
        'Authorization': f'Bearer {access_token}'
    }
    
    response = requests.get(f"{DISCORD_API_BASE}/users/@me", headers=headers)
    
    if response.status_code != 200:
        print(f"[OAUTH] Failed to fetch user: {response.status_code}")
        return None
    
    return response.json()

def get_guild_member(user_id):
    """Fetch guild member data using bot token to get roles"""
    if not DISCORD_BOT_TOKEN or DISCORD_BOT_TOKEN == 'YOUR_BOT_TOKEN_HERE':
        print("[OAUTH] Bot token not configured, cannot fetch member roles")
        return None
    
    headers = {
        'Authorization': f'Bot {DISCORD_BOT_TOKEN}'
    }
    
    response = requests.get(
        f"{DISCORD_API_BASE}/guilds/{GUILD_ID}/members/{user_id}",
        headers=headers
    )
    
    if response.status_code != 200:
        print(f"[OAUTH] Failed to fetch guild member: {response.status_code}")
        return None
    
    return response.json()

def get_guild_info():
    """Fetch guild info to check owner"""
    if not DISCORD_BOT_TOKEN or DISCORD_BOT_TOKEN == 'YOUR_BOT_TOKEN_HERE':
        return None
    
    headers = {
        'Authorization': f'Bot {DISCORD_BOT_TOKEN}'
    }
    
    response = requests.get(
        f"{DISCORD_API_BASE}/guilds/{GUILD_ID}",
        headers=headers
    )
    
    if response.status_code != 200:
        return None
    
    return response.json()

# ============ OAuth Routes ============

@oauth_bp.route('/auth/discord')
def discord_login():
    """Initiate Discord OAuth2 login flow"""
    # Generate state for CSRF protection
    import secrets
    state = secrets.token_urlsafe(32)
    session['oauth_state'] = state
    
    return redirect(get_oauth_url(state))

@oauth_bp.route('/auth/callback')
def discord_callback():
    """Handle Discord OAuth2 callback"""
    # Verify state for CSRF protection
    state = request.args.get('state')
    stored_state = session.pop('oauth_state', None)
    
    if state != stored_state:
        return redirect(url_for('login', error='Invalid state parameter'))
    
    # Check for errors
    error = request.args.get('error')
    if error:
        error_desc = request.args.get('error_description', 'Unknown error')
        print(f"[OAUTH] Authorization error: {error} - {error_desc}")
        return redirect(url_for('login', error='discord_auth_failed'))
    
    # Get authorization code
    code = request.args.get('code')
    if not code:
        return redirect(url_for('login', error='No authorization code'))
    
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
    
    # Check if user is in the guild
    is_member = member_info is not None
    
    if not is_member:
        # User is not a member of the server
        return redirect(url_for('login', error='not_server_member'))
    
    # Get guild info to check for owner
    guild_info = get_guild_info()
    is_owner = guild_info and str(guild_info.get('owner_id')) == str(user_id)
    
    # Build user data for session
    avatar_hash = user_info.get('avatar')
    if avatar_hash:
        avatar_ext = 'gif' if avatar_hash.startswith('a_') else 'png'
        avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.{avatar_ext}?size=256"
    else:
        # Default avatar
        discriminator = int(user_info.get('discriminator', '0'))
        avatar_url = f"https://cdn.discordapp.com/embed/avatars/{discriminator % 5}.png"
    
    user_data = {
        'id': user_id,
        'username': user_info.get('username'),
        'global_name': user_info.get('global_name'),
        'discriminator': user_info.get('discriminator'),
        'avatar': avatar_hash,
        'avatar_url': avatar_url,
        'email': user_info.get('email'),
        'roles': member_info.get('roles', []) if member_info else [],
        'nick': member_info.get('nick') if member_info else None,
        'joined_at': member_info.get('joined_at') if member_info else None,
        'is_member': is_member,
        'is_owner': is_owner,
        'access_token': access_token,
        'refresh_token': refresh_token,
    }
    
    # Calculate permission level
    permission_level = get_user_permission_level(user_data)
    user_data['permission_level'] = permission_level
    user_data['permission_name'] = get_permission_level_name(permission_level)
    user_data['features'] = get_user_features(user_data)
    
    # Check if user has any access at all
    if permission_level < PermissionLevel.VIEWER:
        return redirect(url_for('login', error='no_dashboard_access'))
    
    # Store in session
    session['discord_user'] = user_data
    session['authenticated'] = True  # For backwards compatibility
    session['user_name'] = user_data.get('global_name') or user_data.get('username')
    
    print(f"[OAUTH] User {user_data['username']} logged in with permission level: {user_data['permission_name']}")
    
    return redirect(url_for('dashboard'))

@oauth_bp.route('/auth/logout')
def discord_logout():
    """Log out the user"""
    user = session.get('discord_user')
    if user:
        print(f"[OAUTH] User {user.get('username')} logged out")
    
    session.clear()
    return redirect(url_for('login'))

@oauth_bp.route('/api/auth/user')
def get_current_user():
    """API endpoint to get current logged-in user info"""
    user_data = session.get('discord_user')
    
    if not user_data:
        return jsonify({'authenticated': False}), 401
    
    # Don't expose tokens
    safe_user_data = {k: v for k, v in user_data.items() 
                      if k not in ['access_token', 'refresh_token']}
    
    return jsonify({
        'authenticated': True,
        'user': safe_user_data
    })

@oauth_bp.route('/api/auth/permissions')
def get_user_permissions():
    """API endpoint to get current user's permissions"""
    user_data = session.get('discord_user')
    
    if not user_data:
        return jsonify({'authenticated': False}), 401
    
    return jsonify({
        'permission_level': user_data.get('permission_level', 0),
        'permission_name': user_data.get('permission_name', 'None'),
        'features': user_data.get('features', []),
        'is_owner': user_data.get('is_owner', False),
        'is_member': user_data.get('is_member', False),
    })

@oauth_bp.route('/api/auth/check-feature/<feature>')
def check_feature_permission(feature):
    """API endpoint to check if user has permission for a feature"""
    from .oauth_config import has_permission
    
    user_data = session.get('discord_user')
    
    if not user_data:
        return jsonify({'has_permission': False, 'authenticated': False}), 401
    
    return jsonify({
        'has_permission': has_permission(user_data, feature),
        'feature': feature
    })

# ============ Refresh Token Logic ============

def refresh_access_token(refresh_token):
    """Refresh the access token using refresh token"""
    data = {
        'client_id': DISCORD_CLIENT_ID,
        'client_secret': DISCORD_CLIENT_SECRET,
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token,
    }
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    
    response = requests.post(DISCORD_TOKEN_URL, data=data, headers=headers)
    
    if response.status_code != 200:
        print(f"[OAUTH] Token refresh failed: {response.status_code}")
        return None
    
    return response.json()
