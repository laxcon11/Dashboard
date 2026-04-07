"""
sensibull_smart_fetch.py
========================
Smart Sensibull Fetcher using the user's actual Chrome profile.
- Borrows existing Zerodha/Sensibull session (no login needed after first time)
- Calculates correct expiry dates dynamically
- Downloads Excel files for each expiry
- Falls back gracefully with manual download URLs if anything fails
"""

import sys
import time
import shutil
import subprocess
from pathlib import Path
from datetime import datetime, timedelta

DOWNLOADS = Path.home() / "Downloads"
PROJECT_ROOT = Path(__file__).parent.parent
TARGET = PROJECT_ROOT / "data" / "option_chain"
CHROME_PROFILE = Path.home() / "Library/Application Support/Google/Chrome"

# =========================================================
# EXPIRY CALCULATOR
# =========================================================
# Known NSE trading holidays (add more as needed)
NSE_HOLIDAYS_2026 = {
    datetime(2026, 1, 26),  # Republic Day
    datetime(2026, 3, 25),  # Holi
    datetime(2026, 4, 14),  # Dr. Ambedkar Jayanti / Good Friday
    datetime(2026, 4, 2),   # Good Friday
    datetime(2026, 5, 1),   # Maharashtra Day
    datetime(2026, 8, 15),  # Independence Day
    datetime(2026, 10, 2),  # Gandhi Jayanti
    datetime(2026, 11, 4),  # Diwali Laxmi Pujan
    datetime(2026, 11, 5),  # Diwali Balipratipada
    datetime(2026, 12, 25), # Christmas
}

def _is_trading_day(d: datetime) -> bool:
    """Returns True if the date is a weekday and not an NSE holiday."""
    if d.weekday() >= 5:  # Saturday or Sunday
        return False
    return d.replace(hour=0, minute=0, second=0, microsecond=0) not in NSE_HOLIDAYS_2026

def _adjust_for_holiday(d: datetime) -> datetime:
    """If expiry date is a holiday, roll back to the previous trading day."""
    while not _is_trading_day(d):
        d -= timedelta(days=1)
    return d

def get_target_expiries(today: datetime = None) -> list[dict]:
    """
    Calculate the correct NIFTY weekly expiry dates.
    NIFTY weekly options expire every Tuesday (rolls to Monday if Tuesday is holiday).
    Returns next 4 Tuesdays + first Tuesday of next month if all 4 are same month.
    """
    if today is None:
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    # Find next upcoming Tuesday (weekday=1)
    days_until_tue = (1 - today.weekday()) % 7
    if days_until_tue == 0:
        days_until_tue = 7  # If today is Tuesday, get next one

    first_tue = today + timedelta(days=days_until_tue)

    # Collect next 4 weekly Tuesdays, adjusting for holidays
    tuesdays = [_adjust_for_holiday(first_tue + timedelta(weeks=i)) for i in range(4)]

    # If all 4 are in the same month, append first Tuesday of next month
    if tuesdays[-1].month == tuesdays[0].month:
        next_month_start = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
        days_to_first_tue = (1 - next_month_start.weekday()) % 7
        next_month_tue = next_month_start + timedelta(days=days_to_first_tue)
        tuesdays.append(_adjust_for_holiday(next_month_tue))

    result = []
    for d in tuesdays:
        result.append({
            "date":            d,
            "display":         d.strftime("%d-%b-%Y"),
            "sensibull_param": d.strftime("%Y-%m-%d"),
            "dl_name":         d.strftime("%d_%b_%Y"),
        })
    return result


# =========================================================
# CHROME-BASED PLAYWRIGHT FETCH
# =========================================================
def fetch_with_chrome_profile(status_callback=None) -> dict:
    """
    Use the user's actual Chrome profile (already has Zerodha/Sensibull session).
    Chrome must be closed for this to work.
    Returns: {"success": bool, "downloaded": [filenames], "failed": [expiry_dicts]}
    """
    def log(msg):
        print(msg)
        if status_callback:
            status_callback(msg)

    expiries = get_target_expiries()
    log(f"🎯 Target expiries: {[e['display'] for e in expiries]}")

    # Check if Chrome is running
    try:
        result = subprocess.run(
            ["pgrep", "-x", "Google Chrome"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            return {
                "success": False,
                "error": "chrome_open",
                "message": "Google Chrome is currently open. Please close Chrome first, then retry.",
                "expiries": expiries
            }
    except Exception:
        pass  # pgrep not available, proceed anyway

    # Remove any stale lock files from previous runs
    lock_file = CHROME_PROFILE / "SingletonLock"
    if lock_file.exists():
        try:
            lock_file.unlink()
        except Exception:
            pass

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {
            "success": False,
            "error": "no_playwright",
            "message": "Playwright not installed.",
            "expiries": expiries
        }

    downloaded = []
    failed = []

    try:
        with sync_playwright() as p:
            log("🌐 Launching Chrome with your existing profile...")

            context = p.chromium.launch_persistent_context(
                user_data_dir=str(CHROME_PROFILE),
                channel="chrome",        # Use actual Chrome, not Chromium
                headless=False,
                accept_downloads=True,
                viewport={"width": 1400, "height": 900},
                args=["--no-first-run", "--no-default-browser-check"]
            )

            page = context.pages[0] if context.pages else context.new_page()

            # First: navigate to Sensibull to verify session
            log("🔗 Verifying Sensibull session...")
            page.goto(
                "https://web.sensibull.com/option-chain?view=greeks&tradingsymbol=NIFTY",
                wait_until="domcontentloaded",
                timeout=20000
            )
            page.wait_for_timeout(3000)

            # Check if we're logged in (look for the login button)
            login_present = page.locator("button:has-text('Login')").count() > 0
            if login_present:
                log("⚠️ Session expired — Zerodha login required!")
                context.close()
                return {
                    "success": False,
                    "error": "session_expired",
                    "message": "Your Sensibull session expired. Please open Chrome, log in to Sensibull with Zerodha, then retry.",
                    "expiries": expiries
                }

            log("✅ Session active! Starting multi-expiry download...")

            for i, exp in enumerate(expiries):
                log(f"📥 Fetching expiry {i+1}/{len(expiries)}: {exp['display']}...")
                try:
                    # Navigate to the specific expiry URL
                    url = (
                        f"https://web.sensibull.com/option-chain"
                        f"?view=greeks&tradingsymbol=NIFTY&expiryDate={exp['sensibull_param']}"
                    )
                    page.goto(url, wait_until="domcontentloaded", timeout=15000)
                    page.wait_for_timeout(2500)  # Let the table load

                    # Find and click the Download Excel button
                    # Sensibull uses a cloud/download icon — try multiple selectors
                    dl_selectors = [
                        "[title*='Excel' i]",
                        "[title*='Download' i]",
                        "[aria-label*='Excel' i]",
                        "[aria-label*='Download' i]",
                        "button:has-text('Excel')",
                        ".download-btn",
                    ]

                    clicked = False
                    for sel in dl_selectors:
                        try:
                            btn = page.locator(sel).first
                            if btn.is_visible(timeout=1500):
                                with page.expect_download(timeout=15000) as dl_info:
                                    btn.click()
                                dl = dl_info.value
                                save_path = DOWNLOADS / dl.suggested_filename
                                dl.save_as(save_path)
                                log(f"   ✅ Downloaded: {dl.suggested_filename}")
                                downloaded.append(dl.suggested_filename)
                                clicked = True
                                break
                        except Exception:
                            continue

                    if not clicked:
                        log(f"   ⚠️ Could not auto-click download for {exp['display']}")
                        failed.append(exp)

                except Exception as e:
                    log(f"   ❌ Error for {exp['display']}: {e}")
                    failed.append(exp)

            context.close()

    except Exception as e:
        return {
            "success": False,
            "error": "playwright_error",
            "message": str(e),
            "expiries": expiries
        }

    return {
        "success": True,
        "downloaded": downloaded,
        "failed": failed,
        "expiries": expiries
    }


# =========================================================
# MANUAL DOWNLOAD URL GENERATOR
# =========================================================
def get_manual_download_urls() -> list[dict]:
    """Generate direct Sensibull URLs for each target expiry for manual download."""
    expiries = get_target_expiries()
    urls = []
    for exp in expiries:
        urls.append({
            "display": exp["display"],
            "url": (
                f"https://web.sensibull.com/option-chain"
                f"?view=greeks&tradingsymbol=NIFTY&expiryDate={exp['sensibull_param']}"
            )
        })
    return urls


if __name__ == "__main__":
    result = fetch_with_chrome_profile(status_callback=print)
    print(result)
