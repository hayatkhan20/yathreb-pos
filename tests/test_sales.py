"""Backend and database checks for the immutable Phase 2A sales foundation."""

from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from manage import inspect_database
from shop.db import SCHEMA_IDENTITY, SCHEMA_VERSION, connect_database, initialize_database
from shop.inventory import (
    DomainError,
    add_article,
    add_brand,
    add_colour,
    catalogue,
    finalize_sale,
    get_sale,
    list_movements,
    list_stock,
    receive_stock,
    rename_label,
    set_default_selling_price,
)


class SalesFoundationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = self.root / "inventory.sqlite3"
        initialize_database(self.database, "owner", "test-password-hash", "s" * 48)
        self.conn = connect_database(self.database)

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def product(self, name):
        return next(row for row in catalogue(self.conn)["products"] if row["name"] == name)

    def fabric_variant(self, opening="10"):
        product = self.product("Fabric")
        brand_id = add_brand(self.conn, "Yathreb", product["id"])
        article_id = add_article(self.conn, "Dastan", brand_id)
        colour_id = add_colour(self.conn, "Blue", brand_id, article_id)
        result = receive_stock(
            self.conn,
            product_id=product["id"],
            brand_id=brand_id,
            article_id=article_id,
            colour_id=colour_id,
            size_id=None,
            quantity=opening,
            kind="opening",
            note="",
            request_key="sales-fabric-open-001",
            user_id=1,
        )
        return result["variant_id"], product, brand_id, article_id, colour_id

    def studs_variant(self, opening="10"):
        product = self.product("Studs")
        brand_id = add_brand(self.conn, "Stud Brand", product["id"])
        colour_id = add_colour(self.conn, "Silver", brand_id)
        result = receive_stock(
            self.conn,
            product_id=product["id"],
            brand_id=brand_id,
            article_id=None,
            colour_id=colour_id,
            size_id=None,
            quantity=opening,
            kind="opening",
            note="",
            request_key="sales-studs-open-001",
            user_id=1,
        )
        return result["variant_id"], product, brand_id, colour_id

    def test_schema_v5_identity_and_old_trial_rejection(self):
        self.assertEqual(SCHEMA_VERSION, self.conn.execute("PRAGMA user_version").fetchone()[0])
        self.assertEqual(5, SCHEMA_VERSION)
        identity = self.conn.execute(
            "SELECT value FROM settings WHERE key = 'schema_identity'"
        ).fetchone()[0]
        self.assertEqual(SCHEMA_IDENTITY, identity)
        self.assertEqual("tailor-assignments-v5", identity)
        inspect_database(self.conn)

        old_database = self.root / "schema-v3-trial.sqlite3"
        with closing(sqlite3.connect(old_database)) as old:
            old.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            old.execute(
                "INSERT INTO settings (key, value) VALUES ('schema_identity', 'customer-tailoring-payments-v3')"
            )
            old.execute("PRAGMA user_version = 3")
            old.commit()
            with self.assertRaisesRegex(ValueError, "version"):
                inspect_database(old)

    def test_single_item_uses_default_or_editable_price_and_generates_bill(self):
        variant_id, _, _, _, _ = self.fabric_variant()
        set_default_selling_price(self.conn, variant_id, 10_000)
        first = finalize_sale(
            self.conn,
            items=[{"variant_id": variant_id, "quantity": "1.25"}],
            discount=0,
            paid_amount=12_500,
            request_key="single-default-sale-001",
            user_id=1,
        )
        self.assertEqual("BILL-00000001", first["bill_number"])
        self.assertEqual(12_500, first["subtotal"])
        self.assertEqual(0, first["remaining_balance"])
        saved = get_sale(self.conn, first["sale_id"])
        self.assertEqual("PKR", saved["currency"])
        self.assertTrue(saved["created_at"].endswith("Z"))
        self.assertEqual(1, len(saved["items"]))
        self.assertEqual(10_000, saved["items"][0]["unit_price"])
        self.assertEqual(12_500, saved["items"][0]["line_total"])

        second = finalize_sale(
            self.conn,
            items=[{"variant_id": variant_id, "quantity": "0.5", "unit_price": 12_000}],
            discount=0,
            paid_amount=6_000,
            request_key="single-override-sale-002",
            user_id=1,
        )
        self.assertEqual("BILL-00000002", second["bill_number"])
        self.assertEqual(12_000, get_sale(self.conn, second["sale_id"])["items"][0]["unit_price"])
        self.assertEqual(10_000, list_stock(self.conn)[0]["default_selling_price"])

    def test_multi_item_totals_discount_payment_and_credit_customer(self):
        fabric_id, _, _, _, _ = self.fabric_variant()
        studs_id, _, _, _ = self.studs_variant()
        set_default_selling_price(self.conn, fabric_id, 10_000)
        set_default_selling_price(self.conn, studs_id, 5_000)
        result = finalize_sale(
            self.conn,
            items=[
                {"variant_id": fabric_id, "quantity": "2"},
                {"variant_id": studs_id, "quantity": "2"},
            ],
            discount=2_500,
            paid_amount=7_500,
            customer_name="  Ahmed   Khan ",
            customer_mobile=" 0300 1234567 ",
            request_key="multi-credit-sale-001",
            user_id=1,
        )
        self.assertEqual(30_000, result["subtotal"])
        self.assertEqual(2_500, result["discount"])
        self.assertEqual(27_500, result["grand_total"])
        self.assertEqual(7_500, result["paid_amount"])
        self.assertEqual(20_000, result["remaining_balance"])
        saved = get_sale(self.conn, result["sale_id"])
        self.assertEqual("Ahmed Khan", saved["customer_name"])
        self.assertEqual("0300 1234567", saved["customer_mobile"])
        self.assertEqual(2, len(saved["items"]))

    def test_credit_requires_both_customer_fields_and_bill_amounts_are_bounded(self):
        variant_id, _, _, _ = self.studs_variant()
        set_default_selling_price(self.conn, variant_id, 5_000)
        base = {
            "items": [{"variant_id": variant_id, "quantity": "1"}],
            "discount": 0,
            "paid_amount": 1_000,
            "user_id": 1,
        }
        with self.assertRaisesRegex(DomainError, "name and mobile"):
            finalize_sale(
                self.conn,
                customer_name="",
                customer_mobile="03001234567",
                request_key="credit-missing-name-01",
                **base,
            )
        with self.assertRaisesRegex(DomainError, "name and mobile"):
            finalize_sale(
                self.conn,
                customer_name="Ahmed",
                customer_mobile="",
                request_key="credit-missing-phone1",
                **base,
            )
        with self.assertRaisesRegex(DomainError, "discount"):
            finalize_sale(
                self.conn,
                items=base["items"],
                discount=6_000,
                paid_amount=0,
                request_key="discount-too-large-01",
                user_id=1,
            )
        with self.assertRaisesRegex(DomainError, "paid amount"):
            finalize_sale(
                self.conn,
                items=base["items"],
                discount=0,
                paid_amount=6_000,
                request_key="payment-too-large-001",
                user_id=1,
            )
        paid = finalize_sale(
            self.conn,
            items=base["items"],
            discount=0,
            paid_amount=5_000,
            request_key="paid-no-customer-0001",
            user_id=1,
        )
        self.assertEqual(0, paid["remaining_balance"])

    def test_failure_on_second_line_rolls_back_sale_items_movements_and_sequence(self):
        fabric_id, _, _, _, _ = self.fabric_variant()
        studs_id, _, _, _ = self.studs_variant()
        set_default_selling_price(self.conn, fabric_id, 10_000)
        set_default_selling_price(self.conn, studs_id, 5_000)
        starting = {row["id"]: row["quantity"] for row in list_stock(self.conn)}
        self.conn.execute(
            f"""CREATE TRIGGER force_second_sale_failure BEFORE INSERT ON stock_movements
                WHEN NEW.kind = 'sale' AND NEW.variant_id = {studs_id}
                BEGIN SELECT RAISE(ABORT, 'forced second-line failure'); END"""
        )

        with self.assertRaises(DomainError):
            finalize_sale(
                self.conn,
                items=[
                    {"variant_id": fabric_id, "quantity": "1"},
                    {"variant_id": studs_id, "quantity": "1"},
                ],
                discount=0,
                paid_amount=15_000,
                request_key="atomic-two-line-sale1",
                user_id=1,
            )
        self.assertEqual(0, self.conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0])
        self.assertEqual(0, self.conn.execute("SELECT COUNT(*) FROM sale_items").fetchone()[0])
        self.assertEqual(
            0,
            self.conn.execute("SELECT COUNT(*) FROM stock_movements WHERE kind = 'sale'").fetchone()[0],
        )
        self.assertEqual(1, self.conn.execute("SELECT next_number FROM bill_sequence").fetchone()[0])
        self.assertEqual(starting, {row["id"]: row["quantity"] for row in list_stock(self.conn)})

    def test_duplicate_submission_replays_without_duplicate_sale_or_stock_deduction(self):
        variant_id, _, _, _ = self.studs_variant(opening="5")
        set_default_selling_price(self.conn, variant_id, 5_000)
        values = {
            "items": [{"variant_id": variant_id, "quantity": "2"}],
            "discount": 0,
            "paid_amount": 10_000,
            "request_key": "duplicate-sale-request1",
            "user_id": 1,
        }
        first = finalize_sale(self.conn, **values)
        replay = finalize_sale(self.conn, **values)
        self.assertFalse(first["replayed"])
        self.assertTrue(replay["replayed"])
        self.assertEqual(first["sale_id"], replay["sale_id"])
        self.assertEqual(1, self.conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0])
        self.assertEqual(1, self.conn.execute("SELECT COUNT(*) FROM sale_items").fetchone()[0])
        self.assertEqual(
            1,
            self.conn.execute("SELECT COUNT(*) FROM stock_movements WHERE kind = 'sale'").fetchone()[0],
        )
        self.assertEqual(3_000, list_stock(self.conn)[0]["quantity"])

        changed = dict(values)
        changed["items"] = [{"variant_id": variant_id, "quantity": "1"}]
        with self.assertRaisesRegex(DomainError, "different details"):
            finalize_sale(self.conn, **changed)
        self.assertEqual(3_000, list_stock(self.conn)[0]["quantity"])

    def test_finalized_sale_and_item_snapshots_are_immutable(self):
        variant_id, product, _, _, colour_id = self.fabric_variant()
        set_default_selling_price(self.conn, variant_id, 10_000)
        result = finalize_sale(
            self.conn,
            items=[{"variant_id": variant_id, "quantity": "1", "unit_price": 12_000}],
            discount=0,
            paid_amount=12_000,
            request_key="immutable-sale-record01",
            user_id=1,
        )
        rename_label(self.conn, "product", product["id"], "Dress Fabric")
        rename_label(self.conn, "colour", colour_id, "Navy")
        set_default_selling_price(self.conn, variant_id, 15_000)
        saved = get_sale(self.conn, result["sale_id"])
        self.assertEqual("Fabric", saved["items"][0]["product"])
        self.assertEqual("Blue", saved["items"][0]["colour"])
        self.assertEqual(12_000, saved["items"][0]["unit_price"])
        movement = next(row for row in list_movements(self.conn) if row["kind"] == "sale")
        self.assertEqual("Fabric", movement["product"])
        self.assertEqual("Blue", movement["colour"])

        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "UPDATE sales SET customer_name = 'Changed' WHERE id = ?",
                (result["sale_id"],),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "UPDATE sale_items SET unit_price = 1 WHERE sale_id = ?",
                (result["sale_id"],),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("DELETE FROM sales WHERE id = ?", (result["sale_id"],))

    def test_pair_piece_quantities_are_whole_while_fabric_remains_fixed_precision(self):
        studs_id, _, _, _ = self.studs_variant()
        fabric_id, _, _, _, _ = self.fabric_variant()
        with self.assertRaisesRegex(DomainError, "whole quantities"):
            finalize_sale(
                self.conn,
                items=[{"variant_id": studs_id, "quantity": "1.5", "unit_price": 5_000}],
                discount=0,
                paid_amount=7_500,
                request_key="fractional-pair-sale01",
                user_id=1,
            )
        result = finalize_sale(
            self.conn,
            items=[{"variant_id": fabric_id, "quantity": "1.125", "unit_price": 10_000}],
            discount=0,
            paid_amount=11_250,
            request_key="fractional-metre-sale1",
            user_id=1,
        )
        self.assertEqual(1_125, get_sale(self.conn, result["sale_id"])["items"][0]["quantity"])

    def test_sale_can_make_stock_negative_and_later_incoming_stock_corrects_balance(self):
        variant_id, product, brand_id, colour_id = self.studs_variant(opening="1")
        set_default_selling_price(self.conn, variant_id, 5_000)
        result = finalize_sale(
            self.conn,
            items=[{"variant_id": variant_id, "quantity": "3"}],
            discount=0,
            paid_amount=15_000,
            request_key="negative-stock-sale-001",
            user_id=1,
        )
        self.assertEqual(-2_000, list_stock(self.conn)[0]["quantity"])
        sale_item = get_sale(self.conn, result["sale_id"])["items"][0]
        movement = self.conn.execute(
            "SELECT quantity, kind FROM stock_movements WHERE id = ?",
            (sale_item["stock_movement_id"],),
        ).fetchone()
        self.assertEqual("sale", movement["kind"])
        self.assertEqual(-3_000, movement["quantity"])

        receive_stock(
            self.conn,
            product_id=product["id"],
            brand_id=brand_id,
            article_id=None,
            colour_id=colour_id,
            size_id=None,
            quantity="5",
            kind="receipt",
            note="Entered after the sale",
            request_key="late-incoming-stock-01",
            user_id=1,
        )
        self.assertEqual(3_000, list_stock(self.conn)[0]["quantity"])


if __name__ == "__main__":
    unittest.main()
