"""Route-level checks that also compile and render the server-side templates."""

from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.parse import parse_qs, urlsplit

from werkzeug.security import generate_password_hash

from shop import create_app
from shop.db import connect_database, initialize_database
from shop.inventory import (
    add_article,
    add_brand,
    add_colour,
    add_size,
    catalogue,
    confirm_unit,
    list_stock,
)


class WebFoundationTests(unittest.TestCase):
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
            follow_redirects=True,
        )
        self.assertEqual(200, response.status_code)
        self.assertIn("Dashboard", response.get_data(as_text=True))

    def make_fabric_catalogue(self):
        with closing(connect_database(self.database)) as connection:
            fabric = next(item for item in catalogue(connection)["products"] if item["name"] == "Fabric")
            first_brand = add_brand(connection, "Yathreb", fabric["id"])
            second_brand = add_brand(connection, "Indicote", fabric["id"])
            first_article = add_article(connection, "Dastan", first_brand)
            second_article = add_article(connection, "Classic", second_brand)
            first_colour = add_colour(connection, "Blue", first_brand, first_article)
            second_colour = add_colour(connection, "Black", second_brand, second_article)
        return fabric, first_brand, second_brand, first_article, second_article, first_colour, second_colour

    def make_sized_catalogue(self):
        with closing(connect_database(self.database)) as connection:
            product = next(
                item for item in catalogue(connection)["products"]
                if item["classification"] == "colour_size"
            )
            first_brand = add_brand(connection, "Yathreb", product["id"])
            second_brand = add_brand(connection, "Safeer", product["id"])
            first_colour = add_colour(connection, "Brown", first_brand)
            second_colour = add_colour(connection, "Black", second_brand)
            first_size = add_size(connection, "42", first_colour)
            second_size = add_size(connection, "44", second_colour)
        return product, first_brand, second_brand, first_colour, second_colour, first_size, second_size

    def test_records_require_login_and_post_requires_csrf(self):
        response = self.client.get("/")
        self.assertEqual(302, response.status_code)
        self.assertTrue(response.headers["Location"].endswith("/login"))
        self.client.get("/login")
        response = self.client.post("/login", data={"username": "owner", "password": self.password})
        self.assertEqual(400, response.status_code)
        self.sign_in()

    def test_catalogue_shows_only_children_of_the_open_parent(self):
        fabric, first_brand, _, first_article, _, first_colour, _ = self.make_fabric_catalogue()
        self.sign_in()
        response = self.client.get(
            f"/catalogue?product_id={fabric['id']}&brand_id={first_brand}&article_id={first_article}"
        )
        page = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        self.assertIn("Articles in Yathreb", page)
        self.assertIn("Dastan", page)
        self.assertIn("Blue", page)
        self.assertNotIn("Classic", page)
        self.assertNotIn("Black", page)

        response = self.client.get(
            f"/stock?product_id={fabric['id']}&brand_id={first_brand}&article_id={first_article}&colour_id={first_colour}"
        )
        page = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        self.assertIn('data-stock-entry-ready="true"', page)
        self.assertNotIn("Classic", page)
        self.assertNotIn("Black", page)

    def test_invalid_cross_parent_query_and_post_cannot_create_stock(self):
        fabric, first_brand, _, _, second_article, _, second_colour = self.make_fabric_catalogue()
        self.sign_in()
        response = self.client.get(
            f"/stock?product_id={fabric['id']}&brand_id={first_brand}&article_id={second_article}&colour_id={second_colour}"
        )
        page = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        self.assertIn('data-stock-entry-ready="false"', page)

        response = self.client.post(
            "/stock",
            data={
                "csrf_token": self.csrf(),
                "request_key": "web-cross-parent-001",
                "product_id": fabric["id"],
                "brand_id": first_brand,
                "article_id": second_article,
                "colour_id": second_colour,
                "size_id": "",
                "quantity": "1",
                "kind": "opening",
                "note": "",
            },
        )
        self.assertEqual(400, response.status_code)
        with closing(connect_database(self.database)) as connection:
            self.assertEqual([], list_stock(connection))

    def test_valid_complete_chain_saves_one_exact_variant_and_history(self):
        fabric, first_brand, _, first_article, _, first_colour, _ = self.make_fabric_catalogue()
        self.sign_in()
        response = self.client.post(
            "/stock",
            data={
                "csrf_token": self.csrf(),
                "request_key": "web-stock-entry-0001",
                "product_id": fabric["id"],
                "brand_id": first_brand,
                "article_id": first_article,
                "colour_id": first_colour,
                "size_id": "",
                "quantity": "4.25",
                "kind": "opening",
                "note": "Trial count",
            },
            follow_redirects=True,
        )
        self.assertEqual(200, response.status_code)
        self.assertIn("Stock entry saved", response.get_data(as_text=True))
        with closing(connect_database(self.database)) as connection:
            rows = list_stock(connection)
        self.assertEqual(1, len(rows))
        self.assertEqual(4250, rows[0]["quantity"])
        self.assertEqual("Fabric", rows[0]["product"])

        response = self.client.get(f"/history?variant_id={rows[0]['id']}")
        page = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        self.assertIn("Dastan", page)
        self.assertIn("Trial count", page)

    def test_add_stock_selection_has_cascade_hooks_fallback_and_unit_block(self):
        fabric, first_brand, _, first_article, _, first_colour, _ = self.make_fabric_catalogue()
        sized, sized_brand, _, sized_colour, _, sized_size, _ = self.make_sized_catalogue()
        with closing(connect_database(self.database)) as connection:
            products = catalogue(connection)["products"]
            shawl = next(item for item in products if item["name"] == "Shawl")
            studs = next(item for item in products if item["name"] == "Studs")
            studs_brand = add_brand(connection, "Stud brand", studs["id"])
            studs_colour = add_colour(connection, "Silver", studs_brand)
            confirm_unit(connection, sized["id"], "pair")
        self.sign_in()

        response = self.client.get("/stock", query_string={"product_id": fabric["id"]})
        page = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        self.assertIn("data-stock-entry-selection", page)
        self.assertIn('data-children-url="/catalogue/children"', page)
        self.assertIn('data-stock-entry-filter="product"', page)
        self.assertIn('data-stock-entry-filter="brand"', page)
        self.assertIn('data-stock-entry-filter="article"', page)
        self.assertIn('data-stock-entry-filter="colour"', page)
        self.assertIn('data-stock-entry-filter="size"', page)
        self.assertIn("Yathreb", page)
        self.assertIn("Open selection", page)
        self.assertIn('data-stock-entry-ready="false"', page)

        response = self.client.get(
            "/stock",
            query_string={"product_id": fabric["id"], "brand_id": first_brand},
        )
        page = response.get_data(as_text=True)
        self.assertIn("Dastan", page)
        self.assertNotIn("Classic", page)

        response = self.client.get(
            "/stock",
            query_string={
                "product_id": fabric["id"],
                "brand_id": first_brand,
                "article_id": first_article,
                "colour_id": first_colour,
            },
        )
        page = response.get_data(as_text=True)
        self.assertIn('data-stock-entry-ready="true"', page)
        self.assertIn("Entry type", page)
        self.assertIn("Quantity", page)
        self.assertIn("Note", page)
        self.assertEqual(1, page.count("Save stock entry"))

        response = self.client.get(
            "/stock",
            query_string={
                "product_id": studs["id"],
                "brand_id": studs_brand,
                "colour_id": studs_colour,
            },
        )
        page = response.get_data(as_text=True)
        self.assertIn('data-stock-entry-ready="true"', page)
        self.assertIn("Silver", page)
        self.assertIn("data-stock-entry-unit-label>pairs</span>", page)

        response = self.client.get(
            "/stock",
            query_string={
                "product_id": sized["id"],
                "brand_id": sized_brand,
                "colour_id": sized_colour,
                "size_id": sized_size,
            },
        )
        page = response.get_data(as_text=True)
        self.assertIn('data-stock-entry-ready="true"', page)
        self.assertIn(f'name="size_id" value="{sized_size}"', page)

        response = self.client.get("/stock", query_string={"product_id": shawl["id"]})
        page = response.get_data(as_text=True)
        self.assertIn("Confirm this product&rsquo;s stock unit", page)
        self.assertIn("Stock entry is unavailable until you explicitly choose pairs or pieces", page)
        self.assertIn('data-suggested-unit="piece"', page)
        self.assertIn('data-stock-entry-ready="false"', page)

    def test_add_stock_validation_error_preserves_chain_fields_and_retry_key(self):
        fabric, brand, _, article, _, colour, _ = self.make_fabric_catalogue()
        self.sign_in()
        response = self.client.post(
            "/stock",
            data={
                "csrf_token": self.csrf(),
                "request_key": "stock-validation-retry-001",
                "product_id": fabric["id"],
                "brand_id": brand,
                "article_id": article,
                "colour_id": colour,
                "size_id": "",
                "quantity": "0",
                "kind": "opening",
                "note": "Keep this form",
            },
        )
        page = response.get_data(as_text=True)
        self.assertEqual(400, response.status_code)
        self.assertIn('data-stock-entry-ready="true"', page)
        self.assertIn('value="stock-validation-retry-001"', page)
        self.assertIn(f'name="product_id" value="{fabric["id"]}"', page)
        self.assertIn(f'name="brand_id" value="{brand}"', page)
        self.assertIn(f'name="article_id" value="{article}"', page)
        self.assertIn(f'name="colour_id" value="{colour}"', page)
        self.assertIn('name="quantity" inputmode="decimal"', page)
        self.assertIn('value="0"', page)
        self.assertIn('<option value="opening" selected>', page)
        self.assertIn("Keep this form", page)
        with closing(connect_database(self.database)) as connection:
            self.assertEqual([], list_stock(connection))

    def test_current_stock_summarizes_each_product_separately(self):
        fabric, fabric_brand, _, article, _, fabric_colour, _ = self.make_fabric_catalogue()
        sized, sized_brand, _, sized_colour, _, sized_size, _ = self.make_sized_catalogue()
        self.sign_in()

        for request_key, product_id, brand_id, article_id, colour_id, size_id, quantity in (
            ("product-total-fabric", fabric["id"], fabric_brand, article, fabric_colour, "", "7.5"),
            ("product-total-sized", sized["id"], sized_brand, "", sized_colour, sized_size, "3"),
        ):
            response = self.client.post(
                "/stock",
                data={
                    "csrf_token": self.csrf(),
                    "request_key": request_key,
                    "product_id": product_id,
                    "brand_id": brand_id,
                    "article_id": article_id,
                    "colour_id": colour_id,
                    "size_id": size_id,
                    "quantity": quantity,
                    "kind": "receipt",
                    "note": "",
                },
            )
            self.assertEqual(303, response.status_code)

        page = self.client.get("/").get_data(as_text=True)
        self.assertIn("Product totals", page)
        self.assertIn("<span>Fabric</span><strong>7.5 metres</strong>", page)
        self.assertIn(
            f"<span>{sized['name']}</span><strong>3 {sized['unit']}s</strong>",
            page,
        )
        self.assertEqual(2, page.count("data-stock-product-total"))

    def test_add_stock_can_create_each_catalogue_level_inline(self):
        self.sign_in()
        page = self.client.get("/stock").get_data(as_text=True)
        self.assertIn('data-stock-catalogue-add="product"', page)
        self.assertIn('data-stock-catalogue-add="brand"', page)
        self.assertIn("data-stock-catalogue-dialog", page)

        response = self.client.post(
            "/stock/catalogue",
            data={
                "csrf_token": self.csrf(),
                "kind": "product",
                "name": "Test Belt",
                "classification": "colour_size",
                "unit": "piece",
            },
            headers={"Accept": "application/json"},
        )
        self.assertEqual(201, response.status_code)
        product_id = response.get_json()["item"]["id"]

        response = self.client.post(
            "/stock/catalogue",
            data={
                "csrf_token": self.csrf(),
                "kind": "brand",
                "name": "Test Brand",
                "product_id": product_id,
            },
            headers={"Accept": "application/json"},
        )
        self.assertEqual(201, response.status_code)
        brand_id = response.get_json()["item"]["id"]

        response = self.client.post(
            "/stock/catalogue",
            data={
                "csrf_token": self.csrf(),
                "kind": "colour",
                "name": "Brown",
                "product_id": product_id,
                "brand_id": brand_id,
            },
            headers={"Accept": "application/json"},
        )
        self.assertEqual(201, response.status_code)
        colour_id = response.get_json()["item"]["id"]

        response = self.client.post(
            "/stock/catalogue",
            data={
                "csrf_token": self.csrf(),
                "kind": "size",
                "name": "Medium",
                "product_id": product_id,
                "brand_id": brand_id,
                "colour_id": colour_id,
            },
            headers={"Accept": "application/json"},
        )
        self.assertEqual(201, response.status_code)
        size_payload = response.get_json()
        self.assertIn(f"product_id={product_id}", size_payload["redirect_url"])
        self.assertIn(f"size_id={size_payload['item']['id']}", size_payload["redirect_url"])

        with closing(connect_database(self.database)) as connection:
            fabric = next(
                item for item in catalogue(connection)["products"]
                if item["name"] == "Fabric"
            )
            fabric_brand = add_brand(connection, "Inline Fabric Brand", fabric["id"])
        response = self.client.post(
            "/stock/catalogue",
            data={
                "csrf_token": self.csrf(),
                "kind": "article",
                "name": "Inline Article",
                "product_id": fabric["id"],
                "brand_id": fabric_brand,
            },
            headers={"Accept": "application/json"},
        )
        self.assertEqual(201, response.status_code)

    def test_children_endpoint_returns_only_canonical_parent_scoped_choices(self):
        fabric, first_brand, _, first_article, second_article, first_colour, second_colour = (
            self.make_fabric_catalogue()
        )
        sized, sized_brand, _, sized_colour, other_colour, first_size, other_size = (
            self.make_sized_catalogue()
        )
        response = self.client.get("/catalogue/children")
        self.assertEqual(302, response.status_code)
        self.assertIn("/login", response.headers["Location"])
        self.sign_in()

        response = self.client.get(
            "/catalogue/children",
            query_string={
                "product_id": fabric["id"],
                "brand_id": first_brand,
                "article_id": first_article,
                "colour_id": first_colour,
            },
        )
        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertEqual("article_colour", payload["classification"])
        self.assertEqual("metre", payload["unit"])
        self.assertEqual({"Yathreb", "Indicote"}, {item["name"] for item in payload["brands"]})
        self.assertEqual({"Dastan"}, {item["name"] for item in payload["articles"]})
        self.assertEqual({"Blue"}, {item["name"] for item in payload["colours"]})

        response = self.client.get(
            "/catalogue/children",
            query_string={"product_id": fabric["id"], "brand_id": sized_brand},
        )
        payload = response.get_json()
        self.assertIsNone(payload["brand_id"])
        self.assertEqual({"Yathreb", "Indicote"}, {item["name"] for item in payload["brands"]})
        self.assertEqual([], payload["articles"])
        self.assertEqual([], payload["colours"])

        response = self.client.get(
            "/catalogue/children",
            query_string={
                "product_id": fabric["id"],
                "brand_id": first_brand,
                "article_id": second_article,
                "colour_id": second_colour,
            },
        )
        payload = response.get_json()
        self.assertEqual(first_brand, payload["brand_id"])
        self.assertIsNone(payload["article_id"])
        self.assertIsNone(payload["colour_id"])
        self.assertEqual({"Dastan"}, {item["name"] for item in payload["articles"]})
        self.assertEqual([], payload["colours"])

        response = self.client.get(
            "/catalogue/children",
            query_string={
                "product_id": sized["id"],
                "brand_id": sized_brand,
                "colour_id": sized_colour,
                "size_id": first_size,
            },
        )
        payload = response.get_json()
        self.assertEqual("colour_size", payload["classification"])
        self.assertEqual({"Yathreb", "Safeer"}, {item["name"] for item in payload["brands"]})
        self.assertEqual([], payload["articles"])
        self.assertEqual({"Brown"}, {item["name"] for item in payload["colours"]})
        self.assertEqual({"42"}, {item["name"] for item in payload["sizes"]})

        response = self.client.get(
            "/catalogue/children",
            query_string={
                "product_id": sized["id"],
                "brand_id": sized_brand,
                "colour_id": other_colour,
                "size_id": other_size,
            },
        )
        payload = response.get_json()
        self.assertIsNone(payload["colour_id"])
        self.assertIsNone(payload["size_id"])
        self.assertEqual({"Brown"}, {item["name"] for item in payload["colours"]})
        self.assertEqual([], payload["sizes"])

    def test_current_stock_filters_keep_one_apply_action_and_server_fallback(self):
        fabric, first_brand, _, first_article, _, first_colour, _ = self.make_fabric_catalogue()
        self.sign_in()

        response = self.client.get("/", query_string={"product_id": fabric["id"]})
        page = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        self.assertIn('data-stock-filter-form', page)
        self.assertIn('data-children-url="/catalogue/children"', page)
        self.assertIn('src="/static/app.js"', page)
        self.assertIn("<noscript>", page)
        self.assertEqual(
            1,
            page.count('<button type="submit" class="primary">Apply filters</button>'),
        )
        self.assertIn("Yathreb", page)

        response = self.client.get(
            "/",
            query_string={"product_id": fabric["id"], "brand_id": first_brand},
        )
        page = response.get_data(as_text=True)
        self.assertIn("Dastan", page)
        self.assertNotIn("Classic", page)

        response = self.client.get(
            "/",
            query_string={
                "product_id": fabric["id"],
                "brand_id": first_brand,
                "article_id": first_article,
                "colour_id": first_colour,
            },
        )
        page = response.get_data(as_text=True)
        self.assertIn(f'value="{fabric["id"]}" data-classification="article_colour" selected', page)
        self.assertIn(f'value="{first_brand}" selected', page)
        self.assertIn(f'value="{first_article}" selected', page)
        self.assertIn(f'value="{first_colour}" selected', page)
        self.assertIn("Blue", page)
        self.assertNotIn("Black", page)

    def test_catalogue_actions_keep_the_relevant_management_section(self):
        fabric, brand, _, article, _, colour, _ = self.make_fabric_catalogue()
        sized, sized_brand, _, sized_colour, _, size, _ = self.make_sized_catalogue()
        self.sign_in()

        response = self.client.get(
            "/catalogue",
            query_string={
                "product_id": fabric["id"],
                "brand_id": brand,
                "article_id": article,
                "colour_id": colour,
            },
        )
        page = response.get_data(as_text=True)
        for target in (
            "products-section",
            "product-editor",
            "brands-section",
            "brand-editor",
            "articles-section",
            "article-editor",
            "colours-section",
            "colour-editor",
        ):
            self.assertIn(f'id="{target}"', page)
        for fragment in (
            "products-section",
            "product-editor",
            "brands-section",
            "brand-editor",
            "articles-section",
            "article-editor",
            "colours-section",
            "colour-editor",
        ):
            self.assertIn(f'action="/catalogue#{fragment}"', page)
        for level in ("product", "brand", "article", "colour"):
            self.assertIn(f'data-catalogue-select="{level}"', page)
        self.assertNotIn('data-catalogue-select="size"', page)
        self.assertEqual(4, page.count("data-catalogue-open-fallback"))
        for label in ("Open product", "Open brand", "Open article", "Open colour"):
            self.assertIn(f">{label}</button>", page)
        for label in ("Brand", "Article", "Colour"):
            self.assertIn(f'data-catalogue-add-label="+ Add new {label}&hellip;"', page)

        script = self.client.get("/static/app.js").get_data(as_text=True)
        self.assertIn('querySelectorAll("[data-catalogue-open-form]")', script)
        self.assertIn("fallback.hidden = true", script)
        self.assertIn("openForm.requestSubmit()", script)
        self.assertIn("dataset.catalogueAddForm !== addLevel", script)

        chain = {
            "product_id": fabric["id"],
            "brand_id": brand,
            "article_id": article,
            "colour_id": colour,
        }
        rename_cases = (
            ("product", fabric["id"], "Fabric cloth", "products-section"),
            ("brand", brand, "Yathreb cloth", "brands-section"),
            ("article", article, "Dastan cloth", "articles-section"),
            ("colour", colour, "Blue cloth", "colours-section"),
            ("size", size, "42 regular", "sizes-section"),
        )
        for kind, item_id, name, expected_fragment in rename_cases:
            posted_chain = dict(chain)
            if kind == "size":
                posted_chain = {
                    "product_id": sized["id"],
                    "brand_id": sized_brand,
                    "article_id": "",
                    "colour_id": sized_colour,
                }
            with self.subTest(action="rename", kind=kind):
                response = self.client.post(
                    "/catalogue",
                    data={
                        "csrf_token": self.csrf(),
                        "action": "rename_label",
                        "kind": kind,
                        "item_id": item_id,
                        "name": name,
                        **posted_chain,
                    },
                )
                self.assertEqual(303, response.status_code)
                location = urlsplit(response.headers["Location"])
                self.assertEqual(expected_fragment, location.fragment)
                redirected_chain = parse_qs(location.query)
                for key, value in posted_chain.items():
                    if value != "":
                        self.assertEqual([str(value)], redirected_chain[key])

        add_cases = (
            (
                {"action": "add_product", "name": "Belts", "classification": "colour", "unit": "piece"},
                "product-editor",
                {"product_id": None},
            ),
            (
                {"action": "add_brand", "name": "New brand", **chain},
                "brand-editor",
                {"product_id": fabric["id"], "brand_id": None},
            ),
            (
                {"action": "add_article", "name": "New article", **chain},
                "article-editor",
                {"product_id": fabric["id"], "brand_id": brand, "article_id": None},
            ),
            (
                {"action": "add_colour", "name": "New colour", **chain},
                "colour-editor",
                {
                    "product_id": fabric["id"],
                    "brand_id": brand,
                    "article_id": article,
                    "colour_id": None,
                },
            ),
            (
                {
                    "action": "add_colour",
                    "name": "Tan",
                    "product_id": sized["id"],
                    "brand_id": sized_brand,
                    "article_id": "",
                    "colour_id": "",
                },
                "colour-editor",
                {
                    "product_id": sized["id"],
                    "brand_id": sized_brand,
                    "colour_id": None,
                },
            ),
            (
                {
                    "action": "add_size",
                    "name": "43",
                    "product_id": sized["id"],
                    "brand_id": sized_brand,
                    "article_id": "",
                    "colour_id": sized_colour,
                },
                "size-editor",
                {
                    "product_id": sized["id"],
                    "brand_id": sized_brand,
                    "colour_id": sized_colour,
                    "size_id": None,
                },
            ),
        )
        for data, expected_fragment, expected_chain in add_cases:
            with self.subTest(action=data["action"], fragment=expected_fragment):
                response = self.client.post(
                    "/catalogue",
                    data={"csrf_token": self.csrf(), **data},
                )
                self.assertEqual(303, response.status_code)
                location = urlsplit(response.headers["Location"])
                self.assertEqual(expected_fragment, location.fragment)
                redirected_chain = parse_qs(location.query)
                for key, value in expected_chain.items():
                    self.assertIn(key, redirected_chain)
                    if value is None:
                        self.assertTrue(redirected_chain[key][0])
                    else:
                        self.assertEqual([str(value)], redirected_chain[key])
                redirected_page = self.client.get(response.headers["Location"]).get_data(as_text=True)
                if data["action"] == "add_product":
                    self.assertIn('data-catalogue-select="brand"', redirected_page)
                elif data["action"] == "add_brand":
                    self.assertIn('data-catalogue-select="article"', redirected_page)
                elif data["action"] == "add_article":
                    self.assertIn('data-catalogue-select="colour"', redirected_page)
                elif data["action"] == "add_colour" and data["name"] == "Tan":
                    self.assertIn('data-catalogue-select="size"', redirected_page)
                created_key = next(
                    (key for key, expected in expected_chain.items() if expected is None),
                    None,
                )
                if created_key:
                    self.assertIn(
                        f'value="{redirected_chain[created_key][0]}"',
                        redirected_page,
                    )

        response = self.client.get(
            "/catalogue",
            query_string={
                "product_id": sized["id"],
                "brand_id": sized_brand,
                "colour_id": sized_colour,
            },
        )
        page = response.get_data(as_text=True)
        self.assertIn('id="colour-editor"', page)
        self.assertIn('id="sizes-section"', page)
        self.assertNotIn('data-catalogue-select="article"', page)
        self.assertIn('data-catalogue-select="size"', page)
        self.assertIn('data-catalogue-add-label="+ Add new Size&hellip;"', page)
        self.assertIn(">Open size</button>", page)
        self.assertIn('action="/catalogue#colour-editor"', page)
        self.assertIn('action="/catalogue#sizes-section"', page)
        self.assertIn('action="/catalogue#size-editor"', page)

        selected_size_page = self.client.get(
            "/catalogue",
            query_string={
                "product_id": sized["id"],
                "brand_id": sized_brand,
                "colour_id": sized_colour,
                "size_id": size,
            },
        ).get_data(as_text=True)
        self.assertIn('id="size-editor"', selected_size_page)
        self.assertIn(f'value="{size}" selected', selected_size_page)


if __name__ == "__main__":
    unittest.main()
