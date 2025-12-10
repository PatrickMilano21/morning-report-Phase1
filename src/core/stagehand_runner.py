import os
from datetime import date
from typing import Optional

from dotenv import load_dotenv
from stagehand import Stagehand, StagehandConfig

load_dotenv()


def get_browserbase_region() -> str:
    return os.getenv("BROWSERBASE_REGION", "us-west-2")


def get_browserbase_keep_alive() -> bool:
    return os.getenv("BROWSERBASE_KEEP_ALIVE", "true").lower() == "true"


def get_browserbase_timeout() -> int:
    # Browserbase expects seconds; default 15 minutes = 900 seconds
    # Max allowed: 21600 seconds (6 hours)
    return int(os.getenv("BROWSERBASE_TIMEOUT", "900"))


def get_stagehand_verbose() -> int:
    val = os.getenv("STAGEHAND_VERBOSE", "0")
    try:
        return int(val)
    except ValueError:
        return 0


async def create_stagehand_session(
    source: Optional[str] = None,
    ticker: Optional[str] = None,
    run_id: Optional[str] = None,
):
    """Create and initialize a Stagehand session using Browserbase.

    Args:
        source: Source name for session identification (e.g., "YahooQuote", "GoogleNews")
        ticker: Ticker symbol(s) for session identification (e.g., "NVDA" or "NVDA,AAPL")
        run_id: Run identifier (defaults to "morning_snapshot_YYYY-MM-DD")
    """
    model_name = os.getenv("STAGEHAND_MODEL_NAME", "gpt-4.1-mini")

    # Build user metadata for session identification in Browserbase dashboard
    user_metadata = {}
    if source:
        user_metadata["source"] = source
    if ticker:
        user_metadata["ticker"] = ticker
    # Always include run_id for daily tracking
    user_metadata["run_id"] = run_id or f"morning_snapshot_{date.today().isoformat()}"

    browser_settings = {}

    if os.getenv("BROWSERBASE_ADVANCED_STEALTH", "false").lower() in ("true", "1", "yes"):
        browser_settings["advanced_stealth"] = True
        print("[Stagehand] Advanced Stealth Mode enabled (requires Scale Plan)")
    else:
        print("[Stagehand] Using Basic Stealth Mode (enabled automatically on Startup+ plans)")

    if os.getenv("BROWSERBASE_SOLVE_CAPTCHAS", "true").lower() in ("false", "0", "no"):
        browser_settings["solveCaptchas"] = False
        print("[Stagehand] CAPTCHA solving disabled")

    captcha_image_selector = os.getenv("BROWSERBASE_CAPTCHA_IMAGE_SELECTOR")
    captcha_input_selector = os.getenv("BROWSERBASE_CAPTCHA_INPUT_SELECTOR")

    if captcha_image_selector and captcha_input_selector:
        browser_settings["captchaImageSelector"] = captcha_image_selector
        browser_settings["captchaInputSelector"] = captcha_input_selector
        print(f"[Stagehand] Custom CAPTCHA selectors configured")

    use_proxies = os.getenv("BROWSERBASE_USE_PROXIES", "true").lower() in ("true", "1", "yes")

    if use_proxies:
        print("[Stagehand] Proxies enabled (recommended for CAPTCHA solving)")
    else:
        print("[Stagehand] Proxies disabled")
    
    config = StagehandConfig(
        env="BROWSERBASE",
        api_key=os.getenv("BROWSERBASE_API_KEY"),
        project_id=os.getenv("BROWSERBASE_PROJECT_ID"),
        model_name=model_name,
        model_api_key=os.getenv("OPENAI_API_KEY"),
        verbose=get_stagehand_verbose(),
        dom_settle_timeout_ms=int(
            os.getenv("STAGEHAND_DOM_SETTLE_TIMEOUT_MS", "15000")
        ),
        self_heal=True,
        browser_settings=browser_settings if browser_settings else None,
        proxies=use_proxies,
        browserbase_session_create_params={
            "region": get_browserbase_region(),
            "keepAlive": get_browserbase_keep_alive(),
            "timeout": get_browserbase_timeout(),
            "userMetadata": user_metadata,
        },
    )

    stagehand = Stagehand(config)
    await stagehand.init()
    page = stagehand.page
    return stagehand, page
