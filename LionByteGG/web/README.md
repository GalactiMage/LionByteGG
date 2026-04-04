# LionByteGG Web Dashboard

A comprehensive web dashboard for managing the PNW Esports Discord bot and services.

## 🚀 Quick Start (For University Staff)

### Development Mode
Double-click `start_website.bat` in the parent folder to start the dashboard.

### Production Mode (Recommended for Daily Use)
Double-click `start_website_production.bat` for a more stable server.

## 📁 Access URLs

Once running, access the dashboard at:
- **Local**: http://localhost:5000
- **LAN**: http://[YOUR-IP]:5000 (shown in terminal)

Share the LAN URL with other staff on the same network!

## 🔐 Authentication

### Discord OAuth2 (Recommended)
Click "Login with Discord" to authenticate with your Discord account. Your dashboard permissions are based on your server roles.

### Legacy Login
Enter the security code to access the dashboard with full permissions.

## ✨ Features

### Dashboard Overview
- Bot status and statistics
- Server member counts
- Moderation activity summary
- Quick access to all features

### Moderation
- View and manage warnings, kicks, and bans
- User lookup and profiles
- Flagged word management
- Moderation templates

### Ticket System
- View open/closed tickets
- Send messages to ticket channels
- Close tickets from dashboard
- User blacklist management

### Shift Management (LionShiftGG)
- View and manage worker schedules
- Shift offers and trades
- Time-off requests
- Analytics and reporting

### Voice Channel System
- Manage voice channel generators
- View active voice channels
- Configuration options

### Varsity/Teams
- Player roster management
- Team creation and editing
- Registration review
- Match history tracking

### GGLeap Integration
- Live PC availability status
- Arena hours management
- Game catalog viewing

### Music Bot Dashboard (LionBeatsGG)
- Now playing status
- Playback controls
- Queue management
- Music statistics

## 🛠 Technical Setup

### Requirements
- Python 3.10+
- pip (Python package manager)

### Manual Installation
```bash
cd web
pip install -r requirements.txt
python run.py
```

### Production Deployment
```bash
cd web
pip install -r requirements.txt
python run.py --production
```

### Environment Variables (Optional)
Copy `.env.example` to `.env` and configure:
```
FLASK_ENV=production
FLASK_SECRET_KEY=your-secret-key
DISCORD_CLIENT_ID=your-client-id
DISCORD_CLIENT_SECRET=your-client-secret
DISCORD_BOT_TOKEN=your-bot-token
```

## 🔧 Configuration

### Discord OAuth2 Setup
1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create/select your application
3. Go to OAuth2 section
4. Add redirect URI: `http://localhost:5000/auth/callback`
5. Copy Client ID and Client Secret to `oauth_config.py`

### Role Permissions
Edit `oauth_config.py` to map Discord roles to dashboard permission levels.

## 📊 API Endpoints

### Health Check
```
GET /health
```
Returns server health status.

### Bot Status
```
GET /api/stats
```
Returns bot statistics and status.

### Members
```
GET /api/members
```
Returns cached member list.

## 🔒 Security Features

- Session-based authentication
- CSRF protection via SameSite cookies
- HTTP-only session cookies
- XSS protection headers
- Rate limiting ready
- Input validation on all endpoints
- Activity logging

## 📝 Troubleshooting

### "Python not found"
Install Python 3.10+ from https://python.org and add to PATH.

### "Module not found"
Run `pip install -r requirements.txt` in the web folder.

### "Port already in use"
Another service is using port 5000. Stop it or change the port:
```bash
python run.py --port 5001
```

### Discord OAuth not working
1. Check Client ID and Secret in `oauth_config.py`
2. Verify redirect URI matches exactly
3. Ensure bot token is valid

## 📞 Support

For issues or questions, contact the PNW Esports tech team or open an issue on the repository.

---

Built with ❤️ for PNW Esports
