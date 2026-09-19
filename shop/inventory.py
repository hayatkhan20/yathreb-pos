"""Authoritative inventory, billing, customer, tailoring, and payment services."""

from contextlib import contextmanager
from datetime import date
import hashlib
import json
import re
import sqlite3
from unicodedata import normalize


SCALE = 1000
MAX_QUANTITY = 1_000_000_000_000  # Thousandths: an engineering limit, not a sales rule.
MAX_SALE_LINE_QUANTITY = 1_000_000_000  # Thousandths; keeps money multiplication in SQLite's integer range.
MAX_UNIT_PRICE = 1_000_000_000  # Paisa per whole unit; an engineering storage limit.
MAX_BILL_AMOUNT = 100_000_000_000_000_000  # Paisa; an engineering storage limit.
MAX_SALE_LINES = 100
FABRIC_PRODUCT_ID = 1  # Stable identity of the required seeded Fabric Product.
STANDARD_MEASUREMENT_TEMPLATES = {
    "Pakistani Waistcoat": {
        "measurements": ("Length", "Shoulder", "Neck", "Chest", "Waist", "Hip"),
        "styles": ("Band Collar", "Round Neck", "V Neck", "Rounded Daman", "Square Daman"),
    },
    "Three-Piece Waistcoat": {
        "measurements": ("Length", "Shoulder", "Neck", "Chest", "Waist", "Hip"),
        "styles": ("Band Collar", "Round Neck", "V Neck", "Rounded Daman", "Square Daman"),
    },
    "Coat": {
        "measurements": ("Length", "Shoulder", "Sleeves", "Neck", "Chest", "Hip", "Arm-hole"),
        "styles": ("Band Coat", "Collar Coat", "English Coat", "Two Button", "Single-Breasted", "Double-Breasted"),
    },
    "Sherwani": {
        "measurements": ("Length", "Shoulder", "Sleeves", "Neck", "Chest", "Hip", "Arm-hole"),
        "styles": ("Band Coat", "Collar Coat", "English Coat", "Two Button", "Single-Breasted", "Double-Breasted"),
    },
    "Pant": {
        "measurements": ("Butt", "Hip", "Length", "Thigh (Raan)", "Knee", "Paincha"),
        "styles": ("Plain", "Double Dart", "Baggy Pant"),
    },
    "Shalwar Kameez": {
        "measurements": ("Kameez Length", "Shoulder", "Sleeves", "Collar", "Chest", "Arm-hole", "Shalwar Length", "Paincha"),
        "styles": ("Collar", "Patti", "Cuff", "Front Pocket", "Side Pocket", "Shalwar Pocket", "Daman"),
    },
    "Shirt": {
        "measurements": ("Length", "Shoulder", "Sleeves", "Collar", "Chest", "Arm-hole"),
        "styles": ("Collar", "Patti", "Cuff", "Front Pocket", "Daman"),
    },
}
CUSTOM_GARMENT_CATEGORY = "Other / Custom Item"
GARMENT_CATEGORIES = tuple(STANDARD_MEASUREMENT_TEMPLATES) + (CUSTOM_GARMENT_CATEGORY,)
TAILORING_STATUSES = ("Received", "In Progress", "Ready", "Delivered")
_LABELS = {
    "product": "products",
    "brand": "brands",
    "article": "articles",
    "colour": "colours",
    "size": "sizes",
}
_FILTERS = {"product_id", "brand_id", "article_id", "colour_id", "size_id"}
_REQUIRED_PRODUCT_IDS = frozenset(range(1, 8))


class DomainError(ValueError):
    """A validation or stock-entry problem that may be shown directly to a user."""


def _name(value):
    if not isinstance(value, str):
        raise DomainError("Enter a name.")
    cleaned = " ".join(normalize("NFKC", value).split())
    if not 1 <= len(cleaned) <= 80 or any(not character.isprintable() for character in cleaned):
        raise DomainError("Use a name of 1 to 80 characters without control characters.")
    return cleaned, cleaned.casefold()


def _id(value, label, optional=False):
    if optional and (value is None or value == ""):
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise DomainError(f"Choose a valid {label}.")
    text = str(value)
    if not re.fullmatch(r"[0-9]{1,18}", text) or int(text) < 1:
        raise DomainError(f"Choose a valid {label}.")
    return int(text)


def _quantity(value, unit):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise DomainError("Enter a positive quantity using digits and a decimal point.")
    text = str(value).strip()
    if not re.fullmatch(r"[0-9]{1,12}(?:\.[0-9]{1,3})?", text):
        raise DomainError("Enter a positive quantity with up to 3 decimal places; do not use commas.")
    whole, _, fraction = text.partition(".")
    scaled = int(whole) * SCALE + int(fraction.ljust(3, "0"))
    if not 0 < scaled <= MAX_QUANTITY:
        raise DomainError("Quantity must be greater than zero and no more than 1,000,000,000.")
    if unit in ("pair", "piece") and scaled % SCALE:
        raise DomainError("Pairs and pieces must be entered as whole quantities.")
    return scaled


def _money(value, label, maximum=MAX_BILL_AMOUNT):
    """Validate an already-scaled PKR amount expressed as integer paisa."""
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise DomainError(f"Enter {label} as a non-negative whole number of paisa.")
    return value


def parse_pkr(value, label="amount", maximum=MAX_BILL_AMOUNT):
    """Convert a plain PKR decimal string to integer paisa without floating point."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise DomainError(f"Enter {label} in PKR with no more than two decimal places.")
    text = str(value).strip()
    if not re.fullmatch(r"[0-9]{1,15}(?:\.[0-9]{1,2})?", text):
        raise DomainError(f"Enter {label} in PKR with no more than two decimal places; do not use commas.")
    whole, _, fraction = text.partition(".")
    paisa = int(whole) * 100 + int(fraction.ljust(2, "0") or "0")
    return _money(paisa, label, maximum)


def format_pkr(value):
    """Render integer paisa as a PKR decimal amount."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("Money must be an integer number of paisa.")
    sign = "-" if value < 0 else ""
    whole, paisa = divmod(abs(value), 100)
    return f"{sign}{whole:,}.{paisa:02d}"


def _optional_customer_text(value, label, maximum):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise DomainError(f"Enter a valid {label}.")
    cleaned = " ".join(normalize("NFKC", value).split())
    if len(cleaned) > maximum or any(not character.isprintable() for character in cleaned):
        raise DomainError(f"Keep the {label} within {maximum} printable characters.")
    return cleaned


def _digest(payload):
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def format_quantity(value):
    """Render a scaled integer without ever converting it to floating point."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("Quantity must be an integer number of thousandths.")
    whole, fraction = divmod(abs(value), SCALE)
    suffix = ("." + f"{fraction:03d}".rstrip("0")) if fraction else ""
    return ("-" if value < 0 else "") + str(whole) + suffix


@contextmanager
def _write_transaction(connection):
    if connection.in_transaction:
        raise RuntimeError("Inventory operations must own their transaction.")
    try:
        # Reserve the write lock before reading balances or checking a retry.
        connection.execute("BEGIN IMMEDIATE")
        yield
        connection.commit()
    except sqlite3.IntegrityError as error:
        connection.rollback()
        message = str(error)
        if "UNIQUE constraint failed" in message:
            message = "That name or entry already exists in the selected group."
        elif "FOREIGN KEY constraint failed" in message:
            message = "A selected catalogue item no longer exists. Refresh and try again."
        elif "CHECK constraint failed" in message:
            message = "The entry contains an invalid value. Check the fields and try again."
        raise DomainError(message) from error
    except sqlite3.OperationalError as error:
        connection.rollback()
        if "locked" in str(error).lower() or "busy" in str(error).lower():
            raise DomainError("The database is busy. Please retry the same entry shortly.") from error
        raise
    except BaseException:
        connection.rollback()
        raise


def _product(connection, product_id):
    row = connection.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    if row is None:
        raise DomainError("Choose an existing product.")
    return row


def catalogue(connection):
    queries = {
        "products": "SELECT id, name, classification, unit, suggested_unit FROM products",
        "brands": "SELECT id, product_id, name FROM brands",
        "articles": "SELECT id, brand_id, name FROM articles",
        "colours": "SELECT id, brand_id, article_id, name FROM colours",
        "sizes": "SELECT id, colour_id, name FROM sizes",
    }
    return {
        name: [dict(row) for row in connection.execute(
            f"{query} ORDER BY name COLLATE NOCASE, id"
        )]
        for name, query in queries.items()
    }


def add_product(connection, name, classification, unit):
    cleaned, key = _name(name)
    if classification not in ("colour", "colour_size"):
        raise DomainError("Choose brand and colour, with size only if needed. Articles are reserved for fabric.")
    if unit not in ("pair", "piece"):
        raise DomainError("Choose pairs or pieces for the new product.")
    with _write_transaction(connection):
        cursor = connection.execute(
            "INSERT INTO products (name, name_key, classification, unit, suggested_unit) VALUES (?, ?, ?, ?, ?)",
            (cleaned, key, classification, unit, unit),
        )
        return cursor.lastrowid


def confirm_unit(connection, product_id, unit):
    product_id = _id(product_id, "product")
    if unit not in ("pair", "piece"):
        raise DomainError("Choose pairs or pieces.")
    with _write_transaction(connection):
        product = _product(connection, product_id)
        if product["unit"] is not None:
            raise DomainError("This product already has a confirmed unit, which cannot be changed.")
        connection.execute("UPDATE products SET unit = ? WHERE id = ?", (unit, product_id))


def add_brand(connection, name, product_id):
    cleaned, key = _name(name)
    product_id = _id(product_id, "product")
    with _write_transaction(connection):
        _product(connection, product_id)
        cursor = connection.execute(
            "INSERT INTO brands (product_id, name, name_key) VALUES (?, ?, ?)",
            (product_id, cleaned, key),
        )
        return cursor.lastrowid


def add_article(connection, name, brand_id):
    cleaned, key = _name(name)
    brand_id = _id(brand_id, "brand")
    with _write_transaction(connection):
        parent = connection.execute(
            "SELECT p.classification FROM brands b JOIN products p ON p.id = b.product_id WHERE b.id = ?",
            (brand_id,),
        ).fetchone()
        if parent is None or parent["classification"] != "article_colour":
            raise DomainError("Choose a Fabric brand before adding an article.")
        cursor = connection.execute(
            "INSERT INTO articles (brand_id, name, name_key) VALUES (?, ?, ?)",
            (brand_id, cleaned, key),
        )
        return cursor.lastrowid


def add_colour(connection, name, brand_id, article_id=None):
    cleaned, key = _name(name)
    brand_id = _id(brand_id, "brand")
    article_id = _id(article_id, "article", optional=True)
    with _write_transaction(connection):
        parent = connection.execute(
            "SELECT p.classification FROM brands b JOIN products p ON p.id = b.product_id WHERE b.id = ?",
            (brand_id,),
        ).fetchone()
        if parent is None:
            raise DomainError("Choose an existing brand before adding a colour.")
        if parent["classification"] == "article_colour":
            article = connection.execute(
                "SELECT id FROM articles WHERE id = ? AND brand_id = ?", (article_id, brand_id)
            ).fetchone()
            if article is None:
                raise DomainError("Choose an article belonging to this Fabric brand before adding a colour.")
        elif article_id is not None:
            raise DomainError("This product's colours belong directly to its brands.")
        cursor = connection.execute(
            "INSERT INTO colours (brand_id, article_id, name, name_key) VALUES (?, ?, ?, ?)",
            (brand_id, article_id, cleaned, key),
        )
        return cursor.lastrowid


def add_size(connection, name, colour_id):
    cleaned, key = _name(name)
    colour_id = _id(colour_id, "colour")
    with _write_transaction(connection):
        parent = connection.execute(
            """SELECT p.classification FROM colours co
               JOIN brands b ON b.id = co.brand_id
               JOIN products p ON p.id = b.product_id
               WHERE co.id = ? AND co.article_id IS NULL""",
            (colour_id,),
        ).fetchone()
        if parent is None or parent["classification"] != "colour_size":
            raise DomainError("Choose a colour belonging to a size-based product before adding a size.")
        cursor = connection.execute(
            "INSERT INTO sizes (colour_id, name, name_key) VALUES (?, ?, ?)",
            (colour_id, cleaned, key),
        )
        return cursor.lastrowid


def rename_label(connection, kind, item_id, name):
    if kind not in _LABELS:
        raise DomainError("Choose an existing catalogue item to rename.")
    item_id = _id(item_id, kind)
    cleaned, key = _name(name)
    table = _LABELS[kind]
    with _write_transaction(connection):
        cursor = connection.execute(
            f"UPDATE {table} SET name = ?, name_key = ? WHERE id = ?", (cleaned, key, item_id)
        )
        if cursor.rowcount != 1:
            raise DomainError("That catalogue item does not exist.")


def catalogue_deletion_candidate(connection, kind, item_id):
    """Return a validated catalogue identity for a confirmation screen."""
    if kind not in _LABELS:
        raise DomainError("Choose an existing catalogue item to delete.")
    item_id = _id(item_id, kind)
    row = connection.execute(
        f"SELECT id, name FROM {_LABELS[kind]} WHERE id = ?", (item_id,)
    ).fetchone()
    if row is None:
        raise DomainError("That catalogue item does not exist.")
    return {"kind": kind, "id": row["id"], "name": row["name"]}


def delete_catalogue_item(connection, kind, item_id):
    """Permanently delete only an unused, childless, non-seeded catalogue record."""
    candidate = catalogue_deletion_candidate(connection, kind, item_id)
    item_id = candidate["id"]
    if kind == "product" and item_id in _REQUIRED_PRODUCT_IDS:
        raise DomainError(
            "Required seeded Product definitions cannot be deleted because their hierarchy and unit rules are built into this application."
        )
    child_checks = {
        "product": (("brands", "product_id", "brands"),),
        "brand": (
            ("articles", "brand_id", "articles"),
            ("colours", "brand_id", "colours"),
        ),
        "article": (("colours", "article_id", "colours"),),
        "colour": (("sizes", "colour_id", "sizes"),),
        "size": (),
    }
    variant_fields = {
        "product": "product_id",
        "brand": "brand_id",
        "article": "article_id",
        "colour": "colour_id",
        "size": "size_id",
    }
    with _write_transaction(connection):
        # Re-read inside the write transaction so the decision and deletion are atomic.
        current = connection.execute(
            f"SELECT id FROM {_LABELS[kind]} WHERE id = ?", (item_id,)
        ).fetchone()
        if current is None:
            raise DomainError("That catalogue item no longer exists.")
        for table, field, label in child_checks[kind]:
            if connection.execute(
                f"SELECT 1 FROM {table} WHERE {field} = ? LIMIT 1", (item_id,)
            ).fetchone():
                raise DomainError(
                    f"This {kind} cannot be deleted while it contains {label}. Delete only unused leaf records."
                )
        if connection.execute(
            f"SELECT 1 FROM variants WHERE {variant_fields[kind]} = ? LIMIT 1", (item_id,)
        ).fetchone():
            raise DomainError(
                f"This {kind} cannot be deleted because an inventory variant or finalized sale depends on it."
            )
        connection.execute(f"DELETE FROM {_LABELS[kind]} WHERE id = ?", (item_id,))
    return candidate


def _selection(connection, product_id, brand_id, article_id, colour_id, size_id):
    product = _product(connection, product_id)
    if product["unit"] is None:
        raise DomainError("Confirm the stock unit for this product before entering quantities.")
    brand = connection.execute(
        "SELECT * FROM brands WHERE id = ? AND product_id = ?", (brand_id, product_id)
    ).fetchone()
    if brand is None:
        raise DomainError("Choose a brand belonging to the selected product.")
    article = size = None
    if product["classification"] == "article_colour":
        article = connection.execute(
            "SELECT * FROM articles WHERE id = ? AND brand_id = ?", (article_id, brand_id)
        ).fetchone()
        if article is None or size_id is not None:
            raise DomainError("Choose an article belonging to this fabric brand. Fabric does not use sizes.")
        colour = connection.execute(
            "SELECT * FROM colours WHERE id = ? AND brand_id = ? AND article_id = ?",
            (colour_id, brand_id, article_id),
        ).fetchone()
        if colour is None:
            raise DomainError("Choose a colour belonging to the selected fabric article.")
    else:
        if article_id is not None:
            raise DomainError("This product does not use articles.")
        colour = connection.execute(
            "SELECT * FROM colours WHERE id = ? AND brand_id = ? AND article_id IS NULL",
            (colour_id, brand_id),
        ).fetchone()
        if colour is None:
            raise DomainError("Choose a colour belonging to the selected brand.")
    if product["classification"] == "colour_size":
        size = connection.execute(
            "SELECT * FROM sizes WHERE id = ? AND colour_id = ?", (size_id, colour_id)
        ).fetchone()
        if size is None:
            raise DomainError("Choose a size belonging to the selected colour.")
    elif size_id is not None:
        raise DomainError("This product does not use sizes.")
    return product, brand, article, colour, size


def receive_stock(connection, *, product_id, brand_id, article_id, colour_id, size_id,
                  quantity, kind, note, request_key, user_id):
    product_id = _id(product_id, "product")
    brand_id = _id(brand_id, "brand")
    article_id = _id(article_id, "article", optional=True)
    colour_id = _id(colour_id, "colour")
    size_id = _id(size_id, "size", optional=True)
    user_id = _id(user_id, "user")
    if kind not in ("opening", "receipt"):
        raise DomainError("Choose opening stock or incoming stock.")
    if not isinstance(note, str) or len(note.strip()) > 500 or "\x00" in note:
        raise DomainError("Keep the note within 500 characters and do not include null characters.")
    note = note.strip()
    if not isinstance(request_key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", request_key):
        raise DomainError("The entry reference is invalid. Refresh the form before entering stock.")

    with _write_transaction(connection):
        product, brand, article, colour, size = _selection(
            connection, product_id, brand_id, article_id, colour_id, size_id
        )
        scaled = _quantity(quantity, product["unit"])
        user = connection.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
        if user is None:
            raise DomainError("Sign in again before entering stock.")
        payload = {
            "product_id": product_id, "brand_id": brand_id, "article_id": article_id,
            "colour_id": colour_id, "size_id": size_id, "quantity": scaled,
            "unit": product["unit"], "kind": kind, "note": note, "user_id": user_id,
        }
        digest = _digest(payload)
        previous = connection.execute(
            "SELECT id, variant_id, payload_digest FROM stock_movements WHERE request_key = ?", (request_key,)
        ).fetchone()
        if previous is not None:
            if previous["payload_digest"] != digest:
                raise DomainError("This entry reference was already saved with different details. Check stock history before starting a new entry.")
            return {"movement_id": previous["id"], "variant_id": previous["variant_id"], "replayed": True}

        variant = connection.execute(
            "SELECT id FROM variants WHERE product_id = ? AND brand_id = ? AND article_id IS ? AND colour_id = ? AND size_id IS ?",
            (product_id, brand_id, article_id, colour_id, size_id),
        ).fetchone()
        if variant is None:
            variant_id = connection.execute(
                "INSERT INTO variants (product_id, brand_id, article_id, colour_id, size_id, unit) VALUES (?, ?, ?, ?, ?, ?)",
                (product_id, brand_id, article_id, colour_id, size_id, product["unit"]),
            ).lastrowid
        else:
            variant_id = variant["id"]
        balance = connection.execute(
            "SELECT COALESCE(SUM(quantity), 0) FROM stock_movements WHERE variant_id = ?", (variant_id,)
        ).fetchone()[0]
        if balance + scaled > MAX_QUANTITY:
            raise DomainError("This entry exceeds the supported stock quantity for this combination.")
        if kind == "opening" and balance:
            raise DomainError("This combination already has stock history. Use incoming stock to add more.")
        movement_id = connection.execute(
            """INSERT INTO stock_movements
               (variant_id, user_id, kind, quantity, unit, note, request_key, payload_digest,
                product, brand, article, colour, size, username)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (variant_id, user_id, kind, scaled, product["unit"], note, request_key, digest,
             product["name"], brand["name"], article["name"] if article else None,
             colour["name"], size["name"] if size else None, user["username"]),
        ).lastrowid
        return {"movement_id": movement_id, "variant_id": variant_id, "replayed": False}


def set_default_selling_price(connection, variant_id, unit_price):
    """Set the current default price for one exact variant, in PKR paisa per whole unit."""
    variant_id = _id(variant_id, "stock combination")
    unit_price = _money(unit_price, "the default selling price", MAX_UNIT_PRICE)
    with _write_transaction(connection):
        cursor = connection.execute(
            "UPDATE variants SET default_selling_price = ? WHERE id = ?",
            (unit_price, variant_id),
        )
        if cursor.rowcount != 1:
            raise DomainError("Choose an existing stock combination before setting its price.")


def _record_text(value, label, maximum, required=False):
    cleaned = _optional_customer_text(value, label, maximum)
    if required and not cleaned:
        raise DomainError(f"Enter the {label}.")
    return cleaned


def normalize_mobile(value, *, optional=False):
    """Return a stable searchable digit form, normalizing common Pakistan prefixes."""
    displayed = _record_text(value, "mobile number", 40, required=not optional)
    if optional and not displayed:
        return "", ""
    if not re.fullmatch(r"[0-9+() .-]+", displayed):
        raise DomainError("Enter a mobile number using digits and common phone separators.")
    digits = re.sub(r"\D", "", displayed)
    if digits.startswith("0092"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = "92" + digits[1:]
    if not 7 <= len(digits) <= 15:
        raise DomainError("Enter a mobile number containing 7 to 15 digits.")
    return displayed, digits


def _customer(connection, customer_id):
    customer_id = _id(customer_id, "customer")
    row = connection.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    if row is None:
        raise DomainError("Choose an existing customer.")
    return row


def create_customer(connection, *, name, primary_mobile, alternate_mobile="", address="",
                    notes="", allow_shared_primary_mobile=False):
    """Create a person record; shared primary numbers require an explicit caller decision."""
    name = _record_text(name, "customer name", 120, required=True)
    primary_mobile, primary_key = normalize_mobile(primary_mobile)
    alternate_mobile, alternate_key = normalize_mobile(alternate_mobile, optional=True)
    address = _record_text(address, "address", 500)
    notes = _record_text(notes, "customer notes", 2000)
    if not isinstance(allow_shared_primary_mobile, bool):
        raise DomainError("The shared-mobile decision must be explicit.")
    with _write_transaction(connection):
        if not allow_shared_primary_mobile and connection.execute(
            "SELECT 1 FROM customers WHERE primary_mobile_normalized = ?", (primary_key,)
        ).fetchone():
            raise DomainError("A customer already uses this primary mobile number.")
        sequence = connection.execute(
            "SELECT next_number FROM customer_sequence WHERE id = 1"
        ).fetchone()
        if sequence is None or sequence["next_number"] > 999_999:
            raise DomainError("The supported customer-number sequence has been exhausted.")
        customer_number = f"CUST-{sequence['next_number']:06d}"
        connection.execute("UPDATE customer_sequence SET next_number = next_number + 1 WHERE id = 1")
        customer_id = connection.execute(
            """INSERT INTO customers
               (customer_number, name, primary_mobile, primary_mobile_normalized,
                alternate_mobile, alternate_mobile_normalized, address, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (customer_number, name, primary_mobile, primary_key, alternate_mobile,
             alternate_key, address, notes),
        ).lastrowid
        return {"customer_id": customer_id, "customer_number": customer_number}


def get_customer(connection, customer_id):
    return dict(_customer(connection, customer_id))


def update_customer(connection, customer_id, *, name, primary_mobile, alternate_mobile="",
                    address="", notes=""):
    """Update contact details while keeping the generated customer identity stable."""
    customer_id = _id(customer_id, "customer")
    name = _record_text(name, "customer name", 120, required=True)
    primary_mobile, primary_key = normalize_mobile(primary_mobile)
    alternate_mobile, alternate_key = normalize_mobile(alternate_mobile, optional=True)
    address = _record_text(address, "address", 500)
    notes = _record_text(notes, "customer notes", 2000)
    with _write_transaction(connection):
        _customer(connection, customer_id)
        if connection.execute(
            """SELECT 1 FROM customers
               WHERE primary_mobile_normalized = ? AND id != ?""",
            (primary_key, customer_id),
        ).fetchone():
            raise DomainError("A customer already uses this primary mobile number.")
        connection.execute(
            """UPDATE customers
               SET name = ?, primary_mobile = ?, primary_mobile_normalized = ?,
                   alternate_mobile = ?, alternate_mobile_normalized = ?, address = ?, notes = ?
               WHERE id = ?""",
            (name, primary_mobile, primary_key, alternate_mobile, alternate_key,
             address, notes, customer_id),
        )
    return get_customer(connection, customer_id)


def search_customers(connection, query, limit=50):
    query = _record_text(query, "customer search", 120)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise DomainError("Choose a customer-search limit between 1 and 200.")
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    digits = re.sub(r"\D", "", query)
    if digits.startswith("0092"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = "92" + digits[1:]
    mobile_pattern = f"%{digits}%" if digits else pattern
    return [dict(row) for row in connection.execute(
        """SELECT * FROM customers
           WHERE customer_number COLLATE NOCASE LIKE ? ESCAPE '\\'
              OR name COLLATE NOCASE LIKE ? ESCAPE '\\'
              OR primary_mobile_normalized LIKE ? ESCAPE '\\'
              OR alternate_mobile_normalized LIKE ? ESCAPE '\\'
           ORDER BY name COLLATE NOCASE, id LIMIT ?""",
        (pattern, pattern, mobile_pattern, mobile_pattern, limit),
    )]


def _garment(value, custom_description=""):
    if value not in GARMENT_CATEGORIES:
        raise DomainError("Choose a supported garment category.")
    custom = _record_text(custom_description, "custom garment description", 200)
    if value == CUSTOM_GARMENT_CATEGORY and not custom:
        raise DomainError("Describe the custom garment.")
    if value != CUSTOM_GARMENT_CATEGORY and custom:
        raise DomainError("A custom description is only valid for Other / Custom Item.")
    return value, custom


def _measurements(value):
    if not isinstance(value, dict) or not 1 <= len(value) <= 100:
        raise DomainError("Enter between 1 and 100 named measurements.")
    saved = {}
    keys = set()
    for label, amount in value.items():
        label, key = _name(label)
        if key in keys:
            raise DomainError("Each measurement label must be unique in the profile revision.")
        keys.add(key)
        if isinstance(amount, bool) or not isinstance(amount, (str, int)):
            raise DomainError(f"Enter {label} in inches with up to 3 decimal places.")
        text = str(amount).strip()
        if not re.fullmatch(r"[0-9]{1,5}(?:\.[0-9]{1,3})?", text):
            raise DomainError(f"Enter {label} in inches with up to 3 decimal places.")
        whole, _, fraction = text.partition(".")
        scaled = int(whole) * SCALE + int(fraction.ljust(3, "0") or "0")
        if not 0 < scaled <= 10_000_000:
            raise DomainError(f"Enter a positive supported value for {label}.")
        saved[label] = scaled
    return json.dumps(saved, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def measurement_templates():
    """Return the seven canonical templates without adding Custom as a standard template."""
    return {
        category: {"measurements": list(template["measurements"]),
                   "styles": list(template["styles"])}
        for category, template in STANDARD_MEASUREMENT_TEMPLATES.items()
    }


def _template_measurements(category, values):
    expected = STANDARD_MEASUREMENT_TEMPLATES[category]["measurements"]
    if not isinstance(values, dict) or set(values) != set(expected):
        raise DomainError(f"Enter exactly the confirmed numeric measurements for {category}.")
    return _measurements({label: values[label] for label in expected})


def _template_styles(category, values):
    expected = STANDARD_MEASUREMENT_TEMPLATES[category]["styles"]
    if not isinstance(values, dict) or set(values) != set(expected):
        raise DomainError(f"Provide every confirmed style checkbox for {category}.")
    if any(not isinstance(values[label], bool) for label in expected):
        raise DomainError("Every style checkbox value must be true or false.")
    return json.dumps(
        {label: values[label] for label in expected},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )


def save_measurements(connection, *, customer_id, garment_category, measurements,
                      styles=None, custom_description="", notes=""):
    customer_id = _id(customer_id, "customer")
    garment_category, custom_description = _garment(garment_category, custom_description)
    if garment_category in STANDARD_MEASUREMENT_TEMPLATES:
        measurements_json = _template_measurements(garment_category, measurements)
        styles_json = _template_styles(garment_category, styles)
    else:
        measurements_json = _measurements(measurements)
        if styles not in (None, {}):
            raise DomainError("Other / Custom Item uses flexible measurements and notes, not a standard style template.")
        styles_json = "{}"
    notes = _record_text(notes, "measurement notes", 1000)
    with _write_transaction(connection):
        _customer(connection, customer_id)
        profile = connection.execute(
            "SELECT id FROM measurement_profiles WHERE customer_id = ?", (customer_id,)
        ).fetchone()
        if profile is None:
            profile_id = connection.execute(
                "INSERT INTO measurement_profiles (customer_id) VALUES (?)", (customer_id,)
            ).lastrowid
        else:
            profile_id = profile["id"]
        revision_number = connection.execute(
            "SELECT COALESCE(MAX(revision_number), 0) + 1 FROM measurement_revisions WHERE profile_id = ?",
            (profile_id,),
        ).fetchone()[0]
        revision_id = connection.execute(
            """INSERT INTO measurement_revisions
               (profile_id, revision_number, garment_category, custom_description,
                unit, measurements_json, styles_json, notes)
               VALUES (?, ?, ?, ?, 'inch', ?, ?, ?)""",
            (profile_id, revision_number, garment_category, custom_description,
             measurements_json, styles_json, notes),
        ).lastrowid
        return {"profile_id": profile_id, "revision_id": revision_id,
                "revision_number": revision_number}


def get_measurement_revisions(connection, customer_id, garment_category=None):
    customer_id = _id(customer_id, "customer")
    parameters = [customer_id]
    condition = ""
    if garment_category is not None:
        if garment_category not in GARMENT_CATEGORIES:
            raise DomainError("Choose a supported garment category.")
        condition = " AND mr.garment_category = ?"
        parameters.append(garment_category)
    rows = connection.execute(
        """SELECT mr.* FROM measurement_revisions mr
           JOIN measurement_profiles mp ON mp.id = mr.profile_id
           WHERE mp.customer_id = ?""" + condition + " ORDER BY mr.revision_number DESC",
        parameters,
    )
    result = []
    for row in rows:
        item = dict(row)
        item["measurements"] = json.loads(item.pop("measurements_json"))
        item["styles"] = json.loads(item.pop("styles_json"))
        result.append(item)
    return result


def configure_stitching_rate(connection, garment_category, rate, user_id):
    """Append a new current PKR-paisa rate revision for one standard garment."""
    if garment_category not in STANDARD_MEASUREMENT_TEMPLATES:
        raise DomainError("Default stitching rates belong to the seven standard garment types only.")
    rate = _money(rate, "the default stitching rate", MAX_UNIT_PRICE)
    user_id = _id(user_id, "user")
    with _write_transaction(connection):
        if connection.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone() is None:
            raise DomainError("Sign in again before configuring a stitching rate.")
        revision_number = connection.execute(
            """SELECT COALESCE(MAX(revision_number), 0) + 1
               FROM stitching_rate_revisions WHERE garment_category = ?""",
            (garment_category,),
        ).fetchone()[0]
        revision_id = connection.execute(
            """INSERT INTO stitching_rate_revisions
               (garment_category, revision_number, rate, user_id) VALUES (?, ?, ?, ?)""",
            (garment_category, revision_number, rate, user_id),
        ).lastrowid
        return {"revision_id": revision_id, "revision_number": revision_number,
                "garment_category": garment_category, "rate": rate}


def get_stitching_rate_history(connection, garment_category):
    if garment_category not in STANDARD_MEASUREMENT_TEMPLATES:
        raise DomainError("Choose one of the seven standard garment types.")
    return [dict(row) for row in connection.execute(
        """SELECT * FROM stitching_rate_revisions WHERE garment_category = ?
           ORDER BY revision_number DESC""", (garment_category,)
    )]


def get_current_stitching_rates(connection):
    rows = connection.execute(
        """SELECT rr.* FROM stitching_rate_revisions rr
           WHERE rr.revision_number = (
               SELECT MAX(current.revision_number) FROM stitching_rate_revisions current
               WHERE current.garment_category = rr.garment_category
           ) ORDER BY rr.garment_category"""
    )
    return {row["garment_category"]: dict(row) for row in rows}


def _sale_variant(connection, variant_id):
    row = connection.execute(
        """SELECT v.id, v.product_id, v.brand_id, v.article_id, v.colour_id, v.size_id,
                  v.unit, v.default_selling_price,
                  p.name AS product, b.name AS brand, a.name AS article,
                  co.name AS colour, s.name AS size,
                  COALESCE((SELECT SUM(m.quantity) FROM stock_movements m
                            WHERE m.variant_id = v.id), 0) AS current_balance
           FROM variants v
           JOIN products p ON p.id = v.product_id
           JOIN brands b ON b.id = v.brand_id
           JOIN colours co ON co.id = v.colour_id
           LEFT JOIN articles a ON a.id = v.article_id
           LEFT JOIN sizes s ON s.id = v.size_id
           WHERE v.id = ?""",
        (variant_id,),
    ).fetchone()
    if row is None:
        raise DomainError("Choose an existing exact stock combination for every sale line.")
    return row


def get_sale_variant(connection, *, product_id, brand_id, article_id, colour_id, size_id):
    """Resolve one complete parent chain to its existing exact stock variant."""
    product_id = _id(product_id, "product")
    brand_id = _id(brand_id, "brand")
    article_id = _id(article_id, "article", optional=True)
    colour_id = _id(colour_id, "colour")
    size_id = _id(size_id, "size", optional=True)
    _selection(connection, product_id, brand_id, article_id, colour_id, size_id)
    variant = connection.execute(
        """SELECT id FROM variants
           WHERE product_id = ? AND brand_id = ? AND article_id IS ?
             AND colour_id = ? AND size_id IS ?""",
        (product_id, brand_id, article_id, colour_id, size_id),
    ).fetchone()
    if variant is None:
        raise DomainError(
            "This exact combination has no stock record yet. Add it through Add stock before billing it."
        )
    return dict(_sale_variant(connection, variant["id"]))


def quote_sale_items(connection, items):
    """Revalidate draft lines and calculate display totals without saving a sale."""
    if not isinstance(items, (list, tuple)) or not 1 <= len(items) <= MAX_SALE_LINES:
        raise DomainError(f"A bill must contain between 1 and {MAX_SALE_LINES} items.")
    quoted = []
    projected = {}
    for line_number, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise DomainError("Every bill item must contain a stock combination and quantity.")
        variant = _sale_variant(connection, _id(item.get("variant_id"), "stock combination"))
        quantity = _quantity(item.get("quantity"), variant["unit"])
        if quantity > MAX_SALE_LINE_QUANTITY:
            raise DomainError("A sale-line quantity exceeds the supported engineering limit.")
        requested_price = item.get("unit_price")
        if requested_price is None:
            unit_price = variant["default_selling_price"]
            if unit_price is None:
                raise DomainError("Set a default selling price or enter a price for every bill item.")
        else:
            unit_price = _money(requested_price, "the unit selling price", MAX_UNIT_PRICE)
        line_total = (quantity * unit_price + SCALE // 2) // SCALE
        prior_balance = projected.get(variant["id"], variant["current_balance"])
        projected_balance = prior_balance - quantity
        projected[variant["id"]] = projected_balance
        row = dict(variant)
        row.update(
            line_number=line_number,
            quantity=quantity,
            unit_price=unit_price,
            line_total=line_total,
            projected_balance=projected_balance,
            makes_negative=projected_balance < 0,
        )
        quoted.append(row)
    return quoted


def _sale_result(row, replayed):
    return {
        "sale_id": row["id"],
        "bill_number": row["bill_number"],
        "subtotal": row["subtotal"],
        "discount": row["discount"],
        "grand_total": row["grand_total"],
        "paid_amount": row["paid_amount"],
        "remaining_balance": row["remaining_balance"],
        "replayed": replayed,
    }


def finalize_sale(connection, *, items, discount, paid_amount, customer_name="",
                  customer_mobile="", request_key, user_id):
    """Finalize one immutable PKR bill and all negative stock movements atomically."""
    if not isinstance(items, (list, tuple)) or not 1 <= len(items) <= MAX_SALE_LINES:
        raise DomainError(f"A sale must contain between 1 and {MAX_SALE_LINES} items.")
    discount = _money(discount, "the bill discount")
    paid_amount = _money(paid_amount, "the paid amount")
    customer_name = _optional_customer_text(customer_name, "customer name", 120)
    customer_mobile = _optional_customer_text(customer_mobile, "customer mobile", 40)
    user_id = _id(user_id, "user")
    if not isinstance(request_key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", request_key):
        raise DomainError("The sale reference is invalid. Start a new bill before trying again.")

    with _write_transaction(connection):
        user = connection.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
        if user is None:
            raise DomainError("Sign in again before finalizing the sale.")

        normalized_items = []
        digest_items = []
        for line_number, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                raise DomainError("Every sale item must contain a stock combination and quantity.")
            variant_id = _id(item.get("variant_id"), "stock combination")
            variant = _sale_variant(connection, variant_id)
            quantity = _quantity(item.get("quantity"), variant["unit"])
            if quantity > MAX_SALE_LINE_QUANTITY:
                raise DomainError("A sale-line quantity exceeds the supported engineering limit.")
            requested_price = item.get("unit_price")
            if requested_price is None:
                unit_price = variant["default_selling_price"]
                if unit_price is None:
                    raise DomainError("Set a default selling price or enter a price for every sale item.")
            else:
                unit_price = _money(requested_price, "the unit selling price", MAX_UNIT_PRICE)
            line_total = (quantity * unit_price + SCALE // 2) // SCALE
            normalized_items.append(
                {
                    "line_number": line_number,
                    "variant": variant,
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "line_total": line_total,
                }
            )
            digest_items.append(
                {
                    "line_number": line_number,
                    "variant_id": variant_id,
                    "quantity": quantity,
                    "requested_unit_price": requested_price,
                }
            )

        payload = {
            "currency": "PKR",
            "customer_name": customer_name,
            "customer_mobile": customer_mobile,
            "discount": discount,
            "paid_amount": paid_amount,
            "items": digest_items,
            "user_id": user_id,
        }
        digest = _digest(payload)
        previous = connection.execute(
            """SELECT id, bill_number, subtotal, discount, grand_total,
                      paid_amount, remaining_balance, payload_digest, status
               FROM sales WHERE request_key = ?""",
            (request_key,),
        ).fetchone()
        if previous is not None:
            if previous["payload_digest"] != digest or previous["status"] != "finalized":
                raise DomainError(
                    "This sale reference was already used with different details. Review the saved bill before starting another sale."
                )
            return _sale_result(previous, True)

        subtotal = sum(item["line_total"] for item in normalized_items)
        if subtotal > MAX_BILL_AMOUNT:
            raise DomainError("The bill subtotal exceeds the supported engineering limit.")
        if discount > subtotal:
            raise DomainError("The fixed bill discount cannot exceed the subtotal.")
        grand_total = subtotal - discount
        if paid_amount > grand_total:
            raise DomainError("The paid amount cannot exceed the grand total.")
        remaining_balance = grand_total - paid_amount
        if remaining_balance and (not customer_name or not customer_mobile):
            raise DomainError("Customer name and mobile are required when a balance remains.")

        sequence = connection.execute(
            "SELECT next_number FROM bill_sequence WHERE id = 1"
        ).fetchone()
        if sequence is None:
            raise DomainError("The bill-number sequence is unavailable.")
        if sequence["next_number"] > 99_999_999:
            raise DomainError("The supported bill-number sequence has been exhausted.")
        bill_number = f"BILL-{sequence['next_number']:08d}"
        connection.execute(
            "UPDATE bill_sequence SET next_number = next_number + 1 WHERE id = 1"
        )
        sale_id = connection.execute(
            """INSERT INTO sales
               (bill_number, user_id, currency, customer_name, customer_mobile,
                subtotal, discount, grand_total, paid_amount, remaining_balance,
                request_key, payload_digest, status)
               VALUES (?, ?, 'PKR', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'building')""",
            (
                bill_number, user_id, customer_name, customer_mobile,
                subtotal, discount, grand_total, paid_amount, remaining_balance,
                request_key, digest,
            ),
        ).lastrowid

        for item in normalized_items:
            variant = item["variant"]
            sale_item_id = connection.execute(
                """INSERT INTO sale_items
                   (sale_id, line_number, variant_id, quantity, unit, unit_price, line_total,
                    product, brand, article, colour, size)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    sale_id, item["line_number"], variant["id"], item["quantity"],
                    variant["unit"], item["unit_price"], item["line_total"],
                    variant["product"], variant["brand"], variant["article"],
                    variant["colour"], variant["size"],
                ),
            ).lastrowid
            movement_key = "sale_" + hashlib.sha256(
                f"{sale_id}:{sale_item_id}:{request_key}".encode("utf-8")
            ).hexdigest()
            movement_payload = {
                "sale_id": sale_id,
                "sale_item_id": sale_item_id,
                "variant_id": variant["id"],
                "quantity": -item["quantity"],
                "unit": variant["unit"],
                "user_id": user_id,
            }
            connection.execute(
                """INSERT INTO stock_movements
                   (variant_id, user_id, sale_item_id, kind, quantity, unit, note,
                    request_key, payload_digest, product, brand, article, colour, size, username)
                   VALUES (?, ?, ?, 'sale', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    variant["id"], user_id, sale_item_id, -item["quantity"], variant["unit"],
                    f"Sale {bill_number}", movement_key, _digest(movement_payload),
                    variant["product"], variant["brand"], variant["article"],
                    variant["colour"], variant["size"], user["username"],
                ),
            )

        connection.execute("UPDATE sales SET status = 'finalized' WHERE id = ?", (sale_id,))
        saved = connection.execute(
            """SELECT id, bill_number, subtotal, discount, grand_total,
                      paid_amount, remaining_balance
               FROM sales WHERE id = ?""",
            (sale_id,),
        ).fetchone()
        return _sale_result(saved, False)


def _request_key(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", value):
        raise DomainError(f"The {label} reference is invalid. Start a new submission before trying again.")
    return value


def _iso_date(value, label, *, default_today=False):
    if value is None and default_today:
        return date.today().isoformat()
    if not isinstance(value, str):
        raise DomainError(f"Choose a valid {label}.")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as error:
        raise DomainError(f"Choose a valid {label}.") from error


def _normalize_combined_product_items(connection, items):
    if not isinstance(items, (list, tuple)) or len(items) > MAX_SALE_LINES:
        raise DomainError(f"A bill may contain up to {MAX_SALE_LINES} product items.")
    normalized, digest_items = [], []
    for line_number, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise DomainError("Every product item must contain a stock combination and quantity.")
        variant_id = _id(item.get("variant_id"), "stock combination")
        variant = _sale_variant(connection, variant_id)
        quantity = _quantity(item.get("quantity"), variant["unit"])
        if quantity > MAX_SALE_LINE_QUANTITY:
            raise DomainError("A product-line quantity exceeds the supported engineering limit.")
        requested_price = item.get("unit_price")
        if requested_price is None:
            unit_price = variant["default_selling_price"]
            if unit_price is None:
                raise DomainError("Set a default selling price or enter a price for every product item.")
        else:
            unit_price = _money(requested_price, "the unit selling price", MAX_UNIT_PRICE)
        line_total = (quantity * unit_price + SCALE // 2) // SCALE
        normalized.append({"line_number": line_number, "variant": variant, "quantity": quantity,
                           "unit_price": unit_price, "line_total": line_total})
        digest_items.append({"line_number": line_number, "variant_id": variant_id,
                             "quantity": quantity, "requested_unit_price": requested_price})
    return normalized, digest_items


def _normalize_tailoring_items(connection, customer_id, items, product_items=()):
    if not isinstance(items, (list, tuple)) or len(items) > MAX_SALE_LINES:
        raise DomainError(f"A bill may contain up to {MAX_SALE_LINES} tailoring items.")
    normalized, digest_items = [], []
    source_names = {
        "shop": "shop", "Purchased from shop": "shop",
        "customer": "customer", "Customer-provided": "customer",
    }
    for line_number, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise DomainError("Every tailoring item must contain garment, measurement and charge details.")
        category, custom = _garment(item.get("garment_category"), item.get("custom_description", ""))
        quantity = _quantity(item.get("quantity"), "piece")
        if quantity > MAX_SALE_LINE_QUANTITY:
            raise DomainError("A tailoring-item quantity exceeds the supported engineering limit.")
        rate_revision = None
        if category in STANDARD_MEASUREMENT_TEMPLATES:
            if item.get("stitching_rate") not in (None, ""):
                raise DomainError("Standard tailoring uses its configured default rate and cannot be overridden per order.")
            rate_revision = connection.execute(
                """SELECT * FROM stitching_rate_revisions
                   WHERE garment_category = ? ORDER BY revision_number DESC LIMIT 1""",
                (category,),
            ).fetchone()
            if rate_revision is None:
                raise DomainError(f"Configure a default stitching rate for {category} before finalizing this order.")
            rate = rate_revision["rate"]
        else:
            if item.get("stitching_rate") is None:
                raise DomainError("Enter a stitching price for Other / Custom Item.")
            rate = _money(item.get("stitching_rate"), "the custom stitching price", MAX_UNIT_PRICE)
        line_total = (quantity * rate + SCALE // 2) // SCALE
        cloth_source = source_names.get(item.get("cloth_source"))
        if cloth_source is None:
            raise DomainError("Choose Purchased from shop or Customer-provided as the cloth source.")
        revision_id = item.get("measurement_revision_id")
        conditions = "mp.customer_id = ? AND mr.garment_category = ? AND mr.custom_description = ?"
        parameters = [customer_id, category, custom]
        if revision_id not in (None, ""):
            conditions += " AND mr.id = ?"
            parameters.append(_id(revision_id, "measurement revision"))
        revision = connection.execute(
            """SELECT mr.* FROM measurement_revisions mr
               JOIN measurement_profiles mp ON mp.id = mr.profile_id
               WHERE """ + conditions + " ORDER BY mr.revision_number DESC LIMIT 1",
            parameters,
        ).fetchone()
        if revision is None:
            raise DomainError("Save matching current measurements for this customer and garment first.")
        source_line = _id(item.get("source_product_line"), "source product line", optional=True)
        source_sale_item_id = _id(item.get("source_sale_item_id"), "source sale item", optional=True)
        if source_line is not None and source_sale_item_id is not None:
            raise DomainError("Link shop cloth by either this bill's product line or an earlier sale item, not both.")
        if cloth_source == "customer" and (source_line is not None or source_sale_item_id is not None):
            raise DomainError("Customer-provided cloth cannot link to a product sale item.")
        if cloth_source == "shop" and source_line is None and source_sale_item_id is None:
            raise DomainError("Link Purchased from shop cloth to a product line from this or an earlier bill.")
        if source_line is not None:
            if source_line > len(product_items):
                raise DomainError("The linked current-bill Fabric line does not exist.")
            source_product = product_items[source_line - 1]
            source_variant = source_product.get("variant", source_product)
            if source_variant["product_id"] != FABRIC_PRODUCT_ID:
                raise DomainError("Choose a Fabric line from this bill for the garment cloth.")
        if source_sale_item_id is not None and connection.execute(
            """SELECT 1 FROM sale_items si
               JOIN sales sa ON sa.id = si.sale_id
               JOIN variants v ON v.id = si.variant_id
               WHERE si.id = ? AND sa.status = 'finalized' AND sa.customer_id = ?
                 AND v.product_id = ?""",
            (source_sale_item_id, customer_id, FABRIC_PRODUCT_ID),
        ).fetchone() is None:
            raise DomainError(
                "The selected earlier Fabric purchase is unavailable or does not belong to this customer."
            )
        normalized.append({
            "line_number": line_number, "garment_category": category,
            "custom_description": custom, "quantity": quantity, "stitching_rate": rate,
            "line_total": line_total, "cloth_source": cloth_source,
            "source_product_line": source_line, "revision": revision,
            "source_sale_item_id": source_sale_item_id,
            "rate_revision": rate_revision,
        })
        digest_item = {
            "line_number": line_number, "garment_category": category,
            "custom_description": custom, "quantity": quantity,
            "cloth_source": cloth_source, "source_product_line": source_line,
            "source_sale_item_id": source_sale_item_id,
            "measurement_revision_id": revision["id"],
        }
        if category == CUSTOM_GARMENT_CATEGORY:
            digest_item["stitching_rate"] = rate
        else:
            digest_item["rate_source"] = "configured_default"
        digest_items.append(digest_item)
    return normalized, digest_items


def quote_tailoring_items(connection, customer_id, items, product_items=()):
    """Validate tailoring draft lines and return server-calculated display values."""
    customer_id = _id(customer_id, "customer")
    _customer(connection, customer_id)
    normalized, _ = _normalize_tailoring_items(
        connection, customer_id, items, product_items
    )
    return [
        {
            "garment_category": item["garment_category"],
            "custom_description": item["custom_description"],
            "description": item["custom_description"] or item["garment_category"],
            "quantity": item["quantity"],
            "unit": "piece",
            "stitching_rate": item["stitching_rate"],
            "line_total": item["line_total"],
            "cloth_source": item["cloth_source"],
            "source_product_line": item["source_product_line"],
            "source_sale_item_id": item["source_sale_item_id"],
            "measurement_revision_id": item["revision"]["id"],
            "measurement_revision_number": item["revision"]["revision_number"],
            "measurement_created_at": item["revision"]["created_at"],
            "stitching_rate_revision_id": (
                item["rate_revision"]["id"] if item["rate_revision"] else None
            ),
        }
        for item in normalized
    ]


def list_customer_product_sale_items(connection, customer_id, limit=100):
    """Return finalized Fabric lines eligible as earlier shop-cloth links."""
    customer_id = _id(customer_id, "customer")
    _customer(connection, customer_id)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise DomainError("Choose an earlier-sale limit between 1 and 200.")
    return [dict(row) for row in connection.execute(
        """SELECT si.id, si.quantity, si.unit, si.product, si.brand, si.article,
                  si.colour, si.size, sa.id AS sale_id, sa.bill_number, sa.created_at
           FROM sale_items si
           JOIN sales sa ON sa.id = si.sale_id
           JOIN variants v ON v.id = si.variant_id
           WHERE sa.customer_id = ? AND sa.status = 'finalized' AND v.product_id = ?
           ORDER BY si.id DESC LIMIT ?""",
        (customer_id, FABRIC_PRODUCT_ID, limit),
    )]


def finalize_combined_bill(connection, *, product_items, tailoring_items, discount, paid_amount,
                           customer_id=None, order_date=None, promised_date=None,
                           tailoring_notes="", request_key, user_id):
    """Atomically finalize one product-only, tailoring-only, or combined PKR bill."""
    if not isinstance(product_items, (list, tuple)) or not isinstance(tailoring_items, (list, tuple)):
        raise DomainError("Bill items must be supplied as product and tailoring lists.")
    if not product_items and not tailoring_items:
        raise DomainError("A bill must contain at least one product or tailoring item.")
    if len(product_items) + len(tailoring_items) > MAX_SALE_LINES:
        raise DomainError(f"A bill may contain up to {MAX_SALE_LINES} total items.")
    discount = _money(discount, "the bill discount")
    paid_amount = _money(paid_amount, "the paid amount")
    user_id = _id(user_id, "user")
    request_key = _request_key(request_key, "bill")
    customer_id = _id(customer_id, "customer", optional=True)
    tailoring_notes = _record_text(tailoring_notes, "tailoring notes", 2000)
    if tailoring_items:
        order_date = _iso_date(order_date, "order date", default_today=True)
        promised_date = _iso_date(promised_date, "promised date")
        if promised_date < order_date:
            raise DomainError("The promised date cannot be before the order date.")

    with _write_transaction(connection):
        user = connection.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
        if user is None:
            raise DomainError("Sign in again before finalizing the bill.")
        customer = _customer(connection, customer_id) if customer_id is not None else None
        if tailoring_items and customer is None:
            raise DomainError("A customer is required when tailoring is included.")
        products, product_digest = _normalize_combined_product_items(connection, product_items)
        tailoring, tailoring_digest = _normalize_tailoring_items(
            connection, customer_id, tailoring_items, products
        ) if tailoring_items else ([], [])
        payload = {
            "currency": "PKR", "customer_id": customer_id, "discount": discount,
            "paid_amount": paid_amount, "product_items": product_digest,
            "tailoring_items": tailoring_digest, "order_date": order_date,
            "promised_date": promised_date, "tailoring_notes": tailoring_notes, "user_id": user_id,
        }
        digest = _digest(payload)
        previous = connection.execute(
            """SELECT sa.id, sa.bill_number, sa.subtotal, sa.discount, sa.grand_total,
                      sa.paid_amount, sa.remaining_balance, sa.payload_digest, sa.status,
                      t.id AS tailoring_order_id, t.tailoring_number
               FROM sales sa LEFT JOIN tailoring_orders t ON t.sale_id = sa.id
               WHERE sa.request_key = ?""",
            (request_key,),
        ).fetchone()
        if previous is not None:
            if previous["payload_digest"] != digest or previous["status"] != "finalized":
                raise DomainError("This bill reference was already used with different details.")
            result = _sale_result(previous, True)
            result.update(tailoring_order_id=previous["tailoring_order_id"],
                          tailoring_number=previous["tailoring_number"])
            return result

        subtotal = sum(item["line_total"] for item in products + tailoring)
        if subtotal > MAX_BILL_AMOUNT:
            raise DomainError("The bill subtotal exceeds the supported engineering limit.")
        if discount > subtotal:
            raise DomainError("The fixed bill discount cannot exceed the subtotal.")
        grand_total = subtotal - discount
        if paid_amount > grand_total:
            raise DomainError("The paid amount cannot exceed the grand total.")
        remaining = grand_total - paid_amount
        if remaining and customer is None:
            raise DomainError("A customer is required when a balance remains.")

        sequence = connection.execute("SELECT next_number FROM bill_sequence WHERE id = 1").fetchone()
        if sequence is None or sequence["next_number"] > 99_999_999:
            raise DomainError("The supported bill-number sequence has been exhausted.")
        bill_number = f"BILL-{sequence['next_number']:08d}"
        connection.execute("UPDATE bill_sequence SET next_number = next_number + 1 WHERE id = 1")
        sale_id = connection.execute(
            """INSERT INTO sales
               (bill_number, user_id, customer_id, currency, customer_name, customer_mobile,
                subtotal, discount, grand_total, paid_amount, remaining_balance,
                request_key, payload_digest, status)
               VALUES (?, ?, ?, 'PKR', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'building')""",
            (bill_number, user_id, customer_id, customer["name"] if customer else "",
             customer["primary_mobile"] if customer else "", subtotal, discount, grand_total,
             paid_amount, remaining, request_key, digest),
        ).lastrowid

        product_sale_ids = {}
        for item in products:
            variant = item["variant"]
            sale_item_id = connection.execute(
                """INSERT INTO sale_items
                   (sale_id, line_number, variant_id, quantity, unit, unit_price, line_total,
                    product, brand, article, colour, size)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (sale_id, item["line_number"], variant["id"], item["quantity"], variant["unit"],
                 item["unit_price"], item["line_total"], variant["product"], variant["brand"],
                 variant["article"], variant["colour"], variant["size"]),
            ).lastrowid
            product_sale_ids[item["line_number"]] = sale_item_id
            movement_key = "sale_" + hashlib.sha256(
                f"{sale_id}:{sale_item_id}:{request_key}".encode("utf-8")
            ).hexdigest()
            movement_payload = {"sale_id": sale_id, "sale_item_id": sale_item_id,
                                "variant_id": variant["id"], "quantity": -item["quantity"],
                                "unit": variant["unit"], "user_id": user_id}
            connection.execute(
                """INSERT INTO stock_movements
                   (variant_id, user_id, sale_item_id, kind, quantity, unit, note,
                    request_key, payload_digest, product, brand, article, colour, size, username)
                   VALUES (?, ?, ?, 'sale', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (variant["id"], user_id, sale_item_id, -item["quantity"], variant["unit"],
                 f"Sale {bill_number}", movement_key, _digest(movement_payload), variant["product"],
                 variant["brand"], variant["article"], variant["colour"], variant["size"],
                 user["username"]),
            )

        tailoring_order_id = tailoring_number = None
        if tailoring:
            sequence = connection.execute(
                "SELECT next_number FROM tailoring_sequence WHERE id = 1"
            ).fetchone()
            if sequence is None or sequence["next_number"] > 999_999:
                raise DomainError("The supported tailoring-number sequence has been exhausted.")
            tailoring_number = f"TAIL-{sequence['next_number']:06d}"
            connection.execute("UPDATE tailoring_sequence SET next_number = next_number + 1 WHERE id = 1")
            tailoring_order_id = connection.execute(
                """INSERT INTO tailoring_orders
                   (tailoring_number, sale_id, customer_id, order_date, promised_date, notes, status)
                   VALUES (?, ?, ?, ?, ?, ?, 'Received')""",
                (tailoring_number, sale_id, customer_id, order_date, promised_date, tailoring_notes),
            ).lastrowid
            for item in tailoring:
                source_id = item["source_sale_item_id"]
                if item["source_product_line"] is not None:
                    source_id = product_sale_ids.get(item["source_product_line"])
                    if source_id is None:
                        raise DomainError("The linked shop-cloth line is not part of this bill.")
                revision = item["revision"]
                connection.execute(
                    """INSERT INTO tailoring_items
                       (order_id, line_number, garment_category, custom_description, quantity,
                        unit, stitching_rate, stitching_rate_revision_id, line_total,
                        cloth_source, source_sale_item_id, measurement_revision_id,
                        measurement_unit, measurements_json, styles_json, measurement_notes)
                       VALUES (?, ?, ?, ?, ?, 'piece', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (tailoring_order_id, item["line_number"], item["garment_category"],
                     item["custom_description"], item["quantity"], item["stitching_rate"],
                     item["rate_revision"]["id"] if item["rate_revision"] else None,
                     item["line_total"], item["cloth_source"], source_id, revision["id"],
                     revision["unit"], revision["measurements_json"], revision["styles_json"],
                     revision["notes"]),
                )

        connection.execute("UPDATE sales SET status = 'finalized' WHERE id = ?", (sale_id,))
        saved = connection.execute(
            """SELECT id, bill_number, subtotal, discount, grand_total,
                      paid_amount, remaining_balance FROM sales WHERE id = ?""",
            (sale_id,),
        ).fetchone()
        result = _sale_result(saved, False)
        result.update(tailoring_order_id=tailoring_order_id, tailoring_number=tailoring_number)
        return result


def get_tailoring_order(connection, tailoring_order_id):
    tailoring_order_id = _id(tailoring_order_id, "tailoring order")
    order = connection.execute(
        """SELECT t.*, sa.bill_number, sa.subtotal, sa.discount, sa.grand_total,
                  sa.paid_amount, sa.remaining_balance,
                  sa.remaining_balance - COALESCE(
                      (SELECT SUM(p.amount) FROM payments p WHERE p.sale_id = sa.id), 0
                  ) AS outstanding_balance,
                  sa.created_at AS bill_created_at,
                  c.customer_number, c.name AS customer_name,
                  c.primary_mobile AS customer_mobile
           FROM tailoring_orders t
           JOIN sales sa ON sa.id = t.sale_id
           JOIN customers c ON c.id = t.customer_id
           WHERE t.id = ? AND sa.status = 'finalized'""", (tailoring_order_id,)
    ).fetchone()
    if order is None:
        raise DomainError("Choose an existing finalized tailoring order.")
    result = dict(order)
    result["items"] = []
    for row in connection.execute(
        """SELECT ti.*, mr.revision_number AS measurement_revision_number,
                  si.product AS source_product, si.brand AS source_brand,
                  si.article AS source_article, si.colour AS source_colour,
                  si.size AS source_size, source_sale.bill_number AS source_bill_number
           FROM tailoring_items ti
           JOIN measurement_revisions mr ON mr.id = ti.measurement_revision_id
           LEFT JOIN sale_items si ON si.id = ti.source_sale_item_id
           LEFT JOIN sales source_sale ON source_sale.id = si.sale_id
           WHERE ti.order_id = ? ORDER BY ti.line_number""",
        (tailoring_order_id,),
    ):
        item = dict(row)
        item["measurements"] = json.loads(item["measurements_json"])
        item["styles"] = json.loads(item["styles_json"])
        result["items"].append(item)
    return result


def list_tailoring_orders(connection, search="", status="", limit=200, customer_id=None):
    """Search immutable tailoring-order headers and their customer/bill identities."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise DomainError("Choose a tailoring-history limit between 1 and 500.")
    search = _sales_search(search)
    if status not in ("",) + TAILORING_STATUSES:
        raise DomainError("Choose Received, In Progress, Ready or Delivered as the status.")
    parameters = []
    conditions = ["sa.status = 'finalized'"]
    if customer_id is not None:
        customer_id = _id(customer_id, "customer")
        _customer(connection, customer_id)
        conditions.append("t.customer_id = ?")
        parameters.append(customer_id)
    if search:
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        digits = re.sub(r"\D", "", search)
        if digits.startswith("0092"):
            digits = digits[2:]
        elif len(digits) == 11 and digits.startswith("0"):
            digits = "92" + digits[1:]
        mobile_pattern = f"%{digits}%" if digits else pattern
        conditions.append(
            """(t.tailoring_number COLLATE NOCASE LIKE ? ESCAPE '\\'
                 OR sa.bill_number COLLATE NOCASE LIKE ? ESCAPE '\\'
                 OR c.customer_number COLLATE NOCASE LIKE ? ESCAPE '\\'
                 OR c.name COLLATE NOCASE LIKE ? ESCAPE '\\'
                 OR c.primary_mobile_normalized LIKE ? ESCAPE '\\'
                 OR c.alternate_mobile_normalized LIKE ? ESCAPE '\\')"""
        )
        parameters.extend(
            (pattern, pattern, pattern, pattern, mobile_pattern, mobile_pattern)
        )
    if status:
        conditions.append("t.status = ?")
        parameters.append(status)
    parameters.append(limit)
    return [dict(row) for row in connection.execute(
        """SELECT t.id, t.tailoring_number, t.order_date, t.promised_date, t.status,
                  t.created_at, t.customer_id, c.customer_number, c.name AS customer_name,
                  c.primary_mobile AS customer_mobile, sa.id AS sale_id, sa.bill_number,
                  sa.grand_total, sa.paid_amount, sa.remaining_balance,
                  sa.remaining_balance - COALESCE(
                      (SELECT SUM(p.amount) FROM payments p WHERE p.sale_id = sa.id), 0
                  ) AS outstanding_balance,
                  COUNT(ti.id) AS item_count
           FROM tailoring_orders t
           JOIN customers c ON c.id = t.customer_id
           JOIN sales sa ON sa.id = t.sale_id
           JOIN tailoring_items ti ON ti.order_id = t.id
           WHERE """ + " AND ".join(conditions) +
        " GROUP BY t.id ORDER BY t.id DESC LIMIT ?",
        parameters,
    )]


def update_tailoring_status(connection, tailoring_order_id, status):
    tailoring_order_id = _id(tailoring_order_id, "tailoring order")
    if status not in TAILORING_STATUSES:
        raise DomainError("Choose Received, In Progress, Ready or Delivered.")
    with _write_transaction(connection):
        cursor = connection.execute(
            "UPDATE tailoring_orders SET status = ? WHERE id = ?", (status, tailoring_order_id)
        )
        if cursor.rowcount != 1:
            raise DomainError("Choose an existing tailoring order.")


def bill_outstanding_balance(connection, sale_id):
    sale_id = _id(sale_id, "bill")
    row = connection.execute(
        """SELECT sa.remaining_balance - COALESCE(SUM(p.amount), 0) AS outstanding
           FROM sales sa LEFT JOIN payments p ON p.sale_id = sa.id
           WHERE sa.id = ? AND sa.status = 'finalized' GROUP BY sa.id""", (sale_id,)
    ).fetchone()
    if row is None:
        raise DomainError("Choose an existing finalized bill.")
    return row["outstanding"]


def record_payment(connection, *, sale_id, customer_id, amount, request_key, user_id, note=""):
    sale_id = _id(sale_id, "bill")
    customer_id = _id(customer_id, "customer")
    user_id = _id(user_id, "user")
    amount = _money(amount, "the payment amount")
    if amount == 0:
        raise DomainError("The payment amount must be greater than zero.")
    request_key = _request_key(request_key, "payment")
    note = _record_text(note, "payment note", 500)
    payload = {"sale_id": sale_id, "customer_id": customer_id, "amount": amount,
               "user_id": user_id, "note": note}
    digest = _digest(payload)
    with _write_transaction(connection):
        previous = connection.execute(
            "SELECT * FROM payments WHERE request_key = ?", (request_key,)
        ).fetchone()
        if previous is not None:
            if previous["payload_digest"] != digest:
                raise DomainError("This payment reference was already used with different details.")
            result = dict(previous)
            result["replayed"] = True
            result["outstanding_balance"] = bill_outstanding_balance(connection, previous["sale_id"])
            return result
        sale = connection.execute(
            """SELECT id, customer_id, remaining_balance FROM sales
               WHERE id = ? AND status = 'finalized'""", (sale_id,)
        ).fetchone()
        if sale is None or sale["customer_id"] != customer_id:
            raise DomainError("The payment must identify the customer attached to this finalized bill.")
        if connection.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone() is None:
            raise DomainError("Sign in again before recording the payment.")
        paid_later = connection.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM payments WHERE sale_id = ?", (sale_id,)
        ).fetchone()[0]
        outstanding = sale["remaining_balance"] - paid_later
        if amount > outstanding:
            raise DomainError("The payment cannot exceed this bill's outstanding balance.")
        sequence = connection.execute("SELECT next_number FROM payment_sequence WHERE id = 1").fetchone()
        if sequence is None or sequence["next_number"] > 999_999:
            raise DomainError("The supported payment-number sequence has been exhausted.")
        payment_number = f"PAY-{sequence['next_number']:06d}"
        connection.execute("UPDATE payment_sequence SET next_number = next_number + 1 WHERE id = 1")
        payment_id = connection.execute(
            """INSERT INTO payments
               (payment_number, sale_id, customer_id, user_id, amount, note, request_key, payload_digest)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (payment_number, sale_id, customer_id, user_id, amount, note, request_key, digest),
        ).lastrowid
        saved = dict(connection.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone())
        saved["replayed"] = False
        saved["outstanding_balance"] = outstanding - amount
        return saved


def customer_account_balance(connection, customer_id):
    customer_id = _id(customer_id, "customer")
    _customer(connection, customer_id)
    return connection.execute(
        """SELECT COALESCE(SUM(sa.remaining_balance - COALESCE(
                   (SELECT SUM(p.amount) FROM payments p WHERE p.sale_id = sa.id), 0
               )), 0)
           FROM sales sa WHERE sa.customer_id = ? AND sa.status = 'finalized'""",
        (customer_id,),
    ).fetchone()[0]


def list_payments(connection, sale_id):
    sale_id = _id(sale_id, "bill")
    return [dict(row) for row in connection.execute(
        "SELECT * FROM payments WHERE sale_id = ? ORDER BY id", (sale_id,)
    )]


def get_customer_account(connection, customer_id):
    """Return finalized bills, immutable payments, and derived customer totals."""
    customer_id = _id(customer_id, "customer")
    customer = dict(_customer(connection, customer_id))
    bills = [dict(row) for row in connection.execute(
        """SELECT sa.id, sa.bill_number, sa.created_at, sa.grand_total,
                  sa.paid_amount, sa.remaining_balance,
                  COALESCE(payments.later_paid, 0) AS later_payments,
                  sa.remaining_balance - COALESCE(payments.later_paid, 0)
                      AS current_outstanding,
                  t.id AS tailoring_order_id, t.tailoring_number
           FROM sales sa
           LEFT JOIN (
               SELECT sale_id, SUM(amount) AS later_paid
               FROM payments GROUP BY sale_id
           ) payments ON payments.sale_id = sa.id
           LEFT JOIN tailoring_orders t ON t.sale_id = sa.id
           WHERE sa.customer_id = ? AND sa.status = 'finalized'
           ORDER BY sa.id DESC""",
        (customer_id,),
    )]
    payments = [dict(row) for row in connection.execute(
        """SELECT p.id, p.payment_number, p.created_at, p.amount, p.sale_id,
                  sa.bill_number
           FROM payments p JOIN sales sa ON sa.id = p.sale_id
           WHERE p.customer_id = ? AND sa.status = 'finalized'
           ORDER BY p.id DESC""",
        (customer_id,),
    )]
    total_billed = sum(bill["grand_total"] for bill in bills)
    total_paid = sum(
        bill["paid_amount"] + bill["later_payments"] for bill in bills
    )
    return {
        "customer": customer,
        "bills": bills,
        "payments": payments,
        "total_billed": total_billed,
        "total_paid": total_paid,
        "total_outstanding": sum(bill["current_outstanding"] for bill in bills),
    }


def list_customer_balances(connection, search="", *, outstanding_only=True, limit=200):
    """List customer account totals without treating later payments as sales."""
    search = _record_text(search, "customer balance search", 120)
    if not isinstance(outstanding_only, bool):
        raise DomainError("Choose whether to show outstanding or all customer accounts.")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise DomainError("Choose a customer-balance limit between 1 and 200.")
    escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    digits = re.sub(r"\D", "", search)
    if digits.startswith("0092"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = "92" + digits[1:]
    mobile_pattern = f"%{digits}%" if digits else pattern
    conditions = """(c.customer_number COLLATE NOCASE LIKE ? ESCAPE '\\'
                    OR c.name COLLATE NOCASE LIKE ? ESCAPE '\\'
                    OR c.primary_mobile_normalized LIKE ? ESCAPE '\\'
                    OR c.alternate_mobile_normalized LIKE ? ESCAPE '\\')"""
    parameters = [pattern, pattern, mobile_pattern, mobile_pattern]
    if outstanding_only:
        conditions += " AND COALESCE(accounts.total_outstanding, 0) > 0"
    parameters.append(limit)
    return [dict(row) for row in connection.execute(
        """WITH payment_totals AS (
               SELECT sale_id, SUM(amount) AS later_paid FROM payments GROUP BY sale_id
           ), account_bills AS (
               SELECT sa.customer_id,
                      SUM(sa.grand_total) AS total_billed,
                      SUM(sa.paid_amount + COALESCE(pt.later_paid, 0)) AS total_paid,
                      SUM(sa.remaining_balance - COALESCE(pt.later_paid, 0))
                          AS total_outstanding,
                      SUM(CASE WHEN sa.remaining_balance - COALESCE(pt.later_paid, 0) > 0
                               THEN 1 ELSE 0 END) AS unpaid_bill_count
               FROM sales sa
               LEFT JOIN payment_totals pt ON pt.sale_id = sa.id
               WHERE sa.status = 'finalized' AND sa.customer_id IS NOT NULL
               GROUP BY sa.customer_id
           )
           SELECT c.id, c.customer_number, c.name, c.primary_mobile,
                  COALESCE(accounts.total_billed, 0) AS total_billed,
                  COALESCE(accounts.total_paid, 0) AS total_paid,
                  COALESCE(accounts.total_outstanding, 0) AS total_outstanding,
                  COALESCE(accounts.unpaid_bill_count, 0) AS unpaid_bill_count
           FROM customers c
           LEFT JOIN account_bills accounts ON accounts.customer_id = c.id
           WHERE """ + conditions +
        " ORDER BY total_outstanding DESC, c.name COLLATE NOCASE, c.id LIMIT ?",
        parameters,
    )]


def get_payment(connection, payment_id):
    """Return one immutable payment with stable receipt-time balance calculations."""
    payment_id = _id(payment_id, "payment")
    row = connection.execute(
        """SELECT p.id, p.payment_number, p.sale_id, p.customer_id, p.user_id,
                  p.amount, p.created_at, p.note, sa.bill_number, sa.grand_total,
                  sa.paid_amount, sa.remaining_balance, sa.customer_name,
                  sa.customer_mobile, c.customer_number,
                  sa.remaining_balance - COALESCE((
                      SELECT SUM(prior.amount) FROM payments prior
                      WHERE prior.sale_id = p.sale_id AND prior.id < p.id
                  ), 0) AS outstanding_before
           FROM payments p
           JOIN sales sa ON sa.id = p.sale_id AND sa.status = 'finalized'
           JOIN customers c ON c.id = p.customer_id
           WHERE p.id = ? AND sa.customer_id = p.customer_id""",
        (payment_id,),
    ).fetchone()
    if row is None:
        raise DomainError("Choose an existing finalized payment.")
    result = dict(row)
    result["outstanding_after"] = result["outstanding_before"] - result["amount"]
    return result


def get_sale(connection, sale_id):
    """Return one finalized bill and its immutable item snapshots."""
    sale_id = _id(sale_id, "sale")
    sale = connection.execute(
        """SELECT sa.id, sa.bill_number, sa.user_id, sa.customer_id, sa.created_at,
                  sa.currency, sa.customer_name, sa.customer_mobile, sa.subtotal,
                  sa.discount, sa.grand_total, sa.paid_amount, sa.remaining_balance,
                  sa.status, c.customer_number
           FROM sales sa LEFT JOIN customers c ON c.id = sa.customer_id
           WHERE sa.id = ? AND sa.status = 'finalized'""",
        (sale_id,),
    ).fetchone()
    if sale is None:
        raise DomainError("Choose an existing finalized sale.")
    result = dict(sale)
    result["items"] = [
        dict(row) for row in connection.execute(
            """SELECT si.id, si.line_number, si.variant_id, si.quantity, si.unit,
                      si.unit_price, si.line_total, si.product, si.brand, si.article,
                      si.colour, si.size, m.id AS stock_movement_id
               FROM sale_items si
               JOIN stock_movements m ON m.sale_item_id = si.id
               WHERE si.sale_id = ? ORDER BY si.line_number""",
            (sale_id,),
        )
    ]
    tailoring = connection.execute(
        """SELECT id, tailoring_number, order_date, promised_date, notes, status
           FROM tailoring_orders WHERE sale_id = ?""", (sale_id,)
    ).fetchone()
    result["tailoring_order_id"] = tailoring["id"] if tailoring else None
    result["tailoring_number"] = tailoring["tailoring_number"] if tailoring else None
    result["tailoring_order"] = dict(tailoring) if tailoring else None
    result["tailoring_items"] = []
    for row in connection.execute(
        """SELECT ti.* FROM tailoring_items ti
           JOIN tailoring_orders t ON t.id = ti.order_id
           WHERE t.sale_id = ? ORDER BY ti.line_number""", (sale_id,)
    ):
        item = dict(row)
        item["measurements"] = json.loads(item["measurements_json"])
        item["styles"] = json.loads(item["styles_json"])
        result["tailoring_items"].append(item)
    result["payments"] = list_payments(connection, sale_id)
    result["later_payments"] = sum(payment["amount"] for payment in result["payments"])
    result["outstanding_balance"] = bill_outstanding_balance(connection, sale_id)
    return result


def _sales_search(value):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise DomainError("Enter a valid sales search.")
    cleaned = " ".join(normalize("NFKC", value).split())
    if len(cleaned) > 120 or any(not character.isprintable() for character in cleaned):
        raise DomainError("Keep the sales search within 120 printable characters.")
    return cleaned


def list_sales(connection, search="", limit=200):
    """Return recent immutable finalized-sale headers for sales history."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise DomainError("Choose a sales-history limit between 1 and 500.")
    search = _sales_search(search)
    where = "status = 'finalized'"
    parameters = []
    if search:
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        where += """ AND (bill_number COLLATE NOCASE LIKE ? ESCAPE '\\'
                       OR customer_name COLLATE NOCASE LIKE ? ESCAPE '\\'
                       OR customer_mobile COLLATE NOCASE LIKE ? ESCAPE '\\')"""
        parameters.extend((pattern, pattern, pattern))
    parameters.append(limit)
    return [dict(row) for row in connection.execute(
        """SELECT id, bill_number, created_at, currency, customer_name, customer_mobile,
                  subtotal, discount, grand_total, paid_amount, remaining_balance
           FROM sales WHERE """ + where + " ORDER BY id DESC LIMIT ?",
        parameters,
    )]


def sales_report(connection, start_utc, end_utc):
    """Return finalized bills and totals inside one validated half-open UTC range."""
    boundary = re.compile(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.000Z"
    )
    if (
        not isinstance(start_utc, str)
        or not isinstance(end_utc, str)
        or not boundary.fullmatch(start_utc)
        or not boundary.fullmatch(end_utc)
        or start_utc >= end_utc
    ):
        raise DomainError("Choose a valid sales-report date range.")
    rows = [dict(row) for row in connection.execute(
        """SELECT id, bill_number, created_at, currency, customer_name, customer_mobile,
                  subtotal, discount, grand_total, paid_amount, remaining_balance
           FROM sales
           WHERE status = 'finalized' AND created_at >= ? AND created_at < ?
           ORDER BY id""",
        (start_utc, end_utc),
    )]
    totals = {
        "bill_count": len(rows),
        "subtotal": sum(row["subtotal"] for row in rows),
        "discount": sum(row["discount"] for row in rows),
        "grand_total": sum(row["grand_total"] for row in rows),
        "paid_amount": sum(row["paid_amount"] for row in rows),
        "remaining_balance": sum(row["remaining_balance"] for row in rows),
    }
    return {"sales": rows, "totals": totals}


def list_stock(connection, filters=None):
    conditions, parameters = [], []
    for field, value in (filters or {}).items():
        if field not in _FILTERS:
            raise DomainError("Unknown stock filter.")
        if value is not None and value != "":
            conditions.append(f"v.{field} = ?")
            parameters.append(_id(value, field.removesuffix("_id")))
    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    return [dict(row) for row in connection.execute(
        f"""SELECT v.id, v.product_id, v.brand_id, v.article_id, v.colour_id, v.size_id,
                   p.name AS product, b.name AS brand, a.name AS article,
                   co.name AS colour, s.name AS size, v.unit, v.default_selling_price,
                   SUM(m.quantity) AS quantity
            FROM variants v
            JOIN products p ON p.id = v.product_id
            JOIN brands b ON b.id = v.brand_id
            JOIN colours co ON co.id = v.colour_id
            LEFT JOIN articles a ON a.id = v.article_id
            LEFT JOIN sizes s ON s.id = v.size_id
            JOIN stock_movements m ON m.variant_id = v.id
            {where}
            GROUP BY v.id
            ORDER BY p.name COLLATE NOCASE, b.name COLLATE NOCASE, a.name COLLATE NOCASE,
                     co.name COLLATE NOCASE, s.name COLLATE NOCASE, v.id""",
        parameters,
    )]


def list_movements(connection, variant_id=None, limit=200):
    parameters = []
    where = ""
    if variant_id is not None and variant_id != "":
        where = "WHERE variant_id = ?"
        parameters.append(_id(variant_id, "stock combination"))
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise DomainError("Choose a history limit between 1 and 500.")
    parameters.append(limit)
    return [dict(row) for row in connection.execute(
        f"""SELECT id, variant_id, sale_item_id, kind, quantity, unit, created_at, note,
                   product, brand, article, colour, size, username
            FROM stock_movements {where} ORDER BY id DESC LIMIT ?""", parameters,
    )]
