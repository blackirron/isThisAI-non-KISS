from dotenv import load_dotenv

load_dotenv()

import os


class Settings:
    APP_NAME: str = "IsThisAI"
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")

    AUTH_TOKEN: str = os.getenv("AUTH_TOKEN", "change-me-locally")

    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "groq")

    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    GROQ_VISION_MODEL: str = os.getenv("GROQ_VISION_MODEL", "qwen/qwen3.6-27b")

    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

    CORS_ORIGINS: list[str] = ["*"]

    # Razorpay — one-time "lifetime Pro" purchase. Test-mode keys (rzp_test_...)
    # work with zero KYC and let you test the full flow with Razorpay's dummy
    # card/UPI right now; swap in live keys (rzp_live_...) once KYC clears.
    RAZORPAY_KEY_ID: str = os.getenv("RAZORPAY_KEY_ID", "")
    RAZORPAY_KEY_SECRET: str = os.getenv("RAZORPAY_KEY_SECRET", "")
    PRO_PRICE_INR: int = int(os.getenv("PRO_PRICE_INR", "499"))


settings = Settings()
