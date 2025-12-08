# src/skills/vital_knowledge/research_test.py
#
# TEST VERSION: New approach to ticker-specific Vital Knowledge extraction
# - Navigates to "Everything" tab
# - Extracts all report links with dates from the page
# - Filters by date constraint (today back to N days ago at 12pm ET)
# - Opens each matching report and extracts ticker-specific news for ALL tickers
# - Combines results per ticker, weighting newer articles more

import asyncio
import os
from datetime import datetime, timedelta
from typing import Optional, List, Dict
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


class TickerBullets(BaseModel):
    """Extracted bullets for a specific ticker from a report."""
    bullets: List[str] = Field(default_factory=list, description="List of bullet points about the ticker, max 5 per report")


class TickerSummary(BaseModel):
    """Summary for a ticker across all reports."""
    overall_sentiment: Optional[str] = Field(default=None, description="bullish, bearish, mixed, or neutral")
    key_themes: List[str] = Field(default_factory=list, description="2-3 main themes")
    summary: Optional[str] = Field(default=None, description="1-2 sentence summary")


class ArticleSource(BaseModel):
    """Source article that was scraped."""
    title: str = Field(..., description="Report title")
    date_str: str = Field(..., description="Date string (e.g., 'Dec 3, 2025 02:20 AM')")
    category: str = Field(..., description="Report category (MORNING, MARKET CLOSE, etc.)")


class TickerReport(BaseModel):
    """Complete report for a single ticker."""
    ticker: str = Field(..., description="Stock ticker symbol")
    bullets: List[str] = Field(default_factory=list, description="Top 5 bullets, weighted by importance/recency")
    summary: Optional[TickerSummary] = Field(default=None, description="Overall summary for this ticker")
    sources: List[ArticleSource] = Field(default_factory=list, description="Reports that mentioned this ticker")
    report_count: int = Field(default=0, description="Number of reports that mentioned this ticker")


class BatchTickerResult(BaseModel):
    """Results for all tickers from batch processing."""
    tickers: List[TickerReport] = Field(default_factory=list, description="Results per ticker")
    total_reports_processed: int = Field(default=0, description="Total reports opened")
    date_range: str = Field(default="", description="Date range of reports included")


# =============================================================================
# CONSTANTS
# =============================================================================

TICKER_EXTRACTION_INSTRUCTION = """You are analyzing a Vital Knowledge market report to extract news specific to a particular stock ticker.

Your job is to find and extract ONLY information that DIRECTLY impacts the specified ticker.

INSTRUCTIONS:

1. Read the ENTIRE report carefully.

2. Look for mentions of:
   - The ticker symbol itself (e.g., "AAPL", "GOOGL")
   - The company name (e.g., "Apple", "Alphabet/Google")
   - Products, services, or executives directly tied to that company
   - Analyst ratings, price targets, or earnings for that company
   - Sector news that SPECIFICALLY names or impacts that company

3. DO NOT include:
   - General market/macro news (unless it specifically names the ticker)
   - Sector news that doesn't mention the specific company
   - News about competitors (unless comparing directly to the ticker)

4. For each bullet point:
   - Be specific and include numbers when available (price targets, % moves, earnings figures)
   - Explain WHY it matters for the stock
   - Keep it concise but informative (1-2 sentences)

5. Return up to 5 bullet points. If there is NO news about this ticker in the report, return an empty list.

OUTPUT FORMAT:
Return a list of bullet points, each being a complete, actionable piece of information about the ticker."""


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
        formats = [
            "%b %d, %Y %I:%M %p",  # "Dec 3, 2025 05:20 AM"
            "%B %d, %Y %I:%M %p",  # "December 3, 2025 05:20 AM"
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(date_str, fmt)
                return dt
            except ValueError:
                continue

        # Try date only
        date_only_formats = [
            "%b %d, %Y",  # "Dec 3, 2025"
            "%B %d, %Y",  # "December 3, 2025"
        ]

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
    """
    et = ZoneInfo('US/Eastern')
    now_et = datetime.now(et)
    end_date = now_et
    start_day = now_et - timedelta(days=days_back)
    start_date = start_day.replace(hour=12, minute=0, second=0, microsecond=0)
    return start_date, end_date


def is_in_date_range(report_date: datetime, start_date: datetime, end_date: datetime) -> bool:
    """Check if report date falls within the constraint range."""
    if report_date.tzinfo is None:
        et = ZoneInfo('US/Eastern')
        report_date = report_date.replace(tzinfo=et)
    return start_date <= report_date <= end_date


# =============================================================================
# CONVERSION FUNCTION
# =============================================================================

def _convert_ticker_report_to_vital_knowledge_report(ticker_report: TickerReport):
    """Convert TickerReport to VitalKnowledgeReport for compatibility."""
    # Import here to avoid circular dependency
    from src.skills.vital_knowledge.research import (
        VitalKnowledgeReport,
        VitalKnowledgeHeadline,
        VitalKnowledgeSummary,
    )
    
    # Convert bullets to headlines
    headlines = [
        VitalKnowledgeHeadline(
            headline=bullet,
            context=None,
            sentiment=None,
        )
        for bullet in ticker_report.bullets
    ]
    
    # Convert summary
    summary = None
    if ticker_report.summary:
        summary = VitalKnowledgeSummary(
            overall_sentiment=ticker_report.summary.overall_sentiment,
            key_themes=ticker_report.summary.key_themes,
            summary=ticker_report.summary.summary,
        )
    
    # Extract report dates from sources
    report_dates = []
    seen_dates = set()
    for source in ticker_report.sources:
        # Try to parse date from date_str and format as YYYY-MM-DD
        parsed_date = parse_vital_date(source.date_str)
        if parsed_date:
            date_str = parsed_date.strftime("%Y-%m-%d")
            if date_str not in seen_dates:
                seen_dates.add(date_str)
                report_dates.append(date_str)
    
    return VitalKnowledgeReport(
        ticker=ticker_report.ticker,
        headlines=headlines,
        report_dates=report_dates,
        summary=summary,
    )


# =============================================================================
# MAIN SCRAPING FUNCTION
# =============================================================================

async def fetch_vital_knowledge_headlines_batch(
    page,
    tickers: List[str],
    days_back: Optional[int] = None,
):
    """
    Fetch ticker-specific news from Vital Knowledge for multiple tickers.

    This function:
    1. Logs in to vitalknowledge.net
    2. Navigates to "Everything" tab
    3. Extracts all report links with dates
    4. Filters by date constraint (today back to N days ago at 12pm ET)
    5. Opens each matching report and extracts news for ALL tickers
    6. Combines results per ticker, weighting newer articles more

    Args:
        page: A StagehandPage instance
        tickers: List of stock ticker symbols (e.g., ["AAPL", "GOOGL"])
        days_back: Number of days to look back (defaults to env var Vital_Days_Back or 2)

    Returns:
        List[VitalKnowledgeReport] - one per ticker, compatible with existing code
    """
    # Get days_back from parameter, env var, or default
    if days_back is None:
        days_back = int(os.getenv("Vital_Days_Back", "2"))
    
    print(f"[VitalKnowledge] Starting batch scrape for {len(tickers)} tickers: {tickers}")
    print(f"[VitalKnowledge] Days back: {days_back}")

    # ========================================================================
    # STEP 1: LOGIN TO VITAL KNOWLEDGE
    # ========================================================================
    username = os.getenv("Vital_login")
    password = os.getenv("Vital_password")

    if not username or not password:
        raise ValueError("Missing Vital_login or Vital_password in .env")

    print("[Research] Navigating to login page...")
    await page.goto("https://vitalknowledge.net/login", wait_until="networkidle", timeout=30000)

    print("[Research] Entering credentials...")
    await page.act(f"Enter '{username}' into the username or email input field")
    await page.act(f"Enter '{password}' into the password input field")
    await page.act("Click the login or sign in button")
    await page.wait_for_load_state("networkidle", timeout=30000)
    print("[Research] Login successful")

    # Get date constraint
    start_date, end_date = get_date_constraint(days_back)
    print(f"[Research] Date constraint: {start_date.strftime('%Y-%m-%d %H:%M %Z')} to {end_date.strftime('%Y-%m-%d %H:%M %Z')}")

    # Initialize per-ticker data: ticker -> list of (bullet, weight, source)
    ticker_data: Dict[str, List[tuple[str, float, ArticleSource]]] = {t: [] for t in tickers}

    try:
        # ========================================================================
        # STEP 2: NAVIGATE TO "EVERYTHING" TAB
        # ========================================================================
        print("[Research] Navigating to 'Everything' tab...")
        await page.act("Click on the 'Everything' link or button in the navigation")
        await page.wait_for_load_state("networkidle", timeout=15000)
        await asyncio.sleep(2)

        # ========================================================================
        # STEP 3: EXTRACT ALL REPORT LINKS WITH DATES
        # ========================================================================
        print("[Research] Extracting report links from Everything page...")

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
            print("[VitalKnowledge] No reports found on Everything page")
            from src.skills.vital_knowledge.research import VitalKnowledgeReport
            return [VitalKnowledgeReport(ticker=t) for t in tickers]

        print(f"[Research] Found {len(links_result.reports)} total reports on page")

        # ========================================================================
        # STEP 4: PARSE DATES AND FILTER BY CONSTRAINT
        # ========================================================================
        print("[Research] Parsing dates and filtering by constraint...")

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
            print("[VitalKnowledge] No reports match the date constraint")
            from src.skills.vital_knowledge.research import VitalKnowledgeReport
            return [VitalKnowledgeReport(ticker=t) for t in tickers]

        print(f"[Research] {len(valid_reports)} reports match date constraint")

        # ========================================================================
        # STEP 5: PROCESS EACH REPORT - EXTRACT FOR ALL TICKERS
        # ========================================================================
        reports_processed = 0

        for i, report in enumerate(valid_reports):
            print(f"\n[Research] Processing report {i+1}/{len(valid_reports)}: {report.title}")

            try:
                # Click/open the report link
                observe_results = await page.observe(
                    f"Find the report link with the title '{report.title}' or text matching '{report.title[:50]}...'"
                )

                if observe_results:
                    await page.act(observe_results[0])
                else:
                    await page.act(f"Click the link with the title '{report.title}'")

                await asyncio.sleep(3)
                await page.wait_for_load_state("networkidle", timeout=15000)

                # Calculate weight for this report (newer = higher weight)
                weight = 1.0 - (i * 0.5 / max(len(valid_reports) - 1, 1))

                # Create source info
                source = ArticleSource(
                    title=report.title,
                    date_str=report.date_str,
                    category=report.category,
                )

                # Extract for each ticker
                for ticker in tickers:
                    print(f"  [Research] Extracting {ticker} from report...")

                    extract_result = await page.extract(
                        instruction=f"""{TICKER_EXTRACTION_INSTRUCTION}

                        TICKER TO FIND: {ticker}

                        Extract news ONLY about {ticker}. Return up to 5 bullet points.
                        If there is no news about {ticker}, return an empty list.
                        """,
                        schema=TickerBullets,
                    )

                    if extract_result and extract_result.bullets:
                        for bullet in extract_result.bullets[:5]:
                            ticker_data[ticker].append((bullet, weight, source))
                        print(f"    [OK] Found {len(extract_result.bullets)} bullets for {ticker}")
                    else:
                        print(f"    [--] No news for {ticker}")

                reports_processed += 1

                # Navigate back to Everything page for next report
                if i < len(valid_reports) - 1:
                    print("[Research] Navigating back to Everything page...")
                    await page.goto("https://vitalknowledge.net/", wait_until="networkidle", timeout=15000)
                    await page.act("Click on the 'Everything' link or button in the navigation")
                    await page.wait_for_load_state("networkidle", timeout=15000)
                    await asyncio.sleep(2)

            except Exception as e:
                print(f"  [ERROR] Error processing report: {e}")
                continue

        # ========================================================================
        # STEP 6: COMBINE AND WEIGHT RESULTS PER TICKER
        # ========================================================================
        print(f"\n[Research] Combining results for {len(tickers)} tickers...")

        ticker_results: List[TickerReport] = []

        for ticker in tickers:
            print(f"\n[Research] Processing {ticker}...")

            data = ticker_data[ticker]

            if not data:
                print(f"  [--] No bullets found for {ticker}")
                ticker_results.append(TickerReport(ticker=ticker))
                continue

            # Sort by weight (highest first)
            data.sort(key=lambda x: x[1], reverse=True)

            # Take top 5 bullets
            top_bullets = [bullet for bullet, _, _ in data[:5]]

            # Get unique sources that mentioned this ticker
            seen_sources = set()
            sources = []
            for _, _, source in data:
                key = source.title
                if key not in seen_sources:
                    seen_sources.add(key)
                    sources.append(source)

            print(f"  [OK] {len(top_bullets)} bullets from {len(sources)} reports")

            # Generate summary
            summary = None
            if top_bullets:
                print(f"  [Research] Generating summary for {ticker}...")

                bullets_text = "\n".join(f"- {b}" for b in top_bullets)

                try:
                    summary = await page.extract(
                        instruction=f"""
                        Based on these Vital Knowledge bullets about {ticker}:

                        {bullets_text}

                        Provide:
                        - overall_sentiment: Must be exactly one of: "bullish", "bearish", "mixed", or "neutral"
                        - key_themes: List 2-3 main themes (e.g., ["earnings beat", "analyst upgrade", "product launch"])
                        - summary: Write a very brief 1-2 sentence summary of the key points about {ticker}
                        """,
                        schema=TickerSummary,
                    )
                except Exception as e:
                    print(f"    [WARN] Could not generate summary: {e}")

            ticker_results.append(TickerReport(
                ticker=ticker,
                bullets=top_bullets,
                summary=summary,
                sources=sources,
                report_count=len(sources),
            ))

        # Convert TickerReport to VitalKnowledgeReport for compatibility
        vital_knowledge_reports = [
            _convert_ticker_report_to_vital_knowledge_report(ticker_report)
            for ticker_report in ticker_results
        ]

        print(f"\n[VitalKnowledge] Complete! Processed {reports_processed} reports for {len(tickers)} tickers")
        return vital_knowledge_reports

    except Exception as e:
        print(f"[VitalKnowledge] Failed: {e}")
        import traceback
        traceback.print_exc()
        from src.skills.vital_knowledge.research import VitalKnowledgeReport
        return [VitalKnowledgeReport(ticker=t) for t in tickers]


# =============================================================================
# STANDALONE TEST FUNCTION
# =============================================================================

async def test_research(tickers: List[str] = None, days_back: int = 2):
    """
    Test the Research scraper standalone.

    Usage (from project root):
        python -m src.skills.vital_knowledge.research_test
        python -m src.skills.vital_knowledge.research_test 3  # look back 3 days
    """
    import json
    from pathlib import Path
    from src.core.stagehand_runner import create_stagehand_session

    # Load tickers from watchlist if not provided
    if tickers is None:
        watchlist_path = Path(__file__).parent.parent.parent.parent / "config" / "watchlist.json"
        with open(watchlist_path) as f:
            tickers = json.load(f)

    print(f"\n{'='*60}")
    print(f"Testing Vital Knowledge Research Scraper")
    print(f"Tickers: {tickers}")
    print(f"Days back: {days_back}")
    print(f"{'='*60}\n")

    stagehand = None
    try:
        stagehand, page = await create_stagehand_session()
        results = await fetch_vital_knowledge_headlines_batch(page, tickers, days_back=days_back)

        print(f"\n{'='*60}")
        print("RESULTS")
        print(f"{'='*60}\n")

        for result in results:
            print(f"\n--- {result.ticker} ---")
            print(f"Report dates: {result.report_dates}")

            if result.headlines:
                print(f"Headlines ({len(result.headlines)}):")
                for i, headline in enumerate(result.headlines, 1):
                    print(f"  {i}. {headline.headline}")
            else:
                print("  No news found")

            if result.summary:
                print(f"Sentiment: {result.summary.overall_sentiment}")
                print(f"Themes: {result.summary.key_themes}")
                print(f"Summary: {result.summary.summary}")

        return results

    finally:
        if stagehand:
            await stagehand.close()
            print("\n[Research] Browser session closed")


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

    asyncio.run(test_research(days_back=days_back))
