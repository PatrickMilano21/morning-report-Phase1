import os
from dotenv import load_dotenv
from stagehand import Stagehand, StagehandConfig

load_dotenv()


async def create_stagehand_session():
    """Create and initialize a Stagehand session using Browserbase."""
    model_name = os.getenv("STAGEHAND_MODEL_NAME", "gpt-4.1-mini")

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
        verbose=int(os.getenv("STAGEHAND_VERBOSE", "1")),
        dom_settle_timeout_ms=int(
            os.getenv("STAGEHAND_DOM_SETTLE_TIMEOUT_MS", "30000")
        ),
        self_heal=True,
        browser_settings=browser_settings if browser_settings else None,
        proxies=use_proxies,
    )

    stagehand = Stagehand(config)
    await stagehand.init()
    page = stagehand.page
    return stagehand, page
