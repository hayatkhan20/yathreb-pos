from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from werkzeug.security import generate_password_hash

from shop import create_app
from shop.db import connect_database, initialize_database
from shop.inventory import (
    STANDARD_MEASUREMENT_TEMPLATES,
    create_customer,
    save_measurements,
)


class TailorMobileViewTests(unittest.TestCase):
    pin = "2468"

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.data_dir = Path(self.temp.name)
        self.database = self.data_dir / "inventory.sqlite3"
        initialize_database(
            self.database,
            "owner",
            generate_password_hash("correct-horse-battery", method="scrypt"),
            "s" * 48,
        )
        self.app = create_app(
            self.data_dir,
            test_config={"TESTING": True, "TAILOR_ACCESS_PIN": self.pin},
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp.cleanup()

    def csrf(self):
        with self.client.session_transaction() as session:
            return session.get("csrf_token", "")

    def open_login(self):
        response = self.client.get("/tailor/login")
        self.assertEqual(200, response.status_code)
        return response

    def tailor_sign_in(self, pin=None):
        self.open_login()
        return self.client.post(
            "/tailor/login",
            data={"csrf_token": self.csrf(), "pin": pin or self.pin},
        )

    def create_customer_with_measurements(self):
        with closing(connect_database(self.database)) as connection:
            customer = create_customer(
                connection,
                name="Ahmed Khan",
                primary_mobile="03001234567",
            )
            shirt = STANDARD_MEASUREMENT_TEMPLATES["Shirt"]
            save_measurements(
                connection,
                customer_id=customer["customer_id"],
                garment_category="Shirt",
                measurements={label: "40.5" for label in shirt["measurements"]},
                styles={label: label == "Collar" for label in shirt["styles"]},
                notes="Blue thread",
            )
            save_measurements(
                connection,
                customer_id=customer["customer_id"],
                garment_category="Shirt",
                measurements={label: "41.25" for label in shirt["measurements"]},
                styles={label: label == "Cuff" for label in shirt["styles"]},
                notes="Current fitting",
            )
        return customer

    def test_tailor_routes_require_separate_pin_session(self):
        response = self.client.get("/tailor")
        self.assertEqual(302, response.status_code)
        self.assertTrue(response.headers["Location"].endswith("/tailor/login"))

        bad = self.tailor_sign_in("1111")
        self.assertEqual(401, bad.status_code)
        self.assertIn("Incorrect Tailor View PIN", bad.get_data(as_text=True))

        good = self.client.post(
            "/tailor/login",
            data={"csrf_token": self.csrf(), "pin": self.pin},
        )
        self.assertEqual(303, good.status_code)
        self.assertTrue(good.headers["Location"].endswith("/tailor"))

    def test_tailor_session_cannot_open_management_pages(self):
        self.tailor_sign_in()
        response = self.client.get("/billing")
        self.assertEqual(302, response.status_code)
        self.assertTrue(response.headers["Location"].endswith("/login"))

    def test_search_finds_customer_by_name_id_and_mobile(self):
        customer = self.create_customer_with_measurements()
        self.tailor_sign_in()
        for query in ("Ahmed", customer["customer_number"], "03001234567"):
            with self.subTest(query=query):
                page = self.client.get("/tailor", query_string={"q": query}).get_data(as_text=True)
                self.assertIn("Ahmed Khan", page)
                self.assertIn(customer["customer_number"], page)

    def test_customer_page_shows_only_current_measurements(self):
        customer = self.create_customer_with_measurements()
        self.tailor_sign_in()
        page = self.client.get(
            f"/tailor/customers/{customer['customer_id']}"
        ).get_data(as_text=True)
        self.assertIn("Shirt", page)
        self.assertIn("41.25 in", page)
        self.assertNotIn("40.5 in", page)
        self.assertIn("Cuff", page)
        self.assertNotIn(">Collar<", page)
        self.assertIn("Current fitting", page)
        self.assertNotIn("Revision", page)


if __name__ == "__main__":
    unittest.main()
