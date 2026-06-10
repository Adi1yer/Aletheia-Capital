"""Application settings and configuration"""

from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Alpaca API (required for trading, optional for testing)
    alpaca_api_key: Optional[str] = None
    alpaca_secret_key: Optional[str] = None
    alpaca_base_url: str = "https://paper-api.alpaca.markets/v2"

    # Optional second paper account for biotech catalyst experiments (isolated from main pipeline)
    biotech_alpaca_api_key: Optional[str] = None
    biotech_alpaca_secret_key: Optional[str] = None

    # Shared satellite book: hedge + options + congressional + macro ETF + crypto
    hedge_alpaca_api_key: Optional[str] = None
    hedge_alpaca_api_secret_key: Optional[str] = None
    hedge_alpaca_secret_key: Optional[str] = None
    multi_sleeve_alpaca_api_key: Optional[str] = None
    multi_sleeve_alpaca_api_secret_key: Optional[str] = None
    multi_sleeve_alpaca_secret_key: Optional[str] = None  # legacy alias

    # LLM API Keys (optional - use free tiers)
    deepseek_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    groq_api_key: Optional[str] = None

    # Data API Keys
    alpha_vantage_api_key: Optional[str] = None
    finnhub_api_key: Optional[str] = None  # Insider + analyst data (free tier: 60/min)
    congressional_api_key: Optional[
        str
    ] = None  # FinBrain House Trades (optional, Finnhub also has congressional)
    coingecko_api_key: Optional[str] = None  # CoinGecko (optional, free tier works without key)
    crypto_enabled: bool = False  # Set True to add crypto provider and enable --crypto pipeline
    daily_snapshots_dir: str = (
        "data/daily_snapshots"  # Daily Alpaca JSON per account (stock / biotech)
    )
    scan_cache_dir: str = "data/scan_cache"  # Base directory for scan cache runs
    # 0 = never auto-delete cached runs (retain all history). >0 = prune runs older than N weeks.
    scan_cache_keep_weeks: int = 26

    # Biotech catalyst scanner — watchlist file (one ticker per line); BIOTECH_TICKERS env overrides.
    biotech_watchlist_path: str = "config/biotech_watchlist.txt"
    # Include trials whose primary/completion date falls in [today - grace, today + forward] (catalyst window).
    biotech_readout_forward_days: int = 120
    biotech_readout_past_grace_days: int = 45
    # Catalyst-first discovery (broad universe): cap mega-names, optional blocklist, phase/readout caps.
    biotech_discovery_min_market_cap_usd: float = 500_000_000.0  # 0 disables minimum
    biotech_discovery_max_market_cap_usd: float = 50_000_000_000.0  # 0 or negative disables maximum
    biotech_discovery_exclude_missing_market_cap: bool = True
    biotech_discovery_blocklist_path: str = "config/biotech_discovery_blocklist.txt"
    biotech_discovery_min_phase: int = 2  # 0 = no phase filter; 2 = Phase 2+ trials only
    # 0 = use full forward_days upper bound; >0 caps to today+min(forward, this)
    biotech_discovery_readout_max_forward_days: int = 90
    biotech_mechanical_arm_enabled: bool = True
    biotech_llm_gated_arm_enabled: bool = True
    biotech_thesis_ledger_path: str = "data/biotech/thesis_ledger.jsonl"
    biotech_policy_path: str = "config/biotech_policy.json"
    biotech_learning_blocklist_path: str = "config/biotech_learning_blocklist.txt"

    # Email Configuration (for notifications)
    smtp_server: Optional[str] = None  # e.g., 'smtp.gmail.com'
    smtp_port: int = 587
    sender_email: Optional[str] = None
    sender_password: Optional[str] = None  # Use app password for Gmail
    recipient_email: Optional[str] = None  # Default recipient for notifications
    biotech_recipient_email: Optional[
        str
    ] = None  # Optional dedicated recipient for biotech-only summary

    # Configuration
    trading_frequency: str = "weekly"
    log_level: str = "INFO"
    environment: str = "production"
    alert_webhook_url: Optional[str] = None
    workflow_accounts_path: str = "config/workflow_accounts.yaml"
    fund_allocation_path: str = "config/fund_allocation.json"
    fund_metrics_path: str = "data/fund/weekly_metrics.json"
    enable_short_selling: bool = False
    max_short_position_pct: float = 0.05
    ibkr_gateway_host: Optional[str] = None
    ibkr_gateway_port: int = 4002


# Global settings instance
settings = Settings()
