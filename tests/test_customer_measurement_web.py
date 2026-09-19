"""Focused route and rendering checks for the Phase 3B1 management screens."""

from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from werkzeug.security import generate_password_hash

from shop import create_app
from shop.db import connect_database, initialize_database
from shop.inventory import (
    CUSTOM_GARMENT_CATEGORY,
    STANDARD_MEASUREMENT_TEMPLATES,
    add_article,
    add_brand,
    add_colour,
    catalogue,
    create_customer,
    finalize_combined_bill,
    get_customer,
    get_measurement_revisions,
    get_stitching_rate_history,
    receive_stock,
    save_measurements,
    set_default_selling_price,
)


class CustomerMeasurementWebTests(unittest.TestCase):
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

    def customer(self, name="Ahmed Khan", mobile="03001234567"):
        with closing(connect_database(self.database)) as connection:
            return create_customer(connection, name=name, primary_mobile=mobile)

    def standard_form(self, category, value="40.5", **changes):
        definition = STANDARD_MEASUREMENT_TEMPLATES[category]
        data = {
            "csrf_token": self.csrf(),
            "category": category,
            "notes": changes.pop("notes", "Current fitting"),
        }
        data.update({f"measurement_{index}": value for index, _ in enumerate(definition["measurements"])})
        data.update(changes)
        return data

    def save_direct_measurements(self, customer_id, category="Shirt", value="40.5"):
        definition = STANDARD_MEASUREMENT_TEMPLATES[category]
        with closing(connect_database(self.database)) as connection:
            return save_measurements(
                connection,
                customer_id=customer_id,
                garment_category=category,
                measurements={label: value for label in definition["measurements"]},
                styles={label: False for label in definition["styles"]},
                notes="Saved fitting",
            )

    def test_customer_and_tailoring_routes_require_authentication_and_posts_require_csrf(self):
        for path in ("/customers", "/measurements", "/stitching-rates"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(302, response.status_code)
                self.assertTrue(response.headers["Location"].endswith("/login"))
        self.sign_in()
        self.assertEqual(400, self.client.post(
            "/customers", data={"name": "Ahmed", "primary_mobile": "03001234567"}
        ).status_code)
        self.assertEqual(400, self.client.post(
            "/stitching-rates", data={"category": "Shirt", "rate": "1500"}
        ).status_code)
        customer = self.customer()
        self.assertEqual(400, self.client.post(
            f"/customers/{customer['customer_id']}/measurements",
            data={"category": "Shirt"},
        ).status_code)

    def test_customer_creation_search_detail_and_contact_editing(self):
        self.sign_in()
        response = self.client.post("/customers", data={
            "csrf_token": self.csrf(), "name": "Ahmed Khan", "primary_mobile": "0300 1234567",
            "alternate_mobile": "0311-7654321", "address": "B-17 Islamabad", "notes": "Regular",
        })
        self.assertEqual(303, response.status_code)
        self.assertIn("/customers/1?notice=created", response.headers["Location"])
        for query in ("CUST-000001", "ahmed khan", "+92 300 1234567"):
            page = self.client.get("/customers", query_string={"q": query}).get_data(as_text=True)
            self.assertIn("CUST-000001", page)
            self.assertIn("Ahmed Khan", page)
        detail = self.client.get("/customers/1").get_data(as_text=True)
        self.assertIn("B-17 Islamabad", detail)
        self.assertIn("Measurements", detail)
        response = self.client.post("/customers/1/edit", data={
            "csrf_token": self.csrf(), "name": "Ahmed Ali", "primary_mobile": "0300 1234567",
            "alternate_mobile": "", "address": "Faisal Heights", "notes": "Updated note",
        })
        self.assertEqual(303, response.status_code)
        with closing(connect_database(self.database)) as connection:
            saved = get_customer(connection, 1)
        self.assertEqual("CUST-000001", saved["customer_number"])
        self.assertEqual("Ahmed Ali", saved["name"])
        self.assertEqual("Faisal Heights", saved["address"])

    def test_duplicate_normalized_mobile_is_rejected_and_preserves_form(self):
        self.customer()
        self.sign_in()
        response = self.client.post("/customers", data={
            "csrf_token": self.csrf(), "name": "Duplicate Person",
            "primary_mobile": "+92 300 1234567", "address": "Keep this value",
        })
        page = response.get_data(as_text=True)
        self.assertEqual(400, response.status_code)
        self.assertIn("already uses this primary mobile", page)
        self.assertIn('value="Duplicate Person"', page)
        self.assertIn("Keep this value", page)

    def test_customer_detail_displays_derived_outstanding_balance(self):
        customer = self.customer()
        with closing(connect_database(self.database)) as connection:
            product = next(item for item in catalogue(connection)["products"] if item["name"] == "Fabric")
            brand_id = add_brand(connection, "Yathreb", product["id"])
            article_id = add_article(connection, "Dastan", brand_id)
            colour_id = add_colour(connection, "Blue", brand_id, article_id)
            variant_id = receive_stock(
                connection, product_id=product["id"], brand_id=brand_id,
                article_id=article_id, colour_id=colour_id, size_id=None,
                quantity="5", kind="opening", note="", request_key="customer-balance-stock1", user_id=1,
            )["variant_id"]
            set_default_selling_price(connection, variant_id, 100_000)
            finalize_combined_bill(
                connection, product_items=[{"variant_id": variant_id, "quantity": "1"}],
                tailoring_items=[], customer_id=customer["customer_id"], discount=0, paid_amount=0,
                request_key="customer-balance-bill01", user_id=1,
            )
        self.sign_in()
        page = self.client.get(f"/customers/{customer['customer_id']}").get_data(as_text=True)
        self.assertIn("Outstanding: PKR 1,000.00", page)

    def test_all_seven_authoritative_templates_render_with_dynamic_selector_and_fallback(self):
        customer = self.customer()
        self.sign_in()
        for category, definition in STANDARD_MEASUREMENT_TEMPLATES.items():
            with self.subTest(category=category):
                page = self.client.get(
                    f"/customers/{customer['customer_id']}/measurements",
                    query_string={"category": category},
                ).get_data(as_text=True)
                self.assertIn(f'<option value="{category}" selected>', page)
                for label in definition["measurements"] + definition["styles"]:
                    self.assertIn(label, page)
                self.assertIn("Note", page)
                self.assertIn("Open template", page)
                self.assertIn("data-measurement-category-form", page)
        script = self.client.get("/static/app.js").get_data(as_text=True)
        self.assertIn('fallback.hidden = true', script)
        self.assertIn('selector.addEventListener("change"', script)

    def test_standard_measurements_load_latest_and_history_remains_read_only(self):
        customer = self.customer()
        self.sign_in()
        path = f"/customers/{customer['customer_id']}/measurements"
        first = self.client.post(path, data=self.standard_form("Shirt", "40.5", style_0="true"))
        second = self.client.post(path, data=self.standard_form("Shirt", "41.25", notes="New fitting"))
        self.assertEqual(303, first.status_code)
        self.assertEqual(303, second.status_code)
        page = self.client.get(path, query_string={"category": "Shirt"}).get_data(as_text=True)
        self.assertIn('value="41.25"', page)
        self.assertIn("Latest saved revision: 2", page)
        self.assertIn("New fitting", page)
        self.assertEqual(2, page.count(">View</a>"))
        with closing(connect_database(self.database)) as connection:
            revisions = get_measurement_revisions(connection, customer["customer_id"], "Shirt")
            self.assertEqual(40_500, revisions[1]["measurements"]["Length"])
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE measurement_revisions SET notes = 'Changed' WHERE id = ?",
                    (revisions[1]["id"],),
                )
        history = self.client.get(
            f"/customers/{customer['customer_id']}/measurements/{revisions[1]['id']}"
        ).get_data(as_text=True)
        self.assertIn("Read-only history", history)
        self.assertIn("40.5 inches", history)
        self.assertIn("Yes", history)

    def test_standard_numeric_checkbox_and_unknown_field_validation_preserves_values(self):
        customer = self.customer()
        self.sign_in()
        path = f"/customers/{customer['customer_id']}/measurements"
        invalid = self.standard_form("Shirt", "42.125")
        invalid["measurement_1"] = "0"
        response = self.client.post(path, data=invalid)
        self.assertEqual(400, response.status_code)
        self.assertIn('value="42.125"', response.get_data(as_text=True))
        self.assertIn("positive supported value", response.get_data(as_text=True))
        bad_boolean = self.standard_form("Shirt", "40", style_0="yes")
        self.assertIn("true or false", self.client.post(path, data=bad_boolean).get_data(as_text=True))
        missing = self.standard_form("Shirt", "40")
        missing.pop("measurement_2")
        self.assertEqual(400, self.client.post(path, data=missing).status_code)
        unknown = self.standard_form("Shirt", "40", measurement_99="20")
        response = self.client.post(path, data=unknown)
        self.assertEqual(400, response.status_code)
        self.assertIn("exactly the confirmed", response.get_data(as_text=True))

    def test_custom_measurement_rows_save_reload_and_reject_duplicates(self):
        customer = self.customer()
        self.sign_in()
        path = f"/customers/{customer['customer_id']}/measurements"
        response = self.client.post(path, data={
            "csrf_token": self.csrf(), "category": CUSTOM_GARMENT_CATEGORY,
            "custom_description": "Curtain alteration",
            "custom_name": ["Finished width", "Drop"],
            "custom_value": ["24.25", "36"], "notes": "Match the existing hem",
        })
        self.assertEqual(303, response.status_code)
        page = self.client.get(path, query_string={"category": CUSTOM_GARMENT_CATEGORY}).get_data(as_text=True)
        self.assertIn("Curtain alteration", page)
        self.assertIn("Finished width", page)
        self.assertIn('data-add-custom-measurement', page)
        self.assertIn('data-remove-custom-measurement', page)
        duplicate = self.client.post(path, data={
            "csrf_token": self.csrf(), "category": CUSTOM_GARMENT_CATEGORY,
            "custom_description": "Duplicate test", "custom_name": ["Drop", " drop "],
            "custom_value": ["20", "21"], "notes": "Preserve me",
        })
        duplicate_page = duplicate.get_data(as_text=True)
        self.assertEqual(400, duplicate.status_code)
        self.assertIn("must be unique", duplicate_page)
        self.assertIn("Preserve me", duplicate_page)

    def test_measurement_revision_cannot_be_opened_through_another_customer(self):
        first = self.customer()
        second = self.customer("Bilal Khan", "03007654321")
        revision = self.save_direct_measurements(first["customer_id"])
        self.sign_in()
        response = self.client.get(
            f"/customers/{second['customer_id']}/measurements/{revision['revision_id']}"
        )
        self.assertEqual(404, response.status_code)
        self.assertIn("does not belong to this customer", response.get_data(as_text=True))

    def test_stitching_rates_show_missing_current_and_custom_explanation(self):
        self.sign_in()
        page = self.client.get("/stitching-rates").get_data(as_text=True)
        self.assertEqual(7, page.count("Not configured"))
        for category in STANDARD_MEASUREMENT_TEMPLATES:
            self.assertIn(category, page)
        self.assertIn("Other / Custom Item has no default rate", page)
        response = self.client.post("/stitching-rates", data={
            "csrf_token": self.csrf(), "category": "Shirt", "rate": "1500.00",
        })
        self.assertEqual(303, response.status_code)
        page = self.client.get("/stitching-rates").get_data(as_text=True)
        self.assertIn("PKR 1,500.00", page)
        self.assertIn("Revision 1", page)

    def test_stitching_rate_updates_append_history_and_invalid_amount_is_preserved(self):
        self.sign_in()
        for rate in ("1500", "1750.50"):
            response = self.client.post("/stitching-rates", data={
                "csrf_token": self.csrf(), "category": "Pant", "rate": rate,
            })
            self.assertEqual(303, response.status_code)
        with closing(connect_database(self.database)) as connection:
            history = get_stitching_rate_history(connection, "Pant")
        self.assertEqual([175_050, 150_000], [row["rate"] for row in history])
        page = self.client.get("/stitching-rates").get_data(as_text=True)
        self.assertIn("2 revisions", page)
        response = self.client.post("/stitching-rates", data={
            "csrf_token": self.csrf(), "category": "Pant", "rate": "not-money",
        })
        self.assertEqual(400, response.status_code)
        self.assertIn('value="not-money"', response.get_data(as_text=True))

    def test_sidebar_navigation_and_active_states_cover_phase3b1(self):
        customer = self.customer()
        self.sign_in()
        customer_page = self.client.get("/customers").get_data(as_text=True)
        self.assertIn('href="/customers" aria-current="page">Customers</a>', customer_page)
        self.assertIn('<span class="sidebar-group-label">Setup</span>', customer_page)
        self.assertIn('href="/measurements">Measurements</a>', customer_page)
        measurement_page = self.client.get(
            f"/customers/{customer['customer_id']}/measurements"
        ).get_data(as_text=True)
        self.assertIn('href="/measurements" aria-current="page">Measurements</a>', measurement_page)
        rate_page = self.client.get("/stitching-rates").get_data(as_text=True)
        self.assertIn('href="/stitching-rates" aria-current="page">Stitching Rates</a>', rate_page)

    def test_existing_inventory_billing_and_sales_pages_still_render(self):
        self.sign_in()
        for path, text in (("/", "Current stock"), ("/billing", "Billing"), ("/sales", "Sales history")):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(200, response.status_code)
                self.assertIn(text, response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
