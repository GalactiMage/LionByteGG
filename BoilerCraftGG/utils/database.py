"""
Database Utility for BoilerCraftGG
Handles all database operations using SQLite
"""

import aiosqlite
import os
from datetime import datetime
import config


class Database:
    """Async SQLite database handler"""
    
    def __init__(self):
        self.db_path = config.DATABASE_PATH
        self.connection = None
        
    async def initialize(self):
        """Initialize the database and create tables"""
        # Ensure data directory exists
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        self.connection = await aiosqlite.connect(self.db_path)
        await self._create_tables()
        print(f"[DATABASE] Connected to {self.db_path}")
        
    async def _create_tables(self):
        """Create all necessary tables"""
        # Verified users table
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS verified_users (
                discord_id INTEGER PRIMARY KEY,
                minecraft_username TEXT NOT NULL,
                minecraft_uuid TEXT,
                first_name TEXT,
                email TEXT,
                phone TEXT,
                campus TEXT,
                verified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Temporary voice channels table
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS temp_voice_channels (
                channel_id INTEGER PRIMARY KEY,
                owner_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Bot settings table
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        
        # Temp VC generators table (supports multiple Join to Create channels)
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS temp_vc_generators (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                join_channel_id INTEGER NOT NULL UNIQUE,
                category_id INTEGER NOT NULL,
                name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        await self.connection.commit()
        
    async def close(self):
        """Close the database connection"""
        if self.connection:
            await self.connection.close()
            print("[DATABASE] Connection closed")
            
    # ==================== Verification Methods ====================
    
    async def add_verified_user(
        self, 
        discord_id: int, 
        minecraft_username: str, 
        minecraft_uuid: str = None,
        first_name: str = None,
        email: str = None,
        phone: str = None,
        campus: str = None
    ):
        """Add a verified user to the database"""
        await self.connection.execute(
            """
            INSERT OR REPLACE INTO verified_users 
            (discord_id, minecraft_username, minecraft_uuid, first_name, email, phone, campus, verified_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (discord_id, minecraft_username, minecraft_uuid, first_name, email, phone, campus, datetime.utcnow())
        )
        await self.connection.commit()
        
    async def get_verified_user(self, discord_id: int):
        """Get a verified user by Discord ID"""
        async with self.connection.execute(
            "SELECT * FROM verified_users WHERE discord_id = ?",
            (discord_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "discord_id": row[0],
                    "minecraft_username": row[1],
                    "minecraft_uuid": row[2],
                    "first_name": row[3],
                    "email": row[4],
                    "phone": row[5],
                    "campus": row[6],
                    "verified_at": row[7]
                }
            return None
            
    async def remove_verified_user(self, discord_id: int):
        """Remove a verified user from the database"""
        await self.connection.execute(
            "DELETE FROM verified_users WHERE discord_id = ?",
            (discord_id,)
        )
        await self.connection.commit()
        
    async def get_user_by_minecraft(self, minecraft_username: str):
        """Get a verified user by Minecraft username"""
        async with self.connection.execute(
            "SELECT * FROM verified_users WHERE minecraft_username = ? COLLATE NOCASE",
            (minecraft_username,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "discord_id": row[0],
                    "minecraft_username": row[1],
                    "minecraft_uuid": row[2],
                    "first_name": row[3],
                    "email": row[4],
                    "phone": row[5],
                    "campus": row[6],
                    "verified_at": row[7]
                }
            return None
            
    async def get_user_by_email(self, email: str):
        """Get a verified user by email"""
        async with self.connection.execute(
            "SELECT * FROM verified_users WHERE email = ? COLLATE NOCASE",
            (email,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "discord_id": row[0],
                    "minecraft_username": row[1],
                    "minecraft_uuid": row[2],
                    "first_name": row[3],
                    "email": row[4],
                    "phone": row[5],
                    "campus": row[6],
                    "verified_at": row[7]
                }
            return None
            
    # ==================== Temp VC Methods ====================
    
    async def add_temp_vc(self, channel_id: int, owner_id: int):
        """Add a temporary voice channel to the database"""
        await self.connection.execute(
            """
            INSERT INTO temp_voice_channels (channel_id, owner_id, created_at)
            VALUES (?, ?, ?)
            """,
            (channel_id, owner_id, datetime.utcnow())
        )
        await self.connection.commit()
        
    async def get_temp_vc(self, channel_id: int):
        """Get a temporary voice channel by channel ID"""
        async with self.connection.execute(
            "SELECT * FROM temp_voice_channels WHERE channel_id = ?",
            (channel_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "channel_id": row[0],
                    "owner_id": row[1],
                    "created_at": row[2]
                }
            return None
            
    async def remove_temp_vc(self, channel_id: int):
        """Remove a temporary voice channel from the database"""
        await self.connection.execute(
            "DELETE FROM temp_voice_channels WHERE channel_id = ?",
            (channel_id,)
        )
        await self.connection.commit()
        
    async def get_user_temp_vc(self, owner_id: int):
        """Get a user's temporary voice channel"""
        async with self.connection.execute(
            "SELECT * FROM temp_voice_channels WHERE owner_id = ?",
            (owner_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "channel_id": row[0],
                    "owner_id": row[1],
                    "created_at": row[2]
                }
            return None
            
    async def get_all_temp_vcs(self):
        """Get all temporary voice channels"""
        async with self.connection.execute(
            "SELECT * FROM temp_voice_channels"
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                {
                    "channel_id": row[0],
                    "owner_id": row[1],
                    "created_at": row[2]
                }
                for row in rows
            ]
            
    # ==================== Settings Methods ====================
    
    async def set_setting(self, key: str, value: str):
        """Set a bot setting"""
        await self.connection.execute(
            "INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)",
            (key, value)
        )
        await self.connection.commit()
        
    async def get_setting(self, key: str, default: str = None):
        """Get a bot setting"""
        async with self.connection.execute(
            "SELECT value FROM bot_settings WHERE key = ?",
            (key,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else default
            
    # ==================== Temp VC Generator Methods ====================
    
    async def add_generator(self, join_channel_id: int, category_id: int, name: str = None):
        """Add a temp VC generator configuration"""
        await self.connection.execute(
            """
            INSERT OR REPLACE INTO temp_vc_generators (join_channel_id, category_id, name, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (join_channel_id, category_id, name, datetime.utcnow())
        )
        await self.connection.commit()
        
    async def remove_generator(self, join_channel_id: int):
        """Remove a temp VC generator by join channel ID"""
        await self.connection.execute(
            "DELETE FROM temp_vc_generators WHERE join_channel_id = ?",
            (join_channel_id,)
        )
        await self.connection.commit()
        
    async def get_generator(self, join_channel_id: int):
        """Get a generator by join channel ID"""
        async with self.connection.execute(
            "SELECT * FROM temp_vc_generators WHERE join_channel_id = ?",
            (join_channel_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "id": row[0],
                    "join_channel_id": row[1],
                    "category_id": row[2],
                    "name": row[3],
                    "created_at": row[4]
                }
            return None
            
    async def get_all_generators(self):
        """Get all temp VC generators"""
        async with self.connection.execute(
            "SELECT * FROM temp_vc_generators"
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                {
                    "id": row[0],
                    "join_channel_id": row[1],
                    "category_id": row[2],
                    "name": row[3],
                    "created_at": row[4]
                }
                for row in rows
            ]
            
    async def count_generators(self):
        """Count the number of configured generators"""
        async with self.connection.execute(
            "SELECT COUNT(*) FROM temp_vc_generators"
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0
