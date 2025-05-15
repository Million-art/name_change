import logging
import os
import asyncio
from typing import Dict, Any, List
from telethon import TelegramClient, events, types
from telethon.tl.types import User, UpdateUserName, PeerChannel
from dotenv import load_dotenv
import requests

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='[%(levelname)s] %(asctime)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('name_tracker.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Configuration
class Config:
    API_ID = int(os.getenv('API_ID', 0))
    API_HASH = os.getenv('API_HASH', '')
    BOT_TOKEN = os.getenv('BOT_TOKEN', '')
    ADMIN_ID = int(os.getenv('ADMIN_ID', 0))
    SESSION_NAME = os.getenv('SESSION_NAME', 'name_tracker_bot')
    MAX_CACHE_SIZE = int(os.getenv('MAX_CACHE_SIZE', 10000))
    KEEP_ALIVE_URL = os.getenv('KEEP_ALIVE_URL', '')
    PING_INTERVAL = int(os.getenv('PING_INTERVAL', 300))  # 5 minutes
    SCAN_INTERVAL = int(os.getenv('SCAN_INTERVAL', 3600))  # 1 hour
    MONITORED_GROUPS = [int(x) for x in os.getenv('MONITORED_GROUPS', '').split(',') if x]

# Validate configuration
if not all([Config.API_ID, Config.API_HASH, Config.BOT_TOKEN, Config.ADMIN_ID]):
    logger.error("Missing required environment variables")
    raise ValueError("Missing required environment variables")

# Initialize client
client = TelegramClient(Config.SESSION_NAME, Config.API_ID, Config.API_HASH)

# Store previous user data with LRU cache behavior
user_cache: Dict[int, Dict[str, Any]] = {}
# Store monitored groups
monitored_groups: List[int] = Config.MONITORED_GROUPS

async def keep_alive():
    """Ping keep-alive URL to prevent Render from sleeping"""
    while True:
        try:
            if Config.KEEP_ALIVE_URL:
                response = requests.get(Config.KEEP_ALIVE_URL)
                logger.info(f"Keep-alive ping sent. Status: {response.status_code}")
        except Exception as e:
            logger.error(f"Keep-alive ping failed: {str(e)}")
        await asyncio.sleep(Config.PING_INTERVAL)

async def periodic_scan():
    """Periodically scan all monitored groups for name changes"""
    while True:
        try:
            logger.info("Starting periodic scan of monitored groups")
            for group_id in monitored_groups:
                try:
                    async for user in client.iter_participants(group_id):
                        if isinstance(user, User):
                            await check_name_changes(user)
                except Exception as e:
                    logger.error(f"Error scanning group {group_id}: {str(e)}")
        except Exception as e:
            logger.error(f"Error in periodic scan: {str(e)}")
        await asyncio.sleep(Config.SCAN_INTERVAL)

async def cleanup_cache():
    """Clean up cache if it grows too large"""
    if len(user_cache) > Config.MAX_CACHE_SIZE:
        # Remove oldest entries (simplified LRU)
        for user_id in list(user_cache.keys())[:Config.MAX_CACHE_SIZE // 2]:
            user_cache.pop(user_id, None)
        logger.info(f"Cleaned up cache. New size: {len(user_cache)}")

async def send_to_admin(message: str):
    """Send notification to admin with error handling"""
    try:
        await client.send_message(Config.ADMIN_ID, message)
        logger.info(f"Notification sent to admin: {message}")
    except Exception as e:
        logger.error(f"Failed to send to admin: {str(e)}")

async def update_user_cache(user: User):
    """Update cache with current user data"""
    try:
        user_cache[user.id] = {
            'first_name': user.first_name,
            'last_name': user.last_name or "",
            'username': user.username or "",
            'phone': user.phone or "",
            'last_checked': asyncio.get_event_loop().time()
        }
        await cleanup_cache()
    except Exception as e:
        logger.error(f"Error updating user cache: {str(e)}")

async def check_name_changes(user: User):
    """Check for and report name changes"""
    try:
        current_data = {
            'first_name': user.first_name,
            'last_name': user.last_name or "",
            'username': user.username or "",
            'phone': user.phone or ""
        }
        
        old_data = user_cache.get(user.id, {})
        changes = []
        
        # Check first name
        if 'first_name' in old_data and old_data['first_name'] != current_data['first_name']:
            changes.append(f"First name: {old_data['first_name']} → {current_data['first_name']}")
        
        # Check last name
        if 'last_name' in old_data and old_data['last_name'] != current_data['last_name']:
            changes.append(f"Last name: {old_data['last_name']} → {current_data['last_name']}")
        
        # Check username
        if 'username' in old_data and old_data['username'] != current_data['username']:
            old_un = f"@{old_data['username']}" if old_data['username'] else "[no username]"
            new_un = f"@{current_data['username']}" if current_data['username'] else "[no username]"
            changes.append(f"Username: {old_un} → {new_un}")
        
        # Check phone number (if available)
        if 'phone' in old_data and old_data['phone'] != current_data['phone']:
            changes.append(f"Phone: {old_data['phone']} → {current_data['phone']}")
        
        # Update cache
        await update_user_cache(user)
        
        # Report changes if any
        if changes:
            message = (
                f"🔄 Name change detected!\n"
                f"User ID: `{user.id}`\n"
                f"Profile: https://t.me/{user.username or ''}\n"
                + "\n".join(changes)
            )
            await send_to_admin(message)
    except Exception as e:
        logger.error(f"Error checking name changes: {str(e)}")

@client.on(events.ChatAction())
async def handle_group_events(event):
    """Handle group events where users might change names"""
    try:
        # Add group to monitored list if not already there
        if isinstance(event.chat_id, PeerChannel) and event.chat_id.channel_id not in monitored_groups:
            monitored_groups.append(event.chat_id.channel_id)
        
        if event.user_joined or event.user_added:
            # New user - add to cache
            user = await event.get_user()
            await update_user_cache(user)
            return
        
        if hasattr(event, 'user_id') and event.user_id:
            # Existing user - check for changes
            user = await event.get_user()
            await check_name_changes(user)
            
    except Exception as e:
        logger.error(f"Error in group event: {str(e)}")

@client.on(events.Raw(UpdateUserName))
async def handle_username_update(event):
    """Specifically handle username changes"""
    try:
        user = await client.get_entity(event.user_id)
        await check_name_changes(user)
    except Exception as e:
        logger.error(f"Error in username update: {str(e)}")

@client.on(events.NewMessage(pattern='/start'))
async def start_command(event):
    """Initialize tracking in a group"""
    try:
        if event.is_group:
            # Add group to monitored list
            if isinstance(event.chat_id, PeerChannel):
                if event.chat_id.channel_id not in monitored_groups:
                    monitored_groups.append(event.chat_id.channel_id)
            
            await event.reply("✅ Name tracking activated! I'll report name changes to the admin.")
            
            # Load all current group members into cache
            async for user in client.iter_participants(event.chat_id):
                if isinstance(user, User):
                    await update_user_cache(user)
            
            logger.info(f"Initialized tracking in group {event.chat_id}")
    except Exception as e:
        logger.error(f"Error in start command: {str(e)}")

@client.on(events.NewMessage(pattern='/status'))
async def status_command(event):
    """Report current tracking status"""
    try:
        status_msg = [
            f"📊 Currently tracking {len(user_cache)} users",
            f"👥 Monitoring {len(monitored_groups)} groups",
            f"Next scan in {Config.SCAN_INTERVAL//60} minutes"
        ]
        await event.reply("\n".join(status_msg))
    except Exception as e:
        logger.error(f"Error in status command: {str(e)}")

@client.on(events.NewMessage(pattern='/scan'))
async def manual_scan_command(event):
    """Trigger immediate scan of all groups"""
    try:
        if event.sender_id == Config.ADMIN_ID:
            await event.reply("🔄 Starting manual scan of all monitored groups...")
            asyncio.create_task(periodic_scan(immediate=True))
        else:
            await event.reply("⛔ Only admin can trigger manual scans")
    except Exception as e:
        logger.error(f"Error in scan command: {str(e)}")

@client.on(events.NewMessage(pattern='/help'))
async def help_command(event):
    """Show help message"""
    try:
        help_text = """
        🤖 Name Tracker Bot Help
        
        Commands:
        /start - Initialize tracking in current group
        /status - Show current tracking statistics
        /scan - Manually scan all groups (admin only)
        /help - Show this help message
        
        The bot will automatically detect and report:
        - First name changes
        - Last name changes
        - Username changes
        - Phone number changes
        
        Periodic scans run every hour.
        """
        await event.reply(help_text)
    except Exception as e:
        logger.error(f"Error in help command: {str(e)}")

async def main():
    """Main bot function"""
    try:
        await client.start(bot_token=Config.BOT_TOKEN)
        
        # Start background tasks
        asyncio.create_task(keep_alive())
        asyncio.create_task(periodic_scan())
        
        await client.send_message(Config.ADMIN_ID, "🔔 Name Tracker Bot started and running!")
        logger.info("Bot started and ready to track name changes!")
        
        # Initial scan of monitored groups
        if monitored_groups:
            logger.info(f"Performing initial scan of {len(monitored_groups)} groups")
            for group_id in monitored_groups:
                try:
                    async for user in client.iter_participants(group_id):
                        if isinstance(user, User):
                            await update_user_cache(user)
                except Exception as e:
                    logger.error(f"Error in initial scan of group {group_id}: {str(e)}")
        
        await client.run_until_disconnected()
    except Exception as e:
        logger.error(f"Fatal error in main: {str(e)}")
        raise

if __name__ == '__main__':
    with client:
        client.loop.run_until_complete(main())