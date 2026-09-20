"""Focused route and rendering checks for the Phase 2B billing interface."""

from contextlib import closing
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.parse import urlsplit

from werkzeug.security import generate_password_hash

from shop import create_app
from shop.db import connect_database, initialize_database
from shop.inventory import (
    add_article,
    add_brand,
    add_colour,
    catalogue,
    create_customer,
    get_sale,
    list_stock,
    receive_stock,
    set_default_selling_price,
)


class BillingWebTests(unittest.TestCase):
    password = "correct-horse-battery"

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.data_dir = Path(self.temp.name)
        self.database = self.data_dir / "inventory.sqlite3"
        initialize_database(
            self.database,
            "owner",
            generate_password_hash(self.password, method="scrypt"),
            "s" * 48,
        )
        self.app = create_app(self.data_dir, test_config={"TESTING": True})
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp.cleanup()

    def csrf(self):
        with self.client.session_transaction() as browser_session:
            return browser_session["csrf_token"]

    def sign_in(self):
        self.client.get("/login")
        response = self.client.post(
            "/login",
            data={"username": "owner", "password": self.password, "csrf_token": self.csrf()},
        )
        self.assertEqual(303, response.status_code)

    def product(self, connection, name):
        return next(item for item in catalogue(connection)["products"] if item["name"] == name)

    def fabric_variant(self, opening="5", price=10_000):
        with closing(connect_database(self.database)) as connection:
            product = self.product(connection, "Fabric")
            brand_id = add_brand(connection, "Yathreb", product["id"])
            article_id = add_article(connection, "Dastan", brand_id)
            colour_id = add_colour(connection, "Blue", brand_id, article_id)
            result = receive_stock(
                connection,
                product_id=product["id"],
                brand_id=brand_id,
                article_id=article_id,
                colour_id=colour_id,
                size_id=None,
                quantity=opening,
                kind="opening",
                note="",
                request_key="billing-fabric-stock-001",
                user_id=1,
            )
            set_default_selling_price(connection, result["variant_id"], price)
        return result["variant_id"], product, brand_id, article_id, colour_id

    def studs_variant(self, opening="5", price=5_000):
        with closing(connect_database(self.database)) as connection:
            product = self.product(connection, "Studs")
            brand_id = add_brand(connection, "Safeer", product["id"])
            colour_id = add_colour(connection, "Silver", brand_id)
            result = receive_stock(
                connection,
                product_id=product["id"],
                brand_id=brand_id,
                article_id=None,
                colour_id=colour_id,
                size_id=None,
                quantity=opening,
                kind="opening",
                note="",
                request_key="billing-studs-stock-001",
                user_id=1,
            )
            set_default_selling_price(connection, result["variant_id"], price)
        return result["variant_id"], product, brand_id, colour_id

    def finalize(self, items, request_key, **values):
        data = {
            "csrf_token": self.csrf(),
            "action": "finalize",
            "request_key": request_key,
            "bill_items": json.dumps(items),
            "tailoring_items": "[]",
            "discount": values.pop("discount", "0.00"),
            "paid_amount": values.pop("paid_amount", ""),
            "customer_id": values.pop("customer_id", ""),
            **values,
        }
        return self.client.post("/billing", data=data)

    def customer(self, name="Ahmed Khan", mobile="03001234567"):
        with closing(connect_database(self.database)) as connection:
            return create_customer(
                connection, name=name, primary_mobile=mobile
            )["customer_id"]

    def test_billing_routes_require_authentication_and_post_requires_csrf(self):
        for path in ("/billing", "/billing/variant", "/billing/customers", "/sales", "/sales/1"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(302, response.status_code)
                self.assertTrue(response.headers["Location"].endswith("/login"))

        self.sign_in()
        response = self.client.post(
            "/billing",
            data={"action": "finalize", "bill_items": "[]", "request_key": "missing-csrf-sale01"},
        )
        self.assertEqual(400, response.status_code)

    def test_billing_customer_search_dropdown_uses_authenticated_normalized_lookup(self):
        self.customer("Ahmed Khan", "0300 1234567")
        self.customer("Ayesha", "0311 7654321")
        self.sign_in()

        response = self.client.get(
            "/billing/customers", query_string={"q": "+92 300 1234567"}
        )
        self.assertEqual(200, response.status_code)
        payload = response.get_json()
        self.assertEqual(1, len(payload["customers"]))
        self.assertEqual("CUST-000001", payload["customers"][0]["customer_number"])
        self.assertEqual("Ahmed Khan", payload["customers"][0]["name"])

        page = self.client.get("/billing").get_data(as_text=True)
        self.assertIn('data-customer-url="/billing/customers"', page)
        self.assertIn("data-billing-customer-search", page)
        self.assertIn('role="combobox"', page)
        self.assertIn("data-billing-customer-results", page)
        self.assertIn("data-open-customer-dialog", page)
        self.assertIn('href="/customers?return_to=billing"', page)

        script = self.client.get("/static/app.js").get_data(as_text=True)
        self.assertIn("async function loadCustomerResults()", script)
        self.assertIn("submitBillingAction", script)
        self.assertIn("select_customer:", script)
        self.assertIn('billingScrollKey = "yathreb-billing-scroll-y"', script)
        self.assertIn('actionInput.value && actionInput.value !== "finalize"', script)
        self.assertIn("window.sessionStorage.setItem(billingScrollKey", script)
        self.assertNotIn("confirmation.scrollIntoView", script)

    def test_billing_inline_customer_creation_validates_and_returns_customer(self):
        self.sign_in()
        missing_csrf = self.client.post(
            "/billing/customers",
            data={"name": "Ahmed Khan", "primary_mobile": "03001234567"},
        )
        self.assertEqual(400, missing_csrf.status_code)

        response = self.client.post("/billing/customers", data={
            "csrf_token": self.csrf(),
            "name": "Ahmed Khan",
            "primary_mobile": "0300 1234567",
            "alternate_mobile": "0311 7654321",
            "address": "B-17 Islamabad",
            "notes": "Created during Billing",
        })
        self.assertEqual(201, response.status_code)
        customer = response.get_json()["customer"]
        self.assertEqual(1, customer["id"])
        self.assertEqual("CUST-000001", customer["customer_number"])
        self.assertEqual("Ahmed Khan", customer["name"])

        duplicate = self.client.post("/billing/customers", data={
            "csrf_token": self.csrf(),
            "name": "Duplicate",
            "primary_mobile": "+92 300 1234567",
        })
        self.assertEqual(400, duplicate.status_code)
        self.assertIn(
            "already uses this primary mobile",
            duplicate.get_json()["error"],
        )

        page = self.client.get("/billing").get_data(as_text=True)
        self.assertIn("data-customer-dialog", page)
        self.assertIn("data-inline-customer-form", page)
        self.assertIn("Add and select customer", page)
        self.assertIn('name="alternate_mobile"', page)
        self.assertIn('name="address"', page)
        self.assertIn('name="notes"', page)

    def test_navigation_cascade_hooks_canonical_variant_and_server_fallback(self):
        variant_id, product, brand_id, article_id, colour_id = self.fabric_variant()
        with closing(connect_database(self.database)) as connection:
            other_brand = add_brand(connection, "Indicote", product["id"])
            other_article = add_article(connection, "Classic", other_brand)
            other_colour = add_colour(connection, "Black", other_brand, other_article)
        self.sign_in()

        response = self.client.get(
            "/billing",
            query_string={
                "product_id": product["id"],
                "brand_id": brand_id,
                "article_id": article_id,
                "colour_id": colour_id,
            },
        )
        page = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        self.assertIn('href="/billing" aria-current="page">Billing</a>', page)
        self.assertIn("data-billing-form", page)
        self.assertIn('data-children-url="/catalogue/children"', page)
        self.assertIn('data-variant-url="/billing/variant"', page)
        self.assertIn("Open selection", page)
        self.assertIn('data-variant-ready="true"', page)
        self.assertIn("Fabric &middot; Yathreb", page)
        self.assertIn("Dastan", page)
        self.assertNotIn("Classic", page)

        response = self.client.get(
            "/billing/variant",
            query_string={
                "product_id": product["id"],
                "brand_id": brand_id,
                "article_id": article_id,
                "colour_id": colour_id,
            },
        )
        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertEqual(variant_id, payload["id"])
        self.assertEqual("Fabric · Yathreb · Dastan · Blue", payload["description"])
        self.assertEqual(5_000, payload["current_balance"])

        response = self.client.get(
            "/billing/variant",
            query_string={
                "product_id": product["id"],
                "brand_id": brand_id,
                "article_id": other_article,
                "colour_id": other_colour,
            },
        )
        self.assertEqual(400, response.status_code)

        response = self.client.post(
            "/billing",
            data={
                "csrf_token": self.csrf(),
                "action": "open_selection",
                "request_key": "billing-fallback-001",
                "bill_items": "[]",
                "product_id": product["id"],
            },
        )
        self.assertEqual(200, response.status_code)
        self.assertIn("Yathreb", response.get_data(as_text=True))

        response = self.client.post(
            "/billing",
            data={
                "csrf_token": self.csrf(),
                "action": "add_line",
                "request_key": "billing-fallback-001",
                "bill_items": "[]",
                "product_id": product["id"],
                "brand_id": brand_id,
                "article_id": article_id,
                "colour_id": colour_id,
                "size_id": "",
                "line_quantity": "1.25",
                "line_price": "100.00",
            },
        )
        page = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        self.assertIn("Fabric added to the current bill", page)
        self.assertIn("1.25 metres", page)

    def test_product_addition_shows_confirmation_and_top_current_bill_summary(self):
        _, product, brand_id, article_id, colour_id = self.fabric_variant()
        self.sign_in()
        response = self.client.post(
            "/billing",
            data={
                "csrf_token": self.csrf(),
                "action": "add_line",
                "request_key": "billing-visible-add01",
                "bill_items": "[]",
                "tailoring_items": "[]",
                "product_id": product["id"],
                "brand_id": brand_id,
                "article_id": article_id,
                "colour_id": colour_id,
                "size_id": "",
                "line_quantity": "1.25",
                "line_price": "100.00",
                "discount": "0.00",
                "paid_amount": "125.00",
                "paid_was_edited": "true",
            },
        )
        page = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        self.assertIn("Fabric added to the current bill.", page)
        self.assertIn("Fabric &middot; Yathreb &middot; Dastan &middot; Blue", page)
        self.assertIn("1.25 metres", page)
        self.assertIn('data-current-bill-summary', page)
        self.assertIn("1 item", page)
        self.assertIn("Running subtotal", page)
        self.assertIn("PKR <span data-current-bill-subtotal>125.00</span>", page)
        self.assertIn('href="#bill-review">Review bill</a>', page)
        self.assertLess(page.index("data-current-bill-summary"), page.index("1. Customer"))
        self.assertIn('id="bill-review"', page)
        self.assertIn('value="remove_line:0"', page)
        self.assertIn('<button type="button" class="primary" data-add-bill-line>', page)
        self.assertIn('name="action" value="add_line"', page)
        self.assertIn("billing-add-confirmation billing-action-feedback", page)
        confirmation_position = page.index("billing-add-confirmation")
        self.assertGreater(confirmation_position, page.index("data-billing-variant"))
        self.assertLess(confirmation_position, page.index("data-tailoring-addition"))

    def test_invalid_product_quantity_is_still_rejected_by_product_add_action(self):
        _, product, brand_id, article_id, colour_id = self.fabric_variant()
        self.sign_in()
        response = self.client.post(
            "/billing",
            data={
                "csrf_token": self.csrf(),
                "action": "add_line",
                "request_key": "billing-invalid-add01",
                "bill_items": "[]",
                "tailoring_items": "[]",
                "product_id": product["id"],
                "brand_id": brand_id,
                "article_id": article_id,
                "colour_id": colour_id,
                "line_quantity": "stale-value",
                "line_price": "100.00",
            },
        )
        page = response.get_data(as_text=True)
        self.assertEqual(400, response.status_code)
        self.assertIn("Enter a positive quantity with up to 3 decimal places", page)
        self.assertNotIn("added to the current bill", page)
        self.assertIn('value="stale-value"', page)

    def test_guided_sale_modes_show_only_relevant_sections_with_javascript(self):
        self.sign_in()
        page = self.client.get("/billing").get_data(as_text=True)
        self.assertIn("What is the customer buying?", page)
        self.assertIn('name="sale_mode" value="product" data-sale-mode checked', page)
        self.assertIn('name="sale_mode" value="combined" data-sale-mode', page)
        self.assertIn('name="sale_mode" value="tailoring" data-sale-mode', page)
        self.assertIn('data-sale-mode-section="products"', page)
        self.assertIn('data-sale-mode-section="tailoring"', page)
        self.assertIn("All sale sections remain available below.", page)
        self.assertNotIn("JavaScript is available", page)
        self.assertIn('data-billing-status aria-live="polite"></p>', page)

        response = self.client.post(
            "/billing",
            data={
                "csrf_token": self.csrf(),
                "action": "open_selection",
                "request_key": "billing-mode-preserve1",
                "bill_items": "[]",
                "tailoring_items": "[]",
                "sale_mode": "combined",
            },
        )
        self.assertEqual(200, response.status_code)
        self.assertIn(
            'name="sale_mode" value="combined" data-sale-mode checked',
            response.get_data(as_text=True),
        )

        script = self.client.get("/static/app.js").get_data(as_text=True)
        self.assertIn("function applySaleMode()", script)
        self.assertIn('classList.toggle("sale-mode-hidden"', script)
        css = self.client.get("/static/app.css").get_data(as_text=True)
        self.assertIn(".sale-mode-hidden { display: none !important; }", css)
        self.assertIn(".billing-action-feedback { margin-top: .75rem; }", css)
        self.assertIn("[data-billing-status]:empty { display: none; }", css)

    def test_single_line_submission_recalculates_server_totals_and_redirects(self):
        variant_id, _, _, _, _ = self.fabric_variant()
        self.sign_in()
        response = self.finalize(
            [{"variant_id": variant_id, "quantity": "1.25", "unit_price": 12_000}],
            "billing-single-sale-001",
            discount="5.00",
            paid_amount="145.00",
            subtotal="0.00",
            grand_total="0.00",
            remaining_balance="0.00",
        )
        self.assertEqual(303, response.status_code)
        self.assertEqual("/sales/1", urlsplit(response.headers["Location"]).path)
        with closing(connect_database(self.database)) as connection:
            saved = get_sale(connection, 1)
        self.assertEqual(15_000, saved["subtotal"])
        self.assertEqual(500, saved["discount"])
        self.assertEqual(14_500, saved["grand_total"])
        self.assertEqual(12_000, saved["items"][0]["unit_price"])

    def test_multiple_lines_render_remove_fallback_and_finalize_together(self):
        fabric_id, _, _, _, _ = self.fabric_variant()
        studs_id, _, _, _ = self.studs_variant()
        self.sign_in()
        draft = [
            {"variant_id": fabric_id, "quantity": "2", "unit_price": 10_000},
            {"variant_id": studs_id, "quantity": "3", "unit_price": 5_000},
        ]
        response = self.client.post(
            "/billing",
            data={
                "csrf_token": self.csrf(),
                "action": "remove_line:0",
                "request_key": "billing-remove-line01",
                "bill_items": json.dumps(draft),
                "discount": "0.00",
                "paid_amount": "",
            },
        )
        page = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        self.assertIn("1 item", page)
        self.assertIn("Studs", page)
        self.assertNotIn("Dastan", page)

        response = self.finalize(draft, "billing-multiple-sale1", paid_amount="350.00")
        self.assertEqual(303, response.status_code)
        with closing(connect_database(self.database)) as connection:
            saved = get_sale(connection, 1)
        self.assertEqual(2, len(saved["items"]))
        self.assertEqual(35_000, saved["grand_total"])

    def test_tampered_variants_quantities_and_amounts_are_rejected(self):
        variant_id, _, _, _ = self.studs_variant()
        self.sign_in()
        response = self.finalize([], "empty-billing-sale-001", paid_amount="0.00")
        self.assertEqual(400, response.status_code)
        self.assertIn("Add at least one item", response.get_data(as_text=True))
        invalid_cases = (
            ([{"variant_id": 999999, "quantity": "1", "unit_price": 5_000}], "0.00"),
            ([{"variant_id": variant_id, "quantity": "1.5", "unit_price": 5_000}], "0.00"),
            ([{"variant_id": variant_id, "quantity": "1", "unit_price": "changed"}], "0.00"),
            ([{"variant_id": variant_id, "quantity": "1", "unit_price": 5_000}], "60.00"),
        )
        for index, (items, discount) in enumerate(invalid_cases):
            with self.subTest(index=index):
                response = self.finalize(
                    items,
                    f"tampered-billing-{index:04d}",
                    discount=discount,
                    paid_amount="0.00",
                )
                self.assertEqual(400, response.status_code)
        with closing(connect_database(self.database)) as connection:
            self.assertEqual(0, connection.execute("SELECT COUNT(*) FROM sales").fetchone()[0])

    def test_duplicate_submission_reuses_bill_without_second_deduction(self):
        variant_id, _, _, _ = self.studs_variant(opening="5")
        self.sign_in()
        items = [{"variant_id": variant_id, "quantity": "2", "unit_price": 5_000}]
        first = self.finalize(items, "billing-duplicate-sale1", paid_amount="100.00")
        second = self.finalize(items, "billing-duplicate-sale1", paid_amount="100.00")
        self.assertEqual(303, first.status_code)
        self.assertEqual(first.headers["Location"], second.headers["Location"])
        with closing(connect_database(self.database)) as connection:
            self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM sales").fetchone()[0])
            self.assertEqual(3_000, list_stock(connection)[0]["quantity"])

    def test_remaining_balance_requires_existing_customer(self):
        variant_id, _, _, _ = self.studs_variant()
        self.sign_in()
        items = [{"variant_id": variant_id, "quantity": "1", "unit_price": 5_000}]
        response = self.finalize(
            items,
            "billing-credit-missing1",
            paid_amount="10.00",
            customer_name="Unlinked name",
            customer_mobile="03009999999",
        )
        self.assertEqual(400, response.status_code)
        self.assertIn("customer is required", response.get_data(as_text=True))

        customer_id = self.customer()
        response = self.finalize(
            items,
            "billing-credit-complete",
            paid_amount="10.00",
            customer_id=customer_id,
        )
        self.assertEqual(303, response.status_code)

    def test_negative_stock_warning_is_visible_and_sale_still_finalizes(self):
        variant_id, product, brand_id, colour_id = self.studs_variant(opening="1")
        self.sign_in()
        draft = [{"variant_id": variant_id, "quantity": "3", "unit_price": 5_000}]
        response = self.client.get(
            "/billing",
            query_string={
                "product_id": product["id"],
                "brand_id": brand_id,
                "colour_id": colour_id,
                "bill_items": json.dumps(draft),
            },
        )
        page = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        self.assertIn("Recorded balance after this draft line: -2 pairs", page)
        self.assertIn("Sale remains allowed", page)

        response = self.finalize(draft, "billing-negative-sale01", paid_amount="150.00")
        self.assertEqual(303, response.status_code)
        with closing(connect_database(self.database)) as connection:
            self.assertEqual(-2_000, list_stock(connection)[0]["quantity"])

    def test_default_price_editor_and_bill_override_remain_separate(self):
        variant_id, product, brand_id, article_id, colour_id = self.fabric_variant(price=10_000)
        self.sign_in()
        response = self.client.post(
            "/billing",
            data={
                "csrf_token": self.csrf(),
                "action": "save_default",
                "request_key": "billing-default-edit01",
                "bill_items": "[]",
                "product_id": product["id"],
                "brand_id": brand_id,
                "article_id": article_id,
                "colour_id": colour_id,
                "size_id": "",
                "default_price": "125.50",
            },
        )
        self.assertEqual(200, response.status_code)
        page = response.get_data(as_text=True)
        self.assertIn("Default selling price updated", page)
        self.assertGreater(
            page.index("Default selling price updated"),
            page.index("Save default price"),
        )
        self.assertLess(
            page.index("Default selling price updated"),
            page.index("Selling price for this bill"),
        )

        response = self.finalize(
            [{"variant_id": variant_id, "quantity": "1", "unit_price": 15_000}],
            "billing-price-override1",
            paid_amount="150.00",
        )
        self.assertEqual(303, response.status_code)
        with closing(connect_database(self.database)) as connection:
            row = list_stock(connection)[0]
            saved = get_sale(connection, 1)
        self.assertEqual(12_550, row["default_selling_price"])
        self.assertEqual(15_000, saved["items"][0]["unit_price"])

    def test_finalized_bill_contains_receipt_identity_snapshots_and_print_markup(self):
        variant_id, _, _, _, _ = self.fabric_variant()
        customer_id = self.customer()
        self.sign_in()
        response = self.finalize(
            [{"variant_id": variant_id, "quantity": "1.5", "unit_price": 10_000}],
            "billing-receipt-sale01",
            discount="10.00",
            paid_amount="140.00",
            customer_id=customer_id,
        )
        page = self.client.get(response.headers["Location"]).get_data(as_text=True)
        self.assertIn("Yathreb Fabrics and Tailors", page)
        self.assertIn("L.G. Floor Below Bank Al Habib", page)
        self.assertIn("03365314722", page)
        self.assertIn("03009898997", page)
        self.assertIn("BILL-00000001", page)
        self.assertIn("Ahmed Khan", page)
        self.assertIn("Fabric &rsaquo; Yathreb &rsaquo; Dastan &rsaquo; Blue", page)
        self.assertIn("1.5 metres &times; PKR 100.00", page)
        self.assertIn("Thank you for shopping", page)
        self.assertIn("data-receipt", page)
        self.assertIn("data-print-receipt", page)

        css = self.client.get("/static/app.css").get_data(as_text=True)
        self.assertIn("@page { size: 80mm auto;", css)
        self.assertIn("body.receipt-view .page > :not(.receipt)", css)

    def test_sales_history_lists_immutable_bill_totals_and_reprint_link(self):
        variant_id, _, _, _ = self.studs_variant()
        customer_id = self.customer("Ayesha", "03330000000")
        self.sign_in()
        response = self.finalize(
            [{"variant_id": variant_id, "quantity": "1", "unit_price": 5_000}],
            "billing-history-sale01",
            paid_amount="20.00",
            customer_id=customer_id,
        )
        self.assertEqual(303, response.status_code)
        page = self.client.get("/sales").get_data(as_text=True)
        self.assertIn("BILL-00000001", page)
        self.assertIn("Ayesha", page)
        self.assertIn("PKR 50.00", page)
        self.assertIn("PKR 20.00", page)
        self.assertIn("PKR 30.00", page)
        self.assertIn('href="/sales/1">Open / reprint</a>', page)


if __name__ == "__main__":
    unittest.main()
