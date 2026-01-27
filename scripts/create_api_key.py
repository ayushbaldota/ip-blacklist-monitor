#!/usr/bin/env python3
"""Script to generate API keys."""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.security import create_api_key
from app.db.database import AsyncSessionLocal


async def main():
    """Create an API key."""
    name = sys.argv[1] if len(sys.argv) > 1 else "default"
    permissions = ["read", "write"] if len(sys.argv) <= 2 else sys.argv[2].split(",")

    print(f"Creating API key for '{name}' with permissions: {permissions}")

    async with AsyncSessionLocal() as db:
        raw_key, api_key = await create_api_key(
            db=db,
            name=name,
            permissions=permissions,
        )

    print("\n" + "=" * 60)
    print("API KEY CREATED SUCCESSFULLY")
    print("=" * 60)
    print(f"\nName: {name}")
    print(f"Permissions: {permissions}")
    print(f"\nAPI Key (save this - it won't be shown again):\n")
    print(f"  {raw_key}")
    print("\n" + "=" * 60)
    print("\nUse this key in the X-API-Key header for API requests.")


if __name__ == "__main__":
    asyncio.run(main())
