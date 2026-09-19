"""Focused backend checks for Phase 3A customers, tailoring and later payments."""

from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from manage import inspect_database
from shop.db import SCHEMA_IDENTITY, SCHEMA_VERSION, connect_database, initialize_database
from shop.inventory import (
    CUSTOM_GARMENT_CATEGORY,
    GARMENT_CATEGORIES,
    STANDARD_MEASUREMENT_TEMPLATES,
    DomainError,
    add_article,
    add_brand,
    add_colour,
    bill_outstanding_balance,
    catalogue,
    configure_stitching_rate,
    create_customer,
    customer_account_balance,
    finalize_combined_bill,
    finalize_sale,
    get_measurement_revisions,
    get_sale,
    get_tailoring_order,
    list_payments,
    list_stock,
    receive_stock,
    record_payment,
    save_measurements,
    search_customers,
    set_default_selling_price,
    update_tailoring_status,
)


class CustomerTailoringPaymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.database = Path(self.temp.name) / "inventory.sqlite3"
        initialize_database(self.database, "owner", "test-password-hash", "s" * 48)
        self.conn = connect_database(self.database)

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def customer(self, suffix="1"):
        return create_customer(
            self.conn, name=f"Customer {suffix}", primary_mobile=f"0300123456{suffix}",
            alternate_mobile="051 1234567", address="Islamabad", notes="Test customer",
        )["customer_id"]

    def measurements(self, customer_id, category="Shalwar Kameez", amount="40"):
        if category == CUSTOM_GARMENT_CATEGORY:
            values = {"Custom width": amount, "Custom length": "42.5"}
            styles = {}
            custom = "Special uniform"
        else:
            template = STANDARD_MEASUREMENT_TEMPLATES[category]
            values = {label: amount for label in template["measurements"]}
            styles = {label: False for label in template["styles"]}
            custom = ""
        return save_measurements(
            self.conn, customer_id=customer_id, garment_category=category,
            custom_description=custom, measurements=values, styles=styles,
            notes="Current fitting",
        )["revision_id"]

    def tailoring_line(self, customer_id, **changes):
        changes = dict(changes)
        category = changes.get("garment_category", "Shalwar Kameez")
        rate = changes.pop("stitching_rate", 250_000)
        line = {
            "garment_category": category,
            "custom_description": "Special uniform" if category == CUSTOM_GARMENT_CATEGORY else "",
            "quantity": "1",
            "cloth_source": "Customer-provided",
            "measurement_revision_id": self.measurements(customer_id, category),
        }
        if category == CUSTOM_GARMENT_CATEGORY:
            line["stitching_rate"] = rate
        else:
            configure_stitching_rate(self.conn, category, rate, 1)
        line.update(changes)
        return line

    def fabric_variant(self):
        product = next(p for p in catalogue(self.conn)["products"] if p["name"] == "Fabric")
        brand = add_brand(self.conn, "Yathreb", product["id"])
        article = add_article(self.conn, "Dastan", brand)
        colour = add_colour(self.conn, "Blue", brand, article)
        result = receive_stock(
            self.conn, product_id=product["id"], brand_id=brand, article_id=article,
            colour_id=colour, size_id=None, quantity="2", kind="opening", note="",
            request_key="tailoring-stock-open-001", user_id=1,
        )
        set_default_selling_price(self.conn, result["variant_id"], 100_000)
        return result["variant_id"]

    def combined(self, customer_id, *, product_items=(), tailoring_items=None,
                 paid=0, discount=0, key="combined-bill-key-0001"):
        if tailoring_items is None:
            tailoring_items = [self.tailoring_line(customer_id)]
        return finalize_combined_bill(
            self.conn, product_items=list(product_items), tailoring_items=list(tailoring_items),
            discount=discount, paid_amount=paid, customer_id=customer_id,
            order_date="2026-09-14", promised_date="2026-09-20",
            tailoring_notes="Handle carefully", request_key=key, user_id=1,
        )

    def test_schema_v4_customer_sequences_normalized_search_and_duplicate_override(self):
        self.assertEqual(4, SCHEMA_VERSION)
        self.assertEqual("measurement-templates-rates-v4", SCHEMA_IDENTITY)
        self.assertEqual(4, self.conn.execute("PRAGMA user_version").fetchone()[0])
        inspect_database(self.conn)
        first = create_customer(self.conn, name="Ahmed", primary_mobile="0300 1234567")
        second = create_customer(self.conn, name="Bilal", primary_mobile="0300-1234568")
        self.assertEqual("CUST-000001", first["customer_number"])
        self.assertEqual("CUST-000002", second["customer_number"])
        with self.assertRaisesRegex(DomainError, "already uses"):
            create_customer(self.conn, name="Duplicate", primary_mobile="+92 300 1234567")
        shared = create_customer(
            self.conn, name="Family member", primary_mobile="+92 300 1234567",
            allow_shared_primary_mobile=True,
        )
        self.assertEqual("CUST-000003", shared["customer_number"])
        self.assertEqual(2, len(search_customers(self.conn, "03001234567")))
        self.assertEqual(first["customer_id"], search_customers(self.conn, "CUST-000001")[0]["id"])

    def test_measurement_profile_supports_all_categories_and_append_only_revisions(self):
        customer_id = self.customer()
        revision_ids = []
        for category in GARMENT_CATEGORIES:
            revision_ids.append(self.measurements(customer_id, category))
        newer_id = self.measurements(customer_id, "Shalwar Kameez", "41.125")
        revisions = get_measurement_revisions(self.conn, customer_id, "Shalwar Kameez")
        self.assertEqual(newer_id, revisions[0]["id"])
        self.assertEqual(41_125, revisions[0]["measurements"]["Chest"])
        self.assertEqual(40_000, revisions[1]["measurements"]["Chest"])
        self.assertEqual(1, self.conn.execute("SELECT COUNT(*) FROM measurement_profiles").fetchone()[0])
        self.assertEqual(9, self.conn.execute("SELECT COUNT(*) FROM measurement_revisions").fetchone()[0])
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("UPDATE measurement_revisions SET notes = 'Changed' WHERE id = ?", (revision_ids[0],))

    def test_tailoring_only_bill_has_one_number_totals_and_no_inventory_movement(self):
        customer_id = self.customer()
        line = self.tailoring_line(customer_id, quantity="2", stitching_rate=300_000)
        result = self.combined(customer_id, tailoring_items=[line], paid=100_000, discount=50_000)
        self.assertEqual("BILL-00000001", result["bill_number"])
        self.assertEqual("TAIL-000001", result["tailoring_number"])
        self.assertEqual(600_000, result["subtotal"])
        self.assertEqual(550_000, result["grand_total"])
        self.assertEqual(450_000, result["remaining_balance"])
        self.assertEqual(0, self.conn.execute("SELECT COUNT(*) FROM stock_movements").fetchone()[0])
        order = get_tailoring_order(self.conn, result["tailoring_order_id"])
        self.assertEqual("Received", order["status"])
        self.assertEqual("customer", order["items"][0]["cloth_source"])
        update_tailoring_status(self.conn, order["id"], "In Progress")
        self.assertEqual("In Progress", get_tailoring_order(self.conn, order["id"])["status"])
        second = self.combined(
            customer_id, tailoring_items=[line], paid=600_000,
            key="second-tailoring-order1",
        )
        self.assertEqual("TAIL-000002", second["tailoring_number"])

    def test_combined_bill_links_shop_cloth_and_only_product_line_moves_inventory(self):
        customer_id = self.customer()
        variant_id = self.fabric_variant()
        tailoring = self.tailoring_line(
            customer_id, cloth_source="Purchased from shop", source_product_line=1,
            stitching_rate=200_000,
        )
        result = self.combined(
            customer_id,
            product_items=[{"variant_id": variant_id, "quantity": "1.25", "unit_price": 120_000}],
            tailoring_items=[tailoring], paid=340_000, discount=10_000,
        )
        self.assertEqual(350_000, result["subtotal"])
        self.assertEqual(340_000, result["grand_total"])
        self.assertEqual(1, self.conn.execute("SELECT COUNT(*) FROM sale_items").fetchone()[0])
        self.assertEqual(1, self.conn.execute("SELECT COUNT(*) FROM stock_movements WHERE kind = 'sale'").fetchone()[0])
        self.assertEqual(750, list_stock(self.conn)[0]["quantity"])
        order = get_tailoring_order(self.conn, result["tailoring_order_id"])
        self.assertIsNotNone(order["items"][0]["source_sale_item_id"])
        self.assertEqual(result["bill_number"], order["bill_number"])

    def test_product_only_regression_and_phase3_credit_requires_customer(self):
        variant_id = self.fabric_variant()
        legacy = finalize_sale(
            self.conn, items=[{"variant_id": variant_id, "quantity": "0.5"}],
            discount=0, paid_amount=50_000, request_key="legacy-product-sale-01", user_id=1,
        )
        self.assertEqual(50_000, legacy["subtotal"])
        with self.assertRaisesRegex(DomainError, "customer"):
            finalize_combined_bill(
                self.conn, product_items=[{"variant_id": variant_id, "quantity": "0.25"}],
                tailoring_items=[], discount=0, paid_amount=0, customer_id=None,
                request_key="phase3-credit-no-cust", user_id=1,
            )
        paid = finalize_combined_bill(
            self.conn, product_items=[{"variant_id": variant_id, "quantity": "0.25"}],
            tailoring_items=[], discount=0, paid_amount=25_000, customer_id=None,
            request_key="phase3-paid-no-cust01", user_id=1,
        )
        self.assertEqual(0, paid["remaining_balance"])

    def test_tailoring_requires_customer_measurements_valid_dates_and_whole_quantity(self):
        customer_id = self.customer()
        line = self.tailoring_line(customer_id)
        with self.assertRaisesRegex(DomainError, "customer"):
            finalize_combined_bill(
                self.conn, product_items=[], tailoring_items=[line], discount=0,
                paid_amount=250_000, customer_id=None, order_date="2026-09-14",
                promised_date="2026-09-20", request_key="tailor-no-customer-01", user_id=1,
            )
        fractional = dict(line, quantity="1.5")
        with self.assertRaisesRegex(DomainError, "whole"):
            self.combined(customer_id, tailoring_items=[fractional], key="tailor-fractional-001")
        with self.assertRaisesRegex(DomainError, "before"):
            finalize_combined_bill(
                self.conn, product_items=[], tailoring_items=[line], discount=0,
                paid_amount=250_000, customer_id=customer_id, order_date="2026-09-20",
                promised_date="2026-09-14", request_key="tailor-bad-date-0001", user_id=1,
            )

    def test_failure_in_tailoring_rolls_back_bill_movement_order_and_sequences(self):
        customer_id = self.customer()
        variant_id = self.fabric_variant()
        line = self.tailoring_line(customer_id)
        self.conn.execute(
            """CREATE TRIGGER force_tailoring_failure BEFORE INSERT ON tailoring_items
               BEGIN SELECT RAISE(ABORT, 'forced tailoring failure'); END"""
        )
        with self.assertRaises(DomainError):
            self.combined(
                customer_id, product_items=[{"variant_id": variant_id, "quantity": "1"}],
                tailoring_items=[line], paid=350_000, key="atomic-combined-bill1",
            )
        self.assertEqual(0, self.conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0])
        self.assertEqual(0, self.conn.execute("SELECT COUNT(*) FROM tailoring_orders").fetchone()[0])
        self.assertEqual(0, self.conn.execute("SELECT COUNT(*) FROM stock_movements WHERE kind = 'sale'").fetchone()[0])
        self.assertEqual(1, self.conn.execute("SELECT next_number FROM bill_sequence").fetchone()[0])
        self.assertEqual(1, self.conn.execute("SELECT next_number FROM tailoring_sequence").fetchone()[0])

    def test_bill_and_payment_retries_are_idempotent_and_overpayment_is_rejected(self):
        customer_id = self.customer()
        line = self.tailoring_line(customer_id, stitching_rate=500_000)
        first = self.combined(customer_id, tailoring_items=[line], paid=100_000, key="retry-combined-bill1")
        replay = self.combined(customer_id, tailoring_items=[line], paid=100_000, key="retry-combined-bill1")
        self.assertFalse(first["replayed"])
        self.assertTrue(replay["replayed"])
        payment = record_payment(
            self.conn, sale_id=first["sale_id"], customer_id=customer_id, amount=150_000,
            request_key="later-payment-key-001", user_id=1,
        )
        replayed = record_payment(
            self.conn, sale_id=first["sale_id"], customer_id=customer_id, amount=150_000,
            request_key="later-payment-key-001", user_id=1,
        )
        self.assertEqual("PAY-000001", payment["payment_number"])
        self.assertTrue(replayed["replayed"])
        self.assertEqual(250_000, bill_outstanding_balance(self.conn, first["sale_id"]))
        with self.assertRaisesRegex(DomainError, "exceed"):
            record_payment(
                self.conn, sale_id=first["sale_id"], customer_id=customer_id, amount=250_001,
                request_key="later-overpayment-001", user_id=1,
            )
        self.assertEqual(1, len(list_payments(self.conn, first["sale_id"])))

    def test_tailoring_measurement_and_financial_snapshots_remain_immutable(self):
        customer_id = self.customer()
        line = self.tailoring_line(customer_id, stitching_rate=250_000)
        result = self.combined(customer_id, tailoring_items=[line], paid=0)
        self.measurements(customer_id, "Shalwar Kameez", "44")
        order = get_tailoring_order(self.conn, result["tailoring_order_id"])
        self.assertEqual(40_000, order["items"][0]["measurements"]["Chest"])
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("UPDATE tailoring_items SET stitching_rate = 1 WHERE order_id = ?", (order["id"],))
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("UPDATE sales SET paid_amount = 1 WHERE id = ?", (result["sale_id"],))
        payment = record_payment(
            self.conn, sale_id=result["sale_id"], customer_id=customer_id, amount=1,
            request_key="immutable-payment-001", user_id=1,
        ) if result["remaining_balance"] else None
        if payment:
            with self.assertRaises(sqlite3.IntegrityError):
                self.conn.execute("UPDATE payments SET amount = 2 WHERE id = ?", (payment["id"],))

    def test_customer_account_balance_derives_across_multiple_bills_and_payments(self):
        customer_id = self.customer()
        first = self.combined(customer_id, paid=50_000, key="account-balance-bill01")
        second = self.combined(customer_id, paid=100_000, key="account-balance-bill02")
        self.assertEqual(350_000, customer_account_balance(self.conn, customer_id))
        first_payment = record_payment(
            self.conn, sale_id=first["sale_id"], customer_id=customer_id, amount=75_000,
            request_key="account-payment-one01", user_id=1,
        )
        second_payment = record_payment(
            self.conn, sale_id=second["sale_id"], customer_id=customer_id, amount=25_000,
            request_key="account-payment-two01", user_id=1,
        )
        self.assertEqual("PAY-000001", first_payment["payment_number"])
        self.assertEqual("PAY-000002", second_payment["payment_number"])
        self.assertEqual(250_000, customer_account_balance(self.conn, customer_id))


if __name__ == "__main__":
    unittest.main()
