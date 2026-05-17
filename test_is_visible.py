import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto('https://example.com')
        try:
            await page.locator('h1').is_visible(timeout=2000)
            print("is_visible accepted timeout")
        except Exception as e:
            print("Exception:", e)
        await browser.close()

asyncio.run(main())
