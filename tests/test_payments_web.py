"""Focused Phase 3B2B checks for customer balances and later payments."""

from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from werkzeug.security import generate_password_hash

from shop import create_app
from shop.db import connect_database, initialize_database
from shop.inventory import (
    STANDARD_MEASUREMENT_TEMPLATES,
    add_article,
    add_brand,
    add_colour,
    catalogue,
    configure_stitching_rate,
    create_customer,
    finalize_combined_bill,
    get_sale,
    receive_stock,
    record_payment,
    save_measurements,
    set_default_selling_price,
)


class PaymentWebTests(unittest.TestCase):
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
        self.today = date.today().isoformat()
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
            return create_customer(connection, name=name, primary_mobile=mobile)

    def variant(self):
        with closing(connect_database(self.database)) as connection:
            product = next(
                item for item in catalogue(connection)["products"] if item["name"] == "Fabric"
            )
            brand = add_brand(connection, "Yathreb", product["id"])
            article = add_article(connection, "Dastan", brand)
            colour = add_colour(connection, "Blue", brand, article)
            variant_id = receive_stock(
                connection, product_id=product["id"], brand_id=brand,
                article_id=article, colour_id=colour, size_id=None,
                quantity="10", kind="opening", note="",
                request_key="payment-web-stock01", user_id=1,
            )["variant_id"]
            set_default_selling_price(connection, variant_id, 10_000)
            return variant_id

    def tailoring_line(self, customer_id):
        with closing(connect_database(self.database)) as connection:
            definition = STANDARD_MEASUREMENT_TEMPLATES["Shirt"]
            revision_id = save_measurements(
                connection, customer_id=customer_id, garment_category="Shirt",
                measurements={name: "40.5" for name in definition["measurements"]},
                styles={name: False for name in definition["styles"]},
                notes="Payment test snapshot",
            )["revision_id"]
            if connection.execute(
                "SELECT 1 FROM stitching_rate_revisions WHERE garment_category = 'Shirt'"
            ).fetchone() is None:
                configure_stitching_rate(connection, "Shirt", 150_000, 1)
        return {
            "garment_category": "Shirt", "quantity": "1", "cloth_source": "customer",
            "measurement_revision_id": revision_id,
        }

    def bill(self, customer_id, key, *, products=(), tailoring=(), paid=0):
        with closing(connect_database(self.database)) as connection:
            return finalize_combined_bill(
                connection, product_items=list(products), tailoring_items=list(tailoring),
                customer_id=customer_id, discount=0, paid_amount=paid,
                order_date=self.today if tailoring else None,
                promised_date=self.promised if tailoring else None,
                request_key=key, user_id=1,
            )

    def payment_post(self, customer_id, sale_id, amount, key, *, csrf=True):
        data = {"amount": amount, "request_key": key}
        if csrf:
            data["csrf_token"] = self.csrf()
        return self.client.post(
            f"/customers/{customer_id}/bills/{sale_id}/payments/new", data=data
        )

    def test_authentication_csrf_and_customer_balances_sidebar(self):
        customer = self.customer()
        variant = self.variant()
        sale = self.bill(
            customer["customer_id"], "payment-auth-bill01",
            products=[{"variant_id": variant, "quantity": "1"}], paid=0,
        )
        for path in (
            "/customer-balances",
            f"/customers/{customer['customer_id']}/bills/{sale['sale_id']}/payments/new",
            "/payments/1",
        ):
            self.assertEqual(302, self.client.get(path).status_code)
        self.sign_in()
        self.assertEqual(400, self.payment_post(
            customer["customer_id"], sale["sale_id"], "10.00",
            "payment-no-csrf01", csrf=False,
        ).status_code)
        page = self.client.get("/customer-balances").get_data(as_text=True)
        self.assertIn('href="/customer-balances" aria-current="page">Customer Balances</a>', page)

    def test_customer_account_totals_across_bills_and_later_payments(self):
        customer = self.customer()
        variant = self.variant()
        first = self.bill(
            customer["customer_id"], "account-total-bill01",
            products=[{"variant_id": variant, "quantity": "1"}], paid=2_000,
        )
        self.bill(
            customer["customer_id"], "account-total-bill02",
            products=[{"variant_id": variant, "quantity": "2"}], paid=5_000,
        )
        with closing(connect_database(self.database)) as connection:
            record_payment(
                connection, sale_id=first["sale_id"], customer_id=customer["customer_id"],
                amount=3_000, request_key="account-total-pay001", user_id=1,
            )
        self.sign_in()
        page = self.client.get(
            f"/customers/{customer['customer_id']}"
        ).get_data(as_text=True)
        for text in ("Total billed", "PKR 300.00", "Total paid", "PKR 100.00",
                     "Total outstanding", "PKR 200.00"):
            self.assertIn(text, page)
        self.assertIn("Remaining at finalization", page)
        self.assertIn("Current outstanding", page)

    def test_customer_account_lists_product_tailoring_and_combined_bills(self):
        customer = self.customer()
        variant = self.variant()
        self.bill(customer["customer_id"], "account-product-bill1",
                  products=[{"variant_id": variant, "quantity": "1"}], paid=0)
        tailoring = self.tailoring_line(customer["customer_id"])
        self.bill(customer["customer_id"], "account-tailor-bill01",
                  tailoring=[tailoring], paid=0)
        self.bill(customer["customer_id"], "account-combine-bill1",
                  products=[{"variant_id": variant, "quantity": "1"}],
                  tailoring=[tailoring], paid=0)
        self.sign_in()
        page = self.client.get(f"/customers/{customer['customer_id']}").get_data(as_text=True)
        for bill_number in ("BILL-00000001", "BILL-00000002", "BILL-00000003"):
            self.assertIn(bill_number, page)
        self.assertIn('href="/tailoring/1"', page)
        self.assertIn('href="/tailoring/2"', page)

    def test_balance_search_by_customer_id_name_and_normalized_mobile(self):
        customer = self.customer("Ayesha Noor", "0300 123-4567")
        variant = self.variant()
        self.bill(customer["customer_id"], "balance-search-bill1",
                  products=[{"variant_id": variant, "quantity": "1"}], paid=0)
        self.customer("Bilal Khan", "03115555555")
        self.sign_in()
        for query in ("CUST-000001", "ayesha", "+92 300 1234567"):
            page = self.client.get(
                "/customer-balances", query_string={"q": query}
            ).get_data(as_text=True)
            self.assertIn("Ayesha Noor", page)
            self.assertNotIn("Bilal Khan", page)

    def test_outstanding_only_all_customer_and_invalid_scope_filters(self):
        owing = self.customer("Owing Customer", "03001111111")
        clear = self.customer("Clear Customer", "03002222222")
        variant = self.variant()
        self.bill(owing["customer_id"], "scope-owing-bill001",
                  products=[{"variant_id": variant, "quantity": "1"}], paid=0)
        self.bill(clear["customer_id"], "scope-clear-bill001",
                  products=[{"variant_id": variant, "quantity": "1"}], paid=10_000)
        self.sign_in()
        outstanding = self.client.get("/customer-balances").get_data(as_text=True)
        self.assertIn("Owing Customer", outstanding)
        self.assertNotIn("Clear Customer", outstanding)
        all_accounts = self.client.get(
            "/customer-balances", query_string={"scope": "all"}
        ).get_data(as_text=True)
        self.assertIn("Owing Customer", all_accounts)
        self.assertIn("Clear Customer", all_accounts)
        self.assertEqual(400, self.client.get(
            "/customer-balances", query_string={"scope": "unknown"}
        ).status_code)

    def test_payment_form_shows_bill_state_and_enforces_customer_ownership(self):
        first = self.customer()
        second = self.customer("Bilal", "03007654321")
        variant = self.variant()
        sale = self.bill(first["customer_id"], "owner-check-bill001",
                         products=[{"variant_id": variant, "quantity": "2"}], paid=5_000)
        self.sign_in()
        path = f"/customers/{first['customer_id']}/bills/{sale['sale_id']}/payments/new"
        page = self.client.get(path).get_data(as_text=True)
        for text in ("PKR 200.00", "Paid at finalization", "PKR 50.00",
                     "Current outstanding", "PKR 150.00"):
            self.assertIn(text, page)
        cross_path = f"/customers/{second['customer_id']}/bills/{sale['sale_id']}/payments/new"
        self.assertEqual(404, self.client.get(cross_path).status_code)
        response = self.client.post(cross_path, data={
            "csrf_token": self.csrf(), "amount": "10.00",
            "request_key": "cross-owner-payment1",
        })
        self.assertEqual(400, response.status_code)
        self.assertIn("attached to this customer", response.get_data(as_text=True))

    def test_payment_amount_validation_and_fully_paid_rejection(self):
        customer = self.customer()
        variant = self.variant()
        sale = self.bill(customer["customer_id"], "amount-check-bill01",
                         products=[{"variant_id": variant, "quantity": "1"}], paid=0)
        self.sign_in()
        for index, amount in enumerate(("", "0", "-1", "invalid", "100.01")):
            response = self.payment_post(
                customer["customer_id"], sale["sale_id"], amount,
                f"invalid-payment-{index:02d}-key",
            )
            self.assertEqual(400, response.status_code)
        with closing(connect_database(self.database)) as connection:
            record_payment(
                connection, sale_id=sale["sale_id"], customer_id=customer["customer_id"],
                amount=10_000, request_key="fully-paid-direct01", user_id=1,
            )
        response = self.payment_post(
            customer["customer_id"], sale["sale_id"], "1.00", "fully-paid-reject01"
        )
        self.assertEqual(400, response.status_code)
        self.assertIn("already fully paid", response.get_data(as_text=True))

    def test_successful_payment_uses_prg_and_renders_printable_receipt(self):
        customer = self.customer()
        variant = self.variant()
        sale = self.bill(customer["customer_id"], "receipt-source-bill1",
                         products=[{"variant_id": variant, "quantity": "2"}], paid=5_000)
        self.sign_in()
        response = self.payment_post(
            customer["customer_id"], sale["sale_id"], "50.00", "receipt-payment-key1"
        )
        self.assertEqual(303, response.status_code)
        self.assertTrue(response.headers["Location"].endswith("/payments/1"))
        page = self.client.get(response.headers["Location"]).get_data(as_text=True)
        for text in (
            "Yathreb Fabrics and Tailors", "Faisal Heights", "B-block Markaz",
            "03365314722", "03009898997", "PAY-000001", "CUST-000001",
            "BILL-00000001", "Amount received", "PKR 50.00",
            "Outstanding before", "PKR 150.00", "Outstanding after", "PKR 100.00",
            "Thank you", "data-print-receipt", "data-receipt",
        ):
            self.assertIn(text, page)
        css = self.client.get("/static/app.css").get_data(as_text=True)
        self.assertIn("@page { size: 80mm auto;", css)
        self.assertIn("body.receipt-view .page > :not(.receipt)", css)
        with closing(connect_database(self.database)) as connection:
            record_payment(
                connection, sale_id=sale["sale_id"], customer_id=customer["customer_id"],
                amount=2_500, request_key="receipt-second-pay01", user_id=1,
            )
        original_receipt = self.client.get("/payments/1").get_data(as_text=True)
        self.assertIn("Outstanding before", original_receipt)
        self.assertIn("PKR 150.00", original_receipt)
        self.assertIn("Outstanding after", original_receipt)
        self.assertIn("PKR 100.00", original_receipt)

    def test_duplicate_payment_submission_is_idempotent(self):
        customer = self.customer()
        variant = self.variant()
        sale = self.bill(customer["customer_id"], "duplicate-sourcebill1",
                         products=[{"variant_id": variant, "quantity": "1"}], paid=0)
        self.sign_in()
        first = self.payment_post(
            customer["customer_id"], sale["sale_id"], "100.00", "duplicate-payment01"
        )
        second = self.payment_post(
            customer["customer_id"], sale["sale_id"], "100.00", "duplicate-payment01"
        )
        self.assertEqual(303, first.status_code)
        self.assertEqual(first.headers["Location"], second.headers["Location"])
        with closing(connect_database(self.database)) as connection:
            self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM payments").fetchone()[0])

    def test_payment_history_appears_on_customer_and_bill_pages(self):
        customer = self.customer()
        variant = self.variant()
        sale = self.bill(customer["customer_id"], "history-source-bill1",
                         products=[{"variant_id": variant, "quantity": "2"}], paid=0)
        with closing(connect_database(self.database)) as connection:
            record_payment(
                connection, sale_id=sale["sale_id"], customer_id=customer["customer_id"],
                amount=2_500, request_key="history-payment-key1", user_id=1,
            )
        self.sign_in()
        customer_page = self.client.get(
            f"/customers/{customer['customer_id']}"
        ).get_data(as_text=True)
        bill_page = self.client.get(f"/sales/{sale['sale_id']}").get_data(as_text=True)
        for page in (customer_page, bill_page):
            self.assertIn("PAY-000001", page)
            self.assertIn("PKR 25.00", page)
            self.assertIn('href="/payments/1"', page)
        self.assertIn("Remaining at finalization", bill_page)
        self.assertIn("Current outstanding", bill_page)

    def test_payment_does_not_change_inventory_or_finalized_snapshots(self):
        customer = self.customer()
        variant = self.variant()
        tailoring = self.tailoring_line(customer["customer_id"])
        sale = self.bill(
            customer["customer_id"], "immutable-sourcebill1",
            products=[{"variant_id": variant, "quantity": "1"}],
            tailoring=[tailoring], paid=0,
        )
        with closing(connect_database(self.database)) as connection:
            movement_count = connection.execute("SELECT COUNT(*) FROM stock_movements").fetchone()[0]
            sale_snapshot = tuple(connection.execute(
                "SELECT subtotal, discount, grand_total, paid_amount, remaining_balance FROM sales WHERE id = ?",
                (sale["sale_id"],),
            ).fetchone())
            tailoring_snapshot = tuple(connection.execute(
                "SELECT stitching_rate, line_total, measurements_json FROM tailoring_items WHERE order_id = ?",
                (sale["tailoring_order_id"],),
            ).fetchone())
            record_payment(
                connection, sale_id=sale["sale_id"], customer_id=customer["customer_id"],
                amount=5_000, request_key="immutable-web-payment1", user_id=1,
            )
            self.assertEqual(movement_count, connection.execute(
                "SELECT COUNT(*) FROM stock_movements"
            ).fetchone()[0])
            self.assertEqual(sale_snapshot, tuple(connection.execute(
                "SELECT subtotal, discount, grand_total, paid_amount, remaining_balance FROM sales WHERE id = ?",
                (sale["sale_id"],),
            ).fetchone()))
            self.assertEqual(tailoring_snapshot, tuple(connection.execute(
                "SELECT stitching_rate, line_total, measurements_json FROM tailoring_items WHERE order_id = ?",
                (sale["tailoring_order_id"],),
            ).fetchone()))

    def test_sales_reports_exclude_payments_and_bill_types_regress(self):
        customer = self.customer()
        variant = self.variant()
        tailoring = self.tailoring_line(customer["customer_id"])
        first = self.bill(customer["customer_id"], "report-product-bill1",
                          products=[{"variant_id": variant, "quantity": "1"}], paid=0)
        self.bill(customer["customer_id"], "report-tailor-bill01",
                  tailoring=[tailoring], paid=0)
        self.bill(customer["customer_id"], "report-combinedbill1",
                  products=[{"variant_id": variant, "quantity": "1"}],
                  tailoring=[tailoring], paid=0)
        with closing(connect_database(self.database)) as connection:
            record_payment(
                connection, sale_id=first["sale_id"], customer_id=customer["customer_id"],
                amount=5_000, request_key="report-later-payment1", user_id=1,
            )
            self.assertEqual(3, connection.execute("SELECT COUNT(*) FROM sales").fetchone()[0])
        self.sign_in()
        daily = self.client.get("/sales/daily").get_data(as_text=True)
        monthly = self.client.get("/sales/monthly").get_data(as_text=True)
        for page in (daily, monthly):
            self.assertIn("3 bills", page)
            self.assertIn("PKR 3,200.00", page)
        self.assertIn("BILL-00000003", self.client.get("/sales").get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
