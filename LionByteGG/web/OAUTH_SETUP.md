# Discord OAuth2 Setup Guide for LionByteGG Dashboard

This guide will help you set up Discord OAuth2 authentication for the dashboard.

## Step 1: Create a Discord Application

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Click **"New Application"** 
3. Name it something like "LionByteGG Dashboard"
4. Click **Create**

## Step 2: Get Your Credentials

1. In your application, go to **OAuth2** > **General**
2. Copy your **Client ID** 
3. Click **Reset Secret** and copy your **Client Secret** (save this securely!)

## Step 3: Set Up Redirect URI

1. In **OAuth2** > **General**, scroll to **Redirects**
2. Add your redirect URI:
   - For local development: `http://localhost:5000/auth/callback`
   - For production: `https://yourdomain.com/auth/callback`

## Step 4: Enable Required Bot Permissions

The bot token is needed to fetch member roles. Make sure your bot has:
- `SERVER MEMBERS INTENT` enabled in **Bot** settings
- Permission to read member info

## Step 5: Configure Environment Variables

Create a `.env` file or set these environment variables:

```bash
# Discord OAuth2 Credentials
DISCORD_CLIENT_ID=your_client_id_here
DISCORD_CLIENT_SECRET=your_client_secret_here
DISCORD_REDIRECT_URI=http://localhost:5000/auth/callback

# Your bot token (same as what runs the bot)
DISCORD_BOT_TOKEN=your_bot_token_here

# Flask secret key (generate a random one)
FLASK_SECRET_KEY=your_random_secret_key
```

Or edit `web/oauth_config.py` directly with your values.

## Step 6: Configure Role Permissions

Edit `web/oauth_config.py` and update the `ROLE_PERMISSIONS` dictionary with your actual Discord role IDs:

```python
ROLE_PERMISSIONS = {
    # Directors / Leadership - Full access
    "YOUR_DIRECTOR_ROLE_ID": PermissionLevel.DIRECTOR,
    
    # Admins - Most features
    "YOUR_ADMIN_ROLE_ID": PermissionLevel.ADMIN,
    
    # Moderators - Moderation tools
    "YOUR_MOD_ROLE_ID": PermissionLevel.MODERATOR,
    
    # Student Workers - Limited access
    "YOUR_WORKER_ROLE_ID": PermissionLevel.WORKER,
    
    # Default for any server member
    "default_member": PermissionLevel.VIEWER,
}
```

### How to Get Role IDs

1. Enable Developer Mode in Discord (User Settings > Advanced > Developer Mode)
2. Right-click a role and select "Copy ID"

## Permission Levels

| Level | Name | Description |
|-------|------|-------------|
| 6 | Owner | Server owner - Full access to everything |
| 5 | Director | Full access including bot control and settings |
| 4 | Admin | Most features except critical bot control |
| 3 | Moderator | Moderation tools, ticket management |
| 2 | Worker | View access, basic ticket handling |
| 1 | Viewer | Read-only access to basic info |
| 0 | None | No dashboard access |

## Feature Permissions

You can customize which permission level is required for each feature in `FEATURE_PERMISSIONS`:

```python
FEATURE_PERMISSIONS = {
    # Dashboard sections
    "view_dashboard": PermissionLevel.VIEWER,
    "view_members": PermissionLevel.VIEWER,
    
    # Moderation
    "kick_users": PermissionLevel.MODERATOR,
    "ban_users": PermissionLevel.ADMIN,
    
    # Bot Control
    "restart_bot": PermissionLevel.DIRECTOR,
    "stop_bot": PermissionLevel.OWNER,
    
    # ... etc
}
```

## Testing

1. Start the dashboard: `python web/app.py`
2. Go to `http://localhost:5000/login`
3. Click **"Login with Discord"**
4. Authorize the application
5. You should be redirected to the dashboard with your Discord avatar visible

## Troubleshooting

### "You must be a member of the server"
- Make sure the user is in your Discord server
- Check that `GUILD_ID` is set correctly in `utils/constants.py`

### "Your Discord roles do not grant dashboard access"
- The user doesn't have any roles mapped in `ROLE_PERMISSIONS`
- Add their role ID to the config or set `default_member` permission

### "Failed to authenticate with Discord"
- Check your Client ID and Secret are correct
- Verify the redirect URI matches exactly (including trailing slashes)

### Roles not loading correctly
- Make sure your bot token is valid
- Ensure the bot has the SERVER MEMBERS INTENT enabled
- The bot must be in the same server as the user

## Security Notes

- Never commit your `.env` file or expose secrets in code
- Use HTTPS in production
- The legacy security code login is still available as a backup
- Legacy login grants full owner-level permissions
