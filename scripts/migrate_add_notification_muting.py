#!/usr/bin/env python3
"""
Database migration to add notification muting fields.

Adds:
- notifications_muted: Boolean to enable/disable notifications per IP
- last_notified_status: Track the status we last notified about
- last_notified_at: When we last sent a notification

Run this script:
    cd /root/ip-blacklist-monitor
    source venv/bin/activate
    python scripts/migrate_add_notification_muting.py
"""

import asyncio
import sys
from datetime import datetime, timezone

import asyncpg

DATABASE_URL = "postgresql://postgres:blacklist_secure_pass_2024@localhost:5432/ip_blacklist"


async def migrate():
    """Add notification muting columns to ips table."""
    print("=" * 60)
    print("Adding Notification Muting Fields")
    print("=" * 60)
    print(f"Started at: {datetime.now(timezone.utc).isoformat()}")
    print()

    conn = await asyncpg.connect(DATABASE_URL)

    try:
        async with conn.transaction():
            print("Adding notification muting columns...")

            # Add notifications_muted column
            await conn.execute("""
                ALTER TABLE ips
                ADD COLUMN IF NOT EXISTS notifications_muted BOOLEAN DEFAULT FALSE NOT NULL
            """)
            print("  - Added notifications_muted column")

            # Add last_notified_status column
            await conn.execute("""
                ALTER TABLE ips
                ADD COLUMN IF NOT EXISTS last_notified_status VARCHAR(20)
            """)
            print("  - Added last_notified_status column")

            # Add last_notified_at column
            await conn.execute("""
                ALTER TABLE ips
                ADD COLUMN IF NOT EXISTS last_notified_at TIMESTAMP WITH TIME ZONE
            """)
            print("  - Added last_notified_at column")

            # For existing blacklisted IPs, set last_notified_status to 'blacklisted'
            # so they don't get duplicate notifications on next check
            result = await conn.execute("""
                UPDATE ips
                SET last_notified_status = 'blacklisted'
                WHERE status = 'blacklisted'
            """)
            print(f"  - Marked existing blacklisted IPs as already notified")

            print()
            print("=" * 60)
            print("Migration completed successfully!")
            print("=" * 60)

    except Exception as e:
        print(f"\nError: {e}")
        raise
    finally:
        await conn.close()
        print(f"\nFinished at: {datetime.now(timezone.utc).isoformat()}")


if __name__ == "__main__":
    try:
        asyncio.run(migrate())
    except Exception as e:
        print(f"Migration failed: {e}")
        sys.exit(1)
