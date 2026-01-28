#!/usr/bin/env python3
"""
Database schema migration script.

Migrates from numeric ID primary key to ip_address as primary key.
Adds 'name' field to the IPs table.

Run this script to migrate existing data:
    cd /root/ip-blacklist-monitor
    source venv/bin/activate
    python scripts/migrate_schema.py
"""

import asyncio
import sys
from datetime import datetime, timezone

import asyncpg

# Database connection settings (should match .env)
DATABASE_URL = "postgresql://postgres:blacklist_secure_pass_2024@localhost:5432/ip_blacklist"


async def migrate():
    """Perform the schema migration."""
    print("=" * 60)
    print("IP Blacklist Monitor - Schema Migration")
    print("=" * 60)
    print(f"Started at: {datetime.now(timezone.utc).isoformat()}")
    print()

    # Connect to database
    print("Connecting to database...")
    conn = await asyncpg.connect(DATABASE_URL)

    try:
        # Start transaction
        async with conn.transaction():
            print("Starting migration transaction...")
            print()

            # Step 1: Add 'name' column to ips table if it doesn't exist
            print("Step 1: Adding 'name' column to ips table...")
            await conn.execute("""
                ALTER TABLE ips
                ADD COLUMN IF NOT EXISTS name VARCHAR(100)
            """)
            print("  - Added 'name' column")

            # Step 2: Check if migration is needed (if 'id' column exists)
            column_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'ips' AND column_name = 'id'
                )
            """)

            if not column_exists:
                print("  - Migration already completed (no 'id' column found)")
                print("Migration complete!")
                return

            print()
            print("Step 2: Migrating ip_history foreign key from ip_id to ip_address...")

            # Check if ip_history has ip_id column
            has_ip_id = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'ip_history' AND column_name = 'ip_id'
                )
            """)

            if has_ip_id:
                # Add ip_address column to ip_history if it doesn't exist
                await conn.execute("""
                    ALTER TABLE ip_history
                    ADD COLUMN IF NOT EXISTS ip_address VARCHAR(45)
                """)

                # Populate ip_address from ips table
                await conn.execute("""
                    UPDATE ip_history h
                    SET ip_address = i.ip_address
                    FROM ips i
                    WHERE h.ip_id = i.id AND h.ip_address IS NULL
                """)

                # Drop old foreign key constraint
                await conn.execute("""
                    ALTER TABLE ip_history
                    DROP CONSTRAINT IF EXISTS ip_history_ip_id_fkey
                """)

                # Drop ip_id column
                await conn.execute("""
                    ALTER TABLE ip_history
                    DROP COLUMN IF EXISTS ip_id
                """)

                print("  - Migrated ip_history to use ip_address")

            print()
            print("Step 3: Migrating activity_log ip_id references...")

            # Check if activity_log has ip_id column
            has_activity_ip_id = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'activity_log' AND column_name = 'ip_id'
                )
            """)

            if has_activity_ip_id:
                # Drop foreign key constraint if exists
                await conn.execute("""
                    ALTER TABLE activity_log
                    DROP CONSTRAINT IF EXISTS activity_log_ip_id_fkey
                """)

                # Drop ip_id column
                await conn.execute("""
                    ALTER TABLE activity_log
                    DROP COLUMN IF EXISTS ip_id
                """)

                print("  - Removed ip_id from activity_log")

            print()
            print("Step 4: Changing primary key from id to ip_address...")

            # Drop old primary key
            await conn.execute("""
                ALTER TABLE ips
                DROP CONSTRAINT IF EXISTS ips_pkey
            """)

            # Drop the id column
            await conn.execute("""
                ALTER TABLE ips
                DROP COLUMN IF EXISTS id
            """)

            # Add new primary key on ip_address
            await conn.execute("""
                ALTER TABLE ips
                ADD PRIMARY KEY (ip_address)
            """)

            print("  - Changed primary key to ip_address")

            print()
            print("Step 5: Adding foreign key constraints...")

            # Add foreign key constraint on ip_history
            await conn.execute("""
                ALTER TABLE ip_history
                ADD CONSTRAINT ip_history_ip_address_fkey
                FOREIGN KEY (ip_address) REFERENCES ips(ip_address) ON DELETE CASCADE
            """)

            # Make ip_address NOT NULL in ip_history
            await conn.execute("""
                ALTER TABLE ip_history
                ALTER COLUMN ip_address SET NOT NULL
            """)

            print("  - Added foreign key constraint on ip_history")

            print()
            print("Step 6: Creating/updating indexes...")

            # Create index on ip_history.ip_address if not exists
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_ip_history_ip_address
                ON ip_history(ip_address)
            """)

            # Create composite index
            await conn.execute("""
                DROP INDEX IF EXISTS idx_ip_history_ip_date;
                CREATE INDEX idx_ip_history_ip_date
                ON ip_history(ip_address, checked_at)
            """)

            print("  - Updated indexes")

            print()
            print("=" * 60)
            print("Migration completed successfully!")
            print("=" * 60)

    except Exception as e:
        print(f"\nError during migration: {e}")
        print("Transaction rolled back.")
        raise
    finally:
        await conn.close()
        print()
        print(f"Finished at: {datetime.now(timezone.utc).isoformat()}")


if __name__ == "__main__":
    try:
        asyncio.run(migrate())
    except Exception as e:
        print(f"\nMigration failed: {e}")
        sys.exit(1)
