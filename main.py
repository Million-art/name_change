import logging
import os
import asyncio
from pathlib import Path
from typing import Dict, Any, List
from telethon import TelegramClient, events, types, functions
from telethon.tl.types import User, PeerChannel, UpdateUserName, UpdateUserPhone, UpdateUser, UpdateUserStatus, UpdatePeerSettings, PeerUser
from telethon.errors import FloodWaitError
from dotenv import load_dotenv
import requests
from database import Database
from datetime import datetime
import time
import json
from aiohttp import web
import threading

# Configure logging first
logging.basicConfig(
    format='[%(levelname)s] %(asctime)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('name_tracker.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
logger.info(f"Loading environment from: {env_path}")
load_dotenv(env_path)

# Configuration
class Config:
    API_ID = int(os.getenv('API_ID', 0))
    API_HASH = os.getenv('API_HASH', '')
    BOT_TOKEN = os.getenv('BOT_TOKEN', '')
    ADMIN_ID = int(os.getenv('ADMIN_ID', 0))
    SESSION_NAME = 'name_change_bot'
    SCAN_INTERVAL = int(os.getenv('SCAN_INTERVAL', 300))  # Changed to 5 minutes (300 seconds)
    MONITORED_GROUPS = [int(x) for x in os.getenv('MONITORED_GROUPS', '').split(',') if x]

# Validate configuration
if not all([Config.API_ID, Config.API_HASH, Config.BOT_TOKEN, Config.ADMIN_ID]):
    logger.error("Missing required environment variables")
    logger.error(f"API_ID: {Config.API_ID}")
    logger.error(f"API_HASH: {'Set' if Config.API_HASH else 'Not Set'}")
    logger.error(f"BOT_TOKEN: {'Set' if Config.BOT_TOKEN else 'Not Set'}")
    logger.error(f"ADMIN_ID: {Config.ADMIN_ID}")
    raise ValueError("Missing required environment variables")

# Initialize client
logger.info(f"Initializing client with session name: {Config.SESSION_NAME}")
client = TelegramClient(
    Config.SESSION_NAME,
    Config.API_ID,
    Config.API_HASH,
    device_model="Name Change Bot",
    system_version="1.0",
    app_version="1.0",
    lang_code="en"
)

# Initialize database with consistent name
db = Database(db_name='name_change.db')  # Explicitly set database name

# Store monitored groups
monitored_groups: List[int] = Config.MONITORED_GROUPS

# Initialize web application for health checks
app = web.Application()
app.router.add_get('/health', lambda _: web.Response(text="OK"))

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

async def send_to_admin(message: str):
    """Send notification to admin"""
    try:
        formatted_message = (
            "🔔 Name Change Notification\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{message}\n"
            "━━━━━━━━━━━━━━━━━━━━━━"
        )
        await client.send_message(Config.ADMIN_ID, formatted_message)
        logger.info(f"Notification sent to admin: {message}")
    except Exception as e:
        logger.error(f"Error sending message to admin: {str(e)}")

async def check_name_changes(user: User):
    """Check for and report name changes"""
    try:
        if not user:
            return

        current_data = {
            'first_name': user.first_name,
            'last_name': user.last_name or "",
            'username': user.username or "",
            'phone': user.phone or ""
        }
        
        # Get user data from database
        db_user = db.get_user(user.id)
        
        # If user doesn't exist in database, register them
        if not db_user:
            db.register_user(
                user_id=user.id,
                first_name=user.first_name,
                last_name=user.last_name or "",
                username=user.username or "",
                phone=user.phone or ""
            )
            return
        
        changes = []
        
        # Check first name
        if db_user['first_name'] != current_data['first_name']:
            changes.append(f"👤 First name: {db_user['first_name']} → {current_data['first_name']}")
        
        # Check last name
        if db_user['last_name'] != current_data['last_name']:
            changes.append(f"👤 Last name: {db_user['last_name']} → {current_data['last_name']}")
        
        # Check username
        if db_user['username'] != current_data['username']:
            old_un = f"@{db_user['username']}" if db_user['username'] else "[no username]"
            new_un = f"@{current_data['username']}" if current_data['username'] else "[no username]"
            changes.append(f"🔗 Username: {old_un} → {new_un}")
        
        # Check phone number
        if db_user['phone'] != current_data['phone']:
            changes.append(f"📱 Phone: {db_user['phone']} → {current_data['phone']}")
        
        # Update database
        db.register_user(
            user_id=user.id,
            first_name=user.first_name,
            last_name=user.last_name or "",
            username=user.username or "",
            phone=user.phone or ""
        )
        
        # Report changes if any
        if changes:
            # Get user's groups for context
            user_groups = db.get_user_groups(user.id)
            group_names = [g['group_name'] for g in user_groups]
            
            message = (
                f"👤 User ID: `{user.id}`\n"
                f"🔗 Profile: https://t.me/{user.username or ''}\n"
                f"👥 Groups: {', '.join(group_names) if group_names else 'None'}\n\n"
                + "\n".join(changes)
            )
            await send_to_admin(message)
            logger.info(f"Sent name change notification for user {user.id}")
            
    except FloodWaitError as e:
        logger.warning(f"Flood wait required: {e.seconds} seconds")
        await asyncio.sleep(e.seconds)
        await check_name_changes(user)  # Retry after waiting
    except Exception as e:
        logger.error(f"Error checking name changes: {e}")

@client.on(events.ChatAction())
async def handle_group_events(event):
    """Handle group events where users might change names"""
    try:
        logger.debug(f"Received ChatAction event: {event.action_message}")
        # Get the actual group ID
        if isinstance(event.chat_id, PeerChannel):
            group_id = event.chat_id.channel_id
        else:
            group_id = event.chat_id
        
        logger.debug(f"Processing event for group ID: {group_id}")
        
        # Add group to monitored list if not already there
        if group_id not in monitored_groups:
            monitored_groups.append(group_id)
            logger.info(f"Added new group to monitoring: {group_id}")
            
            # Register group in database
            try:
                chat = await event.get_chat()
                group_name = getattr(chat, 'title', f'Group {group_id}')
                db.register_group(group_id, group_name)
            except Exception as e:
                logger.error(f"Error registering group {group_id}: {e}")
        
        if event.user_joined or event.user_added:
            logger.debug(f"User joined/added event detected")
            # New user - add to database
            user = await event.get_user()
            if user:
                logger.debug(f"Processing new user: {user.id}")
                db.register_user(
                    user_id=user.id,
                    first_name=user.first_name,
                    last_name=user.last_name or "",
                    username=user.username or "",
                    phone=user.phone or ""
                )
                # Add user to group in database
                db.add_user_to_group(user.id, group_id)
                logger.info(f"Added new user {user.id} to group {group_id}")
            return
        
        if hasattr(event, 'user_id') and event.user_id:
            logger.debug(f"Processing existing user event for user_id: {event.user_id}")
            # Existing user - check for changes
            user = await event.get_user()
            if user:
                await check_name_changes(user)
                # Update last seen in group
                db.add_user_to_group(user.id, group_id)
            
    except Exception as e:
        logger.error(f"Error in group event: {str(e)}", exc_info=True)  # Added exc_info for full traceback

@client.on(events.Raw(UpdateUserName))
async def handle_username_update(event):
    """Handle username changes specifically"""
    try:
        logger.debug(f"Received username update event: {event}")
        logger.info(f"Received username update for user {event.user_id}")
        user = await client.get_entity(event.user_id)
        if user:
            await check_name_changes(user)
            logger.info(f"Processed username update for user {user.id}")
    except Exception as e:
        logger.error(f"Error handling username update: {e}", exc_info=True)

@client.on(events.Raw(UpdateUserPhone))
async def handle_phone_update(event):
    """Handle phone number changes specifically"""
    try:
        logger.info(f"Received phone update for user {event.user_id}")
        user = await client.get_entity(event.user_id)
        if user:
            await check_name_changes(user)
            logger.info(f"Processed phone update for user {user.id}")
    except Exception as e:
        logger.error(f"Error handling phone update: {e}")

@client.on(events.Raw(UpdateUser))
async def handle_user_update(event):
    """Handle general user profile updates"""
    try:
        logger.debug(f"Received user update event: {event}")
        logger.info(f"Received user update for user {event.user_id}")
        user = await client.get_entity(event.user_id)
        if user:
            await check_name_changes(user)
            logger.info(f"Processed user update for user {user.id}")
    except Exception as e:
        logger.error(f"Error handling user update: {e}", exc_info=True)

@client.on(events.Raw(UpdateUserStatus))
async def handle_user_status_update(event):
    """Handle user status updates which might accompany name changes"""
    try:
        logger.info(f"Received user status update for user {event.user_id}")
        user = await client.get_entity(event.user_id)
        if user:
            await check_name_changes(user)
            logger.info(f"Processed user status update for user {user.id}")
    except Exception as e:
        logger.error(f"Error handling user status update: {e}")

@client.on(events.Raw(UpdatePeerSettings))
async def handle_peer_settings_update(event):
    """Handle peer settings updates which might accompany name changes"""
    try:
        if isinstance(event.peer, PeerUser):
            logger.info(f"Received peer settings update for user {event.peer.user_id}")
            user = await client.get_entity(event.peer.user_id)
            if user:
                await check_name_changes(user)
                logger.info(f"Processed peer settings update for user {user.id}")
    except Exception as e:
        logger.error(f"Error handling peer settings update: {e}")

@client.on(events.NewMessage(pattern='/start'))
async def start_command(event):
    """Initialize tracking in a group"""
    try:
        if not event.is_group:
            await event.reply("❌ This command can only be used in groups.")
            return

        # Get group information
        try:
            chat = await event.get_chat()
            
            # Get the actual group ID
            if isinstance(event.chat_id, PeerChannel):
                group_id = event.chat_id.channel_id
            else:
                group_id = event.chat_id
            
            group_name = getattr(chat, 'title', f'Group {group_id}')
            
            logger.info(f"Starting tracking for group: {group_name} ({group_id})")
            
            # Register the group in database
            if not db.register_group(group_id, group_name):
                logger.error(f"Failed to register group {group_name} ({group_id}) in database")
                await event.reply("❌ Error registering group in database. Please try again.")
                return
            
            # Add to monitored groups if not already there
            if group_id not in monitored_groups:
                monitored_groups.append(group_id)
                logger.info(f"Added group to monitoring: {group_name} ({group_id})")
            
            # Load all current group members into database
            count = 0
            errors = 0
            try:
                async for user in client.iter_participants(chat):
                    if isinstance(user, User):
                        try:
                            db.register_user(
                                user_id=user.id,
                                first_name=user.first_name,
                                last_name=user.last_name or "",
                                username=user.username or "",
                                phone=user.phone or ""
                            )
                            db.add_user_to_group(user.id, group_id)
                            count += 1
                            if count % 10 == 0:  # Log progress every 10 users
                                logger.info(f"Processed {count} users in group {group_name}")
                        except Exception as e:
                            errors += 1
                            logger.error(f"Error processing user {user.id} in group {group_name}: {e}")
            except Exception as e:
                logger.error(f"Error processing users in group {group_name}: {str(e)}")
                await event.reply("⚠️ Warning: Some users could not be processed. Tracking is still active.")
            
            logger.info(f"Successfully initialized tracking in group {group_name} ({group_id}), added {count} users")
            
            # Send confirmation with group details
            status_msg = [
                f"✅ Name tracking activated!",
                f"Group: {group_name}",
                f"ID: {group_id}",
                f"Added {count} users to tracking."
            ]
            if errors > 0:
                status_msg.append(f"⚠️ {errors} users could not be processed.")
            status_msg.append("I'll report name changes to the admin.")
            
            await event.reply("\n".join(status_msg))
            
        except Exception as e:
            logger.error(f"Error getting group information: {str(e)}")
            await event.reply("❌ Error getting group information. Please try again.")
            
    except Exception as e:
        logger.error(f"Error in start command: {str(e)}")
        await event.reply("❌ An unexpected error occurred. Please try again.")

@client.on(events.NewMessage(pattern='/status'))
async def status_command(event):
    """Report current tracking status"""
    try:
        users = db.get_all_users()
        total_groups = len(set(group['group_id'] for user in users for group in user.get('groups', [])))
        
        # Get group names for monitored groups
        monitored_groups_info = []
        for group_id in monitored_groups:
            try:
                chat = await client.get_entity(group_id)
                group_name = getattr(chat, 'title', f'Group {group_id}')
                monitored_groups_info.append(f"• {group_name}")
            except Exception as e:
                logger.error(f"Error getting group info for {group_id}: {e}")
                monitored_groups_info.append(f"• Group {group_id}")
        
        status_msg = [
            "📊 Status",
            f"👤 Users: {len(users)}",
            f"👥 Groups: {len(monitored_groups)}",
            "",
            "🎯 Monitored:"
        ]
        
        if monitored_groups_info:
            status_msg.extend(monitored_groups_info)
        else:
            status_msg.append("No groups monitored")
            
        status_msg.append(f"\n⏱️ Next scan: {Config.SCAN_INTERVAL//60}m")
        
        await event.reply("\n".join(status_msg))
    except Exception as e:
        logger.error(f"Error in status command: {str(e)}")

@client.on(events.NewMessage(pattern='/scan'))
async def manual_scan_command(event):
    """Trigger immediate scan of all groups"""
    try:
        if event.sender_id == Config.ADMIN_ID:
            await event.reply("🔄 Starting manual scan of all monitored groups...")
            for group_id in monitored_groups:
                try:
                    count = 0
                    async for user in client.iter_participants(group_id):
                        if isinstance(user, User):
                            await check_name_changes(user)
                            count += 1
                    logger.info(f"Scanned {count} users in group {group_id}")
                except Exception as e:
                    logger.error(f"Error scanning group {group_id}: {str(e)}")
            await event.reply("✅ Manual scan completed!")
        else:
            await event.reply("⛔ Only admin can trigger manual scans")
    except Exception as e:
        logger.error(f"Error in scan command: {str(e)}")

@client.on(events.NewMessage(pattern='/export'))
async def export_command(event):
    """Export name changes to JSON file"""
    try:
        if event.sender_id == Config.ADMIN_ID:
            await event.reply("🔄 Preparing name changes export...")
            
            filename = f"name_changes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            if db.export_to_json(filename):
                # Get the total number of changes
                with open(filename, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    total_changes = data['total_changes']
                
                await client.send_file(
                    Config.ADMIN_ID,
                    filename,
                    caption=(
                        f"📊 Name Changes Export\n"
                        f"Total Changes: {total_changes}\n"
                        f"Export Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                )
                os.remove(filename)  # Clean up the file after sending
            else:
                await event.reply("❌ Error exporting name changes")
        else:
            await event.reply("⛔ Only admin can request exports")
    except Exception as e:
        logger.error(f"Error in export command: {str(e)}")
        await event.reply("❌ An error occurred while exporting data")

async def start_web_server():
    """Start web server for health checks"""
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.getenv('PORT', 8080)))
    await site.start()
    logger.info("Health check server started")

async def main():
    """Main bot function"""
    try:
        # Start health check server
        await start_web_server()
        
        # Connect and start
        logger.info("Connecting to Telegram...")
        await client.connect()
        
        # Check if we need to sign in
        if not await client.is_user_authorized():
            logger.info("Not authorized, signing in with bot token...")
            await client.sign_in(bot_token=Config.BOT_TOKEN)
            logger.info("Successfully signed in")
        
        # Ensure we're receiving updates
        me = await client.get_me()
        logger.info(f"Connected as {me.username}")
        
        # Set up update receiving with more detailed logging
        try:
            state = await client(functions.updates.GetStateRequest())
            logger.info(f"Successfully set up update receiving. State: {state}")
        except Exception as e:
            logger.error(f"Could not get update state: {e}", exc_info=True)
        
        # Start background tasks
        asyncio.create_task(periodic_scan())
        
        # Initialize monitored groups from database
        users = db.get_all_users()
        if users:
            # Get all unique group IDs from the database
            db_groups = set()
            for user in users:
                for group in user.get('groups', []):
                    db_groups.add(group['group_id'])
            
            # Add any groups from database that aren't in monitored_groups
            for group_id in db_groups:
                if group_id not in monitored_groups:
                    monitored_groups.append(group_id)
                    try:
                        chat = await client.get_entity(group_id)
                        group_name = getattr(chat, 'title', f'Group {group_id}')
                        db.register_group(group_id, group_name)
                        logger.info(f"Added existing group {group_name} ({group_id}) to monitoring")
                    except Exception as e:
                        logger.error(f"Error getting group info for {group_id}: {e}", exc_info=True)
        
        # Send startup message with current status
        users = db.get_all_users()
        total_groups = len(set(group['group_id'] for user in users for group in user.get('groups', [])))
        await client.send_message(
            Config.ADMIN_ID,
            f"🔔 Name Tracker Bot started!\n"
            f"Tracking {len(users)} users\n"
            f"Monitoring {len(monitored_groups)} groups\n"
            f"Groups in database: {total_groups}"
        )
        logger.info("Bot started and ready to track name changes!")
        
        # Keep the bot running
        await client.run_until_disconnected()
    except Exception as e:
        logger.error(f"Fatal error in main: {str(e)}", exc_info=True)
        raise

if __name__ == '__main__':
    with client:
        client.loop.run_until_complete(main())