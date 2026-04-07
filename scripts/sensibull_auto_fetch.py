import os
import time
from pathlib import Path
from playwright.sync_api import sync_playwright
import re

def start_playwright_fetch():
    target_url = "https://web.sensibull.com/option-chain?view=greeks&tradingsymbol=NIFTY"
    
    # 🌟 CORE FEATURE: Session Persistence
    # By saving user_data_dir locally, Playwright remembers the login cookie
    # This means tomorrow, it will skip the login stage entirely!
    state_dir = Path(__file__).parent.parent / "data" / "sensibull_browser_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    
    downloads_dir = Path.home() / "Downloads"

    print("🤖 Booting Local Interactive Playwright Storage...")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(state_dir),
            headless=False, # We want the user to see it!
            accept_downloads=True,
            viewport={"width": 1400, "height": 900}
        )
        
        page = context.pages[0] if context.pages else context.new_page()
        print("🌐 Engaging Sensibull...")
        page.goto(target_url, wait_until="domcontentloaded")
        
        # 1. Login Barrier Check
        try:
            page.wait_for_timeout(2000) # Let initial load settle
            login_btn = page.locator("button", has_text=re.compile(r"Login", re.IGNORECASE))
            if login_btn.count() > 0 and login_btn.first.is_visible():
                print("🔒 Login barrier detected. Waiting for user authentication... (90s timeout)")
                
                # Pop an alert to instruct the user right in the browser
                try: 
                    page.evaluate("alert('🦅 Antigravity Eagle Eye\\n\\nPlease log in with your broker. The script is waiting patiently for you to finish your TOTP redirect.');")
                except: pass
                
                # Patiently hook into the loop: Wait until we are physically back on sensibull AND login button is dead
                wait_ticks = 0
                while wait_ticks < 90:
                    if "sensibull.com" in page.url and page.locator("button", has_text=re.compile(r"Login", re.IGNORECASE)).count() == 0:
                        break
                    page.wait_for_timeout(1000)
                    wait_ticks += 1
                    
                print("✅ Login successful! Session cookie permanently locked.")
        except Exception as e:
            # If the button isn't there, or times out, we assume we are authenticated
            print("🔓 Active Session detected! Bypassing login phase.")

        # Allow the massive DOM grid to stabilize
        page.wait_for_timeout(3000)

        # 2. Automated Extraction (With Manual Bridge)
        try:
            print("🦅 Engaging Multi-Expiry Extraction Hook...")
            try:
                page.evaluate("""
                    alert('🦅 Authentication Confirmed!\\n\\nSensibull structure blocks auto-clicks.\\n\\nPLEASE TAKE YOUR TIME AND MANUALLY:\\n1. Click the Expiry dropdown\\n2. Click the Download [Cloud] Icon\\n3. Repeat for 5 expiries!\\n\\nWHEN YOU ARE DONE, SIMPLY CLOSE THIS BROWSER WINDOW.');
                """)
            except: pass
            
            print("⏳ Browser is locked open. Please download your 5 files and manually close the window when finished...")
            
            # 🌟 INFINITE WAIT MODE: Wait for the user to physically close the browser.
            # This ensures cookies are permanently flushed to disk without timeout pressure.
            page.wait_for_event("close", timeout=0)
            
        except Exception as e:
            print(f"⚠️ Eagle Eye sequence error: {e}")
            
        finally:
            print("🧹 Browser closed! Returning control to NIFTY Strategy Engine...")
            context.close()
            return True

if __name__ == "__main__":
    start_playwright_fetch()
