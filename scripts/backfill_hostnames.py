#!/usr/bin/env python3
"""
Backfill hostnames for existing IPs.

This script performs reverse DNS lookups for all IPs that don't have a hostname set.
Run with: python scripts/backfill_hostnames.py
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select, update
from app.db.database import AsyncSessionLocal
from app.db.models import IP
from app.services.hostname_lookup import get_hostname_service


async def backfill_hostnames():
    """Backfill hostname for all IPs that don't have one."""
    hostname_service = get_hostname_service()

    async with AsyncSessionLocal() as db:
        # Get all IPs without hostname
        result = await db.execute(
            select(IP).where(IP.hostname.is_(None))
        )
        ips = list(result.scalars().all())

        if not ips:
            print("All IPs already have hostnames.")
            return

        print(f"Found {len(ips)} IPs without hostname. Starting backfill...")

        success_count = 0
        no_ptr_count = 0
        error_count = 0

        for i, ip in enumerate(ips, 1):
            try:
                hostname = await hostname_service.lookup(ip.ip_address)

                if hostname:
                    await db.execute(
                        update(IP)
                        .where(IP.ip_address == ip.ip_address)
                        .values(hostname=hostname)
                    )
                    success_count += 1
                    print(f"[{i}/{len(ips)}] {ip.ip_address} -> {hostname}")
                else:
                    no_ptr_count += 1
                    print(f"[{i}/{len(ips)}] {ip.ip_address} -> No PTR record")

                # Commit every 50 IPs
                if i % 50 == 0:
                    await db.commit()
                    print(f"  Committed batch ({i} processed)")

            except Exception as e:
                error_count += 1
                print(f"[{i}/{len(ips)}] {ip.ip_address} -> Error: {e}")

        # Final commit
        await db.commit()

        print(f"\nBackfill complete!")
        print(f"  - Hostnames resolved: {success_count}")
        print(f"  - No PTR record: {no_ptr_count}")
        print(f"  - Errors: {error_count}")


if __name__ == "__main__":
    asyncio.run(backfill_hostnames())
