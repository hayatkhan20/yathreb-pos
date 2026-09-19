"""Focused checks for the task-oriented Dashboard and login landing page."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.parse import urlsplit

from werkzeug.security import generate_password_hash

from shop import create_app
from shop.db import initialize_database


class DashboardWebTests(unittest.TestCase):
    password = "correct-horse-battery"

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.data_dir = Path(self.temp.name)
        initialize_database(
            self.data_dir / "inventory.sqlite3",
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
            data={
                "username": "owner",
                "password": self.password,
                "csrf_token": self.csrf(),
            },
        )
        self.assertEqual(303, response.status_code)
        return response

    def test_successful_login_opens_dashboard_and_root_still_serves_current_stock(self):
        response = self.sign_in()
        self.assertEqual("/dashboard", urlsplit(response.headers["Location"]).path)

        stock = self.client.get("/")
        self.assertEqual(200, stock.status_code)
        self.assertIn("<h1>Current stock</h1>", stock.get_data(as_text=True))

    def test_dashboard_requires_authentication_and_has_dominant_new_sale_action(self):
        signed_out = self.client.get("/dashboard")
        self.assertEqual(302, signed_out.status_code)
        self.assertEqual("/login", urlsplit(signed_out.headers["Location"]).path)

        self.sign_in()
        page = self.client.get("/dashboard").get_data(as_text=True)
        self.assertIn("<h1>Dashboard</h1>", page)
        self.assertIn('class="dashboard-primary-link" href="/billing" data-dashboard-primary', page)
        self.assertIn("<strong>New Sale</strong>", page)
        self.assertIn("Start a product, stitching, or combined sale.", page)
        self.assertNotIn("<p class=\"eyebrow\">Management</p>", page)

    def test_dashboard_daily_work_and_stock_actions_use_existing_destinations(self):
        self.sign_in()
        page = self.client.get("/dashboard").get_data(as_text=True)
        expected_links = {
            "Find Order / Collection": "/tailoring",
            "Find Customer": "/customers",
            "Customer Balances / Receive Payment": "/customer-balances",
            "Current Stock": "/",
            "Add Stock": "/stock",
        }
        for label, destination in expected_links.items():
            with self.subTest(label=label):
                self.assertIn(f'href="{destination}"><strong>{label}</strong>', page)
        self.assertIn('aria-label="Daily work"', page)
        self.assertIn('aria-label="Stock actions"', page)

    def test_dashboard_keeps_every_records_and_setup_destination_in_markup(self):
        self.sign_in()
        page = self.client.get("/dashboard").get_data(as_text=True)
        expected_links = {
            "Sales &amp; Receipts": "/sales",
            "Daily Sales": "/sales/daily",
            "Monthly Sales": "/sales/monthly",
            "Stock History": "/history",
            "Catalogue": "/catalogue",
            "Measurements": "/measurements",
            "Stitching Rates": "/stitching-rates",
        }
        self.assertIn('aria-label="Records and Setup"', page)
        for label, destination in expected_links.items():
            with self.subTest(label=label):
                self.assertIn(f'href="{destination}"><strong>{label}</strong>', page)


if __name__ == "__main__":
    unittest.main()
