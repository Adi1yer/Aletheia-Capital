"""Application settings and configuration"""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Alpaca API (required for trading, optional for testing)
    alpaca_api_key: Optional[str] = None
    alpaca_secret_key: Optional[str] = None
    alpaca_base_url: str = "https://paper-api.alpaca.markets/v2"

    # Optional second paper account for biotech catalyst experiments (isolated from main pipeline)
    biotech_alpaca_api_key: Optional[str] = None
    biotech_alpaca_secret_key: Optional[str] = None
    
    # LLM API Keys (optional - use free tiers)
    deepseek_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    groq_api_key: Optional[str] = None
    
    # Data API Keys
    alpha_vantage_api_key: Optional[str] = None
    finnhub_api_key: Optional[str] = None  # Insider + analyst data (free tier: 60/min)
    congressional_api_key: Optional[str] = None  # FinBrain House Trades (optional, Finnhub also has congressional)
    coingecko_api_key: Optional[str] = None  # CoinGecko (optional, free tier works without key)
    crypto_enabled: bool = False  # Set True to add crypto provider and enable --crypto pipeline
    scan_cache_dir: str = "data/scan_cache"  # Base directory for scan cache runs
    scan_cache_keep_weeks: int = 260  # Keep 5 years of weekly runs for internal analysis without API calls (0 = disable prune)
    
    # Email Configuration (for notifications)
    smtp_server: Optional[str] = None  # e.g., 'smtp.gmail.com'
    smtp_port: int = 587
    sender_email: Optional[str] = None
    sender_password: Optional[str] = None  # Use app password for Gmail
    recipient_email: Optional[str] = None  # Default recipient for notifications
    
    # Configuration
    trading_frequency: str = "weekly"
    log_level: str = "INFO"
    environment: str = "production"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# Global settings instance
settings = Settings()

