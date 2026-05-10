"""
Bot configuration settings
"""
from pathlib import Path
from decouple import config as decouple_config


def load_env():
    """Load environment variables from .env file"""
    env_file = Path(__file__).parent.parent.parent / '.env'
    if env_file.exists():
        from dotenv import load_dotenv
        load_dotenv(env_file)


class Settings:
    """Bot settings"""

    # Telegram Bot
    BOT_TOKEN = decouple_config('BOT_TOKEN', default='')

    # Django HTTP API (the bot lives on a separate host)
    DJANGO_API_URL = decouple_config('DJANGO_API_URL', default='').rstrip('/')
    BOT_API_TOKEN = decouple_config('BOT_API_TOKEN', default='')

    @classmethod
    def _normalize_api_url(cls, url: str) -> str:
        """aiohttp's base_url requires a scheme; prepend http:// if missing."""
        if url and '://' not in url:
            url = 'http://' + url
        return url

    # Network — proxy & timeouts (helpful when the server's network
    # blocks/throttles Telegram API; e.g. Russia-hosted VPS)
    # Examples:
    #   socks5://user:pass@1.2.3.4:1080
    #   http://user:pass@1.2.3.4:8080
    BOT_PROXY_URL = decouple_config('BOT_PROXY_URL', default='')
    BOT_REQUEST_TIMEOUT = decouple_config('BOT_REQUEST_TIMEOUT', default=60, cast=int)
    BOT_POLLING_TIMEOUT = decouple_config('BOT_POLLING_TIMEOUT', default=30, cast=int)

    # Logging
    LOG_LEVEL = decouple_config('LOG_LEVEL', default='INFO')

    # PDF Settings
    PDF_TEMP_DIR = Path(__file__).parent.parent.parent / 'temp_pdfs'

    def __init__(self):
        """Validate settings on initialization"""
        if not self.BOT_TOKEN:
            raise ValueError("BOT_TOKEN is not set in environment variables")
        if not self.DJANGO_API_URL:
            raise ValueError("DJANGO_API_URL is not set in environment variables")
        if not self.BOT_API_TOKEN:
            raise ValueError("BOT_API_TOKEN is not set in environment variables")

        self.DJANGO_API_URL = self._normalize_api_url(self.DJANGO_API_URL)

        # Create temp directory if it doesn't exist
        self.PDF_TEMP_DIR.mkdir(exist_ok=True)


def get_settings() -> Settings:
    """Get bot settings instance"""
    return Settings()
