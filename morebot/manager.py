import logging
import json
import aiohttp
from typing import Dict, Any, Optional
from collections import defaultdict

from config import morebot_settings

logger = logging.getLogger("uvicorn.error")


class Morebot:
    _timeout = 3
    _failed_reports: Dict[int, int] = defaultdict(int)

    @classmethod
    def _base_url(cls) -> str:
        return f"https://{morebot_settings.license}.morebot.top/api/subscriptions/{morebot_settings.secret}"

    @classmethod
    async def report_admin_usage(
        cls,
        admin_usage: Dict[int, int],
        admin_usernames: Dict[int, str],
    ) -> bool:
        """
        Report admin usage to Morebot. Merges any previously failed reports
        before sending.

        Args:
            admin_usage: Mapping of admin_id -> bytes used in current cycle.
            admin_usernames: Mapping of admin_id -> username (for the report payload).
        """
        if not admin_usage:
            return True

        current_total = sum(admin_usage.values())
        failed_total = sum(cls._failed_reports.values())

        logger.info(f"📊 New usage total: {current_total / (1024**3):.2f} GB")
        logger.info(f"📊 Previous failed usage total: {failed_total / (1024**3):.2f} GB")

        # Merge failed reports from previous cycles with the current cycle
        total_admin_usage: Dict[int, int] = defaultdict(int)
        for admin_id, failed_usage in cls._failed_reports.items():
            total_admin_usage[admin_id] += failed_usage
        for admin_id, current_usage in admin_usage.items():
            total_admin_usage[admin_id] += current_usage

        total_to_report = sum(total_admin_usage.values())
        logger.info(f"📊 Total to report: {total_to_report / (1024**3):.2f} GB")

        report_data = [
            {"username": admin_usernames.get(admin_id, "Unknown"), "usage": int(value)}
            for admin_id, value in total_admin_usage.items()
            if value > 0
        ]

        if not report_data:
            return True

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{cls._base_url()}/usages",
                    json=report_data,
                    timeout=cls._timeout,
                ) as response:
                    response.raise_for_status()
                    logger.info(f"✅ Report sent successfully - Total: {total_to_report / (1024**3):.2f} GB")
                    cls._failed_reports.clear()
                    return True
        except Exception as e:
            logger.error(f"❌ Report failed: {str(e)}")
            # Persist the current cycle's usage so it is included next time
            for admin_id, usage in admin_usage.items():
                cls._failed_reports[admin_id] += usage
            new_failed_total = sum(cls._failed_reports.values())
            logger.info(f"📊 Failed usage saved: {new_failed_total / (1024**3):.2f} GB")
            return False
