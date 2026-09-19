-- Schema 4: inventory, sales, canonical measurements, versioned tailoring rates, and payments.
CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT INTO settings (key, value) VALUES ('schema_identity', 'measurement-templates-rates-v4');

CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE CHECK (length(username) BETWEEN 1 AND 80),
    password_hash TEXT NOT NULL,
    session_version INTEGER NOT NULL DEFAULT 1 CHECK (session_version > 0)
);

CREATE TABLE login_guard (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    failures INTEGER NOT NULL DEFAULT 0 CHECK (failures >= 0),
    window_start INTEGER NOT NULL DEFAULT 0
);
INSERT INTO login_guard (id) VALUES (1);

CREATE TABLE products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 80),
    name_key TEXT NOT NULL UNIQUE,
    classification TEXT NOT NULL CHECK (classification IN ('article_colour', 'colour_size', 'colour')),
    unit TEXT CHECK (unit IN ('metre', 'pair', 'piece')),
    suggested_unit TEXT CHECK (suggested_unit IN ('metre', 'pair', 'piece')),
    CHECK ((classification = 'article_colour' AND unit = 'metre')
        OR (classification IN ('colour', 'colour_size') AND (unit IS NULL OR unit IN ('pair', 'piece'))))
);

INSERT INTO products (name, name_key, classification, unit, suggested_unit) VALUES
    ('Fabric', 'fabric', 'article_colour', 'metre', 'metre'),
    ('Chappal / Peshawari Chappal', 'chappal / peshawari chappal', 'colour_size', NULL, 'pair'),
    ('Shawl', 'shawl', 'colour', NULL, 'piece'),
    ('Wallet', 'wallet', 'colour', NULL, 'piece'),
    ('Studs', 'studs', 'colour', 'pair', 'pair'),
    ('Waistcoat', 'waistcoat', 'colour_size', NULL, 'piece'),
    ('Coat', 'coat', 'colour_size', NULL, 'piece');

CREATE TABLE brands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    name TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 80),
    name_key TEXT NOT NULL,
    UNIQUE (product_id, name_key)
);

CREATE TABLE articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brand_id INTEGER NOT NULL REFERENCES brands(id) ON DELETE RESTRICT,
    name TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 80),
    name_key TEXT NOT NULL,
    UNIQUE (brand_id, name_key)
);

CREATE TABLE colours (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brand_id INTEGER NOT NULL REFERENCES brands(id) ON DELETE RESTRICT,
    article_id INTEGER REFERENCES articles(id) ON DELETE RESTRICT,
    name TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 80),
    name_key TEXT NOT NULL
);
CREATE UNIQUE INDEX colours_parent_name ON colours (
    brand_id, COALESCE(article_id, 0), name_key
);

CREATE TABLE sizes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    colour_id INTEGER NOT NULL REFERENCES colours(id) ON DELETE RESTRICT,
    name TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 80),
    name_key TEXT NOT NULL,
    UNIQUE (colour_id, name_key)
);

CREATE TABLE variants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    brand_id INTEGER NOT NULL REFERENCES brands(id) ON DELETE RESTRICT,
    article_id INTEGER REFERENCES articles(id) ON DELETE RESTRICT,
    colour_id INTEGER NOT NULL REFERENCES colours(id) ON DELETE RESTRICT,
    size_id INTEGER REFERENCES sizes(id) ON DELETE RESTRICT,
    unit TEXT NOT NULL CHECK (unit IN ('metre', 'pair', 'piece')),
    -- PKR paisa per one whole stock unit; NULL means no default has been set.
    default_selling_price INTEGER CHECK (
        default_selling_price IS NULL OR
        (typeof(default_selling_price) = 'integer' AND default_selling_price BETWEEN 0 AND 1000000000)
    )
);
CREATE UNIQUE INDEX variants_combination ON variants (
    product_id, brand_id, COALESCE(article_id, 0), colour_id, COALESCE(size_id, 0)
);

CREATE TABLE bill_sequence (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    -- 100000000 is the exhausted sentinel after BILL-99999999 is allocated.
    next_number INTEGER NOT NULL CHECK (next_number BETWEEN 1 AND 100000000)
);
INSERT INTO bill_sequence (id, next_number) VALUES (1, 1);

CREATE TABLE customer_sequence (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    -- 1000000 is the exhausted sentinel after CUST-999999 is allocated.
    next_number INTEGER NOT NULL CHECK (next_number BETWEEN 1 AND 1000000)
);
INSERT INTO customer_sequence (id, next_number) VALUES (1, 1);

CREATE TABLE customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_number TEXT NOT NULL UNIQUE CHECK (
        length(customer_number) = 11 AND
        customer_number GLOB 'CUST-[0-9][0-9][0-9][0-9][0-9][0-9]'
    ),
    name TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 120),
    primary_mobile TEXT NOT NULL CHECK (length(primary_mobile) BETWEEN 7 AND 40),
    primary_mobile_normalized TEXT NOT NULL CHECK (
        length(primary_mobile_normalized) BETWEEN 7 AND 15 AND
        primary_mobile_normalized NOT GLOB '*[^0-9]*'
    ),
    alternate_mobile TEXT NOT NULL DEFAULT '' CHECK (length(alternate_mobile) <= 40),
    alternate_mobile_normalized TEXT NOT NULL DEFAULT '' CHECK (
        alternate_mobile_normalized = '' OR
        (length(alternate_mobile_normalized) BETWEEN 7 AND 15 AND alternate_mobile_normalized NOT GLOB '*[^0-9]*')
    ),
    address TEXT NOT NULL DEFAULT '' CHECK (length(address) <= 500),
    notes TEXT NOT NULL DEFAULT '' CHECK (length(notes) <= 2000),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX customers_number ON customers (customer_number);
CREATE INDEX customers_primary_mobile ON customers (primary_mobile_normalized);
CREATE INDEX customers_alternate_mobile ON customers (alternate_mobile_normalized);

CREATE TABLE measurement_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL UNIQUE REFERENCES customers(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE measurement_revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL REFERENCES measurement_profiles(id) ON DELETE RESTRICT,
    revision_number INTEGER NOT NULL CHECK (revision_number > 0),
    garment_category TEXT NOT NULL CHECK (garment_category IN (
        'Pakistani Waistcoat', 'Three-Piece Waistcoat', 'Coat', 'Sherwani',
        'Pant', 'Shalwar Kameez', 'Shirt', 'Other / Custom Item'
    )),
    custom_description TEXT NOT NULL DEFAULT '' CHECK (
        (garment_category = 'Other / Custom Item' AND length(trim(custom_description)) BETWEEN 1 AND 200)
        OR (garment_category != 'Other / Custom Item' AND custom_description = '')
    ),
    unit TEXT NOT NULL DEFAULT 'inch' CHECK (unit = 'inch'),
    -- JSON object: printable field labels mapped to integer thousandths of an inch.
    measurements_json TEXT NOT NULL CHECK (json_valid(measurements_json) AND json_type(measurements_json) = 'object'),
    styles_json TEXT NOT NULL CHECK (json_valid(styles_json) AND json_type(styles_json) = 'object'),
    notes TEXT NOT NULL DEFAULT '' CHECK (length(notes) <= 1000),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (profile_id, revision_number)
);
CREATE INDEX measurement_revisions_profile_category
    ON measurement_revisions (profile_id, garment_category, id DESC);

CREATE TABLE sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_number TEXT NOT NULL UNIQUE CHECK (
        length(bill_number) = 13 AND
        bill_number GLOB 'BILL-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'
    ),
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    customer_id INTEGER REFERENCES customers(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    currency TEXT NOT NULL DEFAULT 'PKR' CHECK (currency = 'PKR'),
    customer_name TEXT NOT NULL DEFAULT '' CHECK (length(customer_name) <= 120),
    customer_mobile TEXT NOT NULL DEFAULT '' CHECK (length(customer_mobile) <= 40),
    subtotal INTEGER NOT NULL CHECK (typeof(subtotal) = 'integer' AND subtotal BETWEEN 0 AND 100000000000000000),
    discount INTEGER NOT NULL CHECK (typeof(discount) = 'integer' AND discount BETWEEN 0 AND subtotal),
    grand_total INTEGER NOT NULL CHECK (typeof(grand_total) = 'integer' AND grand_total = subtotal - discount),
    paid_amount INTEGER NOT NULL CHECK (typeof(paid_amount) = 'integer' AND paid_amount BETWEEN 0 AND grand_total),
    remaining_balance INTEGER NOT NULL CHECK (
        typeof(remaining_balance) = 'integer' AND
        remaining_balance = grand_total - paid_amount AND
        remaining_balance BETWEEN 0 AND 100000000000000000
    ),
    request_key TEXT NOT NULL UNIQUE CHECK (length(request_key) BETWEEN 16 AND 128),
    payload_digest TEXT NOT NULL CHECK (length(payload_digest) = 64),
    status TEXT NOT NULL CHECK (status IN ('building', 'finalized')),
    CHECK (remaining_balance = 0 OR (length(trim(customer_name)) > 0 AND length(trim(customer_mobile)) > 0))
);

CREATE TABLE sale_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id INTEGER NOT NULL REFERENCES sales(id) ON DELETE RESTRICT,
    line_number INTEGER NOT NULL CHECK (line_number BETWEEN 1 AND 100),
    variant_id INTEGER NOT NULL REFERENCES variants(id) ON DELETE RESTRICT,
    quantity INTEGER NOT NULL CHECK (typeof(quantity) = 'integer' AND quantity BETWEEN 1 AND 1000000000),
    unit TEXT NOT NULL CHECK (unit IN ('metre', 'pair', 'piece')),
    unit_price INTEGER NOT NULL CHECK (typeof(unit_price) = 'integer' AND unit_price BETWEEN 0 AND 1000000000),
    line_total INTEGER NOT NULL CHECK (typeof(line_total) = 'integer' AND line_total BETWEEN 0 AND 1000000000000000),
    product TEXT NOT NULL,
    brand TEXT NOT NULL,
    article TEXT,
    colour TEXT NOT NULL,
    size TEXT,
    UNIQUE (sale_id, line_number),
    CHECK (unit = 'metre' OR quantity % 1000 = 0),
    CHECK (line_total = CAST((quantity * unit_price + 500) / 1000 AS INTEGER))
);
CREATE INDEX sale_items_sale ON sale_items (sale_id, line_number);
CREATE INDEX sale_items_variant ON sale_items (variant_id, id);
CREATE INDEX sales_customer ON sales (customer_id, id);
CREATE INDEX sales_created_at ON sales (created_at, id);

CREATE TABLE stock_movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    variant_id INTEGER NOT NULL REFERENCES variants(id) ON DELETE RESTRICT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    sale_item_id INTEGER UNIQUE REFERENCES sale_items(id) ON DELETE RESTRICT,
    kind TEXT NOT NULL CHECK (kind IN ('opening', 'receipt', 'sale')),
    -- All quantities use thousandths, with no floating-point arithmetic.
    quantity INTEGER NOT NULL CHECK (
        typeof(quantity) = 'integer' AND quantity != 0 AND quantity BETWEEN -1000000000000 AND 1000000000000
    ),
    unit TEXT NOT NULL CHECK (unit IN ('metre', 'pair', 'piece')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    note TEXT NOT NULL DEFAULT '' CHECK (length(note) <= 500),
    request_key TEXT NOT NULL UNIQUE CHECK (length(request_key) BETWEEN 16 AND 128),
    payload_digest TEXT NOT NULL CHECK (length(payload_digest) = 64),
    product TEXT NOT NULL,
    brand TEXT NOT NULL,
    article TEXT,
    colour TEXT NOT NULL,
    size TEXT,
    username TEXT NOT NULL,
    CHECK (unit = 'metre' OR quantity % 1000 = 0),
    CHECK (
        (kind IN ('opening', 'receipt') AND quantity > 0 AND sale_item_id IS NULL)
        OR (kind = 'sale' AND quantity < 0 AND sale_item_id IS NOT NULL)
    )
);
CREATE INDEX stock_movements_variant ON stock_movements (variant_id, id);

CREATE TABLE tailoring_sequence (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    -- 1000000 is the exhausted sentinel after TAIL-999999 is allocated.
    next_number INTEGER NOT NULL CHECK (next_number BETWEEN 1 AND 1000000)
);
INSERT INTO tailoring_sequence (id, next_number) VALUES (1, 1);

CREATE TABLE stitching_rate_revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    garment_category TEXT NOT NULL CHECK (garment_category IN (
        'Pakistani Waistcoat', 'Three-Piece Waistcoat', 'Coat', 'Sherwani',
        'Pant', 'Shalwar Kameez', 'Shirt'
    )),
    revision_number INTEGER NOT NULL CHECK (revision_number > 0),
    rate INTEGER NOT NULL CHECK (typeof(rate) = 'integer' AND rate BETWEEN 0 AND 1000000000),
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (garment_category, revision_number)
);
CREATE INDEX stitching_rate_revisions_current
    ON stitching_rate_revisions (garment_category, revision_number DESC);

CREATE TABLE tailoring_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tailoring_number TEXT NOT NULL UNIQUE CHECK (
        length(tailoring_number) = 11 AND
        tailoring_number GLOB 'TAIL-[0-9][0-9][0-9][0-9][0-9][0-9]'
    ),
    sale_id INTEGER NOT NULL UNIQUE REFERENCES sales(id) ON DELETE RESTRICT,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE RESTRICT,
    order_date TEXT NOT NULL CHECK (order_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    promised_date TEXT NOT NULL CHECK (
        promised_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
    ),
    notes TEXT NOT NULL DEFAULT '' CHECK (length(notes) <= 2000),
    status TEXT NOT NULL DEFAULT 'Received' CHECK (status IN ('Received', 'In Progress', 'Ready', 'Delivered')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX tailoring_orders_number ON tailoring_orders (tailoring_number);
CREATE INDEX tailoring_orders_customer ON tailoring_orders (customer_id, id);
CREATE INDEX tailoring_orders_sale ON tailoring_orders (sale_id);
CREATE INDEX tailoring_orders_dates ON tailoring_orders (order_date, promised_date);
CREATE INDEX tailoring_orders_status ON tailoring_orders (status, order_date);

CREATE TABLE tailoring_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES tailoring_orders(id) ON DELETE RESTRICT,
    line_number INTEGER NOT NULL CHECK (line_number BETWEEN 1 AND 100),
    garment_category TEXT NOT NULL CHECK (garment_category IN (
        'Pakistani Waistcoat', 'Three-Piece Waistcoat', 'Coat', 'Sherwani',
        'Pant', 'Shalwar Kameez', 'Shirt', 'Other / Custom Item'
    )),
    custom_description TEXT NOT NULL DEFAULT '' CHECK (
        (garment_category = 'Other / Custom Item' AND length(trim(custom_description)) BETWEEN 1 AND 200)
        OR (garment_category != 'Other / Custom Item' AND custom_description = '')
    ),
    quantity INTEGER NOT NULL CHECK (
        typeof(quantity) = 'integer' AND quantity BETWEEN 1000 AND 1000000000 AND quantity % 1000 = 0
    ),
    unit TEXT NOT NULL DEFAULT 'piece' CHECK (unit = 'piece'),
    stitching_rate INTEGER NOT NULL CHECK (
        typeof(stitching_rate) = 'integer' AND stitching_rate BETWEEN 0 AND 1000000000
    ),
    stitching_rate_revision_id INTEGER REFERENCES stitching_rate_revisions(id) ON DELETE RESTRICT,
    line_total INTEGER NOT NULL CHECK (
        typeof(line_total) = 'integer' AND line_total BETWEEN 0 AND 1000000000000000 AND
        line_total = CAST((quantity * stitching_rate + 500) / 1000 AS INTEGER)
    ),
    cloth_source TEXT NOT NULL CHECK (cloth_source IN ('shop', 'customer')),
    source_sale_item_id INTEGER REFERENCES sale_items(id) ON DELETE RESTRICT,
    measurement_revision_id INTEGER NOT NULL REFERENCES measurement_revisions(id) ON DELETE RESTRICT,
    measurement_unit TEXT NOT NULL CHECK (measurement_unit = 'inch'),
    measurements_json TEXT NOT NULL CHECK (json_valid(measurements_json) AND json_type(measurements_json) = 'object'),
    styles_json TEXT NOT NULL CHECK (json_valid(styles_json) AND json_type(styles_json) = 'object'),
    measurement_notes TEXT NOT NULL DEFAULT '' CHECK (length(measurement_notes) <= 1000),
    UNIQUE (order_id, line_number),
    CHECK (cloth_source = 'shop' OR source_sale_item_id IS NULL),
    CHECK (
        (garment_category = 'Other / Custom Item' AND stitching_rate_revision_id IS NULL)
        OR (garment_category != 'Other / Custom Item' AND stitching_rate_revision_id IS NOT NULL)
    )
);
CREATE INDEX tailoring_items_order ON tailoring_items (order_id, line_number);
CREATE INDEX tailoring_items_source_sale_item ON tailoring_items (source_sale_item_id);
CREATE INDEX tailoring_items_rate_revision ON tailoring_items (stitching_rate_revision_id);

CREATE TABLE payment_sequence (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    -- 1000000 is the exhausted sentinel after PAY-999999 is allocated.
    next_number INTEGER NOT NULL CHECK (next_number BETWEEN 1 AND 1000000)
);
INSERT INTO payment_sequence (id, next_number) VALUES (1, 1);

CREATE TABLE payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_number TEXT NOT NULL UNIQUE CHECK (
        length(payment_number) = 10 AND
        payment_number GLOB 'PAY-[0-9][0-9][0-9][0-9][0-9][0-9]'
    ),
    sale_id INTEGER NOT NULL REFERENCES sales(id) ON DELETE RESTRICT,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE RESTRICT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    amount INTEGER NOT NULL CHECK (typeof(amount) = 'integer' AND amount BETWEEN 1 AND 100000000000000000),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    note TEXT NOT NULL DEFAULT '' CHECK (length(note) <= 500),
    request_key TEXT NOT NULL UNIQUE CHECK (length(request_key) BETWEEN 16 AND 128),
    payload_digest TEXT NOT NULL CHECK (length(payload_digest) = 64)
);
CREATE INDEX payments_number ON payments (payment_number);
CREATE INDEX payments_sale ON payments (sale_id, id);
CREATE INDEX payments_customer ON payments (customer_id, id);
CREATE INDEX payments_date ON payments (created_at);

CREATE TRIGGER articles_classification BEFORE INSERT ON articles
WHEN NOT EXISTS (
    SELECT 1 FROM brands b JOIN products p ON p.id = b.product_id
    WHERE b.id = NEW.brand_id AND p.classification = 'article_colour'
)
BEGIN SELECT RAISE(ABORT, 'Articles belong to fabric brands only.'); END;

CREATE TRIGGER colours_ownership BEFORE INSERT ON colours
WHEN NOT EXISTS (
    SELECT 1 FROM brands b
    JOIN products p ON p.id = b.product_id
    WHERE b.id = NEW.brand_id
      AND ((p.classification = 'article_colour'
            AND EXISTS (SELECT 1 FROM articles a WHERE a.id = NEW.article_id AND a.brand_id = b.id))
        OR (p.classification IN ('colour', 'colour_size') AND NEW.article_id IS NULL))
)
BEGIN SELECT RAISE(ABORT, 'A colour must belong to the correct brand or fabric article.'); END;

CREATE TRIGGER sizes_ownership BEFORE INSERT ON sizes
WHEN NOT EXISTS (
    SELECT 1 FROM colours co
    JOIN brands b ON b.id = co.brand_id
    JOIN products p ON p.id = b.product_id
    WHERE co.id = NEW.colour_id AND co.article_id IS NULL AND p.classification = 'colour_size'
)
BEGIN SELECT RAISE(ABORT, 'A size must belong to a colour in a size-based product.'); END;

CREATE TRIGGER variants_dimensions BEFORE INSERT ON variants
WHEN NOT EXISTS (
    SELECT 1 FROM products p
    JOIN brands b ON b.id = NEW.brand_id AND b.product_id = p.id
    JOIN colours co ON co.id = NEW.colour_id AND co.brand_id = b.id
    WHERE p.id = NEW.product_id AND p.unit = NEW.unit
      AND ((p.classification = 'article_colour' AND NEW.size_id IS NULL
            AND co.article_id = NEW.article_id
            AND EXISTS (SELECT 1 FROM articles a WHERE a.id = NEW.article_id AND a.brand_id = b.id))
        OR (p.classification = 'colour_size' AND NEW.article_id IS NULL AND co.article_id IS NULL
            AND EXISTS (SELECT 1 FROM sizes s WHERE s.id = NEW.size_id AND s.colour_id = co.id))
        OR (p.classification = 'colour' AND NEW.article_id IS NULL
            AND co.article_id IS NULL AND NEW.size_id IS NULL))
)
BEGIN SELECT RAISE(ABORT, 'Invalid stock combination or unconfirmed unit.'); END;

CREATE TRIGGER products_identity BEFORE UPDATE OF id ON products
WHEN NEW.id != OLD.id
BEGIN SELECT RAISE(ABORT, 'Catalogue identities cannot change.'); END;

CREATE TRIGGER products_classification BEFORE UPDATE OF classification ON products
WHEN NEW.classification != OLD.classification AND (
    EXISTS (SELECT 1 FROM brands WHERE product_id = OLD.id)
    OR EXISTS (SELECT 1 FROM variants WHERE product_id = OLD.id)
)
BEGIN SELECT RAISE(ABORT, 'A product already in use cannot be reclassified.'); END;

CREATE TRIGGER products_unit BEFORE UPDATE OF unit ON products
WHEN OLD.unit IS NOT NULL AND NEW.unit IS NOT OLD.unit
BEGIN SELECT RAISE(ABORT, 'A confirmed stock unit cannot change.'); END;

CREATE TRIGGER brands_identity BEFORE UPDATE OF id, product_id ON brands
WHEN NEW.id != OLD.id OR NEW.product_id != OLD.product_id
BEGIN SELECT RAISE(ABORT, 'Brands cannot be moved to another product.'); END;

CREATE TRIGGER articles_identity BEFORE UPDATE OF id, brand_id ON articles
WHEN NEW.id != OLD.id OR NEW.brand_id != OLD.brand_id
BEGIN SELECT RAISE(ABORT, 'Articles cannot be moved to another brand.'); END;

CREATE TRIGGER colours_identity BEFORE UPDATE OF id, brand_id, article_id ON colours
WHEN NEW.id != OLD.id OR NEW.brand_id != OLD.brand_id OR NEW.article_id IS NOT OLD.article_id
BEGIN SELECT RAISE(ABORT, 'Colours cannot be moved to another parent.'); END;

CREATE TRIGGER sizes_identity BEFORE UPDATE OF id, colour_id ON sizes
WHEN NEW.id != OLD.id OR NEW.colour_id != OLD.colour_id
BEGIN SELECT RAISE(ABORT, 'Sizes cannot be moved to another colour.'); END;

CREATE TRIGGER variants_identity BEFORE UPDATE ON variants
WHEN NEW.id != OLD.id OR NEW.product_id != OLD.product_id OR NEW.brand_id != OLD.brand_id
  OR NEW.article_id IS NOT OLD.article_id OR NEW.colour_id != OLD.colour_id
  OR NEW.size_id IS NOT OLD.size_id OR NEW.unit != OLD.unit
BEGIN SELECT RAISE(ABORT, 'Stock combinations cannot be rewritten.'); END;

CREATE TRIGGER bill_sequence_identity BEFORE UPDATE OF id ON bill_sequence
WHEN NEW.id != OLD.id
BEGIN SELECT RAISE(ABORT, 'The bill sequence identity cannot change.'); END;

CREATE TRIGGER bill_sequence_no_delete BEFORE DELETE ON bill_sequence
BEGIN SELECT RAISE(ABORT, 'The bill sequence cannot be deleted.'); END;

CREATE TRIGGER customer_sequence_identity BEFORE UPDATE OF id ON customer_sequence
WHEN NEW.id != OLD.id
BEGIN SELECT RAISE(ABORT, 'The customer sequence identity cannot change.'); END;

CREATE TRIGGER customer_sequence_no_delete BEFORE DELETE ON customer_sequence
BEGIN SELECT RAISE(ABORT, 'The customer sequence cannot be deleted.'); END;

CREATE TRIGGER tailoring_sequence_identity BEFORE UPDATE OF id ON tailoring_sequence
WHEN NEW.id != OLD.id
BEGIN SELECT RAISE(ABORT, 'The tailoring sequence identity cannot change.'); END;

CREATE TRIGGER tailoring_sequence_no_delete BEFORE DELETE ON tailoring_sequence
BEGIN SELECT RAISE(ABORT, 'The tailoring sequence cannot be deleted.'); END;

CREATE TRIGGER payment_sequence_identity BEFORE UPDATE OF id ON payment_sequence
WHEN NEW.id != OLD.id
BEGIN SELECT RAISE(ABORT, 'The payment sequence identity cannot change.'); END;

CREATE TRIGGER payment_sequence_no_delete BEFORE DELETE ON payment_sequence
BEGIN SELECT RAISE(ABORT, 'The payment sequence cannot be deleted.'); END;

CREATE TRIGGER customer_identity BEFORE UPDATE OF id, customer_number ON customers
WHEN NEW.id != OLD.id OR NEW.customer_number != OLD.customer_number
BEGIN SELECT RAISE(ABORT, 'Customer identities cannot change.'); END;

CREATE TRIGGER customers_no_delete BEFORE DELETE ON customers
BEGIN SELECT RAISE(ABORT, 'Customer records cannot be deleted.'); END;

CREATE TRIGGER measurement_profiles_no_update BEFORE UPDATE ON measurement_profiles
BEGIN SELECT RAISE(ABORT, 'Measurement profile identities cannot be edited.'); END;

CREATE TRIGGER measurement_profiles_no_delete BEFORE DELETE ON measurement_profiles
BEGIN SELECT RAISE(ABORT, 'Measurement profiles cannot be deleted.'); END;

CREATE TRIGGER measurement_revisions_no_update BEFORE UPDATE ON measurement_revisions
BEGIN SELECT RAISE(ABORT, 'Measurement revisions cannot be edited. Save a new revision instead.'); END;

CREATE TRIGGER measurement_revisions_no_delete BEFORE DELETE ON measurement_revisions
BEGIN SELECT RAISE(ABORT, 'Measurement revisions cannot be deleted.'); END;

CREATE TRIGGER stitching_rate_revisions_no_update BEFORE UPDATE ON stitching_rate_revisions
BEGIN SELECT RAISE(ABORT, 'Stitching-rate revisions cannot be edited. Save a new revision instead.'); END;

CREATE TRIGGER stitching_rate_revisions_no_delete BEFORE DELETE ON stitching_rate_revisions
BEGIN SELECT RAISE(ABORT, 'Stitching-rate revisions cannot be deleted.'); END;

CREATE TRIGGER sales_start_building BEFORE INSERT ON sales
WHEN NEW.status != 'building'
BEGIN SELECT RAISE(ABORT, 'A sale must be assembled transactionally before finalization.'); END;

CREATE TRIGGER sale_items_building BEFORE INSERT ON sale_items
WHEN NOT EXISTS (SELECT 1 FROM sales WHERE id = NEW.sale_id AND status = 'building')
BEGIN SELECT RAISE(ABORT, 'Items can be added only while a sale is being assembled.'); END;

CREATE TRIGGER tailoring_orders_building BEFORE INSERT ON tailoring_orders
WHEN NOT EXISTS (
    SELECT 1 FROM sales
    WHERE id = NEW.sale_id AND status = 'building' AND customer_id = NEW.customer_id
)
BEGIN SELECT RAISE(ABORT, 'A tailoring order requires its customer and a bill being assembled.'); END;

CREATE TRIGGER tailoring_items_building BEFORE INSERT ON tailoring_items
WHEN NOT EXISTS (
    SELECT 1 FROM tailoring_orders t JOIN sales sa ON sa.id = t.sale_id
    WHERE t.id = NEW.order_id AND sa.status = 'building'
)
BEGIN SELECT RAISE(ABORT, 'Tailoring items can be added only while their bill is being assembled.'); END;

CREATE TRIGGER tailoring_items_details BEFORE INSERT ON tailoring_items
WHEN NOT EXISTS (
    SELECT 1 FROM tailoring_orders t
    JOIN measurement_profiles mp ON mp.customer_id = t.customer_id
    JOIN measurement_revisions mr ON mr.id = NEW.measurement_revision_id AND mr.profile_id = mp.id
    WHERE t.id = NEW.order_id
      AND mr.garment_category = NEW.garment_category
      AND mr.custom_description = NEW.custom_description
      AND mr.unit = NEW.measurement_unit
      AND mr.measurements_json = NEW.measurements_json
      AND mr.styles_json = NEW.styles_json
      AND mr.notes = NEW.measurement_notes
      AND (
          (NEW.garment_category = 'Other / Custom Item' AND NEW.stitching_rate_revision_id IS NULL)
          OR (NEW.garment_category != 'Other / Custom Item' AND EXISTS (
              SELECT 1 FROM stitching_rate_revisions rr
              WHERE rr.id = NEW.stitching_rate_revision_id
                AND rr.garment_category = NEW.garment_category
                AND rr.rate = NEW.stitching_rate
          ))
      )
      AND (
          (NEW.cloth_source = 'customer' AND NEW.source_sale_item_id IS NULL)
          OR (NEW.cloth_source = 'shop' AND (
              NEW.source_sale_item_id IS NULL OR EXISTS (
                  SELECT 1 FROM sale_items si WHERE si.id = NEW.source_sale_item_id
              )
          ))
      )
)
BEGIN SELECT RAISE(ABORT, 'Tailoring items must preserve their measurement, rate and cloth-source snapshots.'); END;

CREATE TRIGGER sale_items_details BEFORE INSERT ON sale_items
WHEN NOT EXISTS (
    SELECT 1 FROM variants v
    JOIN products p ON p.id = v.product_id
    JOIN brands b ON b.id = v.brand_id
    JOIN colours co ON co.id = v.colour_id
    LEFT JOIN articles a ON a.id = v.article_id
    LEFT JOIN sizes s ON s.id = v.size_id
    WHERE v.id = NEW.variant_id AND v.unit = NEW.unit
      AND NEW.product = p.name AND NEW.brand = b.name AND NEW.colour = co.name
      AND NEW.article IS a.name AND NEW.size IS s.name
)
BEGIN SELECT RAISE(ABORT, 'Sale items must preserve the current exact-variant details.'); END;

CREATE TRIGGER sale_items_no_update BEFORE UPDATE ON sale_items
BEGIN SELECT RAISE(ABORT, 'Finalized sale items cannot be edited.'); END;

CREATE TRIGGER sale_items_no_delete BEFORE DELETE ON sale_items
BEGIN SELECT RAISE(ABORT, 'Finalized sale items cannot be deleted.'); END;

CREATE TRIGGER movement_details BEFORE INSERT ON stock_movements
WHEN NOT EXISTS (
    SELECT 1 FROM variants v
    JOIN products p ON p.id = v.product_id
    JOIN brands b ON b.id = v.brand_id
    JOIN colours co ON co.id = v.colour_id
    LEFT JOIN articles a ON a.id = v.article_id
    LEFT JOIN sizes s ON s.id = v.size_id
    JOIN users u ON u.id = NEW.user_id
    WHERE v.id = NEW.variant_id AND v.unit = NEW.unit
      AND NEW.product = p.name AND NEW.brand = b.name AND NEW.colour = co.name
      AND NEW.article IS a.name AND NEW.size IS s.name AND NEW.username = u.username
      AND (
          (NEW.kind IN ('opening', 'receipt') AND NEW.sale_item_id IS NULL)
          OR (NEW.kind = 'sale' AND EXISTS (
              SELECT 1 FROM sale_items si
              JOIN sales sa ON sa.id = si.sale_id
              WHERE si.id = NEW.sale_item_id AND si.variant_id = v.id
                AND si.quantity = -NEW.quantity AND si.unit = NEW.unit
                AND si.product = NEW.product AND si.brand = NEW.brand
                AND si.article IS NEW.article AND si.colour = NEW.colour AND si.size IS NEW.size
                AND sa.user_id = NEW.user_id AND sa.status = 'building'
          ))
      )
)
BEGIN SELECT RAISE(ABORT, 'Stock history must preserve the current item and user details.'); END;

CREATE TRIGGER sales_finalize_complete BEFORE UPDATE OF status ON sales
WHEN NEW.status = 'finalized' AND (
    (NOT EXISTS (SELECT 1 FROM sale_items WHERE sale_id = NEW.id)
     AND NOT EXISTS (SELECT 1 FROM tailoring_orders t JOIN tailoring_items ti ON ti.order_id = t.id WHERE t.sale_id = NEW.id))
    OR NEW.subtotal != (
        (SELECT COALESCE(SUM(line_total), 0) FROM sale_items WHERE sale_id = NEW.id)
        + (SELECT COALESCE(SUM(ti.line_total), 0) FROM tailoring_orders t
           JOIN tailoring_items ti ON ti.order_id = t.id WHERE t.sale_id = NEW.id)
    )
    OR EXISTS (
        SELECT 1 FROM tailoring_orders t
        WHERE t.sale_id = NEW.id AND (NEW.customer_id IS NULL OR t.customer_id != NEW.customer_id)
    )
    OR EXISTS (
        SELECT 1 FROM sale_items si
        WHERE si.sale_id = NEW.id
          AND NOT EXISTS (
              SELECT 1 FROM stock_movements m
              WHERE m.sale_item_id = si.id AND m.kind = 'sale'
                AND m.variant_id = si.variant_id AND m.quantity = -si.quantity
          )
    )
)
BEGIN SELECT RAISE(ABORT, 'A bill cannot finalize without matching product or tailoring items and stock movements.'); END;

CREATE TRIGGER sales_finalize_only BEFORE UPDATE ON sales
WHEN OLD.status != 'building' OR NEW.status != 'finalized'
  OR NEW.id != OLD.id OR NEW.bill_number != OLD.bill_number OR NEW.user_id != OLD.user_id
  OR NEW.customer_id IS NOT OLD.customer_id
  OR NEW.created_at != OLD.created_at OR NEW.currency != OLD.currency
  OR NEW.customer_name != OLD.customer_name OR NEW.customer_mobile != OLD.customer_mobile
  OR NEW.subtotal != OLD.subtotal OR NEW.discount != OLD.discount
  OR NEW.grand_total != OLD.grand_total OR NEW.paid_amount != OLD.paid_amount
  OR NEW.remaining_balance != OLD.remaining_balance OR NEW.request_key != OLD.request_key
  OR NEW.payload_digest != OLD.payload_digest
BEGIN SELECT RAISE(ABORT, 'Finalized sales cannot be edited.'); END;

CREATE TRIGGER sales_no_delete BEFORE DELETE ON sales
BEGIN SELECT RAISE(ABORT, 'Finalized sales cannot be deleted.'); END;

CREATE TRIGGER tailoring_items_no_update BEFORE UPDATE ON tailoring_items
BEGIN SELECT RAISE(ABORT, 'Finalized tailoring items and measurement snapshots cannot be edited.'); END;

CREATE TRIGGER tailoring_items_no_delete BEFORE DELETE ON tailoring_items
BEGIN SELECT RAISE(ABORT, 'Finalized tailoring items cannot be deleted.'); END;

CREATE TRIGGER tailoring_orders_status_only BEFORE UPDATE ON tailoring_orders
WHEN NEW.id != OLD.id OR NEW.tailoring_number != OLD.tailoring_number OR NEW.sale_id != OLD.sale_id
  OR NEW.customer_id != OLD.customer_id OR NEW.order_date != OLD.order_date
  OR NEW.promised_date IS NOT OLD.promised_date OR NEW.notes != OLD.notes
  OR NEW.created_at != OLD.created_at
BEGIN SELECT RAISE(ABORT, 'Only a tailoring order status may change.'); END;

CREATE TRIGGER tailoring_orders_no_delete BEFORE DELETE ON tailoring_orders
BEGIN SELECT RAISE(ABORT, 'Tailoring orders cannot be deleted.'); END;

CREATE TRIGGER payments_details BEFORE INSERT ON payments
WHEN NOT EXISTS (
    SELECT 1 FROM sales sa
    WHERE sa.id = NEW.sale_id AND sa.status = 'finalized'
      AND sa.customer_id = NEW.customer_id
      AND NEW.amount <= sa.remaining_balance - COALESCE(
          (SELECT SUM(p.amount) FROM payments p WHERE p.sale_id = sa.id), 0
      )
)
BEGIN SELECT RAISE(ABORT, 'A payment must match the bill customer and cannot exceed its outstanding balance.'); END;

CREATE TRIGGER payments_no_update BEFORE UPDATE ON payments
BEGIN SELECT RAISE(ABORT, 'Saved payments cannot be edited.'); END;

CREATE TRIGGER payments_no_delete BEFORE DELETE ON payments
BEGIN SELECT RAISE(ABORT, 'Saved payments cannot be deleted.'); END;

CREATE TRIGGER movement_opening BEFORE INSERT ON stock_movements
WHEN NEW.kind = 'opening' AND EXISTS (SELECT 1 FROM stock_movements WHERE variant_id = NEW.variant_id)
BEGIN SELECT RAISE(ABORT, 'Opening stock is only allowed for a new stock combination.'); END;

CREATE TRIGGER movement_balance_limit BEFORE INSERT ON stock_movements
WHEN COALESCE((SELECT SUM(quantity) FROM stock_movements WHERE variant_id = NEW.variant_id), 0)
     + NEW.quantity > 1000000000000
BEGIN SELECT RAISE(ABORT, 'This entry exceeds the supported stock quantity.'); END;

CREATE TRIGGER stock_movements_no_update BEFORE UPDATE ON stock_movements
BEGIN SELECT RAISE(ABORT, 'Saved stock movements cannot be edited.'); END;

CREATE TRIGGER stock_movements_no_delete BEFORE DELETE ON stock_movements
BEGIN SELECT RAISE(ABORT, 'Saved stock movements cannot be deleted.'); END;

PRAGMA user_version = 4;
