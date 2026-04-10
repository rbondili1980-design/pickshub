"""
One-time script to refresh Action Network cookies via manual login.
Run this when the scraper keeps showing 'headless login failed'.

Usage:
    python3 refresh_an_login.py
"""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

COOKIES_FILE = Path(__file__).parent / "cookies" / "action_network.json"
LOGIN_URL    = "https://www.actionnetwork.com/login"
PICKS_URL    = "https://www.actionnetwork.com/picks?tab=following"


async def main():
    print("Opening Action Network login page...")
    print("Please log in, then the script will verify and save cookies.\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--start-maximized"],
        )
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="en-US",
            timezone_id="America/New_York",
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        page = await ctx.new_page()
        await page.goto(LOGIN_URL, wait_until="domcontentloaded")

        print("Waiting for you to log in (up to 3 minutes)...")
        logged_in = False
        for i in range(36):
            await asyncio.sleep(5)
            body = await page.evaluate("() => document.body.innerText")
            url = page.url
            if "login" not in url and ("Following" in body or "Sign Out" in body or "My Account" in body or "Log Out" in body):
                print(f"✅ Detected logged-in state! URL: {url}")
                logged_in = True
                break
            elif "login" not in url:
                # Navigated away from login, check more
                print(f"  Navigated to: {url} — verifying session...")
            remaining = (36 - i) * 5
            print(f"  Waiting... ({remaining}s remaining) URL: {page.url}")

        if not logged_in:
            print("⚠️  Could not confirm login — saving cookies anyway")

        # Navigate to the following picks page to ensure cookies are fully set
        print("\nNavigating to Following picks page to verify session...")
        await page.goto(PICKS_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        body = await page.evaluate("() => document.body.innerText")
        print(f"Following page body snippet: {body[:200]}")

        # Save cookies
        cookies = await ctx.cookies()
        COOKIES_FILE.parent.mkdir(exist_ok=True)
        COOKIES_FILE.write_text(json.dumps(cookies))

        auth_cookies = [c for c in cookies if any(k in c.get("name", "").lower() for k in ["session", "auth", "token", "jwt"])]
        print(f"\n✅ Saved {len(cookies)} cookies ({len(auth_cookies)} auth cookies) to {COOKIES_FILE}")
        for c in auth_cookies:
            print(f"   {c['name']}: expires {c.get('expires', 'session')}")

        print("\nThe scraper will now use these cookies automatically.")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
