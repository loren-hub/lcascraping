import time
import random
import asyncio

# UA pool: 5-10 real browser User-Agent strings, pick one at init
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0"
]

def get_random_user_agent():
    return random.choice(USER_AGENTS)

async def random_delay(config):
    min_delay = config.get('delays.min_action_delay', 0.5)
    max_delay = config.get('delays.max_action_delay', 3.0)
    await asyncio.sleep(random.uniform(min_delay, max_delay))

async def type_slowly(page, selector, text, config):
    for char in text:
        await page.locator(selector).type(char, delay=random.randint(50, 200))
    await random_delay(config)

async def simulate_mouse_movement(page):
    try:
        width = page.viewport_size['width']
        height = page.viewport_size['height']
        
        start_x = random.randint(0, width)
        start_y = random.randint(0, height)
        end_x = random.randint(0, width)
        end_y = random.randint(0, height)
        
        await page.mouse.move(start_x, start_y)
        
        steps = random.randint(5, 15)
        for i in range(steps):
            x = start_x + (end_x - start_x) * (i / steps) + random.randint(-10, 10)
            y = start_y + (end_y - start_y) * (i / steps) + random.randint(-10, 10)
            await page.mouse.move(x, y, steps=2)
            await asyncio.sleep(random.uniform(0.01, 0.05))
    except Exception:
        pass

async def human_scroll(page, steps, config, container_selector=None):
    pause = config.get('delays.scroll_pause', 1.5)
    for _ in range(steps):
        scroll_amount = random.randint(300, 800)
        try:
            if container_selector:
                # Scroll a specific element
                await page.evaluate(f"""
                    const el = document.querySelector('{container_selector}');
                    if (el) {{ el.scrollBy(0, {scroll_amount}); }}
                """)
            else:
                await page.mouse.wheel(0, scroll_amount)
        except Exception:
            pass
        await asyncio.sleep(pause + random.uniform(-0.5, 0.5))

async def delay_after_action(page, config):
    await simulate_mouse_movement(page)
    await random_delay(config)
