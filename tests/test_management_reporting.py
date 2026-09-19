"""Focused source tests for Phase 2C management navigation and sales reporting."""

from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from werkzeug.security import generate_password_hash

from shop import create_app
from shop.db import connect_database, initialize_database
from shop.inventory import (
    add_brand,
    add_colour,
    add_product,
    catalogue,
    finalize_sale,
    list_stock,
    receive_stock,
)


class ManagementReportingTests(unittest.TestCase):
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

    def studs_variant(self):
        with closing(connect_database(self.database)) as connection:
            product = next(
                item for item in catalogue(connection)["products"] if item["name"] == "Studs"
            )
            brand_id = add_brand(connection, "Safeer", product["id"])
            colour_id = add_colour(connection, "Silver", brand_id)
            stock = receive_stock(
                connection,
                product_id=product["id"],
                brand_id=brand_id,
                article_id=None,
                colour_id=colour_id,
                size_id=None,
                quantity="20",
                kind="opening",
                note="",
                request_key="management-stock-001",
                user_id=1,
            )
        return stock["variant_id"], product, brand_id, colour_id

    def make_sales(self):
        variant_id, _, _, _ = self.studs_variant()
        with closing(connect_database(self.database)) as connection:
            first = finalize_sale(
                connection,
                items=[{"variant_id": variant_id, "quantity": "2", "unit_price": 5_000}],
                discount=1_000,
                paid_amount=4_000,
                customer_name="Ahmed Khan",
                customer_mobile="03001234567",
                request_key="management-sale-0001",
                user_id=1,
            )
            second = finalize_sale(
                connection,
                items=[{"variant_id": variant_id, "quantity": "1", "unit_price": 7_500}],
                discount=500,
                paid_amount=7_000,
                request_key="management-sale-0002",
                user_id=1,
            )
        return first, second, variant_id

    def post_delete(self, kind, item_id, **chain):
        return self.client.post(
            "/catalogue",
            data={
                "csrf_token": self.csrf(),
                "action": "delete_label",
                "confirm_delete": "yes",
                "kind": kind,
                "item_id": item_id,
                **chain,
            },
        )

    def test_sidebar_has_management_order_mobile_toggle_and_active_state(self):
        self.sign_in()
        page = self.client.get("/dashboard").get_data(as_text=True)
        labels = (
            "Dashboard", "Billing", "Orders / Collection", "Customers",
            "Current Stock", "Add Stock", "Sales", "Setup",
            "Catalogue", "Measurements", "Stitching Rates", "Logout",
        )
        positions = [page.index(f">{label}<") for label in labels]
        self.assertEqual(sorted(positions), positions)
        self.assertIn('data-sidebar-toggle', page)
        self.assertIn('aria-controls="management-sidebar"', page)
        self.assertIn('href="/dashboard" aria-current="page">Dashboard</a>', page)

        sales_page = self.client.get("/sales/daily").get_data(as_text=True)
        self.assertIn('href="/sales" aria-current="page">Sales</a>', sales_page)

    def test_catalogue_shows_hierarchy_before_collapsed_product_management(self):
        _, product, brand_id, colour_id = self.studs_variant()
        self.sign_in()
        response = self.client.get(
            "/catalogue",
            query_string={
                "product_id": product["id"],
                "brand_id": brand_id,
                "colour_id": colour_id,
            },
        )
        page = response.get_data(as_text=True)
        positions = [
            page.index('id="open-product-section"'),
            page.index('id="brands-section"'),
            page.index('id="colours-section"'),
            page.index('id="products-section"'),
        ]
        self.assertEqual(sorted(positions), positions)
        details_start = page.index('<details id="products-section"')
        self.assertNotIn(" open", page[details_start:page.index(">", details_start)])
        self.assertGreater(page.index('id="add-product-section"'), details_start)
        self.assertIn("<summary><strong>Manage Products</strong>", page)

        invalid = self.client.post(
            "/catalogue",
            data={
                "csrf_token": self.csrf(),
                "action": "add_product",
                "name": "",
                "classification": "colour",
                "unit": "piece",
                "product_id": product["id"],
                "brand_id": brand_id,
                "colour_id": colour_id,
            },
        )
        self.assertEqual(400, invalid.status_code)
        error_page = invalid.get_data(as_text=True)
        details_start = error_page.index('<details id="products-section"')
        self.assertIn(" open", error_page[details_start:error_page.index(">", details_start)])

    def test_unused_record_deletion_has_confirmation_and_succeeds(self):
        with closing(connect_database(self.database)) as connection:
            product_id = add_product(connection, "Unused Product", "colour", "piece")
        self.sign_in()
        response = self.client.post(
            "/catalogue",
            data={
                "csrf_token": self.csrf(),
                "action": "request_delete",
                "kind": "product",
                "item_id": product_id,
                "product_id": product_id,
            },
        )
        self.assertEqual(200, response.status_code)
        self.assertIn("Confirm permanent deletion", response.get_data(as_text=True))

        response = self.post_delete("product", product_id, product_id=product_id)
        self.assertEqual(303, response.status_code)
        with closing(connect_database(self.database)) as connection:
            names = [item["name"] for item in catalogue(connection)["products"]]
        self.assertNotIn("Unused Product", names)

    def test_deletion_blocks_seeded_children_and_inventory_references(self):
        with closing(connect_database(self.database)) as connection:
            unused_product = add_product(connection, "Has Child", "colour", "piece")
            add_brand(connection, "Child Brand", unused_product)
        variant_id, product, brand_id, colour_id = self.studs_variant()
        self.sign_in()

        seeded = self.post_delete("product", 1)
        self.assertEqual(400, seeded.status_code)
        self.assertIn("Required seeded Product definitions cannot be deleted", seeded.get_data(as_text=True))
        parent = self.post_delete("product", unused_product, product_id=unused_product)
        self.assertEqual(400, parent.status_code)
        self.assertIn("contains brands", parent.get_data(as_text=True))
        referenced = self.post_delete(
            "colour", colour_id, product_id=product["id"], brand_id=brand_id, colour_id=colour_id
        )
        self.assertEqual(400, referenced.status_code)
        self.assertIn("inventory variant or finalized sale depends on it", referenced.get_data(as_text=True))
        with closing(connect_database(self.database)) as connection:
            finalize_sale(
                connection,
                items=[{"variant_id": variant_id, "quantity": "1", "unit_price": 5_000}],
                discount=0,
                paid_amount=5_000,
                request_key="management-delete-sale1",
                user_id=1,
            )
        sale_referenced = self.post_delete(
            "colour", colour_id, product_id=product["id"], brand_id=brand_id, colour_id=colour_id
        )
        self.assertEqual(400, sale_referenced.status_code)
        self.assertIn(
            "inventory variant or finalized sale depends on it",
            sale_referenced.get_data(as_text=True),
        )

    def test_deletion_requires_authentication_csrf_and_explicit_confirmation(self):
        with closing(connect_database(self.database)) as connection:
            product_id = add_product(connection, "Protected Request", "colour", "piece")
        response = self.client.post(
            "/catalogue",
            data={"action": "delete_label", "confirm_delete": "yes", "kind": "product", "item_id": product_id},
        )
        self.assertEqual(302, response.status_code)
        self.sign_in()
        missing_csrf = self.client.post(
            "/catalogue",
            data={"action": "delete_label", "confirm_delete": "yes", "kind": "product", "item_id": product_id},
        )
        self.assertEqual(400, missing_csrf.status_code)
        missing_confirmation = self.client.post(
            "/catalogue",
            data={"csrf_token": self.csrf(), "action": "delete_label", "kind": "product", "item_id": product_id},
        )
        self.assertEqual(400, missing_confirmation.status_code)

    def test_sales_searches_bill_customer_and_mobile_and_handles_empty_results(self):
        first, second, _ = self.make_sales()
        self.sign_in()
        cases = (
            (first["bill_number"].lower(), first["bill_number"]),
            ("aHmEd", first["bill_number"]),
            ("1234567", first["bill_number"]),
        )
        for query, expected in cases:
            with self.subTest(query=query):
                page = self.client.get("/sales", query_string={"q": query}).get_data(as_text=True)
                self.assertIn(expected, page)
                self.assertNotIn(second["bill_number"], page)
        empty = self.client.get("/sales", query_string={"q": "not-a-customer"})
        self.assertEqual(200, empty.status_code)
        self.assertIn("No finalized bills match", empty.get_data(as_text=True))
        self.assertIn(">Clear<", empty.get_data(as_text=True))
        invalid = self.client.get("/sales", query_string={"q": "x" * 121})
        self.assertEqual(400, invalid.status_code)
        self.assertIn("Keep the sales search within 120", invalid.get_data(as_text=True))

    def test_daily_report_defaults_to_today_and_lists_accurate_totals(self):
        first, second, _ = self.make_sales()
        self.sign_in()
        response = self.client.get("/sales/daily")
        page = response.get_data(as_text=True)
        today = datetime.now(timezone(timedelta(hours=5))).date().isoformat()
        self.assertEqual(200, response.status_code)
        self.assertIn(f'value="{today}"', page)
        self.assertIn(first["bill_number"], page)
        self.assertIn(second["bill_number"], page)
        for value in ("PKR 175.00", "PKR 15.00", "PKR 160.00", "PKR 110.00", "PKR 50.00"):
            self.assertIn(value, page)
        self.assertIn("Bill count</span><strong>2", page)
        prior_day = datetime.now(timezone(timedelta(hours=5))).date() - timedelta(days=1)
        prior = self.client.get("/sales/daily", query_string={"date": prior_day.isoformat()})
        self.assertEqual(200, prior.status_code)
        self.assertIn(f'value="{prior_day.isoformat()}"', prior.get_data(as_text=True))
        self.assertIn("Bill count</span><strong>0", prior.get_data(as_text=True))

    def test_monthly_report_defaults_to_current_month_and_lists_bills(self):
        first, second, _ = self.make_sales()
        self.sign_in()
        response = self.client.get("/sales/monthly")
        page = response.get_data(as_text=True)
        month = datetime.now(timezone(timedelta(hours=5))).strftime("%Y-%m")
        self.assertEqual(200, response.status_code)
        self.assertIn(f'value="{month}"', page)
        self.assertIn(first["bill_number"], page)
        self.assertIn(second["bill_number"], page)
        self.assertIn("Ahmed Khan", page)
        self.assertIn("PKR 160.00", page)
        prior_month_end = datetime.now(timezone(timedelta(hours=5))).date().replace(day=1) - timedelta(days=1)
        prior_month = prior_month_end.strftime("%Y-%m")
        prior = self.client.get("/sales/monthly", query_string={"month": prior_month})
        self.assertEqual(200, prior.status_code)
        self.assertIn(f'value="{prior_month}"', prior.get_data(as_text=True))
        self.assertIn("Bill count</span><strong>0", prior.get_data(as_text=True))

    def test_invalid_daily_and_monthly_parameters_return_clear_400_errors(self):
        self.sign_in()
        invalid_day = self.client.get("/sales/daily", query_string={"date": "2026-02-30"})
        self.assertEqual(400, invalid_day.status_code)
        self.assertIn("Choose a valid daily report date", invalid_day.get_data(as_text=True))
        overflow_day = self.client.get("/sales/daily", query_string={"date": "9999-12-31"})
        self.assertEqual(400, overflow_day.status_code)
        self.assertIn("Choose a valid daily report date", overflow_day.get_data(as_text=True))
        underflow_day = self.client.get("/sales/daily", query_string={"date": "0001-01-01"})
        self.assertEqual(400, underflow_day.status_code)
        invalid_month = self.client.get("/sales/monthly", query_string={"month": "2026-13"})
        self.assertEqual(400, invalid_month.status_code)
        self.assertIn("Choose a valid report month and year", invalid_month.get_data(as_text=True))

    def test_billing_and_inventory_remain_consistent_after_reporting(self):
        first, second, variant_id = self.make_sales()
        self.sign_in()
        self.assertEqual(200, self.client.get("/").status_code)
        self.assertEqual(200, self.client.get("/billing").status_code)
        self.assertEqual(200, self.client.get(f"/sales/{first['sale_id']}").status_code)
        self.assertEqual(200, self.client.get(f"/sales/{second['sale_id']}").status_code)
        with closing(connect_database(self.database)) as connection:
            stock = next(row for row in list_stock(connection) if row["id"] == variant_id)
        self.assertEqual(17_000, stock["quantity"])


if __name__ == "__main__":
    unittest.main()
