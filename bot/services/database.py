"""
HTTP client for the Django ledger API.

The Telegram bot runs on a separate server from Django, so it talks to
Django over HTTP. The dict shapes returned here mirror the JSON sent by
`finance/api.py` so call sites in handlers don't need to know.
"""
import logging
from typing import Optional, List, Dict, Tuple

import aiohttp

from bot.config.settings import get_settings


logger = logging.getLogger(__name__)


_session: Optional[aiohttp.ClientSession] = None


def _get_session() -> aiohttp.ClientSession:
    """Lazily build a single shared aiohttp session.

    Created on first use so it binds to the running event loop.
    """
    global _session
    if _session is None or _session.closed:
        settings = get_settings()
        timeout = aiohttp.ClientTimeout(total=settings.BOT_REQUEST_TIMEOUT)
        _session = aiohttp.ClientSession(
            base_url=settings.DJANGO_API_URL,
            timeout=timeout,
            headers={'X-Bot-Token': settings.BOT_API_TOKEN},
        )
    return _session


async def close_session() -> None:
    """Close the shared session on shutdown."""
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
    _session = None


async def _get(path: str, params: Optional[Dict] = None) -> Optional[Dict]:
    """GET helper. Returns parsed JSON, or None on 404."""
    session = _get_session()
    try:
        async with session.get(path, params=params) as resp:
            if resp.status == 404:
                return None
            if resp.status == 401:
                logger.error("Django API rejected bot token (401). Check BOT_API_TOKEN matches on both servers.")
                resp.raise_for_status()
            resp.raise_for_status()
            return await resp.json()
    except aiohttp.ClientError:
        logger.exception("HTTP call to Django failed: %s", path)
        raise


class CustomerService:
    """HTTP-backed customer queries."""

    @staticmethod
    async def get_all_customers() -> List[Dict]:
        data = await _get('/api/bot/customers/')
        return (data or {}).get('results', [])

    @staticmethod
    async def get_customer_by_phone(phone: str) -> Optional[Dict]:
        return await _get('/api/bot/customers/by-phone/', params={'phone': phone})

    @staticmethod
    async def get_customer_summary(customer_id: int) -> Optional[Dict]:
        return await _get(f'/api/bot/customers/{customer_id}/summary/')

    @staticmethod
    async def get_customer_combined_data(customer_id: int) -> Tuple[List[Dict], Optional[Dict]]:
        """Return (combined_data, customer) to match the previous tuple shape."""
        data = await _get(f'/api/bot/customers/{customer_id}/combined/')
        if not data:
            return [], None
        return data.get('combined_data', []), data.get('customer')


class SupplierService:
    """HTTP-backed supplier queries."""

    @staticmethod
    async def get_supplier_by_phone(phone: str) -> Optional[Dict]:
        return await _get('/api/bot/suppliers/by-phone/', params={'phone': phone})

    @staticmethod
    async def get_supplier_report(supplier_id: int) -> Optional[Dict]:
        return await _get(f'/api/bot/suppliers/{supplier_id}/report/')
