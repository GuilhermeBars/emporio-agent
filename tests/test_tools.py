import json
import unittest

from src.tools import search_products, get_order_status, search_policies


class ToolTests(unittest.TestCase):
    def test_price_lookup(self):
        result = json.loads(search_products("Takamine GD20"))
        self.assertEqual(result["results"][0]["price_brl"], 2199)

    def test_violao_under_1000(self):
        result = json.loads(search_products(category="Violões", max_price=1000,
                                            only_available=True, limit=50))
        self.assertGreater(result["count"], 0)
        self.assertTrue(all(p["price_brl"] <= 1000 for p in result["results"]))

    def test_active_promo_only(self):
        self.assertIn("promotion", json.loads(search_products("Ohana CK-20"))["results"][0])
        self.assertNotIn("promotion", json.loads(search_products("Martin D-28 Dreadnought"))["results"][0])

    def test_order_identity(self):
        self.assertIn("error", json.loads(get_order_status(8, "wrong@x.com")))
        self.assertEqual(json.loads(get_order_status(8, "anacarol.ferreira@coldmail.com"))["status"], "shipped")

    def test_policy_returns(self):
        self.assertIn("7 (sete) dias", json.loads(search_policies("devolver arrependimento"))["sections"][0])

    def test_order_identity_rejects_lossy_matches(self):
        for identity in ("anacarolferreira@coldmail.com", "anacarol.ferreira coldmail.com",
                         "garbage67996547821", ""):
            with self.subTest(identity=identity):
                result = json.loads(get_order_status(8, identity))
                self.assertEqual(set(result), {"error"})
                self.assertNotIn("BRJL5544332BR", json.dumps(result))

    def test_order_identity_accepts_case_and_phone_formatting(self):
        for identity in (" ANACAROL.FERREIRA@COLDMAIL.COM ", "(67) 99654-7821"):
            with self.subTest(identity=identity):
                self.assertEqual(json.loads(get_order_status(8, identity))["tracking_code"], "BRJL5544332BR")

    def test_missing_order_does_not_disclose_existence(self):
        self.assertEqual(get_order_status(9999, "wrong@example.com"), get_order_status(8, "wrong@example.com"))

    def test_no_policy_matches_returns_no_sections(self):
        self.assertEqual(json.loads(search_policies("quasarxyz"))["sections"], [])
        self.assertEqual(json.loads(search_policies(""))["sections"], [])

    def test_unknown_product_returns_empty_results(self):
        self.assertEqual(json.loads(search_products("quasarxyz")), {"count": 0, "results": []})

    def test_promotion_budget_uses_sale_price(self):
        product = json.loads(search_products("Ohana CK-20"))["results"][0]
        sale = product["promotion"]["promo_price_brl"]
        self.assertEqual(sale, 439.20)
        self.assertLess(sale, product["price_brl"])
        self.assertEqual(json.loads(search_products("Ohana CK-20", max_price=sale))["count"], 1)
        self.assertEqual(json.loads(search_products("Ohana CK-20", max_price=sale - 0.01))["count"], 0)

    def test_available_products_have_active_status_and_stock(self):
        result = json.loads(search_products(only_available=True, limit=50))
        self.assertTrue(result["results"])
        self.assertTrue(all(p["status"] == "active" and p["in_stock"] and p["stock_quantity"] > 0
                            for p in result["results"]))

    def test_invalid_product_limit(self):
        for limit in (-1, 0, 51, True):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                search_products(limit=limit)

    def test_price_bounds_are_validated(self):
        with self.assertRaises(ValueError):
            search_products(min_price=1000, max_price=100)
