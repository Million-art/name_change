# Telegram Name Change Tracking Bot 🤖

A powerful Telegram bot that monitors and tracks name changes of users in specified groups. Get instant notifications when users change their names, usernames 

## Features ✨

- 🔍 Real-time name change monitoring
- 👥 Multi-group support
- 📊 Historical change tracking
- 🔔 Instant admin notifications
- 🛡️ Flood control protection
- 💾 SQLite database for reliable storage
- 🔄 Automatic new user detection
- 👤 Username change tracking

## Setup Instructions 🚀

### Prerequisites
- Python 3.7 or higher
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))
- Telegram API ID and API Hash (from [my.telegram.org](https://my.telegram.org))

### Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd name_change
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create a `.env` file with the following variables:
```env
# Required Variables
API_ID=your_api_id
API_HASH=your_api_hash
BOT_TOKEN=your_bot_token
ADMIN_ID=your_telegram_id

# Optional Variables
SCAN_INTERVAL=60  # Default: 60 seconds
MONITORED_GROUPS=group_id1,group_id2  # Optional: Groups to monitor at startup
RENDER_HEALTH_CHECK=true  # Optional: Required only if deploying on Render.com
```

Note: Only the first four variables (API_ID, API_HASH, BOT_TOKEN, ADMIN_ID) are required. The bot will work without the optional variables, but you may want to configure them based on your needs.

### Running the Bot

1. Start the bot:
```bash
python main.py
```

2. Add the bot to your groups
3. Send `/start` in the group to begin monitoring

## Usage Guide 📖

### Commands

- `/start` - Initialize tracking in a group
- `/status` - Check bot status and monitored groups
- `/scan` - Trigger immediate scan of all groups (admin only)

### Admin Features

- Receive notifications for all name changes
- Monitor multiple groups simultaneously
- Access to detailed change history
- Manual scan capability

### Group Management

1. Add the bot to your group
2. Make the bot an admin (recommended)
3. Send `/start` to begin monitoring
4. The bot will automatically:
   - Register all current members
   - Start monitoring for changes
   - Track new members as they join

## Notifications 📬

The bot sends notifications for:
- First name changes
- Last name changes
- Username changes
- Phone number changes

Format:
```
🔔 Name Change Notification
━━━━━━━━━━━━━━━━━━━━━━
👤 User ID: `123456789`
👥 Groups: Group Name 1, Group Name 2
👤 First name: Old Name → New Name
━━━━━━━━━━━━━━━━━━━━━━
```

## Database Structure 💾

The bot uses SQLite with the following tables:
- `users` - User information
- `groups` - Group information
- `user_groups` - User-group relationships
- `name_changes` - Change history

## Security 🔒

- Environment variable based configuration
- Admin-only access to sensitive commands
- Secure database storage

## Deployment 🚀

The bot is configured for deployment on Render.com:
1. Fork the repository
2. Connect to Render
3. Set environment variables
4. Deploy


Made By millionmulugeta09@gmail.com 