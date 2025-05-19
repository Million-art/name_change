import sqlite3
import logging
import os
from typing import Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_name='name_change.db'):
        """Initialize database connection"""
        self.db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), db_name)
        logger.info(f"Initializing database at: {self.db_path}")
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
        self.init_db()
        logger.info("Database initialized successfully")
        self.migrate_db()

    def get_connection(self):
        """Get database connection with proper row factory"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row 
            return conn
        except Exception as e:
            logger.error(f"Error connecting to database at {self.db_path}: {str(e)}")
            raise

    def migrate_db(self):
        """Migrate database schema to latest version"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Check if is_active column exists in users table
                cursor.execute("PRAGMA table_info(users)")
                columns = [column[1] for column in cursor.fetchall()]
                
                if 'is_active' not in columns:
                    logger.info("Adding is_active column to users table")
                    cursor.execute('ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT 1')
                
                if 'last_checked' not in columns:
                    logger.info("Adding last_checked column to users table")
                    cursor.execute('ALTER TABLE users ADD COLUMN last_checked TIMESTAMP')
                
                if 'username' not in columns:
                    logger.info("Adding username column to users table")
                    cursor.execute('ALTER TABLE users ADD COLUMN username TEXT')
                
                # Check if is_active column exists in groups table
                cursor.execute("PRAGMA table_info(groups)")
                columns = [column[1] for column in cursor.fetchall()]
                
                if 'is_active' not in columns:
                    logger.info("Adding is_active column to groups table")
                    cursor.execute('ALTER TABLE groups ADD COLUMN is_active BOOLEAN DEFAULT 1')
                
                # Check if last_seen and is_active columns exist in user_groups table
                cursor.execute("PRAGMA table_info(user_groups)")
                columns = [column[1] for column in cursor.fetchall()]
                
                if 'last_seen' not in columns:
                    logger.info("Adding last_seen column to user_groups table")
                    cursor.execute('ALTER TABLE user_groups ADD COLUMN last_seen TIMESTAMP')
                
                if 'is_active' not in columns:
                    logger.info("Adding is_active column to user_groups table")
                    cursor.execute('ALTER TABLE user_groups ADD COLUMN is_active BOOLEAN DEFAULT 1')
                
                if 'added_at' not in columns:
                    logger.info("Adding added_at column to user_groups table")
                    cursor.execute('ALTER TABLE user_groups ADD COLUMN added_at TIMESTAMP')
                
                # Check if name_changes table exists
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='name_changes'")
                if not cursor.fetchone():
                    logger.info("Creating name_changes table")
                    cursor.execute('''
                        CREATE TABLE name_changes (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id INTEGER,
                            change_type TEXT,
                            old_value TEXT,
                            new_value TEXT,
                            changed_at TIMESTAMP,
                            FOREIGN KEY (user_id) REFERENCES users(user_id)
                        )
                    ''')
                
                conn.commit()
                logger.info("Database migration completed successfully")
        except Exception as e:
            logger.error(f"Error during database migration: {str(e)}")
            raise

    def init_db(self):
        """Initialize database tables"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Create users table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        first_name TEXT,
                        last_name TEXT,
                        username TEXT,
                        last_updated TIMESTAMP,
                        last_checked TIMESTAMP
                    )
                ''')
                
                # Create groups table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS groups (
                        group_id INTEGER PRIMARY KEY,
                        group_name TEXT,
                        added_at TIMESTAMP
                    )
                ''')
                
                # Create user_groups table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS user_groups (
                        user_id INTEGER,
                        group_id INTEGER,
                        last_seen TIMESTAMP,
                        is_active BOOLEAN DEFAULT 1,
                        added_at TIMESTAMP,
                        PRIMARY KEY (user_id, group_id),
                        FOREIGN KEY (user_id) REFERENCES users(user_id),
                        FOREIGN KEY (group_id) REFERENCES groups(group_id)
                    )
                ''')
                
                # Create name_changes table to track history
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS name_changes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        change_type TEXT,
                        old_value TEXT,
                        new_value TEXT,
                        changed_at TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users(user_id)
                    )
                ''')
                
                conn.commit()
                logger.info("Database initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing database: {str(e)}")
            raise

    def register_user(self, user_id: int, first_name: str, last_name: str, username: str = None):
        """Register or update user in database"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Get existing user data
                cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
                existing_user = cursor.fetchone()
                
                # Check for changes if user exists
                if existing_user:
                    changes = []
                    if existing_user['first_name'] != first_name:
                        changes.append(('first_name', existing_user['first_name'], first_name))
                    if existing_user['last_name'] != last_name:
                        changes.append(('last_name', existing_user['last_name'], last_name))
                    if username and existing_user.get('username') != username:
                        changes.append(('username', existing_user.get('username', ''), username))
                    
                    # Record changes
                    for change_type, old_value, new_value in changes:
                        cursor.execute('''
                            INSERT INTO name_changes 
                            (user_id, change_type, old_value, new_value, changed_at)
                            VALUES (?, ?, ?, ?, ?)
                        ''', (user_id, change_type, old_value, new_value, datetime.now()))
                        logger.info(f"Recorded {change_type} change for user {user_id}: {old_value} → {new_value}")
                
                # Update user data
                cursor.execute('''
                    INSERT OR REPLACE INTO users 
                    (user_id, first_name, last_name, username, last_updated, last_checked)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (user_id, first_name, last_name, username, datetime.now(), datetime.now()))
                
                conn.commit()
                logger.debug(f"Updated user {user_id} in database")
        except Exception as e:
            logger.error(f"Error registering user: {str(e)}")
            raise

    def register_group(self, group_id: int, group_name: str):
        """Register or update group in database"""
        try:
            if not group_name:
                logger.warning(f"Attempted to register group {group_id} with empty name")
                return False
                
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO groups 
                    (group_id, group_name, added_at, is_active)
                    VALUES (?, ?, ?, 1)
                ''', (group_id, group_name.strip(), datetime.now()))
                conn.commit()
                logger.info(f"Successfully registered group: {group_name} ({group_id})")
                return True
        except Exception as e:
            logger.error(f"Error registering group: {str(e)}")
            return False

    def add_user_to_group(self, user_id: int, group_id: int):
        """Add user to group"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO user_groups 
                    (user_id, group_id, added_at, last_seen, is_active)
                    VALUES (?, ?, ?, ?, 1)
                ''', (user_id, group_id, datetime.now(), datetime.now()))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error adding user to group: {str(e)}")
            return False

    def get_user(self, user_id: int):
        """Get user data from database"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT u.*, 
                           (SELECT COUNT(*) FROM name_changes WHERE user_id = u.user_id) as change_count
                    FROM users u 
                    WHERE u.user_id = ?
                ''', (user_id,))
                user = cursor.fetchone()
                if user:
                    user_dict = dict(user)
                    logger.debug(f"Retrieved user data for {user_id}: {user_dict}")
                    return user_dict
                logger.debug(f"No user found with ID {user_id}")
                return None
        except Exception as e:
            logger.error(f"Error getting user: {str(e)}")
            return None

    def get_all_users(self):
        """Get all users from database"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM users WHERE is_active = 1')
                return [dict(user) for user in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting all users: {str(e)}")
            return []

    def get_user_groups(self, user_id: int):
        """Get all groups a user belongs to"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT g.group_id, g.group_name, g.is_active
                    FROM groups g
                    JOIN user_groups ug ON g.group_id = ug.group_id
                    WHERE ug.user_id = ? 
                    AND ug.is_active = 1 
                    AND g.is_active = 1
                    AND g.group_name IS NOT NULL
                ''', (user_id,))
                groups = [dict(row) for row in cursor.fetchall()]
                if not groups:
                    logger.debug(f"No active groups found for user {user_id}")
                return groups
        except Exception as e:
            logger.error(f"Error getting user groups: {str(e)}")
            return []

    def get_name_changes(self, user_id: int, limit: int = 10):
        """Get recent name changes for a user"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT * FROM name_changes 
                    WHERE user_id = ? 
                    ORDER BY changed_at DESC 
                    LIMIT ?
                ''', (user_id, limit))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting name changes: {str(e)}")
            return []

    def check_name_changes(self, user_id: int, current_data: Dict[str, Any]) -> Dict[str, Any]:
        """Check for name changes and return changes if any"""
        try:
            old_data = self.get_user(user_id)
            if not old_data:
                logger.debug(f"No existing data found for user {user_id}")
                return {}

            changes = {}
            if old_data['first_name'] != current_data['first_name']:
                changes['first_name'] = {
                    'old': old_data['first_name'],
                    'new': current_data['first_name']
                }
                logger.debug(f"First name change detected for user {user_id}: {old_data['first_name']} → {current_data['first_name']}")
            
            if old_data['last_name'] != current_data['last_name']:
                changes['last_name'] = {
                    'old': old_data['last_name'],
                    'new': current_data['last_name']
                }
                logger.debug(f"Last name change detected for user {user_id}: {old_data['last_name']} → {current_data['last_name']}")

            return changes
        except Exception as e:
            logger.error(f"Error checking name changes: {str(e)}")
            return {} 