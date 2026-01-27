#!/usr/bin/env python3
"""Script to run a blacklist check immediately."""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import get_settings
from app.db.database import AsyncSessionLocal
from app.services.blacklist_checker import BlacklistCheckerService
from app.services.providers.dnsbl import create_dnsbl_providers
from app.services.slack_notifier import SlackNotifier
from app.utils.logging import setup_logging

setup_logging()
settings = get_settings()


async def main():
    """Run a blacklist check immediately."""
    print("Starting immediate blacklist check...")
    print(f"DNSBL zones: {len(settings.dnsbl_zones_list)}")

    # Initialize providers
    providers = create_dnsbl_providers(
        zones=settings.dnsbl_zones_list,
        timeout=settings.dnsbl_timeout,
    )

    # Initialize Slack notifier
    slack = SlackNotifier(
        webhook_url=settings.slack_webhook_url,
        enabled=settings.slack_enabled,
    )

    # Initialize checker
    checker = BlacklistCheckerService(
        providers=providers,
        slack_notifier=slack,
        max_concurrent_checks=settings.check_max_concurrent,
    )

    # Run check
    async with AsyncSessionLocal() as db:
        results = await checker.run_scheduled_check(db)

    print("\n" + "=" * 60)
    print("CHECK COMPLETE")
    print("=" * 60)
    print(f"\nTotal checked: {results['total_checked']}")
    print(f"Newly blacklisted: {len(results['newly_blacklisted'])}")
    print(f"Newly clean: {len(results['newly_clean'])}")
    print(f"Still blacklisted: {len(results['still_blacklisted'])}")
    print(f"Still clean: {len(results['still_clean'])}")
    print(f"Errors: {len(results['errors'])}")

    if results['newly_blacklisted']:
        print("\nNewly blacklisted IPs:")
        for item in results['newly_blacklisted']:
            print(f"  - {item['ip']}: {[s['provider'] for s in item['sources']]}")

    if results['errors']:
        print("\nErrors:")
        for item in results['errors']:
            print(f"  - {item['ip']}: {item['error']}")

    # Cleanup
    await checker.close()
    await slack.close()


if __name__ == "__main__":
    asyncio.run(main())
