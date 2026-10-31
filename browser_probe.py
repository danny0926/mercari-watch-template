"""Verify native Suruga-ya DOM, prices and images without private monitor rules."""
import asyncio
from datetime import datetime
from pathlib import Path

import httpx

from surugaya_source import EXTRACT_SEARCH, JST, SurugayaSearch, SurugayaUnavailable, parse_surugaya_results, surugaya_search_url


async def verify_price_dom(source):
    html = (Path(__file__).parent / ".github/fixtures/surugaya-mixed-offers.html").read_text(encoding="utf-8")
    fixture_url = surugaya_search_url("example")
    for inverse in (False, True):
        body = html
        if inverse:
            body = body.replace("新品：￥1,500", "中古：￥1,500").replace("中古通常価格", "新品通常価格")
        async def fulfill(route):
            await route.fulfill(status=200, content_type="text/html", body=body)
        await source.page.route(fixture_url, fulfill)
        try:
            await source.page.goto(fixture_url, wait_until="domcontentloaded")
            extracted = await source.page.evaluate(EXTRACT_SEARCH)
            items = parse_surugaya_results(extracted, "example", now=datetime(2030, 1, 2, 12, tzinfo=JST))
            by_condition = {item.id_.rsplit(":", 1)[-1]: item for item in items}
            expected = {"new": 900, "used": 1500} if inverse else {"new": 1500, "used": 900}
            if set(by_condition) != set(expected) or any(by_condition[key].real_price != price for key, price in expected.items()):
                raise RuntimeError("Mixed normal and time-sale prices were not preserved")
            discounted = "new" if inverse else "used"
            if any(("限時特價" in item.price_note) != (condition == discounted) for condition, item in by_condition.items()):
                raise RuntimeError("Sale deadline was attached to the wrong condition")
        finally:
            await source.page.unroute(fixture_url, fulfill)
    print("Mixed-price DOM verified: new and used conditions, prices and deadlines")


async def probe():
    async with SurugayaSearch() as source:
        await source.open_browser()
        # Verify production navigation before any request interception for DOM fixtures.
        try:
            items = await source.search("Nintendo Switch")
        except SurugayaUnavailable:
            print("Native probe page title:", (await source.page.title())[:100], flush=True)
            print("Verification checkbox clicked:", source.challenge_clicked, flush=True)
            print("Cloudflare frame present:", any("challenges.cloudflare.com" in frame.url for frame in source.page.frames), flush=True)
            raise
        if not items:
            raise RuntimeError("Expected public native search results")
        await source.prepare_item(items[0])
        if not items[0].thumbnails:
            raise RuntimeError("Native product image redirect was not confirmed")
        async with httpx.AsyncClient() as client:
            response = await client.get(items[0].thumbnails[0], timeout=15)
            if response.status_code != 200 or not response.headers.get("content-type", "").startswith("image/"):
                raise RuntimeError("Public product image was not accessible")
        print(f"Native Japanese search verified: {len(items)} direct condition offers; public image verified")
        await verify_price_dom(source)


if __name__ == "__main__":
    asyncio.run(probe())
