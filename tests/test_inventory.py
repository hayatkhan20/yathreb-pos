"""Meaningful data-correctness checks for the user to run after setup."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from shop.db import connect_database, initialize_database
from shop.inventory import (
    DomainError,
    add_article,
    add_brand,
    add_colour,
    add_size,
    catalogue,
    confirm_unit,
    list_movements,
    list_stock,
    receive_stock,
    rename_label,
)


class InventoryModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.database = Path(self.temp.name) / "inventory.sqlite3"
        initialize_database(self.database, "owner", "test-password-hash", "s" * 48)
        self.conn = connect_database(self.database)

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def product(self, name):
        return next(row for row in catalogue(self.conn)["products"] if row["name"] == name)

    def test_seeded_units_keep_proposals_distinct_from_confirmed_values(self):
        rows = {row["name"]: row for row in catalogue(self.conn)["products"]}
        self.assertEqual("metre", rows["Fabric"]["unit"])
        self.assertEqual("pair", rows["Studs"]["unit"])
        self.assertIsNone(rows["Chappal / Peshawari Chappal"]["unit"])
        self.assertEqual("pair", rows["Chappal / Peshawari Chappal"]["suggested_unit"])
        self.assertIsNone(rows["Coat"]["unit"])
        self.assertEqual("piece", rows["Coat"]["suggested_unit"])

    def test_fabric_uses_exact_chain_fixed_precision_and_stable_history(self):
        fabric = self.product("Fabric")
        brand_id = add_brand(self.conn, "Yathreb", fabric["id"])
        article_id = add_article(self.conn, "Dastan", brand_id)
        colour_id = add_colour(self.conn, "Blue", brand_id, article_id)
        values = dict(
            product_id=fabric["id"], brand_id=brand_id, article_id=article_id,
            colour_id=colour_id, size_id=None, quantity="12.375", kind="opening",
            note="Counted at setup", request_key="fabric-opening-0001", user_id=1,
        )
        result = receive_stock(self.conn, **values)
        self.assertFalse(result["replayed"])
        self.assertTrue(receive_stock(self.conn, **values)["replayed"])
        self.assertEqual(12375, list_stock(self.conn)[0]["quantity"])

        rename_label(self.conn, "product", fabric["id"], "Dress Fabric")
        rename_label(self.conn, "colour", colour_id, "Navy Blue")
        current = list_stock(self.conn)[0]
        self.assertEqual("Dress Fabric", current["product"])
        self.assertEqual("Navy Blue", current["colour"])
        history = list_movements(self.conn, result["variant_id"])
        self.assertEqual(1, len(history))
        self.assertEqual("Fabric", history[0]["product"])
        self.assertEqual("Blue", history[0]["colour"])

    def test_fabric_names_are_unique_only_within_the_immediate_parent(self):
        fabric = self.product("Fabric")
        first_brand = add_brand(self.conn, "Yathreb", fabric["id"])
        second_brand = add_brand(self.conn, "Indicote", fabric["id"])
        first_article = add_article(self.conn, "Dastan", first_brand)
        second_article = add_article(self.conn, "Dastan", second_brand)
        another_article = add_article(self.conn, "Hayat", first_brand)

        with self.assertRaises(DomainError):
            add_article(self.conn, "  dastan  ", first_brand)

        first_blue = add_colour(self.conn, "Blue", first_brand, first_article)
        second_blue = add_colour(self.conn, "Blue", second_brand, second_article)
        third_blue = add_colour(self.conn, "Blue", first_brand, another_article)
        with self.assertRaises(DomainError):
            add_colour(self.conn, "BLUE", first_brand, first_article)

        data = catalogue(self.conn)
        self.assertNotEqual(first_article, second_article)
        self.assertEqual(
            3,
            len([row for row in data["colours"] if row["id"] in (first_blue, second_blue, third_blue)]),
        )
        self.assertTrue(all(row["article_id"] for row in data["colours"]))

    def test_non_fabric_colours_and_sizes_are_scoped_to_their_parents(self):
        shawl = self.product("Shawl")
        first_shawl_brand = add_brand(self.conn, "Shared Name", shawl["id"])
        second_shawl_brand = add_brand(self.conn, "Beta", shawl["id"])
        with self.assertRaises(DomainError):
            add_brand(self.conn, "shared name", shawl["id"])
        wallet = self.product("Wallet")
        add_brand(self.conn, "Shared Name", wallet["id"])
        add_colour(self.conn, "Blue", first_shawl_brand)
        add_colour(self.conn, "Blue", second_shawl_brand)
        with self.assertRaises(DomainError):
            add_colour(self.conn, "blue", first_shawl_brand)

        chappal = self.product("Chappal / Peshawari Chappal")
        chappal_brand = add_brand(self.conn, "Peshawar Works", chappal["id"])
        brown = add_colour(self.conn, "Brown", chappal_brand)
        black = add_colour(self.conn, "Black", chappal_brand)
        brown_42 = add_size(self.conn, "42", brown)
        black_42 = add_size(self.conn, "42", black)
        with self.assertRaises(DomainError):
            add_size(self.conn, " 42 ", brown)

        data = catalogue(self.conn)
        sizes = {row["id"]: row for row in data["sizes"]}
        self.assertEqual(brown, sizes[brown_42]["colour_id"])
        self.assertEqual(black, sizes[black_42]["colour_id"])

    def test_invalid_cross_parent_stock_chains_are_rejected_by_service_and_schema(self):
        fabric = self.product("Fabric")
        first_brand = add_brand(self.conn, "First Fabric", fabric["id"])
        second_brand = add_brand(self.conn, "Second Fabric", fabric["id"])
        first_article = add_article(self.conn, "Article One", first_brand)
        other_first_brand_article = add_article(self.conn, "Article Three", first_brand)
        second_article = add_article(self.conn, "Article Two", second_brand)
        first_colour = add_colour(self.conn, "Blue", first_brand, first_article)
        other_first_brand_colour = add_colour(
            self.conn, "Green", first_brand, other_first_brand_article
        )
        second_colour = add_colour(self.conn, "Black", second_brand, second_article)

        with self.assertRaises(DomainError):
            add_colour(self.conn, "Red", first_brand, second_article)
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO colours (brand_id, article_id, name, name_key) VALUES (?, ?, 'Red', 'red')",
                (first_brand, second_article),
            )
        with self.assertRaises(DomainError):
            receive_stock(
                self.conn, product_id=fabric["id"], brand_id=first_brand,
                article_id=first_article, colour_id=other_first_brand_colour, size_id=None,
                quantity="1", kind="opening", note="",
                request_key="cross-fabric-chain-001", user_id=1,
            )
        with self.assertRaises(DomainError):
            receive_stock(
                self.conn, product_id=fabric["id"], brand_id=first_brand,
                article_id=first_article, colour_id=second_colour, size_id=None,
                quantity="1", kind="opening", note="",
                request_key="cross-fabric-brand-001", user_id=1,
            )

        chappal = self.product("Chappal / Peshawari Chappal")
        confirm_unit(self.conn, chappal["id"], "pair")
        first_chappal_brand = add_brand(self.conn, "First Chappal", chappal["id"])
        second_chappal_brand = add_brand(self.conn, "Second Chappal", chappal["id"])
        first_chappal_colour = add_colour(self.conn, "Brown", first_chappal_brand)
        other_first_chappal_colour = add_colour(self.conn, "Black", first_chappal_brand)
        second_chappal_colour = add_colour(self.conn, "Tan", second_chappal_brand)
        other_first_size = add_size(self.conn, "41", other_first_chappal_colour)
        second_size = add_size(self.conn, "42", second_chappal_colour)
        with self.assertRaises(DomainError):
            receive_stock(
                self.conn, product_id=chappal["id"], brand_id=first_chappal_brand,
                article_id=None, colour_id=first_chappal_colour, size_id=other_first_size,
                quantity="1", kind="opening", note="",
                request_key="cross-size-chain-0001", user_id=1,
            )
        with self.assertRaises(DomainError):
            receive_stock(
                self.conn, product_id=chappal["id"], brand_id=first_chappal_brand,
                article_id=None, colour_id=second_chappal_colour, size_id=second_size,
                quantity="1", kind="opening", note="",
                request_key="cross-colour-brand-001", user_id=1,
            )

        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                """INSERT INTO variants
                   (product_id, brand_id, article_id, colour_id, size_id, unit)
                   VALUES (?, ?, NULL, ?, ?, 'pair')""",
                (chappal["id"], first_chappal_brand, second_chappal_colour, second_size),
            )
        self.assertEqual(0, self.conn.execute("SELECT COUNT(*) FROM variants").fetchone()[0])
        self.assertEqual(0, self.conn.execute("SELECT COUNT(*) FROM stock_movements").fetchone()[0])
        self.assertNotEqual(first_colour, second_colour)

    def test_retry_key_rejects_changed_payload_without_duplicate_stock(self):
        studs = self.product("Studs")
        brand_id = add_brand(self.conn, "Sample Brand", studs["id"])
        colour_id = add_colour(self.conn, "Silver", brand_id)
        values = dict(
            product_id=studs["id"], brand_id=brand_id, article_id=None,
            colour_id=colour_id, size_id=None, kind="receipt", note="",
            request_key="studs-receipt-0001", user_id=1,
        )
        receive_stock(self.conn, quantity="2", **values)
        with self.assertRaises(DomainError):
            receive_stock(self.conn, quantity="3", **values)
        self.assertEqual(2000, list_stock(self.conn)[0]["quantity"])
        self.assertEqual(1, len(list_movements(self.conn)))

    def test_unconfirmed_unit_and_wrong_dimensions_cannot_create_stock(self):
        coat = self.product("Coat")
        coat_brand = add_brand(self.conn, "Sample Coat", coat["id"])
        coat_colour = add_colour(self.conn, "Charcoal", coat_brand)
        coat_size = add_size(self.conn, "Medium", coat_colour)
        values = dict(
            product_id=coat["id"], brand_id=coat_brand, article_id=None,
            colour_id=coat_colour, size_id=coat_size, quantity="1", kind="opening",
            note="", request_key="coat-stock-entry-001", user_id=1,
        )
        with self.assertRaises(DomainError):
            receive_stock(self.conn, **values)
        confirm_unit(self.conn, coat["id"], "piece")
        wrong_values = {key: value for key, value in values.items() if key != "article_id"}
        with self.assertRaises(DomainError):
            receive_stock(self.conn, article_id=1, **wrong_values)
        self.assertEqual(0, self.conn.execute("SELECT COUNT(*) FROM variants").fetchone()[0])

    def test_whole_units_and_one_opening_entry_are_enforced(self):
        studs = self.product("Studs")
        brand_id = add_brand(self.conn, "Sample Brand", studs["id"])
        colour_id = add_colour(self.conn, "Gold", brand_id)
        values = dict(
            product_id=studs["id"], brand_id=brand_id, article_id=None,
            colour_id=colour_id, size_id=None, note="", user_id=1,
        )
        with self.assertRaises(DomainError):
            receive_stock(self.conn, quantity="1.5", kind="opening", request_key="whole-unit-check-001", **values)
        receive_stock(self.conn, quantity="1", kind="opening", request_key="whole-unit-check-002", **values)
        with self.assertRaises(DomainError):
            receive_stock(self.conn, quantity="1", kind="opening", request_key="whole-unit-check-003", **values)
        receive_stock(self.conn, quantity="2", kind="receipt", request_key="whole-unit-check-004", **values)
        self.assertEqual(3000, list_stock(self.conn)[0]["quantity"])

    def test_two_connections_serialize_stock_entries(self):
        studs = self.product("Studs")
        brand_id = add_brand(self.conn, "Concurrent Brand", studs["id"])
        colour_id = add_colour(self.conn, "Black", brand_id)

        def add_from_terminal(key):
            connection = connect_database(self.database)
            try:
                return receive_stock(
                    connection, product_id=studs["id"], brand_id=brand_id,
                    article_id=None, colour_id=colour_id, size_id=None,
                    quantity="1", kind="receipt", note="", request_key=key, user_id=1,
                )
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(add_from_terminal, f"terminal-entry-{index:04d}") for index in (1, 2)]
            for future in futures:
                self.assertFalse(future.result()["replayed"])
        self.assertEqual(2000, list_stock(self.conn)[0]["quantity"])
        self.assertEqual(2, len(list_movements(self.conn)))


if __name__ == "__main__":
    unittest.main()
