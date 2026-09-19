"""Focused Phase 3A.1 checks for canonical templates and versioned rates."""

from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from shop.db import connect_database, initialize_database
from shop.inventory import (
    CUSTOM_GARMENT_CATEGORY,
    STANDARD_MEASUREMENT_TEMPLATES,
    DomainError,
    add_article,
    add_brand,
    add_colour,
    catalogue,
    configure_stitching_rate,
    create_customer,
    finalize_combined_bill,
    finalize_sale,
    get_current_stitching_rates,
    get_measurement_revisions,
    get_stitching_rate_history,
    get_tailoring_order,
    list_stock,
    measurement_templates,
    receive_stock,
    save_measurements,
    set_default_selling_price,
)


class TailoringTemplateRateTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.database = Path(self.temp.name) / "inventory.sqlite3"
        initialize_database(self.database, "owner", "test-password-hash", "s" * 48)
        self.conn = connect_database(self.database)
        self.customer_id = create_customer(
            self.conn, name="Ahmed Khan", primary_mobile="03001234567"
        )["customer_id"]

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def fields(self, category, value="40.5"):
        template = STANDARD_MEASUREMENT_TEMPLATES[category]
        measurements = {name: value for name in template["measurements"]}
        styles = {name: False for name in template["styles"]}
        return measurements, styles

    def save_standard(self, category, value="40.5", note="Template note"):
        measurements, styles = self.fields(category, value)
        return save_measurements(
            self.conn, customer_id=self.customer_id, garment_category=category,
            measurements=measurements, styles=styles, notes=note,
        )["revision_id"]

    def finalize_tailoring(self, line, key, paid):
        return finalize_combined_bill(
            self.conn, product_items=[], tailoring_items=[line], customer_id=self.customer_id,
            discount=0, paid_amount=paid, order_date="2026-09-14",
            promised_date="2026-09-20", request_key=key, user_id=1,
        )

    def fabric_variant(self):
        product = next(row for row in catalogue(self.conn)["products"] if row["name"] == "Fabric")
        brand_id = add_brand(self.conn, "Yathreb", product["id"])
        article_id = add_article(self.conn, "Dastan", brand_id)
        colour_id = add_colour(self.conn, "Blue", brand_id, article_id)
        variant_id = receive_stock(
            self.conn, product_id=product["id"], brand_id=brand_id, article_id=article_id,
            colour_id=colour_id, size_id=None, quantity="5", kind="opening", note="",
            request_key="template-stock-open-001", user_id=1,
        )["variant_id"]
        set_default_selling_price(self.conn, variant_id, 100_000)
        return variant_id

    def test_exactly_seven_standard_templates_and_confirmed_shared_shapes(self):
        templates = measurement_templates()
        waistcoat = {
            "measurements": ["Length", "Shoulder", "Neck", "Chest", "Waist", "Hip"],
            "styles": ["Band Collar", "Round Neck", "V Neck", "Rounded Daman", "Square Daman"],
        }
        coat = {
            "measurements": ["Length", "Shoulder", "Sleeves", "Neck", "Chest", "Hip", "Arm-hole"],
            "styles": ["Band Coat", "Collar Coat", "English Coat", "Two Button",
                       "Single-Breasted", "Double-Breasted"],
        }
        self.assertEqual({
            "Pakistani Waistcoat": waistcoat,
            "Three-Piece Waistcoat": waistcoat,
            "Coat": coat,
            "Sherwani": coat,
            "Pant": {
                "measurements": ["Butt", "Hip", "Length", "Thigh (Raan)", "Knee", "Paincha"],
                "styles": ["Plain", "Double Dart", "Baggy Pant"],
            },
            "Shalwar Kameez": {
                "measurements": ["Kameez Length", "Shoulder", "Sleeves", "Collar", "Chest",
                                 "Arm-hole", "Shalwar Length", "Paincha"],
                "styles": ["Collar", "Patti", "Cuff", "Front Pocket", "Side Pocket",
                           "Shalwar Pocket", "Daman"],
            },
            "Shirt": {
                "measurements": ["Length", "Shoulder", "Sleeves", "Collar", "Chest", "Arm-hole"],
                "styles": ["Collar", "Patti", "Cuff", "Front Pocket", "Daman"],
            },
        }, templates)
        self.assertNotIn(CUSTOM_GARMENT_CATEGORY, templates)
        self.assertEqual(templates["Pakistani Waistcoat"], templates["Three-Piece Waistcoat"])
        self.assertEqual(templates["Coat"], templates["Sherwani"])

    def test_standard_numeric_measurements_are_exact_positive_and_decimal(self):
        measurements, styles = self.fields("Pakistani Waistcoat", "40.125")
        saved = save_measurements(
            self.conn, customer_id=self.customer_id, garment_category="Pakistani Waistcoat",
            measurements=measurements, styles=styles, notes="Fitting note",
        )
        revision = get_measurement_revisions(
            self.conn, self.customer_id, "Pakistani Waistcoat"
        )[0]
        self.assertEqual(saved["revision_id"], revision["id"])
        self.assertEqual(40_125, revision["measurements"]["Chest"])
        self.assertEqual("Fitting note", revision["notes"])
        invalid = dict(measurements, Chest="0")
        with self.assertRaisesRegex(DomainError, "positive"):
            save_measurements(
                self.conn, customer_id=self.customer_id, garment_category="Pakistani Waistcoat",
                measurements=invalid, styles=styles,
            )
        missing = dict(measurements)
        missing.pop("Hip")
        with self.assertRaisesRegex(DomainError, "exactly"):
            save_measurements(
                self.conn, customer_id=self.customer_id, garment_category="Pakistani Waistcoat",
                measurements=missing, styles=styles,
            )

    def test_standard_style_values_require_every_named_boolean_checkbox(self):
        measurements, styles = self.fields("Coat")
        invalid = dict(styles)
        invalid["Band Coat"] = 1
        with self.assertRaisesRegex(DomainError, "true or false"):
            save_measurements(
                self.conn, customer_id=self.customer_id, garment_category="Coat",
                measurements=measurements, styles=invalid,
            )
        missing = dict(styles)
        missing.pop("English Coat")
        with self.assertRaisesRegex(DomainError, "every confirmed"):
            save_measurements(
                self.conn, customer_id=self.customer_id, garment_category="Coat",
                measurements=measurements, styles=missing,
            )
        styles["English Coat"] = True
        save_measurements(
            self.conn, customer_id=self.customer_id, garment_category="Coat",
            measurements=measurements, styles=styles,
        )
        self.assertTrue(get_measurement_revisions(self.conn, self.customer_id, "Coat")[0]["styles"]["English Coat"])

    def test_custom_item_has_flexible_fields_notes_and_no_standard_template(self):
        saved = save_measurements(
            self.conn, customer_id=self.customer_id, garment_category=CUSTOM_GARMENT_CATEGORY,
            custom_description="Curtain alteration",
            measurements={"Finished width": "24.25", "Drop": "36"}, notes="Match existing hem",
        )
        revision = get_measurement_revisions(
            self.conn, self.customer_id, CUSTOM_GARMENT_CATEGORY
        )[0]
        self.assertEqual(saved["revision_id"], revision["id"])
        self.assertEqual({}, revision["styles"])
        self.assertEqual(24_250, revision["measurements"]["Finished width"])
        self.assertEqual("Match existing hem", revision["notes"])

    def test_standard_order_requires_configured_rate_and_rejects_manual_override(self):
        revision_id = self.save_standard("Shirt")
        line = {
            "garment_category": "Shirt", "quantity": "1", "cloth_source": "customer",
            "measurement_revision_id": revision_id,
        }
        with self.assertRaisesRegex(DomainError, "Configure a default stitching rate"):
            self.finalize_tailoring(line, "missing-default-rate-01", 0)
        configure_stitching_rate(self.conn, "Shirt", 150_000, 1)
        with self.assertRaisesRegex(DomainError, "cannot be overridden"):
            self.finalize_tailoring(
                dict(line, stitching_rate=150_000), "manual-standard-rate01", 150_000
            )

    def test_rate_changes_append_revisions_and_expose_latest_without_overwrite(self):
        first = configure_stitching_rate(self.conn, "Pant", 200_000, 1)
        second = configure_stitching_rate(self.conn, "Pant", 225_000, 1)
        history = get_stitching_rate_history(self.conn, "Pant")
        self.assertEqual([2, 1], [row["revision_number"] for row in history])
        self.assertEqual([225_000, 200_000], [row["rate"] for row in history])
        self.assertEqual(second["revision_id"], get_current_stitching_rates(self.conn)["Pant"]["id"])
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "UPDATE stitching_rate_revisions SET rate = 1 WHERE id = ?",
                (first["revision_id"],),
            )

    def test_new_order_uses_latest_rate_while_old_snapshot_and_retry_remain_stable(self):
        revision_id = self.save_standard("Shalwar Kameez")
        line = {
            "garment_category": "Shalwar Kameez", "quantity": "1",
            "cloth_source": "Customer-provided", "measurement_revision_id": revision_id,
        }
        configure_stitching_rate(self.conn, "Shalwar Kameez", 250_000, 1)
        first = self.finalize_tailoring(line, "old-rate-order-key001", 250_000)
        configure_stitching_rate(self.conn, "Shalwar Kameez", 300_000, 1)
        second = self.finalize_tailoring(line, "new-rate-order-key001", 300_000)
        first_item = get_tailoring_order(self.conn, first["tailoring_order_id"])["items"][0]
        second_item = get_tailoring_order(self.conn, second["tailoring_order_id"])["items"][0]
        self.assertEqual(250_000, first_item["stitching_rate"])
        self.assertEqual(300_000, second_item["stitching_rate"])
        self.assertNotEqual(first_item["stitching_rate_revision_id"], second_item["stitching_rate_revision_id"])
        replay = self.finalize_tailoring(line, "old-rate-order-key001", 250_000)
        self.assertTrue(replay["replayed"])
        self.assertEqual(first["sale_id"], replay["sale_id"])

    def test_custom_tailoring_product_only_and_combined_billing_regressions(self):
        custom_revision = save_measurements(
            self.conn, customer_id=self.customer_id, garment_category=CUSTOM_GARMENT_CATEGORY,
            custom_description="Repair", measurements={"Opening": "8.5"}, notes="Repair note",
        )["revision_id"]
        custom = self.finalize_tailoring(
            {"garment_category": CUSTOM_GARMENT_CATEGORY, "custom_description": "Repair",
             "quantity": "1", "stitching_rate": 75_000, "cloth_source": "customer",
             "measurement_revision_id": custom_revision},
            "custom-tailoring-key01", 75_000,
        )
        self.assertEqual(75_000, custom["subtotal"])
        self.assertEqual(0, self.conn.execute("SELECT COUNT(*) FROM stock_movements").fetchone()[0])

        variant_id = self.fabric_variant()
        product_only = finalize_sale(
            self.conn, items=[{"variant_id": variant_id, "quantity": "1"}], discount=0,
            paid_amount=100_000, request_key="template-product-only1", user_id=1,
        )
        self.assertEqual(100_000, product_only["subtotal"])

        standard_revision = self.save_standard("Shirt")
        configure_stitching_rate(self.conn, "Shirt", 200_000, 1)
        combined = finalize_combined_bill(
            self.conn, product_items=[{"variant_id": variant_id, "quantity": "0.5"}],
            tailoring_items=[{"garment_category": "Shirt", "quantity": "1",
                              "cloth_source": "shop", "source_product_line": 1,
                              "measurement_revision_id": standard_revision}],
            customer_id=self.customer_id, discount=0, paid_amount=250_000,
            order_date="2026-09-14", promised_date="2026-09-20",
            request_key="template-combined-key1", user_id=1,
        )
        self.assertEqual(250_000, combined["subtotal"])
        self.assertEqual(2, self.conn.execute("SELECT COUNT(*) FROM stock_movements WHERE kind = 'sale'").fetchone()[0])
        self.assertEqual(3_500, list_stock(self.conn)[0]["quantity"])


if __name__ == "__main__":
    unittest.main()
