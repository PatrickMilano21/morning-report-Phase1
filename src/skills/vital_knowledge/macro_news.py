# src/skills/vital_knowledge/macro_news.py
#
# This script scrapes Vital Knowledge for macro market-moving news.
# - Navigates to "Everything" tab
# - Extracts all report links with dates from the page
# - Filters by date constraint (today back to N days ago at 4pm ET)
# - Opens each matching report and extracts macro news
# - Combines results, weighting newer articles more

import asyncio
import os
from datetime import datetime, timedelta
from typing import Optional, List
from pydantic import BaseModel, Field
from zoneinfo import ZoneInfo


# =============================================================================
# DATA MODELS (Pydantic)
# =============================================================================

class ReportLink(BaseModel):
    """A single report link extracted from the Everything page."""
    title: str = Field(..., description="Report title")
    date_str: str = Field(..., description="Date string as shown on page (e.g., 'Dec 3, 2025 05:20 AM')")
    category: str = Field(..., description="Report category (MORNING, MARKET CLOSE, etc.)")
    url: Optional[str] = Field(default=None, description="Report URL if available")
    parsed_date: Optional[datetime] = Field(default=None, description="Parsed datetime object")


class MacroExtract(BaseModel):
    """Helper model for extracting macro news from a report."""
    summary: str = Field(..., description="2-3 sentence overview of the global market backdrop and main drivers")
    bullets: List[str] = Field(..., description="7-10 detailed bullet points with tags like [MACRO], [CENTRAL BANK], [DATA], etc.")


class ArticleSource(BaseModel):
    """Source article that was scraped."""
    title: str = Field(..., description="Report title")
    date_str: str = Field(..., description="Date string (e.g., 'Dec 3, 2025 02:20 AM')")
    category: str = Field(..., description="Report category (MORNING, MARKET CLOSE, etc.)")


class MacroNewsSummary(BaseModel):
    """Container for aggregated macro news from multiple reports."""
    report_count: int = Field(default=0, description="Number of reports processed")
    date_range: str = Field(default="", description="Date range of reports included")
    summary: Optional[str] = Field(default=None, description="2-3 sentence combined summary")
    bullets: List[str] = Field(default_factory=list, description="7-10 detailed bullet points, weighted by importance/recency")
    sources: List[ArticleSource] = Field(default_factory=list, description="List of source articles with dates")


# =============================================================================
# CONSTANTS
# =============================================================================

MACRO_EXTRACTION_INSTRUCTION = """You are a senior macro equity strategist writing a pre-market brief for a hedge fund PM.

You will be given one or more market reports and news summaries.

Your job is to extract and synthesize the MOST IMPORTANT, MARKET-MOVING INFORMATION across:
- Global indices and major asset classes (equities, rates, FX, commodities, credit)
- Key economic data and central bank developments
- Geopolitical events with market impact
- Major sector moves and cross-asset themes
- Individual stock stories that are big enough to matter for the tape

Focus primarily on US equity markets and stocks, though include global context when it impacts US markets.

INSTRUCTIONS

1. Read ALL of the text carefully. Do not skip sections.

2. Identify the 7–10 HIGHEST-IMPACT forces driving markets TODAY.
   - These can be macro, geopolitical, cross-asset, sector-specific, or single-stock.
   - Prioritize by actual or likely market impact, not by article length.

3. For every move you mention, include NUMBERS whenever available:
   - Index/asset moves in % terms (e.g., "S&P futures +0.8%", "10Y UST +7bp").
   - Data surprises vs expectations (e.g., "CPI 3.1% YoY vs 3.3% est").
   - Size of flows, deal sizes, or earnings surprises if given.

4. Always explain the "WHY" behind each move when the text provides it.
   - Link price action ↔ catalyst (data, earnings, policy, geopolitics, positioning, etc.).
   - If the reason is unclear, say that explicitly ("move on light news / positioning / unclear drivers").

OUTPUT FORMAT (VERY IMPORTANT)

Return your answer in this exact structure:

summary:
- A 2–3 sentence overview of the global market backdrop and main drivers.
- It should answer: "What kind of day is this and what's pushing things around?"

bullets:
- A ranked list of 7–10 detailed bullet points.
- Start each bullet with a TAG in ALL CAPS indicating the main bucket:
  - [MACRO], [CENTRAL BANK], [DATA], [GEOPOLITICS], [SECTOR], [STOCK], [FLOW/SENTIMENT]
- Each bullet MUST:
  * Be a complete, self-contained thought.
  * Include specific numbers and percentages whenever they appear in the text.
  * Clearly link the move to its driver ("because / after / on the back of…").
  * Be detailed enough that a PM could trade or adjust risk off that line.
  * Mention time-frame if relevant ("overnight", "this morning", "yesterday's close").

STYLE & SCOPE

- Focus ONLY on information present in the text; do NOT invent numbers or catalysts.
- If multiple sources mention the same theme, MERGE them into one stronger bullet instead of repeating.
- If an item feels important but lacks numbers, still include it but say "no specific numbers given".
- Keep language concise but information-dense; avoid fluff like "investors are watching closely" unless paired with concrete details.

Now read the following material and produce the summary + bullets as specified above."""


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def parse_vital_date(date_str: str) -> Optional[datetime]:
    """
    Parse Vital Knowledge date string to datetime.
    
    Examples:
    - "Dec 3, 2025 05:20 AM" -> datetime(2025, 12, 3, 5, 20)
    - "Dec 2, 2025 04:02 PM" -> datetime(2025, 12, 2, 16, 2)
    """
    try:
        # Try parsing with common formats
        formats = [
            "%b %d, %Y %I:%M %p",  # "Dec 3, 2025 05:20 AM"
            "%B %d, %Y %I:%M %p",   # "December 3, 2025 05:20 AM"
        ]
        
        for fmt in formats:
            try:
                dt = datetime.strptime(date_str, fmt)
                return dt
            except ValueError:
                continue
        
        # If no format matches, try date only
        date_only_formats = [
            "%b %d, %Y",  # "Dec 3, 2025"
            "%B %d, %Y",  # "December 3, 2025"
        ]
        
        # Try to extract just the date part (first 3 words: "Dec 3, 2025")
        date_parts = ' '.join(date_str.split()[:3])
        for fmt in date_only_formats:
            try:
                dt = datetime.strptime(date_parts, fmt)
                return dt
            except ValueError:
                continue
        
        return None
    except Exception:
        return None


def get_date_constraint(days_back: int = 1) -> tuple[datetime, datetime]:
    """
    Get the date range constraint: today back to N days ago at 12pm ET.

    Args:
        days_back: Number of days to go back.
                   1 = yesterday 12pm ET to now
                   2 = 2 days ago 12pm ET to now
                   etc.

    Returns:
        (start_date, end_date) where:
        - start_date: N days ago at 12pm ET
        - end_date: now
    """
    et = ZoneInfo('US/Eastern')
    now_et = datetime.now(et)

    # End date: now
    end_date = now_et

    # Start date: N days ago at 12pm ET (noon)
    start_day = now_et - timedelta(days=days_back)
    start_date = start_day.replace(hour=12, minute=0, second=0, microsecond=0)  # 12pm ET

    return start_date, end_date


def is_in_date_range(report_date: datetime, start_date: datetime, end_date: datetime) -> bool:
    """Check if report date falls within the constraint range."""
    # Convert report_date to ET if it's naive (assume ET)
    if report_date.tzinfo is None:
        et = ZoneInfo('US/Eastern')
        report_date = report_date.replace(tzinfo=et)
    
    return start_date <= report_date <= end_date


# =============================================================================
# MAIN SCRAPING FUNCTION
# =============================================================================

async def fetch_macro_news(page, days_back: int = 2) -> MacroNewsSummary:
    """
    Fetch macro market-moving news from Vital Knowledge using the new approach.

    This function:
    1. Logs in to vitalknowledge.net
    2. Navigates to "Everything" tab
    3. Extracts all report links with dates from the page
    4. Filters links by date constraint (today back to N days ago at 4pm ET)
    5. Opens each matching report (newest to oldest)
    6. Extracts macro news from each report
    7. Combines results, weighting newer articles more

    Args:
        page: A StagehandPage instance
        days_back: Number of days to look back (1 = yesterday 4pm, 2 = 2 days ago 4pm, etc.)

    Returns:
        MacroNewsSummary with aggregated summaries and bullets from all reports
    """
    print(f"[MacroNews] Starting macro news scrape (days_back={days_back})")

    # ========================================================================
    # STEP 1: LOGIN TO VITAL KNOWLEDGE
    # ========================================================================
    username = os.getenv("Vital_login")
    password = os.getenv("Vital_password")

    if not username or not password:
        raise ValueError("Missing Vital_login or Vital_password in .env")

    print("[MacroNews] Navigating to login page...")
    await page.goto("https://vitalknowledge.net/login", wait_until="networkidle", timeout=30000)

    print("[MacroNews] Entering credentials...")
    await page.act(f"Enter '{username}' into the username or email input field")
    await page.act(f"Enter '{password}' into the password input field")
    await page.act("Click the login or sign in button")
    await page.wait_for_load_state("networkidle", timeout=30000)
    print("[MacroNews] Login successful")

    # Get date constraint
    start_date, end_date = get_date_constraint(days_back)
    print(f"[MacroNews] Date constraint: {start_date.strftime('%Y-%m-%d %H:%M %Z')} to {end_date.strftime('%Y-%m-%d %H:%M %Z')}")
    
    try:
        # ========================================================================
        # STEP 2: NAVIGATE TO "EVERYTHING" TAB
        # ========================================================================
        print("[MacroNews] Navigating to 'Everything' tab...")
        await page.act("Click on the 'Everything' link or button in the navigation")
        await page.wait_for_load_state("networkidle", timeout=15000)
        await asyncio.sleep(2)  # Give page time to render
        
        # ========================================================================
        # STEP 3: EXTRACT ALL REPORT LINKS WITH DATES
        # ========================================================================
        print("[MacroNews] Extracting report links from Everything page...")
        
        # Extract all report links with their dates
        # The page shows reports with: category, date/time, title, summary
        class ReportLinksExtract(BaseModel):
            reports: List[ReportLink] = Field(..., description="List of all reports visible on the page")
        
        links_result = await page.extract(
            instruction="""
            On this Vital Knowledge "Everything" page, extract all visible report links.
            
            For each report, extract:
            - title: The report title/headline
            - date_str: The full date and time string as shown (e.g., "Dec 3, 2025 05:20 AM")
            - category: The report category label (MORNING, MARKET CLOSE, INTRADAY, EARNINGS, etc.)
            
            Include ALL reports visible on the page, regardless of category.
            """,
            schema=ReportLinksExtract,
        )
        
        if not links_result or not links_result.reports:
            print("[MacroNews] No reports found on Everything page")
            return MacroNewsSummary()
        
        print(f"[MacroNews] Found {len(links_result.reports)} total reports on page")
        
        # ========================================================================
        # STEP 4: PARSE DATES AND FILTER BY CONSTRAINT
        # ========================================================================
        print("[MacroNews] Parsing dates and filtering by constraint...")
        
        valid_reports: List[ReportLink] = []
        for report in links_result.reports:
            parsed_date = parse_vital_date(report.date_str)
            if parsed_date:
                report.parsed_date = parsed_date
                if is_in_date_range(parsed_date, start_date, end_date):
                    valid_reports.append(report)
                    print(f"  [OK] {report.category}: {report.title} ({report.date_str})")
                else:
                    print(f"  [SKIP] {report.category}: {report.title} ({report.date_str}) - outside date range")
            else:
                print(f"  [WARN] Could not parse date: {report.date_str}")
        
        if not valid_reports:
            print("[MacroNews] No reports match the date constraint")
            return MacroNewsSummary()
        
        print(f"[MacroNews] {len(valid_reports)} reports match date constraint")
        
        # Reports are already in newest-to-oldest order (as shown on page)
        # ========================================================================
        # STEP 5: EXTRACT MACRO NEWS FROM EACH REPORT
        # ========================================================================
        all_summaries: List[str] = []
        all_bullets: List[tuple[str, float]] = []  # (bullet, weight)
        sources_processed: List[ArticleSource] = []
        
        for i, report in enumerate(valid_reports):
            print(f"\n[MacroNews] Processing report {i+1}/{len(valid_reports)}: {report.title}")
            
            try:
                # Click/open the report link
                # Use observe to find the link by title
                observe_results = await page.observe(
                    f"Find the report link with the title '{report.title}' or text matching '{report.title[:50]}...'"
                )
                
                if observe_results:
                    await page.act(observe_results[0])
                else:
                    # Fallback: try to click by title directly
                    await page.act(f"Click the link with the title '{report.title}'")
                
                await asyncio.sleep(3)
                await page.wait_for_load_state("networkidle", timeout=15000)
                
                # Extract macro news using the professional instruction template
                extract_result = await page.extract(
                    instruction=MACRO_EXTRACTION_INSTRUCTION,
                    schema=MacroExtract,
                )
                
                if extract_result:
                    if extract_result.summary:
                        all_summaries.append(extract_result.summary)

                    # Calculate weight: newer reports get higher weight
                    # Weight decreases linearly: newest = 1.0, oldest = 0.5
                    weight = 1.0 - (i * 0.5 / max(len(valid_reports) - 1, 1))

                    for bullet in extract_result.bullets[:10]:  # Limit to 10 bullets per report
                        all_bullets.append((bullet, weight))

                    # Store source with date info
                    sources_processed.append(ArticleSource(
                        title=report.title,
                        date_str=report.date_str,
                        category=report.category,
                    ))
                    print(f"  [OK] Extracted {len(extract_result.bullets)} bullets")
                else:
                    print(f"  [WARN] No content extracted")
                
                # Navigate back to Everything page for next report
                if i < len(valid_reports) - 1:  # Don't navigate back after last report
                    print("[MacroNews] Navigating back to Everything page...")
                    await page.goto("https://vitalknowledge.net/", wait_until="networkidle", timeout=15000)
                    await page.act("Click on the 'Everything' link or button in the navigation")
                    await page.wait_for_load_state("networkidle", timeout=15000)
                    await asyncio.sleep(2)
                
            except Exception as e:
                print(f"  [ERROR] Error processing report: {e}")
                # Continue with next report
                continue
        
        # ========================================================================
        # STEP 6: COMBINE AND WEIGHT RESULTS
        # ========================================================================
        print(f"\n[MacroNews] Combining results from {len(sources_processed)} reports...")

        # Combine summaries (newer reports first)
        combined_summary = " ".join(all_summaries) if all_summaries else None

        # Sort bullets by weight (highest first) and deduplicate similar ones
        # For now, just take top bullets by weight
        all_bullets.sort(key=lambda x: x[1], reverse=True)

        # Take top 10 bullets (weighted by recency/importance)
        final_bullets = [bullet for bullet, _ in all_bullets[:10]]

        # Generate final aggregated summary using the same professional template
        if combined_summary and final_bullets:
            class CombinedSummary(BaseModel):
                summary: str = Field(..., description="2-3 sentence overview of the global market backdrop and main drivers")
                bullets: List[str] = Field(..., description="7-10 detailed bullet points with tags, ranked by importance")

            try:
                # Combine all summaries into one text block for synthesis
                combined_text = "\n\n".join(all_summaries[:5])  # Use top 5 summaries
                
                combined_result = await page.extract(
                    instruction=f"""{MACRO_EXTRACTION_INSTRUCTION}

                    You are synthesizing MULTIPLE reports. Here are summaries from different reports:

                    {combined_text}

                    Your job is to create ONE unified summary and ranked bullet list that captures the most important
                    market-moving information across ALL these reports. Merge duplicate themes into single, stronger bullets.
                    Rank by market impact, not by which report mentioned it first.
                    """,
                    schema=CombinedSummary,
                )
                if combined_result:
                    combined_summary = combined_result.summary
                    # Use synthesized bullets if available (they're already ranked and merged)
                    if combined_result.bullets:
                        final_bullets = combined_result.bullets[:10]
            except Exception as e:
                print(f"[MacroNews] Could not generate combined summary: {e}")
                # Use first summary as fallback
                combined_summary = all_summaries[0] if all_summaries else None

        date_range_str = f"{start_date.strftime('%Y-%m-%d %H:%M ET')} to {end_date.strftime('%Y-%m-%d %H:%M ET')}"

        result = MacroNewsSummary(
            report_count=len(sources_processed),
            date_range=date_range_str,
            summary=combined_summary,
            bullets=final_bullets,
            sources=sources_processed,
        )
        
        print(f"[MacroNews] Complete! Processed {len(sources_processed)} reports, extracted {len(final_bullets)} bullets")
        return result
        
    except Exception as e:
        print(f"[MacroNews] Failed: {e}")
        import traceback
        traceback.print_exc()
        return MacroNewsSummary()


# =============================================================================
# STANDALONE TEST FUNCTION
# =============================================================================

async def test_macro_news(days_back: int = 2):
    """
    Test the Macro News scraper standalone.

    Usage (from project root):
        python -m src.skills.vital_knowledge.macro_news
        python -m src.skills.vital_knowledge.macro_news 3  # look back 3 days
    """
    from src.core.stagehand_runner import create_stagehand_session

    print(f"\n{'='*60}")
    print(f"Testing Vital Knowledge Macro News Scraper (days_back={days_back})")
    print(f"{'='*60}\n")

    stagehand = None
    try:
        stagehand, page = await create_stagehand_session()
        result = await fetch_macro_news(page, days_back=days_back)
        
        print(f"\n{'='*60}")
        print("RESULTS")
        print(f"{'='*60}\n")

        print(f"Reports Processed: {result.report_count}")
        print(f"Date Range: {result.date_range}\n")

        if result.summary:
            print(f"Summary:\n{result.summary}\n")

        if result.bullets:
            print(f"Key Bullets ({len(result.bullets)} total, weighted by importance/recency):")
            for i, bullet in enumerate(result.bullets, 1):
                print(f"  {i}. {bullet}")
            print()

        if result.sources:
            print("Sources:")
            for source in result.sources:
                print(f"  - {source.title} ({source.date_str}) [{source.category}]")
        
        return result
        
    finally:
        if stagehand:
            await stagehand.close()
            print("\n[MacroNews] Browser session closed")


# =============================================================================
# SCRIPT ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv

    load_dotenv()

    # Get days_back from .env (Vital_Days_Back), CLI arg, or default to 2
    days_back = int(os.getenv("Vital_Days_Back", "2"))

    # CLI argument overrides .env
    if len(sys.argv) > 1:
        try:
            days_back = int(sys.argv[1])
        except ValueError:
            print(f"Invalid days_back argument: {sys.argv[1]}, using env value {days_back}")

    asyncio.run(test_macro_news(days_back=days_back))
