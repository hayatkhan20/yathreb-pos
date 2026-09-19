"""Focused Phase 3B2A checks for combined billing and tailoring records."""

from contextlib import closing
from datetime import date, timedelta
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from werkzeug.datastructures import MultiDict
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
    configure_stitching_rate,
    create_customer,
    create_tailor,
    finalize_combined_bill,
    get_sale,
    get_tailoring_order,
    list_stock,
    receive_stock,
    save_measurements,
    set_default_selling_price,
)


class TailoringWebTests(unittest.TestCase):
    password = "correct-horse-battery"

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.data_dir = Path(self.temp.name)
        self.database = self.data_dir / "inventory.sqlite3"
        initialize_database(
            self.database, "owner", generate_password_hash(self.password, method="scrypt"),
            "s" * 48,
        )
        self.app = create_app(self.data_dir, test_config={"TESTING": True})
        self.client = self.app.test_client()
        self.promised = (date.today() + timedelta(days=10)).isoformat()

    def tearDown(self):
        self.temp.cleanup()

    def csrf(self):
        with self.client.session_transaction() as browser_session:
            return browser_session["csrf_token"]

    def sign_in(self):
        self.client.get("/login")
        response = self.client.post("/login", data={
            "username": "owner", "password": self.password, "csrf_token": self.csrf(),
        })
        self.assertEqual(303, response.status_code)

    def customer(self, name="Ahmed Khan", mobile="03001234567"):
        with closing(connect_database(self.database)) as connection:
            return create_customer(
                connection, name=name, primary_mobile=mobile
            )

    def measurements(self, customer_id, category="Shirt", custom_description=""):
        with closing(connect_database(self.database)) as connection:
            if category == CUSTOM_GARMENT_CATEGORY:
                measurements = {"Finished width": "24.25", "Drop": "36"}
                styles = None
            else:
                definition = STANDARD_MEASUREMENT_TEMPLATES[category]
                measurements = {label: "40.5" for label in definition["measurements"]}
                styles = {label: False for label in definition["styles"]}
            return save_measurements(
                connection, customer_id=customer_id, garment_category=category,
                custom_description=custom_description, measurements=measurements,
                styles=styles, notes="Current fitting",
            )["revision_id"]

    def rate(self, category="Shirt", amount=150_000):
        with closing(connect_database(self.database)) as connection:
            return configure_stitching_rate(connection, category, amount, 1)

    def variant(self, opening="5", price=10_000):
        with closing(connect_database(self.database)) as connection:
            product = next(row for row in catalogue(connection)["products"] if row["name"] == "Fabric")
            brand = add_brand(connection, "Yathreb", product["id"])
            article = add_article(connection, "Dastan", brand)
            colour = add_colour(connection, "Blue", brand, article)
            variant = receive_stock(
                connection, product_id=product["id"], brand_id=brand, article_id=article,
                colour_id=colour, size_id=None, quantity=opening, kind="opening", note="",
                request_key="tailoring-web-stock01", user_id=1,
            )["variant_id"]
            set_default_selling_price(connection, variant, price)
            return variant

    def second_fabric_variant(self, opening="5", price=12_000):
        with closing(connect_database(self.database)) as connection:
            product = next(row for row in catalogue(connection)["products"] if row["name"] == "Fabric")
            brand = add_brand(connection, "Indicote", product["id"])
            article = add_article(connection, "Classic", brand)
            colour = add_colour(connection, "Black", brand, article)
            variant = receive_stock(
                connection, product_id=product["id"], brand_id=brand, article_id=article,
                colour_id=colour, size_id=None, quantity=opening, kind="opening", note="",
                request_key="tailoring-web-stock02", user_id=1,
            )["variant_id"]
            set_default_selling_price(connection, variant, price)
            return variant

    def non_fabric_variant(self, opening="5", price=5_000):
        with closing(connect_database(self.database)) as connection:
            product = next(row for row in catalogue(connection)["products"] if row["name"] == "Studs")
            brand = add_brand(connection, "Safeer", product["id"])
            colour = add_colour(connection, "Silver", brand)
            variant = receive_stock(
                connection, product_id=product["id"], brand_id=brand, article_id=None,
                colour_id=colour, size_id=None, quantity=opening, kind="opening", note="",
                request_key="tailoring-web-studs01", user_id=1,
            )["variant_id"]
            set_default_selling_price(connection, variant, price)
            return variant

    def standard_line(self, revision_id, **changes):
        line = {
            "garment_category": "Shirt", "custom_description": "", "quantity": "1",
            "stitching_rate": None, "cloth_source": "customer",
            "source_product_line": None, "source_sale_item_id": None,
            "measurement_revision_id": revision_id, "promised_date": self.promised,
        }
        line.update(changes)
        return line

    def post_bill(self, *, products=(), tailoring=(), customer_id="", key="tailoring-web-bill01",
                  discount="0.00", paid=""):
        return self.client.post("/billing", data={
            "csrf_token": self.csrf(), "action": "finalize", "request_key": key,
            "bill_items": json.dumps(list(products)),
            "tailoring_items": json.dumps(list(tailoring)), "customer_id": customer_id,
            "promised_date": tailoring[0]["promised_date"] if tailoring else "",
            "order_notes": "Handle carefully", "discount": discount, "paid_amount": paid,
        })

    def test_authentication_csrf_and_no_javascript_fallback(self):
        for path in ("/billing", "/tailoring", "/tailoring/1"):
            self.assertEqual(302, self.client.get(path).status_code)
        self.sign_in()
        self.assertEqual(400, self.client.post("/billing", data={"action": "finalize"}).status_code)
        page = self.client.get("/billing").get_data(as_text=True)
        self.assertIn("Open selection", page)
        self.assertIn("Load tailoring details", page)
        self.assertIn("data-tailoring-fallback", page)
        response = self.client.post("/billing", data={
            "csrf_token": self.csrf(), "action": "open_tailoring", "request_key": "fallback-tailoring01",
            "bill_items": "[]", "tailoring_items": "[]", "tailoring_category": "Shirt",
        })
        self.assertEqual(200, response.status_code)
        tailoring_page = self.client.get("/tailoring").get_data(as_text=True)
        self.assertIn(
            'href="/tailoring" aria-current="page">Orders / Collection</a>',
            tailoring_page,
        )

    def test_customer_search_selection_and_create_return_to_billing(self):
        customer = self.customer()
        self.sign_in()
        response = self.client.post("/billing", data={
            "csrf_token": self.csrf(), "action": "search_customer", "request_key": "customer-search-key1",
            "bill_items": "[]", "tailoring_items": "[]", "customer_query": "+92 300 1234567",
        })
        page = response.get_data(as_text=True)
        self.assertIn("CUST-000001", page)
        self.assertIn("Ahmed Khan", page)
        response = self.client.post("/billing", data={
            "csrf_token": self.csrf(), "action": f"select_customer:{customer['customer_id']}",
            "request_key": "customer-search-key1", "bill_items": "[]", "tailoring_items": "[]",
        })
        page = response.get_data(as_text=True)
        self.assertIn('name="customer_id" value="1"', page)
        self.assertIn("Selected customer", page)
        self.assertIn('href="/customers?return_to=billing"', page)
        response = self.client.post("/customers", data={
            "csrf_token": self.csrf(), "return_to": "billing", "name": "Bilal Khan",
            "primary_mobile": "03007654321",
        })
        self.assertEqual(303, response.status_code)
        self.assertTrue(response.headers["Location"].endswith("/billing?customer_id=2"))

    def test_required_customer_missing_rate_and_missing_measurements_are_blocked(self):
        customer = self.customer()
        revision = self.measurements(customer["customer_id"])
        self.sign_in()
        line = self.standard_line(revision)
        response = self.post_bill(tailoring=[line], customer_id="", paid="1500.00")
        self.assertEqual(400, response.status_code)
        self.assertIn("Select an existing customer", response.get_data(as_text=True))
        response = self.client.post("/billing", data={
            "csrf_token": self.csrf(), "action": "add_tailoring", "request_key": "missing-rate-key001",
            "bill_items": "[]", "tailoring_items": "[]", "customer_id": customer["customer_id"],
            "tailoring_category": "Shirt", "tailoring_quantity": "1",
            "promised_date": self.promised, "cloth_source": "customer",
        })
        self.assertEqual(400, response.status_code)
        self.assertIn("Configure a default stitching rate", response.get_data(as_text=True))
        other = self.customer("Bilal", "03007654321")
        self.rate()
        response = self.client.post("/billing", data={
            "csrf_token": self.csrf(), "action": "add_tailoring", "request_key": "missing-measure-key1",
            "bill_items": "[]", "tailoring_items": "[]", "customer_id": other["customer_id"],
            "tailoring_category": "Shirt", "tailoring_quantity": "1",
            "promised_date": self.promised, "cloth_source": "customer",
        })
        self.assertEqual(400, response.status_code)
        self.assertIn("Save matching current measurements", response.get_data(as_text=True))

    def test_tailoring_quantity_defaults_to_one_and_uses_specific_validation(self):
        customer = self.customer()
        self.measurements(customer["customer_id"])
        self.rate()
        self.sign_in()

        page = self.client.get("/billing", query_string={
            "customer_id": customer["customer_id"],
            "sale_mode": "tailoring",
            "tailoring_category": "Shirt",
        }).get_data(as_text=True)
        self.assertIn('name="tailoring_quantity" value="1"', page)
        self.assertIn("Current measurements", page)
        self.assertIn(
            'name="sale_mode" value="tailoring" data-sale-mode checked',
            page,
        )

        response = self.client.post("/billing", data={
            "csrf_token": self.csrf(), "action": "add_tailoring",
            "request_key": "tailoring-quantity-empty1", "bill_items": "[]",
            "tailoring_items": "[]", "customer_id": customer["customer_id"],
            "sale_mode": "tailoring", "tailoring_category": "Shirt",
            "tailoring_quantity": "", "promised_date": self.promised,
            "cloth_choice": "customer",
        })
        self.assertEqual(400, response.status_code)
        self.assertIn(
            "Enter the tailoring quantity as a whole number greater than zero.",
            response.get_data(as_text=True),
        )

        response = self.client.post("/billing", data={
            "csrf_token": self.csrf(), "action": "add_tailoring",
            "request_key": "tailoring-quantity-valid1", "bill_items": "[]",
            "tailoring_items": "[]", "customer_id": customer["customer_id"],
            "sale_mode": "tailoring", "tailoring_category": "Shirt",
            "tailoring_quantity": "1", "promised_date": self.promised,
            "cloth_choice": "customer",
        })
        page = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        self.assertIn("Tailoring item added to the bill draft", page)
        self.assertIn('name="tailoring_quantity" value="1"', page)
        self.assertIn("Stitching &middot; Shirt", page)

    def test_custom_item_manual_price_and_standard_override_validation(self):
        customer = self.customer()
        custom_revision = self.measurements(
            customer["customer_id"], CUSTOM_GARMENT_CATEGORY, "Curtain alteration"
        )
        standard_revision = self.measurements(customer["customer_id"])
        self.rate()
        self.sign_in()
        page = self.client.get("/billing", query_string={
            "customer_id": customer["customer_id"],
            "tailoring_category": CUSTOM_GARMENT_CATEGORY,
            "tailoring_custom_description": "Curtain alteration",
        }).get_data(as_text=True)
        self.assertIn("Manual price required", page)
        self.assertIn("Current measurements", page)
        self.assertNotIn("Configured revision", page)
        self.assertIn("data-tailoring-custom-description", page)
        custom = {
            "garment_category": CUSTOM_GARMENT_CATEGORY,
            "custom_description": "Curtain alteration", "quantity": "2",
            "stitching_rate": 75_000, "cloth_source": "customer",
            "source_product_line": None, "source_sale_item_id": None,
            "measurement_revision_id": custom_revision, "promised_date": self.promised,
        }
        response = self.post_bill(
            tailoring=[custom], customer_id=customer["customer_id"], paid="1500.00",
            key="custom-tailoring-web1",
        )
        self.assertEqual(303, response.status_code)
        with closing(connect_database(self.database)) as connection:
            sale = get_sale(connection, 1)
        self.assertEqual(75_000, sale["tailoring_items"][0]["stitching_rate"])
        override = self.standard_line(standard_revision, stitching_rate=1)
        response = self.post_bill(
            tailoring=[override], customer_id=customer["customer_id"], paid="1500.00",
            key="standard-override-web1",
        )
        self.assertEqual(400, response.status_code)
        self.assertIn("cannot be overridden", response.get_data(as_text=True))

    def test_tailoring_only_customer_cloth_has_no_inventory_movement(self):
        customer = self.customer()
        revision = self.measurements(customer["customer_id"])
        self.rate()
        self.sign_in()
        fallback = self.client.post("/billing", data={
            "csrf_token": self.csrf(), "action": "add_tailoring",
            "request_key": "tailoring-fallback-add1", "bill_items": "[]",
            "tailoring_items": "[]", "customer_id": customer["customer_id"],
            "tailoring_category": "Shirt", "tailoring_quantity": "1",
            "promised_date": self.promised, "cloth_source": "customer",
        })
        self.assertEqual(200, fallback.status_code)
        self.assertIn("Tailoring item added to the bill draft", fallback.get_data(as_text=True))
        response = self.post_bill(
            tailoring=[self.standard_line(revision)], customer_id=customer["customer_id"],
            paid="1500.00",
        )
        self.assertEqual(303, response.status_code)
        with closing(connect_database(self.database)) as connection:
            self.assertEqual(0, connection.execute("SELECT COUNT(*) FROM stock_movements").fetchone()[0])
            order = get_tailoring_order(connection, 1)
        self.assertEqual("customer", order["items"][0]["cloth_source"])
        self.assertEqual("Received", order["status"])

    def test_combined_current_bill_cloth_link_and_server_totals(self):
        customer = self.customer()
        revision = self.measurements(customer["customer_id"])
        self.rate(amount=150_000)
        variant = self.variant()
        products = [{"variant_id": variant, "quantity": "1.5", "unit_price": 10_000}]
        tailoring = [self.standard_line(
            revision, cloth_source="shop", source_product_line=1
        )]
        self.sign_in()
        page = self.client.get("/billing", query_string={
            "customer_id": customer["customer_id"],
            "bill_items": json.dumps(products),
        }).get_data(as_text=True)
        self.assertIn('value="current:1"', page)
        response = self.post_bill(
            products=products, tailoring=tailoring, customer_id=customer["customer_id"],
            discount="50.00", paid="1450.00", key="combined-current-link1",
        )
        self.assertEqual(303, response.status_code)
        with closing(connect_database(self.database)) as connection:
            sale = get_sale(connection, 1)
            order = get_tailoring_order(connection, 1)
            sale_movements = connection.execute(
                "SELECT COUNT(*) FROM stock_movements WHERE kind = 'sale'"
            ).fetchone()[0]
        self.assertEqual(165_000, sale["subtotal"])
        self.assertEqual(160_000, sale["grand_total"])
        self.assertEqual(15_000, sale["remaining_balance"])
        self.assertEqual(1, sale_movements)
        self.assertIsNotNone(order["items"][0]["source_sale_item_id"])

    def test_top_summary_keeps_product_and_tailoring_lines_and_complete_bill_table(self):
        customer = self.customer()
        revision = self.measurements(customer["customer_id"])
        self.rate()
        fabric = self.variant()
        studs = self.non_fabric_variant()
        products = [
            {"variant_id": fabric, "quantity": "1", "unit_price": 10_000},
            {"variant_id": studs, "quantity": "1", "unit_price": 5_000},
        ]
        tailoring = [self.standard_line(revision)]
        self.sign_in()
        page = self.client.get("/billing", query_string={
            "customer_id": customer["customer_id"],
            "bill_items": json.dumps(products),
            "tailoring_items": json.dumps(tailoring),
            "promised_date": self.promised,
        }).get_data(as_text=True)
        summary_start = page.index('data-current-bill-summary')
        bill_start = page.index('id="bill-review"')
        self.assertLess(summary_start, bill_start)
        self.assertIn("3 items", page)
        self.assertIn("Fabric &middot; Yathreb &middot; Dastan &middot; Blue", page)
        self.assertIn("Studs &middot; Safeer &middot; Silver", page)
        self.assertIn("Stitching &middot; Shirt", page)
        self.assertIn("PKR <span data-current-bill-subtotal>1,650.00</span>", page)
        self.assertIn('value="remove_line:0"', page)
        self.assertIn('value="remove_line:1"', page)
        self.assertIn('value="remove_tailoring:0"', page)
        self.assertEqual(1, page.count('id="bill-review"'))

    def test_tailoring_add_ignores_empty_or_stale_product_quantity_fields(self):
        customer = self.customer()
        self.measurements(customer["customer_id"])
        self.rate()
        variant = self.variant()
        with closing(connect_database(self.database)) as connection:
            selected = connection.execute(
                "SELECT product_id, brand_id, article_id, colour_id FROM variants WHERE id = ?",
                (variant,),
            ).fetchone()
        self.sign_in()
        for suffix, product_quantity in (("empty", ""), ("stale", "stale-value")):
            with self.subTest(product_quantity=product_quantity):
                response = self.client.post("/billing", data={
                    "csrf_token": self.csrf(), "action": "add_tailoring",
                    "request_key": f"tailoring-ignore-{suffix}01",
                    "bill_items": json.dumps([{
                        "variant_id": variant, "quantity": "1", "unit_price": 10_000,
                    }]),
                    "tailoring_items": "[]", "customer_id": customer["customer_id"],
                    "product_id": selected["product_id"], "brand_id": selected["brand_id"],
                    "article_id": selected["article_id"], "colour_id": selected["colour_id"],
                    "line_quantity": product_quantity, "line_price": "100.00",
                    "tailoring_category": "Shirt", "tailoring_quantity": "1",
                    "promised_date": self.promised, "cloth_choice": "customer",
                    "discount": "10.00", "paid_amount": "1590.00",
                    "paid_was_edited": "true",
                })
                page = response.get_data(as_text=True)
                self.assertEqual(200, response.status_code)
                self.assertIn("Tailoring item added to the bill draft", page)
                self.assertNotIn("Enter a positive quantity with up to 3 decimal places", page)
                self.assertIn(f'value="tailoring-ignore-{suffix}01"', page)
                self.assertIn('value="1590.00"', page)
                self.assertIn('data-tailoring-addition', page)
                self.assertIn('<button type="button" class="primary" data-add-bill-line>', page)
        script = self.client.get("/static/app.js").get_data(as_text=True)
        self.assertIn('tailoringSection.addEventListener("keydown"', script)

    def test_browser_shaped_tailoring_action_cannot_be_read_as_product_add(self):
        customer = self.customer()
        self.measurements(customer["customer_id"], "Shalwar Kameez")
        self.rate("Shalwar Kameez")
        variant = self.variant()
        with closing(connect_database(self.database)) as connection:
            selected = connection.execute(
                "SELECT product_id, brand_id, article_id, colour_id FROM variants WHERE id = ?",
                (variant,),
            ).fetchone()
        self.sign_in()
        payload = MultiDict({
            "csrf_token": self.csrf(), "action": "add_tailoring",
            "request_key": "browser-tailoring-action1",
            "bill_items": json.dumps([{
                "variant_id": variant, "quantity": "1", "unit_price": 10_000,
            }]),
            "tailoring_items": "[]", "customer_id": customer["customer_id"],
            "product_id": selected["product_id"], "brand_id": selected["brand_id"],
            "article_id": selected["article_id"], "colour_id": selected["colour_id"],
            "size_id": "", "line_quantity": "", "line_price": "100.00",
            "default_price": "100.00", "tailoring_category": "Shalwar Kameez",
            "tailoring_quantity": "1", "promised_date": self.promised,
            "cloth_choice": "current:1", "discount": "0.00",
            "paid_amount": "1600.00", "paid_was_edited": "true",
        })
        response = self.client.post("/billing", data=payload)
        page = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        self.assertNotIn("Enter a positive quantity with up to 3 decimal places", page)
        self.assertIn("Tailoring item added to the bill draft", page)
        self.assertIn("2 items", page)
        self.assertIn("Stitching &middot; Shalwar Kameez", page)
        self.assertIn("PKR <span data-current-bill-subtotal>1,600.00</span>", page)
        self.assertIn("This bill: Fabric", page)
        self.assertIn('value="remove_line:0"', page)
        self.assertIn('value="remove_tailoring:0"', page)
        self.assertIn(customer["customer_number"], page)
        self.assertIn(self.promised, page)
        self.assertIn('value="browser-tailoring-action1"', page)

        duplicate = payload.copy()
        duplicate.setlist("action", ["add_line", "add_tailoring"])
        rejected = self.client.post("/billing", data=duplicate)
        self.assertEqual(400, rejected.status_code)
        self.assertIn("exactly one Billing action", rejected.get_data(as_text=True))
        script = self.client.get("/static/app.js").get_data(as_text=True)
        self.assertIn('button.removeAttribute("name")', script)
        self.assertIn('actionInput.name = "action"', script)

    def test_one_current_bill_fabric_is_automatically_selected_for_tailoring(self):
        customer = self.customer()
        self.measurements(customer["customer_id"])
        self.rate()
        variant = self.variant()
        products = [{"variant_id": variant, "quantity": "1.5", "unit_price": 10_000}]
        self.sign_in()
        page = self.client.get("/billing", query_string={
            "customer_id": customer["customer_id"], "bill_items": json.dumps(products),
        }).get_data(as_text=True)
        self.assertIn("Fabric from this bill", page)
        self.assertIn("Fabric &middot; Yathreb &middot; Dastan &middot; Blue", page)
        self.assertIn("1.5 metres", page)
        self.assertIn('name="cloth_choice" value="current:1" checked', page)
        self.assertIn("Use a different cloth source", page)
        self.assertIn("Customer-provided cloth", page)
        response = self.client.post("/billing", data={
            "csrf_token": self.csrf(), "action": "add_tailoring",
            "request_key": "tailoring-auto-fabric1", "bill_items": json.dumps(products),
            "tailoring_items": "[]", "customer_id": customer["customer_id"],
            "tailoring_category": "Shirt", "tailoring_quantity": "1",
            "promised_date": self.promised,
        })
        self.assertEqual(200, response.status_code)
        self.assertIn("Tailoring item added", response.get_data(as_text=True))

    def test_multiple_current_bill_fabrics_require_an_explicit_selection(self):
        customer = self.customer()
        self.measurements(customer["customer_id"])
        self.rate()
        first = self.variant()
        second = self.second_fabric_variant()
        products = [
            {"variant_id": first, "quantity": "1", "unit_price": 10_000},
            {"variant_id": second, "quantity": "2", "unit_price": 12_000},
        ]
        self.sign_in()
        page = self.client.get("/billing", query_string={
            "customer_id": customer["customer_id"], "bill_items": json.dumps(products),
        }).get_data(as_text=True)
        self.assertIn("Which fabric is being used for this garment?", page)
        self.assertIn('value="current:1"', page)
        self.assertIn('value="current:2"', page)
        self.assertNotIn('value="current:1" checked', page)
        self.assertNotIn('value="current:2" checked', page)
        common = {
            "csrf_token": self.csrf(), "action": "add_tailoring",
            "bill_items": json.dumps(products), "tailoring_items": "[]",
            "customer_id": customer["customer_id"], "tailoring_category": "Shirt",
            "tailoring_quantity": "1", "promised_date": self.promised,
        }
        missing = self.client.post("/billing", data={
            **common, "request_key": "tailoring-multi-missing1",
        })
        self.assertEqual(400, missing.status_code)
        self.assertIn("Choose which Fabric", missing.get_data(as_text=True))
        selected = self.client.post("/billing", data={
            **common, "request_key": "tailoring-multi-selected1", "cloth_choice": "current:2",
        })
        self.assertEqual(200, selected.status_code)
        self.assertIn("Tailoring item added", selected.get_data(as_text=True))

    def test_no_current_fabric_shows_customer_and_earlier_fabric_choices(self):
        customer = self.customer()
        variant = self.variant()
        with closing(connect_database(self.database)) as connection:
            earlier = finalize_combined_bill(
                connection, product_items=[{"variant_id": variant, "quantity": "1"}],
                tailoring_items=[], customer_id=customer["customer_id"], discount=0,
                paid_amount=10_000, request_key="earlier-fabric-choice1", user_id=1,
            )
            sale_item_id = get_sale(connection, earlier["sale_id"])["items"][0]["id"]
        self.sign_in()
        page = self.client.get("/billing", query_string={
            "customer_id": customer["customer_id"],
        }).get_data(as_text=True)
        self.assertIn("Customer-provided cloth", page)
        self.assertIn("Fabric purchased in BILL-00000001", page)
        self.assertIn(f'value="earlier:{sale_item_id}"', page)
        self.assertNotIn('value="current:1"', page)
        self.assertIn('value="customer" checked', page)

    def test_invalid_fabric_references_are_rejected_without_record_changes(self):
        first_customer = self.customer()
        second_customer = self.customer("Bilal", "03007654321")
        self.measurements(first_customer["customer_id"])
        self.measurements(second_customer["customer_id"])
        self.rate()
        fabric = self.variant()
        non_fabric = self.non_fabric_variant()
        with closing(connect_database(self.database)) as connection:
            fabric_sale = finalize_combined_bill(
                connection, product_items=[{"variant_id": fabric, "quantity": "1"}],
                tailoring_items=[], customer_id=first_customer["customer_id"], discount=0,
                paid_amount=10_000, request_key="invalid-ref-fabric01", user_id=1,
            )
            non_fabric_sale = finalize_combined_bill(
                connection, product_items=[{"variant_id": non_fabric, "quantity": "1"}],
                tailoring_items=[], customer_id=first_customer["customer_id"], discount=0,
                paid_amount=5_000, request_key="invalid-ref-studs001", user_id=1,
            )
            fabric_item = get_sale(connection, fabric_sale["sale_id"])["items"][0]["id"]
            non_fabric_item = get_sale(connection, non_fabric_sale["sale_id"])["items"][0]["id"]
            before = {
                "sales": [tuple(row) for row in connection.execute("SELECT * FROM sales ORDER BY id")],
                "sale_items": [
                    tuple(row) for row in connection.execute("SELECT * FROM sale_items ORDER BY id")
                ],
                "orders": [
                    tuple(row) for row in connection.execute(
                        "SELECT * FROM tailoring_orders ORDER BY id"
                    )
                ],
                "movements": [
                    tuple(row) for row in connection.execute(
                        "SELECT * FROM stock_movements ORDER BY id"
                    )
                ],
            }
        self.sign_in()

        def attempt(products, customer_id, choice, key):
            return self.client.post("/billing", data={
                "csrf_token": self.csrf(), "action": "add_tailoring", "request_key": key,
                "bill_items": json.dumps(products), "tailoring_items": "[]",
                "customer_id": customer_id, "tailoring_category": "Shirt",
                "tailoring_quantity": "1", "promised_date": self.promised,
                "cloth_choice": choice,
            })

        cases = (
            ([{"variant_id": non_fabric, "quantity": "1"}], first_customer["customer_id"], "current:1", "bad-current-product1"),
            ([{"variant_id": fabric, "quantity": "1"}], first_customer["customer_id"], "current:2", "removed-current-line1"),
            ([], second_customer["customer_id"], f"earlier:{fabric_item}", "cross-customer-link1"),
            ([], first_customer["customer_id"], f"earlier:{non_fabric_item}", "ineligible-earlier1"),
            ([], first_customer["customer_id"], "current:not-a-number", "tampered-cloth-link1"),
        )
        for products, customer_id, choice, key in cases:
            with self.subTest(choice=choice):
                response = attempt(products, customer_id, choice, key)
                self.assertEqual(400, response.status_code)
                self.assertNotIn("Tailoring item added", response.get_data(as_text=True))
        with closing(connect_database(self.database)) as connection:
            after = {
                "sales": [tuple(row) for row in connection.execute("SELECT * FROM sales ORDER BY id")],
                "sale_items": [
                    tuple(row) for row in connection.execute("SELECT * FROM sale_items ORDER BY id")
                ],
                "orders": [
                    tuple(row) for row in connection.execute(
                        "SELECT * FROM tailoring_orders ORDER BY id"
                    )
                ],
                "movements": [
                    tuple(row) for row in connection.execute(
                        "SELECT * FROM stock_movements ORDER BY id"
                    )
                ],
            }
        self.assertEqual(before, after)

    def test_earlier_bill_cloth_link_is_allowed_only_for_selected_customer(self):
        first_customer = self.customer()
        second_customer = self.customer("Bilal", "03007654321")
        variant = self.variant()
        with closing(connect_database(self.database)) as connection:
            earlier = finalize_combined_bill(
                connection, product_items=[{"variant_id": variant, "quantity": "1"}],
                tailoring_items=[], customer_id=first_customer["customer_id"], discount=0,
                paid_amount=10_000, request_key="earlier-product-bill1", user_id=1,
            )
            sale_item_id = get_sale(connection, earlier["sale_id"])["items"][0]["id"]
        revision = self.measurements(first_customer["customer_id"])
        self.rate()
        line = self.standard_line(
            revision, cloth_source="shop", source_sale_item_id=sale_item_id
        )
        self.sign_in()
        page = self.client.get("/billing", query_string={
            "customer_id": first_customer["customer_id"],
        }).get_data(as_text=True)
        self.assertIn(f'value="earlier:{sale_item_id}"', page)
        self.assertIn("BILL-00000001", page)
        response = self.post_bill(
            tailoring=[line], customer_id=first_customer["customer_id"], paid="1500.00",
            key="earlier-link-allowed1",
        )
        self.assertEqual(303, response.status_code)
        other_revision = self.measurements(second_customer["customer_id"])
        cross = self.standard_line(
            other_revision, cloth_source="shop", source_sale_item_id=sale_item_id
        )
        response = self.post_bill(
            tailoring=[cross], customer_id=second_customer["customer_id"], paid="1500.00",
            key="earlier-cross-denied1",
        )
        self.assertEqual(400, response.status_code)
        self.assertIn("does not belong", response.get_data(as_text=True))

    def test_selected_customer_cannot_change_while_tailoring_draft_exists(self):
        first = self.customer()
        second = self.customer("Bilal", "03007654321")
        revision = self.measurements(first["customer_id"])
        self.rate()
        self.sign_in()
        response = self.client.post("/billing", data={
            "csrf_token": self.csrf(), "action": f"select_customer:{second['customer_id']}",
            "request_key": "stale-customer-draft1", "bill_items": "[]",
            "tailoring_items": json.dumps([self.standard_line(revision)]),
            "customer_id": first["customer_id"], "promised_date": self.promised,
        })
        self.assertEqual(400, response.status_code)
        self.assertIn("Remove all tailoring lines", response.get_data(as_text=True))

    def test_combined_failure_rolls_back_bill_order_and_product_movement(self):
        customer = self.customer()
        revision = self.measurements(customer["customer_id"])
        self.rate()
        variant = self.variant()
        with closing(connect_database(self.database)) as connection:
            connection.execute(
                """CREATE TRIGGER fail_web_tailoring BEFORE INSERT ON tailoring_items
                   BEGIN SELECT RAISE(ABORT, 'forced web failure'); END"""
            )
        self.sign_in()
        response = self.post_bill(
            products=[{"variant_id": variant, "quantity": "1"}],
            tailoring=[self.standard_line(revision)], customer_id=customer["customer_id"],
            paid="1600.00", key="atomic-web-combined1",
        )
        self.assertEqual(400, response.status_code)
        with closing(connect_database(self.database)) as connection:
            self.assertEqual(0, connection.execute("SELECT COUNT(*) FROM sales").fetchone()[0])
            self.assertEqual(0, connection.execute("SELECT COUNT(*) FROM tailoring_orders").fetchone()[0])
            self.assertEqual(0, connection.execute("SELECT COUNT(*) FROM stock_movements WHERE kind = 'sale'").fetchone()[0])

    def test_combined_duplicate_submission_is_idempotent(self):
        customer = self.customer()
        revision = self.measurements(customer["customer_id"])
        self.rate()
        variant = self.variant()
        products = [{"variant_id": variant, "quantity": "1"}]
        tailoring = [self.standard_line(revision)]
        self.sign_in()
        first = self.post_bill(
            products=products, tailoring=tailoring, customer_id=customer["customer_id"],
            paid="1600.00", key="duplicate-web-combined1",
        )
        second = self.post_bill(
            products=products, tailoring=tailoring, customer_id=customer["customer_id"],
            paid="1600.00", key="duplicate-web-combined1",
        )
        self.assertEqual(303, first.status_code)
        self.assertEqual(first.headers["Location"], second.headers["Location"])
        with closing(connect_database(self.database)) as connection:
            self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM sales").fetchone()[0])
            self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM tailoring_orders").fetchone()[0])
            self.assertEqual(4_000, list_stock(connection)[0]["quantity"])

    def test_tailors_can_be_added_in_billing_and_assigned_or_changed(self):
        customer = self.customer()
        revision = self.measurements(customer["customer_id"])
        self.rate()
        self.sign_in()

        response = self.client.post("/tailors", data={
            "csrf_token": self.csrf(), "action": "add",
            "name": "Naveed", "mobile": "03001112222",
        })
        self.assertEqual(303, response.status_code)
        response = self.client.post(
            "/billing/tailors",
            data={"csrf_token": self.csrf(), "name": "Rashid", "mobile": ""},
            headers={"Accept": "application/json"},
        )
        self.assertEqual(201, response.status_code)
        second_tailor = response.get_json()["tailor"]
        billing_page = self.client.get("/billing").get_data(as_text=True)
        self.assertIn("Assigned Tailor", billing_page)
        self.assertIn("data-tailor-dialog", billing_page)
        self.assertIn("Naveed", billing_page)
        self.assertIn("Rashid", billing_page)

        with closing(connect_database(self.database)) as connection:
            first_tailor = connection.execute(
                "SELECT id FROM tailors WHERE name = 'Naveed'"
            ).fetchone()[0]
        line = self.standard_line(revision, tailor_id=first_tailor)
        response = self.post_bill(
            tailoring=[line], customer_id=customer["customer_id"], paid="1500.00",
            key="tailor-web-bill-0001",
        )
        self.assertEqual(303, response.status_code)

        detail = self.client.get("/tailoring/1").get_data(as_text=True)
        self.assertIn("Assigned Tailor", detail)
        self.assertIn("Naveed", detail)
        response = self.client.post("/tailoring/1/items/1/tailor", data={
            "csrf_token": self.csrf(), "tailor_id": second_tailor["id"],
        })
        self.assertEqual(303, response.status_code)
        self.assertIn("#garment-1", response.headers["Location"])
        updated = self.client.get("/tailoring/1").get_data(as_text=True)
        self.assertIn("Tailor assignment updated.", updated)
        self.assertIn("<strong>Rashid</strong>", updated)

    def test_tailoring_search_status_list_and_detail_render_immutable_snapshot(self):
        customer = self.customer()
        revision = self.measurements(customer["customer_id"])
        self.rate()
        self.sign_in()
        self.assertEqual(303, self.post_bill(
            tailoring=[self.standard_line(revision)], customer_id=customer["customer_id"],
            paid="1500.00",
        ).status_code)
        for query in ("TAIL-000001", "CUST-000001", "Ahmed", "03001234567"):
            page = self.client.get("/tailoring", query_string={"q": query}).get_data(as_text=True)
            self.assertIn("TAIL-000001", page)
        page = self.client.get("/tailoring", query_string={"status": "Received"}).get_data(as_text=True)
        self.assertIn("BILL-00000001", page)
        self.assertEqual(400, self.client.get("/tailoring", query_string={"status": "Unknown"}).status_code)
        detail = self.client.get("/tailoring/1").get_data(as_text=True)
        self.assertIn("Immutable measurement snapshot", detail)
        self.assertIn("Saved for this order &middot; inch", detail)
        self.assertIn("40.5 inches", detail)
        self.assertIn("PKR 1,500.00", detail)
        self.assertIn('href="/sales/1"', detail)

    def test_combined_receipt_history_reports_and_product_only_regression(self):
        customer = self.customer()
        revision = self.measurements(customer["customer_id"])
        self.rate()
        variant = self.variant()
        self.sign_in()
        response = self.post_bill(
            products=[{"variant_id": variant, "quantity": "1"}],
            tailoring=[self.standard_line(revision)], customer_id=customer["customer_id"],
            paid="1600.00", key="combined-receipt-web1",
        )
        receipt = self.client.get(response.headers["Location"]).get_data(as_text=True)
        for text in (
            "CUST-000001", "TAIL-000001", "Fabric &rsaquo; Yathreb",
            "Stitching &rsaquo; Shirt", "Customer-provided cloth",
            "Promised delivery", "Initial paid / advance",
        ):
            self.assertIn(text, receipt)
        self.assertNotIn("Current fitting", receipt)
        self.assertIn("BILL-00000001", self.client.get("/sales").get_data(as_text=True))
        self.assertIn("PKR 1,600.00", self.client.get("/sales/daily").get_data(as_text=True))
        product_only = self.post_bill(
            products=[{"variant_id": variant, "quantity": "1"}], paid="100.00",
            key="product-only-regress1",
        )
        self.assertEqual(303, product_only.status_code)
        page = self.client.get(product_only.headers["Location"]).get_data(as_text=True)
        self.assertIn("Fabric &rsaquo; Yathreb", page)
        self.assertNotIn("Tailoring record", page)


if __name__ == "__main__":
    unittest.main()
