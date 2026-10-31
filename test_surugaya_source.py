import asyncio
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import mercari_watch as app
from market_sources import SourceUnavailable
from surugaya_source import JST, NEWEST, SurugayaSearch, parse_surugaya_results, surugaya_search_url


def card(**changes):
    return {"url": "https://www.suruga-ya.jp/product/detail/EXAMPLE100",
            "title": "Example product", "image": "https://example.org/image.jpg",
            "prices": ["中古：￥1,200 税込", "定価：￥9,999", "1,500円以上は送料無料"],
            "soldOut": False, "reservation": False, "timeSale": False, "marketplace": True,
            **changes}


def data(rows):
    return {"url": surugaya_search_url("example"), "sort": NEWEST, "stock": "Off",
            "stockOff": True, "query": "example", "hasRoot": True,
            "hit": f"該当件数:{len(rows)}件中 1-{len(rows)}件", "items": rows}


class SurugayaTests(unittest.TestCase):
    def test_latest_and_sold_out_exclusion_must_be_verified(self):
        self.assertIn("inStock=Off", surugaya_search_url("example"))
        for key, value in [("sort", "relavancy(int)"), ("stock", "On"),
                           ("stockOff", False), ("query", "other"), ("hasRoot", False)]:
            with self.subTest(key=key), self.assertRaises(SourceUnavailable):
                parse_surugaya_results({**data([card()]), key: value}, "example")
        with self.assertRaises(SourceUnavailable):
            parse_surugaya_results({**data([card()]), "url": surugaya_search_url("other")}, "example")

    def test_own_price_does_not_use_retail_marketplace_or_shipping(self):
        item = parse_surugaya_results(data([card()]), "example")[0]
        self.assertEqual(item.real_price, 1200)
        self.assertEqual(item.thumbnails, ["https://example.org/image.jpg"])
        self.assertEqual(item.id_, "surugaya:EXAMPLE100:0000:used")
        self.assertEqual(item.url, card()["url"])
        rec = app.to_record(item, {"id": "sample", "keyword": "example"})
        embed = app.build_discord_messages([rec])[0]["embeds"][0]
        self.assertEqual(embed["image"]["url"], item.thumbnails[0])
        self.assertEqual(embed["url"], item.url)
        self.assertIn("駿河屋本店", embed["description"])

    def test_range_and_condition_branch_are_preserved(self):
        item = parse_surugaya_results(data([card(
            url=card()["url"] + "?branch_number=0010",
            prices=["中古：￥1,200 ～ ￥1,800 税込"],
        )]), "example")[0]
        self.assertIn(":0010:used", item.id_)
        self.assertTrue(item.url.endswith("branch_number=0010"))
        self.assertIn("起價", item.price_note)
        self.assertEqual(app.price_label(app.to_record(item, {"id": "sample", "keyword": "example"})), "¥1,200 起")

    def test_mixed_regular_new_and_sale_used_prices_remain_distinct(self):
        sale = {"condition": "中古通常価格", "price": "￥900 税込",
                "period": "2030-01-02 11:00:00 から2030-01-03 11:59:59 まで"}
        raw = card(timeSale=True, saleOffers=[sale], prices=[
            "新品：￥1,500 税込", "中古通常価格", "￥900 税込", "999円以上は送料無料", "定価：￥9,999",
        ])
        items = parse_surugaya_results(data([raw]), "example", now=datetime(2030, 1, 2, 12, tzinfo=JST))
        self.assertEqual({item.id_: item.real_price for item in items}, {
            "surugaya:EXAMPLE100:0000:new": 1500, "surugaya:EXAMPLE100:0000:used": 900,
        })
        self.assertEqual({item.id_.rsplit(":", 1)[-1] for item in items if "限時特價" in item.price_note}, {"used"})

    def test_primary_browser_is_headless_and_excludes_notification_secrets(self):
        from pathlib import Path
        import os
        import sys
        context = SimpleNamespace(pages=[SimpleNamespace()], close=AsyncMock())
        launch = AsyncMock(return_value=context)
        configuration = {"profile": Path(".state/example-profile"), "temporary": Path(".state/example-tmp"),
                         "version": "146.0.7680.177.5"}
        async def check():
            async with SurugayaSearch() as source:
                await source.open_browser()
                await source.open_browser()
        with patch.dict(os.environ, {"SURUGAYA_BROWSER_BACKEND": "cloakbrowser", "WATCHLIST_JSON": "private-example",
                                    "DISCORD_WEBHOOK_URL": "private-example", "MONITOR_STATE_KEY": "private-example"}), \
                patch.dict(sys.modules, {"cloakbrowser": SimpleNamespace(launch_persistent_context_async=launch)}), \
                patch("surugaya_source.configure_cloak_runtime", return_value=configuration):
            asyncio.run(check())
        launch.assert_awaited_once()
        self.assertTrue(launch.call_args.kwargs["headless"])
        for name in ("WATCHLIST_JSON", "DISCORD_WEBHOOK_URL", "MONITOR_STATE_KEY"):
            self.assertNotIn(name, launch.call_args.kwargs["env"])
        context.close.assert_awaited_once()

    def test_time_sale_uses_current_direct_price_and_retains_identity(self):
        now = datetime(2030, 1, 2, 12, tzinfo=JST)
        for condition, amount, expected in [("中古", "￥900 税込", 900), ("新品", "￥900 ～ ￥1,100 税込", 900)]:
            with self.subTest(condition=condition):
                regular = card(prices=[f"{condition}：￥1,200 税込"])
                sale = {"condition": condition + "通常価格", "price": amount,
                        "period": "2030-01-02 11:00:00 から2030-01-03 11:59:59 まで"}
                discounted = card(timeSale=True, saleOffers=[sale], prices=[
                    f"{condition}通常価格 ￥1,200", amount, "定価：￥9,999", "1,500円以上は送料無料",
                ])
                before = parse_surugaya_results(data([regular]), "example")[0]
                item = parse_surugaya_results(data([discounted]), "example", now=now)[0]
                self.assertEqual((item.id_, item.url), (before.id_, before.url))
                self.assertEqual(item.real_price, expected)
                self.assertIn("限時特價至 2030-01-03 11:59:59（日本時間）", item.price_note)
                self.assertEqual(item.price_from, condition == "新品")

    def test_unverified_or_inactive_sale_prices_fail_closed(self):
        now = datetime(2030, 1, 2, 12, tzinfo=JST)
        sale = {"condition": "中古通常価格", "price": "￥900 税込",
                "period": "2030-01-02 11:00:00 から2030-01-03 11:59:59 まで"}
        invalid_sales = [
            [], [{**sale, "condition": "マケプレ"}], [{**sale, "price": "定価：￥9,999"}],
            [{**sale, "price": "￥1,200 ￥900 税込"}], [{**sale, "price": "￥0 税込"}],
            [{**sale, "period": "2030-02-30 11:00:00 から2030-03-03 11:59:59 まで"}],
            [{**sale, "period": "2030-01-03 11:00:00 から2030-01-02 11:59:59 まで"}],
            [sale, sale],
        ]
        for sales in invalid_sales:
            with self.subTest(sales=sales), self.assertRaises(SourceUnavailable):
                parse_surugaya_results(data([card(timeSale=True, saleOffers=sales)]), "example", now=now)
        row = card(timeSale=True, saleOffers=[sale], prices=[])
        for outside in (now - timedelta(days=1), now + timedelta(days=2)):
            with self.subTest(now=outside), self.assertRaises(SourceUnavailable):
                parse_surugaya_results(data([row]), "example", now=outside)
        with self.assertRaises(SourceUnavailable):
            parse_surugaya_results(data([card(timeSale=True, saleOffers=[sale])]), "example", now=now)

    def test_unavailable_and_marketplace_only_goods_are_excluded(self):
        rows = [card(soldOut=True, url="https://www.suruga-ya.jp/product/other/EXAMPLE100"),
                card(reservation=True), card(prices=["定価：￥9,999"])]
        self.assertEqual(parse_surugaya_results(data(rows), "example"), [])

    def test_challenge_or_missing_rows_are_not_empty_results(self):
        empty = {"url": surugaya_search_url("example"), "hit": "該当件数：0件中 0 -0件", "items": []}
        self.assertEqual(parse_surugaya_results(empty, "example"), [])
        for broken in [{}, {"url": empty["url"], "items": []}, {**data([card()]), "items": []}]:
            with self.assertRaises(SourceUnavailable):
                parse_surugaya_results(broken, "example")

    def test_unknown_sale_layout_and_external_domains_fail_closed(self):
        for row in [card(timeSale=True), card(prices=["中古：￥1,200 ￥800 税込"]),
                    card(url="https://www.suruga-ya.com/product/detail/EXAMPLE100"),
                    card(prices=["中古：￥0 税込"]), card(prices=["中古：￥1,800 ～ ￥1,200 税込"])]:
            with self.assertRaises(SourceUnavailable):
                parse_surugaya_results(data([row]), "example")

    def test_direct_condition_and_mirror_links_do_not_duplicate(self):
        rows = [card(), card(), card(prices=["新品：￥1,500 税込"])]
        items = parse_surugaya_results(data(rows), "example")
        self.assertEqual(len(items), 2)
        self.assertNotEqual(items[0].id_, items[1].id_)

    def test_monitor_routes_through_source_client(self):
        client = AsyncMock()
        client.search.return_value = parse_surugaya_results(data([card()]), "example")
        items = asyncio.run(app.search_new(None, {"id": "sample", "keyword": "example", "source": "surugaya"},
                                          external={"surugaya": client}))
        self.assertEqual(len(items), 1)
        client.search.assert_awaited_once_with("example")

    def test_images_use_verified_public_cdn_instead_of_protected_entry(self):
        for status, url, expected in [
            (200, "https://cdn.suruga-ya.jp/pics_webp/example.webp", True),
            (403, "https://www.suruga-ya.jp/challenge", False),
            (200, "https://other.example/image.webp", False),
        ]:
            with self.subTest(status=status, url=url):
                item = parse_surugaya_results(data([card(
                    image="https://www.suruga-ya.jp/database/photo.php?shinaban=EXAMPLE100&size=m",
                )]), "example")[0]
                response = SimpleNamespace(status=status, url=url, headers={"content-type": "image/webp"}, dispose=AsyncMock())
                request = SimpleNamespace(get=AsyncMock(return_value=response))
                source = SurugayaSearch()
                source.context = SimpleNamespace(request=request)
                asyncio.run(source.prepare_item(item))
                self.assertEqual(item.thumbnails, [url] if expected else [])
                response.dispose.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
