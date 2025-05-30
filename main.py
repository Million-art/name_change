import logging
import os
import asyncio
from pathlib import Path
from typing import Dict, Any, List
from telethon import TelegramClient, events, types, functions
from telethon.tl.types import User, PeerChannel, UpdateUserName, UpdateUser, UpdateUserStatus, UpdatePeerSettings, PeerUser
from telethon.errors import FloodWaitError
from dotenv import load_dotenv
from database import Database
from datetime import datetime
from aiohttp import web, ClientSession
import gc

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
    SCAN_INTERVAL = int(os.getenv('SCAN_INTERVAL', 60))  # Changed to 1 minute for more frequent checks
    MONITORED_GROUPS = [int(x) for x in os.getenv('MONITORED_GROUPS', '').split(',') if x]
    RENDER_HEALTH_CHECK = os.getenv('RENDER_HEALTH_CHECK', 'true').lower() == 'true'

# Validate configuration
if not all([Config.API_ID, Config.API_HASH, Config.BOT_TOKEN, Config.ADMIN_ID]):
    logger.error("Missing required environment variables")
    logger.error(f"API_ID: {Config.API_ID}")
    logger.error(f"API_HASH: {'Set' if Config.API_HASH else 'Not Set'}")
    logger.error(f"BOT_TOKEN: {'Set' if Config.BOT_TOKEN else 'Not Set'}")
    logger.error(f"ADMIN_ID: {Config.ADMIN_ID}")
    raise ValueError("Missing required environment variables")

# Initialize client with optimized settings
client = TelegramClient(
    Config.SESSION_NAME,
    Config.API_ID,
    Config.API_HASH,
    device_model="Name Change Bot",
    system_version="1.0",
    app_version="1.0",
    lang_code="en",
    connection_retries=5,
    retry_delay=1,
    auto_reconnect=True
).start(bot_token=Config.BOT_TOKEN)

# Initialize database with consistent name
db = Database(db_name='name_change.db')

# Store monitored groups
monitored_groups: List[int] = Config.MONITORED_GROUPS

# Health check endpoint
async def health_check(request):
    """Health check endpoint for Render.com"""
    try:
        # Check if client is connected
        if not client.is_connected():
            return web.Response(status=503, text="Bot not connected")
        
        # Check if database is accessible
        try:
            db.get_connection()
        except Exception as e:
            logger.error(f"Database health check failed: {str(e)}")
            return web.Response(status=503, text="Database not accessible")
            
        return web.Response(text="OK")
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return web.Response(status=503, text="Service unhealthy")

# Setup health check server
async def start_health_check_server():
    """Start the health check server"""
    if Config.RENDER_HEALTH_CHECK:
        app = web.Application()
        app.router.add_get('/health', health_check)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', int(os.getenv('PORT', 8080)))
        await site.start()
        logger.info("Health check server started on port 8080")
        
        # Keep the server running
        while True:
            await asyncio.sleep(30)  # Check every 30 seconds
            if not client.is_connected():
                logger.warning("Bot disconnected, attempting to reconnect...")
                await client.connect()

# Memory optimization function
def optimize_memory():
    gc.collect()
    if hasattr(gc, 'collect_generations'):
        gc.collect_generations()

async def periodic_scan():
    """Periodically scan all monitored groups for name changes"""
    while True:
        try:
            logger.info("Starting periodic scan of monitored groups")
            for group_id in monitored_groups:
                try:
                    # Get all participants at once to reduce API calls
                    participants = await client.get_participants(group_id)
                    for user in participants:
                        if isinstance(user, User):
                            try:
                                await check_name_changes(user)
                            except FloodWaitError as e:
                                logger.warning(f"Flood wait required: {e.seconds} seconds")
                                await asyncio.sleep(e.seconds)
                                continue
                            except Exception as e:
                                logger.error(f"Error checking user {user.id}: {str(e)}")
                                continue
                except Exception as e:
                    logger.error(f"Error scanning group {group_id}: {str(e)}")
                    continue
        except Exception as e:
            logger.error(f"Error in periodic scan: {str(e)}")
        
        # Optimize memory after each scan
        optimize_memory()
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

        # First check if user is in any active monitored groups
        active_groups = db.get_user_active_groups(user.id)
        if not active_groups:
            logger.debug(f"User {user.id} is not in any active monitored groups, skipping name check")
            return

        current_data = {
            'first_name': user.first_name,
            'last_name': user.last_name or ""
        }

        # Get user data from database
        db_user = db.get_user(user.id)
        
        # Log the data for debugging
        logger.debug(f"DB user data: {db_user}")
        logger.debug(f"Current user data: {current_data}")

        # If user doesn't exist in database, register them
        if not db_user:
            db.register_user(
                user_id=user.id,
                first_name=user.first_name,
                last_name=user.last_name or ""
            )
            logger.info(f"Registered new user {user.id} in database")
            return

        changes = []

        # Check first name
        if db_user['first_name'] != current_data['first_name']:
            changes.append(f"👤 First name: {db_user['first_name']} -> {current_data['first_name']}")

        # Check last name
        if db_user['last_name'] != current_data['last_name']:
            changes.append(f"👤 Last name: {db_user['last_name']} -> {current_data['last_name']}")

        # Only update database if changes were detected
        if changes:
            # Update database with new data
            db.register_user(
                user_id=user.id,
                first_name=user.first_name,
                last_name=user.last_name or ""
            )
            
            # Get user's active groups for context
            group_names = [g['group_name'] for g in active_groups]

            message = (
                f"👤 User ID: `{user.id}`\n"
                f"👥 Groups: {', '.join(group_names) if group_names else 'None'}\n\n"    
                + "\n".join(changes)
            )
            await send_to_admin(message)
            logger.info(f"Sent name change notification for user {user.id}")
        else:
            logger.debug(f"No name changes detected for user {user.id}")

    except FloodWaitError as e:
        logger.warning(f"Flood wait required: {e.seconds} seconds")
        await asyncio.sleep(e.seconds)
        await check_name_changes(user)  # Retry after waiting
    except Exception as e:
        logger.error(f"Error checking name changes: {e}")

async def notify_user_left(user_id: int, group_id: int, group_name: str):
    """Notify admin when a user leaves a group"""
    try:
        # Get user info
        user = await client.get_entity(user_id)
        if not user:
            return

        # Get user's remaining active groups
        remaining_groups = db.get_user_active_groups(user_id)
        remaining_group_names = [g['group_name'] for g in remaining_groups]

        # Create direct chat link
        chat_link = f"tg://user?id={user_id}"

        message = (
            "👋 User Left Group Notification\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 User: {user.first_name} {user.last_name or ''}\n"
            f"🆔 User ID: `{user_id}`\n"
            f"🚪 Left Group: {group_name}\n"
            f"💬 [Click to Chat]({chat_link})\n"
        )

        if remaining_groups:
            message += f"\n📋 Still in groups:\n• " + "\n• ".join(remaining_group_names)
        else:
            message += "\n⚠️ User is no longer in any monitored groups"

        # Send message with parse_mode to enable the link
        await client.send_message(
            Config.ADMIN_ID,
            message,
            parse_mode='markdown',
            link_preview=False
        )
        logger.info(f"Notified admin about user {user_id} leaving group {group_name}")
    except Exception as e:
        logger.error(f"Error notifying about user leaving: {str(e)}")

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

        # Handle user leaving
        if event.user_left or event.user_kicked:
            logger.debug(f"User left/kicked event detected")
            if hasattr(event, 'user_id') and event.user_id:
                user_id = event.user_id
                try:
                    chat = await event.get_chat()
                    group_name = getattr(chat, 'title', f'Group {group_id}')
                    
                    # Remove user from group in database
                    if db.remove_user_from_group(user_id, group_id):
                        # Notify admin
                        await notify_user_left(user_id, group_id, group_name)
                except Exception as e:
                    logger.error(f"Error handling user leaving: {str(e)}")
            return

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
                    username=user.username or ""
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
        logger.error(f"Error in group event: {str(e)}", exc_info=True)

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

@client.on(events.Raw(UpdateUser))
async def handle_user_update(event):
    """Handle general user profile updates including phone changes"""
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
            error_details = []
            
            try:
                # Get all participants at once to reduce API calls
                participants = await client.get_participants(chat)
                total_participants = len(participants)
                
                for user in participants:
                    if isinstance(user, User):
                        try:
                            # Check if user is already in database
                            existing_user = db.get_user(user.id)
                            if not existing_user:
                                # Only register new users
                                try:
                                    # Ensure we have valid values
                                    first_name = user.first_name or "Unknown"
                                    last_name = user.last_name or ""
                                    username = user.username or ""
                                    
                                    db.register_user(
                                        user_id=user.id,
                                        first_name=first_name,
                                        last_name=last_name,
                                        username=username
                                    )
                                    count += 1
                                except Exception as e:
                                    errors += 1
                                    error_msg = f"User {user.id}: {str(e)}"
                                    error_details.append(error_msg)
                                    logger.error(error_msg)
                                    continue
                            
                            # Add user to group regardless
                            try:
                                db.add_user_to_group(user.id, group_id)
                            except Exception as e:
                                errors += 1
                                error_msg = f"Error adding user {user.id} to group: {str(e)}"
                                error_details.append(error_msg)
                                logger.error(error_msg)
                            
                            if count % 10 == 0:  # Log progress every 10 users
                                logger.info(f"Processed {count}/{total_participants} users in group {group_name}")
                                
                        except Exception as e:
                            errors += 1
                            error_msg = f"User {user.id}: {str(e)}"
                            error_details.append(error_msg)
                            logger.error(error_msg)
                            
            except Exception as e:
                logger.error(f"Error processing users in group {group_name}: {str(e)}")
                await event.reply("⚠️ Warning: Error processing users. Tracking is still active.")
                return

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
                if len(error_details) > 0:
                    status_msg.append("\nError details (first 3):")
                    for detail in error_details[:3]:
                        status_msg.append(f"• {detail}")
                    if len(error_details) > 3:
                        status_msg.append(f"... and {len(error_details) - 3} more errors")
            
            status_msg.append("\nI'll report name changes to the admin.")

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

# Add new handler for message events that might indicate name changes
@client.on(events.NewMessage())
async def handle_new_message(event):
    """Handle new messages which might indicate name changes"""
    try:
        if event.sender_id:
            user = await event.get_sender()
            if isinstance(user, User):
                await check_name_changes(user)
                logger.debug(f"Checked name changes for user {user.id} from message")
    except Exception as e:
        logger.error(f"Error handling new message: {e}", exc_info=True)

# Add handler for service messages
@client.on(events.ChatAction())
async def handle_service_message(event):
    """Handle service messages which might indicate name changes"""
    try:
        if event.user_id:
            user = await event.get_user()
            if isinstance(user, User):
                await check_name_changes(user)
                logger.debug(f"Checked name changes for user {user.id} from service message")
    except Exception as e:
        logger.error(f"Error handling service message: {e}", exc_info=True)

async def send_ping():
    """Send periodic ping to keep the server alive"""
    while True:
        try:
            async with ClientSession() as session:
                # Get the current time
                current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                # Send ping to a reliable service
                async with session.get('https://api.telegram.org') as response:
                    if response.status == 200:
                        logger.info(f"🟢 Ping successful at {current_time}")
                    else:
                        logger.warning(f"⚠️ Ping failed with status {response.status} at {current_time}")
                
                # Also send a message to admin for monitoring
                try:
                    await client.send_message(
                        Config.ADMIN_ID,
                        f"🟢 Server ping at {current_time}\n"
                        f"Status: Active\n"
                        f"Monitored Groups: {len(monitored_groups)}"
                    )
                except Exception as e:
                    logger.error(f"Error sending ping message to admin: {str(e)}")
                
        except Exception as e:
            logger.error(f"Error in ping mechanism: {str(e)}")
        
        # Wait for 5 minutes
        await asyncio.sleep(300)  # 300 seconds = 5 minutes

async def main():
    """Main bot function"""
    try:
        # Start health check server
        await start_health_check_server()
        
        # Start ping mechanism
        asyncio.create_task(send_ping())
        
        # Ensure we're receiving updates
        me = await client.get_me()
        logger.info(f"Connected as {me.username}")

        # Set up update receiving with more detailed logging and state management
        try:
            state = await client(functions.updates.GetStateRequest())
            logger.info(f"Successfully set up update receiving. State: {state}")
            
            # Set up update handling with proper state management
            await client(functions.updates.GetDifferenceRequest(
                pts=state.pts,
                date=state.date,
                qts=state.qts
            ))
            logger.info("Successfully synchronized update state")
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
            f"Groups in database: {total_groups}\n"
            f"Running on Render free tier"
        )
        logger.info("Bot started and ready to track name changes!")

        # Keep the bot running
        await client.run_until_disconnected()
    except Exception as e:
        logger.error(f"Fatal error in main: {str(e)}", exc_info=True)
        raise

if __name__ == '__main__':
    try:
        with client:
            client.loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}", exc_info=True)
 