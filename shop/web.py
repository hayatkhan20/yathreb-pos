"""Server-rendered inventory, billing, finalized bills, and history."""

from datetime import date, datetime, time, timedelta, timezone
import json
import re
from uuid import uuid4

from flask import Blueprint, abort, g, jsonify, redirect, render_template, request, url_for

from .db import get_db
from .inventory import (
    CUSTOM_GARMENT_CATEGORY,
    DomainError,
    FABRIC_PRODUCT_ID,
    MAX_UNIT_PRICE,
    STANDARD_MEASUREMENT_TEMPLATES,
    TAILORING_STATUSES,
    add_article,
    assign_tailor,
    add_brand,
    add_colour,
    add_product,
    add_size,
    catalogue,
    catalogue_deletion_candidate,
    confirm_unit,
    configure_stitching_rate,
    create_customer,
    create_tailor,
    delete_catalogue_item,
    finalize_combined_bill,
    format_pkr,
    format_quantity,
    get_current_stitching_rates,
    get_customer,
    get_customer_account,
    get_measurement_revisions,
    get_payment,
    get_sale,
    get_sale_variant,
    get_stitching_rate_history,
    get_tailoring_order,
    list_customer_product_sale_items,
    list_customer_balances,
    list_movements,
    list_sales,
    list_stock,
    list_tailoring_orders,
    list_tailors,
    parse_pkr,
    quote_sale_items,
    quote_tailoring_items,
    receive_stock,
    record_payment,
    rename_label,
    save_measurements,
    sales_report,
    search_customers,
    set_default_selling_price,
    set_tailor_active,
    update_customer,
)

bp = Blueprint("web", __name__)

NOTICE_MESSAGES = {
    "product-added": "Product added.",
    "unit-confirmed": "Stock unit confirmed. This unit is now permanent for the product.",
    "label-added": "Catalogue item added.",
    "renamed": "Name updated without changing its stock identity or history.",
    "stock-added": "Stock entry saved.",
    "stock-replayed": "This submission was already saved; no duplicate stock was added.",
    "deleted": "Unused catalogue record permanently deleted.",
}

CUSTOMER_NOTICES = {
    "created": "Customer created.",
    "updated": "Customer contact details updated.",
    "measurement-saved": "A new measurement revision was saved.",
    "rate-saved": "A new stitching-rate revision was saved.",
}

SHOP_TIMEZONE = timezone(timedelta(hours=5), name="PKT")


def _optional_id(value):
    if value is None or value == "":
        return None
    text = str(value)
    if not text.isascii() or not text.isdigit() or int(text) < 1:
        raise DomainError("Choose catalogue values from the lists provided.")
    return int(text)


def _selection(source):
    """Build dependent choices without trusting posted or queried relationships."""
    data = catalogue(get_db())
    requested_product_id = _optional_id(source.get("product_id"))
    requested_brand_id = _optional_id(source.get("brand_id"))
    requested_article_id = _optional_id(source.get("article_id"))
    requested_colour_id = _optional_id(source.get("colour_id"))
    requested_size_id = _optional_id(source.get("size_id"))

    selected_product = next(
        (item for item in data["products"] if item["id"] == requested_product_id), None
    )
    product_id = selected_product["id"] if selected_product else None
    brands = [item for item in data["brands"] if item["product_id"] == product_id]
    selected_brand = next((item for item in brands if item["id"] == requested_brand_id), None)
    brand_id = selected_brand["id"] if selected_brand else None
    articles = [item for item in data["articles"] if item["brand_id"] == brand_id]
    selected_article = None
    if selected_product and selected_product["classification"] == "article_colour":
        selected_article = next(
            (item for item in articles if item["id"] == requested_article_id), None
        )
    article_id = selected_article["id"] if selected_article else None

    if selected_product and selected_product["classification"] == "article_colour":
        colours = [
            item for item in data["colours"]
            if selected_article and item["brand_id"] == brand_id and item["article_id"] == article_id
        ]
    else:
        colours = [
            item for item in data["colours"]
            if selected_brand and item["brand_id"] == brand_id and item["article_id"] is None
        ]
    selected_colour = next((item for item in colours if item["id"] == requested_colour_id), None)
    colour_id = selected_colour["id"] if selected_colour else None
    sizes = [item for item in data["sizes"] if item["colour_id"] == colour_id]
    selected_size = next((item for item in sizes if item["id"] == requested_size_id), None)
    size_id = selected_size["id"] if selected_size else None
    return {
        "catalogue": data,
        "product_id": product_id,
        "brand_id": brand_id,
        "article_id": article_id,
        "colour_id": colour_id,
        "size_id": size_id,
        "selected_product": selected_product,
        "selected_brand": selected_brand,
        "selected_article": selected_article,
        "selected_colour": selected_colour,
        "selected_size": selected_size,
        "brands": brands,
        "articles": articles,
        "colours": colours,
        "sizes": sizes,
    }


def _render_catalogue(source, *, error=None, delete_candidate=None, status=200):
    try:
        context = _selection(source)
    except DomainError as selection_error:
        context = _selection({})
        error = error or str(selection_error)
        status = 400
    context.update(
        error=error,
        notice=None if error else NOTICE_MESSAGES.get(request.args.get("notice")),
        form=source,
        delete_candidate=delete_candidate,
    )
    return render_template("catalogue.html", **context), status


def _report_boundary(day):
    local_midnight = datetime.combine(day, time.min, tzinfo=SHOP_TIMEZONE)
    utc_boundary = local_midnight.astimezone(timezone.utc)
    return (
        f"{utc_boundary.year:04d}-{utc_boundary.month:02d}-{utc_boundary.day:02d}"
        f"T{utc_boundary.hour:02d}:{utc_boundary.minute:02d}:{utc_boundary.second:02d}.000Z"
    )


def _report_local_times(report):
    for sale in report["sales"]:
        instant = datetime.fromisoformat(sale["created_at"].replace("Z", "+00:00"))
        sale["local_created_at"] = instant.astimezone(SHOP_TIMEZONE).strftime(
            "%d %b %Y, %I:%M %p"
        )
    return report


def _selected_day(value):
    if not value:
        return datetime.now(SHOP_TIMEZONE).date()
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise DomainError("Choose a valid daily report date.")
    try:
        selected = date.fromisoformat(value)
    except ValueError as error:
        raise DomainError("Choose a valid daily report date.") from error
    if not 2 <= selected.year <= 9998:
        raise DomainError("Choose a valid daily report date.")
    return selected


def _selected_month(value):
    if not value:
        today = datetime.now(SHOP_TIMEZONE).date()
        return today.year, today.month
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}", value):
        raise DomainError("Choose a valid report month and year.")
    year, month = (int(part) for part in value.split("-"))
    if not 2 <= year <= 9998 or not 1 <= month <= 12:
        raise DomainError("Choose a valid report month and year.")
    return year, month


def _render_stock(source, *, error=None, status=200):
    try:
        context = _selection(source)
    except DomainError as selection_error:
        context = _selection({})
        error = error or str(selection_error)
        status = 400
    request_key = source.get("request_key", "")
    if not request_key:
        request_key = uuid4().hex
    context.update(
        error=error,
        notice=None if error else NOTICE_MESSAGES.get(request.args.get("notice")),
        movement_id=request.args.get("movement_id"),
        saved_variant_id=request.args.get("saved_variant_id"),
        form=source,
        request_key=request_key,
    )
    return render_template("stock_entry.html", **context), status


def _choice_rows(rows):
    return [{"id": item["id"], "name": item["name"]} for item in rows]


def _complete_chain(context):
    product = context["selected_product"]
    if not product or not product["unit"] or not context["selected_brand"] or not context["selected_colour"]:
        return False
    if product["classification"] == "article_colour" and not context["selected_article"]:
        return False
    if product["classification"] == "colour_size" and not context["selected_size"]:
        return False
    return True


def _variant_from_context(context):
    if not _complete_chain(context):
        raise DomainError("Choose the complete Product hierarchy before adding an item.")
    return get_sale_variant(
        get_db(),
        product_id=context["product_id"],
        brand_id=context["brand_id"],
        article_id=context["article_id"],
        colour_id=context["colour_id"],
        size_id=context["size_id"],
    )


def _parse_bill_items(raw):
    if raw in (None, ""):
        return []
    if not isinstance(raw, str) or len(raw) > 30000:
        raise DomainError("The bill draft is too large or invalid. Start a new bill.")
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError) as error:
        raise DomainError("The bill draft could not be read. Start a new bill.") from error
    if not isinstance(payload, list) or len(payload) > 100:
        raise DomainError("A bill draft can contain no more than 100 items.")
    items = []
    for item in payload:
        if not isinstance(item, dict):
            raise DomainError("The bill draft contains an invalid item.")
        items.append(
            {
                "variant_id": item.get("variant_id"),
                "quantity": item.get("quantity"),
                "unit_price": item.get("unit_price"),
            }
        )
    return items


def _draft_from_quote(rows):
    return [
        {
            "variant_id": str(row["id"]),
            "quantity": format_quantity(row["quantity"]),
            "unit_price": row["unit_price"],
        }
        for row in rows
    ]


def _parse_tailoring_items(raw):
    if raw in (None, ""):
        return []
    if not isinstance(raw, str) or len(raw) > 30000:
        raise DomainError("The tailoring draft is too large or invalid. Start a new bill.")
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError) as error:
        raise DomainError("The tailoring draft could not be read. Start a new bill.") from error
    if not isinstance(payload, list) or len(payload) > 100:
        raise DomainError("A bill draft can contain no more than 100 tailoring items.")
    items = []
    for item in payload:
        if not isinstance(item, dict):
            raise DomainError("The tailoring draft contains an invalid item.")
        items.append({
            "garment_category": item.get("garment_category"),
            "custom_description": item.get("custom_description", ""),
            "quantity": item.get("quantity"),
            "stitching_rate": item.get("stitching_rate"),
            "cloth_source": item.get("cloth_source"),
            "source_product_line": item.get("source_product_line"),
            "source_sale_item_id": item.get("source_sale_item_id"),
            "measurement_revision_id": item.get("measurement_revision_id"),
            "promised_date": item.get("promised_date"),
            "tailor_id": item.get("tailor_id"),
        })
    return items


def _tailoring_draft_from_quote(rows, source_rows):
    return [
        {
            "garment_category": row["garment_category"],
            "custom_description": row["custom_description"],
            "quantity": format_quantity(row["quantity"]),
            "stitching_rate": (
                row["stitching_rate"]
                if row["garment_category"] == CUSTOM_GARMENT_CATEGORY else None
            ),
            "cloth_source": row["cloth_source"],
            "source_product_line": row["source_product_line"],
            "source_sale_item_id": row["source_sale_item_id"],
            "measurement_revision_id": row["measurement_revision_id"],
            "promised_date": source_rows[index].get("promised_date"),
            "tailor_id": row.get("tailor_id"),
        }
        for index, row in enumerate(rows)
    ]


def _billing_customer(source):
    customer_id = source.get("customer_id", "")
    if customer_id in (None, ""):
        return None
    return get_customer(get_db(), customer_id)


def _variant_description(item):
    parts = [item["product"], item["brand"]]
    if item.get("article"):
        parts.append(item["article"])
    parts.append(item["colour"])
    if item.get("size"):
        parts.append(item["size"])
    return " · ".join(parts)


def _cloth_choice(source):
    choice = source.get("cloth_choice", "")
    if choice:
        return choice
    legacy_source = source.get("cloth_source", "")
    if legacy_source == "customer":
        return "customer"
    if legacy_source == "shop":
        return source.get("cloth_link", "")
    return ""


def _current_fabric_lines(product_items):
    return [
        item for item in product_items
        if item.get("product_id") == FABRIC_PRODUCT_ID
    ]


def _resolve_tailoring_cloth(source, product_items, customer):
    fabric_lines = _current_fabric_lines(product_items)
    choice = _cloth_choice(source)
    if not choice and len(fabric_lines) == 1:
        choice = f"current:{fabric_lines[0]['line_number']}"
    elif not choice and not fabric_lines:
        choice = "customer"
    elif not choice:
        raise DomainError("Choose which Fabric from this bill is being used for this garment.")

    if choice == "customer":
        return "customer", None, None

    link_kind, separator, link_id = choice.partition(":")
    if not separator or not link_id.isascii() or not link_id.isdigit() or int(link_id) < 1:
        raise DomainError("Choose a valid cloth source for this garment.")
    link_id = int(link_id)
    if link_kind == "current":
        eligible_lines = {item["line_number"] for item in fabric_lines}
        if link_id not in eligible_lines:
            raise DomainError("Choose an existing Fabric line from this bill for the garment cloth.")
        return "shop", link_id, None
    if link_kind == "earlier":
        eligible = {
            item["id"] for item in list_customer_product_sale_items(
                get_db(), customer["id"]
            )
        }
        if link_id not in eligible:
            raise DomainError(
                "The selected earlier Fabric purchase is unavailable or does not belong to this customer."
            )
        return "shop", None, link_id
    raise DomainError("Choose a valid cloth source for this garment.")


def _tailoring_selection(source, customer):
    category = source.get("tailoring_category", next(iter(STANDARD_MEASUREMENT_TEMPLATES)))
    categories = tuple(STANDARD_MEASUREMENT_TEMPLATES) + (CUSTOM_GARMENT_CATEGORY,)
    if category not in categories:
        category = categories[0]
    custom_description = " ".join(source.get("tailoring_custom_description", "").split())
    rate = get_current_stitching_rates(get_db()).get(category)
    measurement = None
    if customer:
        revisions = get_measurement_revisions(get_db(), customer["id"], category)
        if category == CUSTOM_GARMENT_CATEGORY:
            measurement = next(
                (row for row in revisions if row["custom_description"] == custom_description), None
            )
        else:
            measurement = revisions[0] if revisions else None
    return {
        "categories": categories,
        "category": category,
        "custom_description": custom_description,
        "definition": STANDARD_MEASUREMENT_TEMPLATES.get(category),
        "rate": rate,
        "measurement": measurement,
    }


def _validated_promised_date(value):
    if not isinstance(value, str):
        raise DomainError("Choose a valid promised delivery date.")
    try:
        promised = date.fromisoformat(value)
    except ValueError as error:
        raise DomainError("Choose a valid promised delivery date.") from error
    today = datetime.now(SHOP_TIMEZONE).date()
    if promised < today:
        raise DomainError("The promised delivery date cannot be before the order date.")
    return promised.isoformat()


def _money_input(value):
    whole, paisa = divmod(value, 100)
    return f"{whole}.{paisa:02d}"


def _render_billing(
    source, *, draft=None, tailoring_draft=None, error=None, notice=None,
    feedback_target=None, product_confirmation=None, status=200,
):
    try:
        context = _selection(source)
    except DomainError as selection_error:
        context = _selection({})
        error = error or str(selection_error)
        status = 400

    try:
        draft = _parse_bill_items(source.get("bill_items")) if draft is None else draft
        quoted_items = quote_sale_items(get_db(), draft) if draft else []
        draft = _draft_from_quote(quoted_items)
    except DomainError as draft_error:
        draft = []
        quoted_items = []
        error = error or str(draft_error)
        status = 400

    try:
        customer = _billing_customer(source)
    except DomainError as customer_error:
        customer = None
        error = error or str(customer_error)
        status = 400

    try:
        tailoring_draft = (
            _parse_tailoring_items(source.get("tailoring_items"))
            if tailoring_draft is None else tailoring_draft
        )
        if tailoring_draft and customer is None:
            raise DomainError("Select the existing customer attached to the tailoring draft.")
        quoted_tailoring = (
            quote_tailoring_items(
                get_db(), customer["id"], tailoring_draft, quoted_items
            )
            if tailoring_draft else []
        )
        tailoring_draft = _tailoring_draft_from_quote(quoted_tailoring, tailoring_draft)
    except DomainError as tailoring_error:
        tailoring_draft = []
        quoted_tailoring = []
        error = error or str(tailoring_error)
        status = 400

    selected_variant = None
    variant_error = None
    if _complete_chain(context):
        try:
            selected_variant = _variant_from_context(context)
            selected_variant["is_fabric"] = (
                selected_variant["product_id"] == FABRIC_PRODUCT_ID
            )
        except DomainError as caught:
            variant_error = str(caught)

    earlier_sale_items = (
        list_customer_product_sale_items(get_db(), customer["id"]) if customer else []
    )
    earlier_by_id = {item["id"]: item for item in earlier_sale_items}
    for item in quoted_items:
        item["description"] = _variant_description(item)
        item["is_fabric"] = item["product_id"] == FABRIC_PRODUCT_ID
    current_fabric_lines = _current_fabric_lines(quoted_items)
    for index, item in enumerate(quoted_tailoring):
        item["promised_date"] = tailoring_draft[index]["promised_date"]
        if item["source_product_line"] is not None:
            product_index = item["source_product_line"] - 1
            item["cloth_link_label"] = (
                f"This bill: {_variant_description(quoted_items[product_index])}"
                if 0 <= product_index < len(quoted_items) else "Invalid current-bill product link"
            )
        elif item["source_sale_item_id"] is not None:
            earlier = earlier_by_id.get(item["source_sale_item_id"])
            item["cloth_link_label"] = (
                f"{earlier['bill_number']}: {_variant_description(earlier)}"
                if earlier else "Invalid earlier-bill product link"
            )
        else:
            item["cloth_link_label"] = "Customer-provided cloth"

    subtotal = sum(item["line_total"] for item in quoted_items + quoted_tailoring)
    discount_text = source.get("discount", "0.00") or "0.00"
    paid_marker = source.get("paid_was_edited")
    paid_was_supplied = (
        paid_marker == "true" if paid_marker in ("true", "false")
        else bool(source.get("paid_amount", "").strip())
    )
    try:
        preview_discount = parse_pkr(discount_text, "the bill discount")
        if preview_discount > subtotal:
            raise DomainError("The fixed bill discount cannot exceed the subtotal.")
    except DomainError:
        preview_discount = 0
    grand_total = subtotal - preview_discount
    paid_text = source.get("paid_amount", "") if paid_was_supplied else _money_input(grand_total)
    try:
        preview_paid = parse_pkr(paid_text or "0", "the paid amount")
        if preview_paid > grand_total:
            preview_paid = grand_total
    except DomainError:
        preview_paid = 0

    line_price = source.get("line_price", "")
    default_price = source.get("default_price", "")
    if selected_variant and not line_price and selected_variant["default_selling_price"] is not None:
        line_price = _money_input(selected_variant["default_selling_price"])
    if selected_variant and not default_price and selected_variant["default_selling_price"] is not None:
        default_price = _money_input(selected_variant["default_selling_price"])

    customer_query = source.get("customer_query", "")
    try:
        customer_matches = search_customers(get_db(), customer_query, limit=20) if customer_query else []
    except DomainError as search_error:
        customer_matches = []
        error = error or str(search_error)
        status = 400
    tailoring_selection = _tailoring_selection(source, customer)
    cloth_choice = _cloth_choice(source)
    if not cloth_choice and len(current_fabric_lines) == 1:
        cloth_choice = f"current:{current_fabric_lines[0]['line_number']}"
    elif not cloth_choice and not current_fabric_lines:
        cloth_choice = "customer"
    promised_date = source.get("promised_date", "")
    if tailoring_draft:
        promised_date = tailoring_draft[0]["promised_date"] or promised_date
    today = datetime.now(SHOP_TIMEZONE).date().isoformat()
    sale_mode = source.get("sale_mode", "")
    if sale_mode not in ("product", "combined", "tailoring"):
        if quoted_tailoring and quoted_items:
            sale_mode = "combined"
        elif quoted_tailoring:
            sale_mode = "tailoring"
        else:
            sale_mode = "product"

    context.update(
        error=error,
        notice=notice,
        form=source,
        request_key=source.get("request_key") or uuid4().hex,
        bill_items=json.dumps(draft, separators=(",", ":")),
        tailoring_items=json.dumps(tailoring_draft, separators=(",", ":")),
        quoted_items=quoted_items,
        quoted_tailoring=quoted_tailoring,
        customer=customer,
        customer_matches=customer_matches,
        customer_query=customer_query,
        earlier_sale_items=earlier_sale_items,
        current_fabric_lines=current_fabric_lines,
        cloth_choice=cloth_choice,
        tailoring_selection=tailoring_selection,
        promised_date=promised_date,
        order_notes=source.get("order_notes", ""),
        today=today,
        selected_variant=selected_variant,
        variant_error=variant_error,
        subtotal=subtotal,
        preview_discount=preview_discount,
        grand_total=grand_total,
        preview_paid=preview_paid,
        remaining_balance=grand_total - preview_paid,
        discount_text=discount_text,
        paid_text=paid_text,
        paid_was_supplied=paid_was_supplied,
        line_price=line_price,
        default_price=default_price,
        product_confirmation=product_confirmation,
        feedback_target=feedback_target,
        sale_mode=sale_mode,
        tailors=list_tailors(get_db(), active_only=True),
    )
    return render_template("billing.html", **context), status


@bp.get("/catalogue/children")
def catalogue_children():
    """Return only the choices owned by the submitted, canonical parent chain."""
    try:
        context = _selection(request.args)
    except DomainError as error:
        return jsonify(error=str(error)), 400
    product = context["selected_product"]
    return jsonify(
        product_id=context["product_id"],
        brand_id=context["brand_id"],
        article_id=context["article_id"],
        colour_id=context["colour_id"],
        size_id=context["size_id"],
        classification=product["classification"] if product else None,
        unit=product["unit"] if product else None,
        suggested_unit=product["suggested_unit"] if product else None,
        brands=_choice_rows(context["brands"]),
        articles=_choice_rows(context["articles"]),
        colours=_choice_rows(context["colours"]),
        sizes=_choice_rows(context["sizes"]),
    )


@bp.get("/billing/variant")
def billing_variant():
    """Return one canonical exact variant for the JavaScript billing enhancement."""
    try:
        context = _selection(request.args)
        variant = _variant_from_context(context)
    except DomainError as error:
        return jsonify(error=str(error)), 400
    description = [variant["product"], variant["brand"]]
    if variant["article"]:
        description.append(variant["article"])
    description.append(variant["colour"])
    if variant["size"]:
        description.append(variant["size"])
    return jsonify(
        id=variant["id"],
        product=variant["product"],
        product_id=variant["product_id"],
        is_fabric=variant["product_id"] == FABRIC_PRODUCT_ID,
        description=" · ".join(description),
        unit=variant["unit"],
        current_balance=variant["current_balance"],
        current_balance_display=format_quantity(variant["current_balance"]),
        default_selling_price=variant["default_selling_price"],
        default_selling_price_input=(
            _money_input(variant["default_selling_price"])
            if variant["default_selling_price"] is not None else ""
        ),
        default_selling_price_display=(
            format_pkr(variant["default_selling_price"])
            if variant["default_selling_price"] is not None else None
        ),
    )


@bp.get("/")
def index():
    error = None
    try:
        context = _selection(request.args)
        filters = {
            key: context[key]
            for key in ("product_id", "brand_id", "article_id", "colour_id", "size_id")
        }
        rows = list_stock(get_db(), filters)
    except DomainError as caught:
        context = _selection({})
        rows = list_stock(get_db())
        error = str(caught)
    product_brand_totals = {}
    for row in rows:
        key = (row["product_id"], row["brand_id"])
        total = product_brand_totals.setdefault(
            key,
            {
                "product": row["product"],
                "brand": row["brand"],
                "unit": row["unit"],
                "quantity": 0,
            },
        )
        total["quantity"] += row["quantity"]
    return render_template(
        "index.html",
        **context,
        form=request.args,
        rows=rows,
        product_brand_totals=list(product_brand_totals.values()),
        error=error,
    ), 400 if error else 200


@bp.get("/dashboard")
def dashboard():
    return render_template("dashboard.html")


@bp.route("/stock", methods=["GET", "POST"])
def stock():
    if request.method == "GET":
        return _render_stock(request.args)
    form = request.form
    try:
        result = receive_stock(
            get_db(),
            product_id=form.get("product_id"),
            brand_id=form.get("brand_id"),
            article_id=form.get("article_id"),
            colour_id=form.get("colour_id"),
            size_id=form.get("size_id"),
            quantity=form.get("quantity", ""),
            kind=form.get("kind", ""),
            note=form.get("note", ""),
            request_key=form.get("request_key", ""),
            user_id=g.user["id"],
        )
    except DomainError as error:
        return _render_stock(form, error=str(error), status=400)
    notice = "stock-replayed" if result["replayed"] else "stock-added"
    return redirect(
        url_for(
            "web.stock",
            product_id=form.get("product_id"),
            brand_id=form.get("brand_id"),
            article_id=form.get("article_id"),
            colour_id=form.get("colour_id"),
            size_id=form.get("size_id"),
            notice=notice,
            movement_id=result["movement_id"],
            saved_variant_id=result["variant_id"],
        ),
        code=303,
    )


@bp.post("/stock/catalogue")
def stock_catalogue():
    """Create one catalogue level without leaving the Add Stock workflow."""
    form = request.form
    kind = form.get("kind", "")
    selection = {
        key: form.get(key, "")
        for key in ("product_id", "brand_id", "article_id", "colour_id", "size_id")
    }
    try:
        if kind == "product":
            item_id = add_product(
                get_db(),
                form.get("name", ""),
                form.get("classification", ""),
                form.get("unit", ""),
            )
            selection = {"product_id": item_id}
        elif kind == "brand":
            item_id = add_brand(get_db(), form.get("name", ""), selection["product_id"])
            selection.update(
                brand_id=item_id, article_id="", colour_id="", size_id=""
            )
        elif kind == "article":
            item_id = add_article(get_db(), form.get("name", ""), selection["brand_id"])
            selection.update(article_id=item_id, colour_id="", size_id="")
        elif kind == "colour":
            item_id = add_colour(
                get_db(),
                form.get("name", ""),
                selection["brand_id"],
                selection["article_id"] or None,
            )
            selection.update(colour_id=item_id, size_id="")
        elif kind == "size":
            item_id = add_size(get_db(), form.get("name", ""), selection["colour_id"])
            selection.update(size_id=item_id)
        else:
            raise DomainError("Choose a valid catalogue level to add.")

        context = _selection(selection)
    except DomainError as caught:
        return jsonify(error=str(caught)), 400

    redirect_parameters = {
        key: context[key]
        for key in ("product_id", "brand_id", "article_id", "colour_id", "size_id")
        if context[key] is not None
    }
    return jsonify(
        item={"id": item_id, "kind": kind},
        redirect_url=url_for("web.stock", **redirect_parameters),
    ), 201


def _billing_customer_option(customer):
    return {
        "id": customer["id"],
        "customer_number": customer["customer_number"],
        "name": customer["name"],
        "primary_mobile": customer["primary_mobile"],
    }


@bp.route("/billing/customers", methods=["GET", "POST"])
def billing_customers():
    if request.method == "GET":
        query = request.args.get("q", "")
        if not query.strip():
            return jsonify(customers=[])
        try:
            rows = search_customers(get_db(), query, limit=8)
        except DomainError as caught:
            return jsonify(error=str(caught)), 400
        return jsonify(customers=[_billing_customer_option(row) for row in rows])

    form_values = _customer_values(request.form)
    try:
        saved = create_customer(get_db(), **form_values)
        customer = get_customer(get_db(), saved["customer_id"])
    except DomainError as caught:
        return jsonify(error=str(caught)), 400
    return jsonify(customer=_billing_customer_option(customer)), 201


@bp.post("/billing/tailors")
def billing_tailors():
    """Add a Tailor without leaving the current Billing draft."""
    try:
        tailor_id = create_tailor(
            get_db(), request.form.get("name", ""), request.form.get("mobile", "")
        )
        tailor = next(
            item for item in list_tailors(get_db()) if item["id"] == tailor_id
        )
    except DomainError as caught:
        return jsonify(error=str(caught)), 400
    return jsonify(tailor=tailor), 201


def _billing_feedback_target(action):
    if action.startswith("select_customer:") or action in {"search_customer", "clear_customer"}:
        return "customer"
    if action.startswith("remove_line:") or action.startswith("remove_tailoring:"):
        return "bill"
    if action in {"open_selection", "add_line", "save_default"}:
        return "product"
    if action in {"open_tailoring", "add_tailoring"}:
        return "tailoring"
    if action == "finalize":
        return "checkout"
    return None


@bp.route("/billing", methods=["GET", "POST"])
def billing():
    if request.method == "GET":
        return _render_billing(request.args)

    form = request.form
    draft = None
    tailoring_draft = None
    action = ""
    try:
        actions = form.getlist("action")
        if len(actions) != 1:
            raise DomainError("Submit exactly one Billing action and try again.")
        action = actions[0]
        simple_actions = {
            "open_selection", "open_tailoring", "search_customer", "clear_customer",
            "add_line", "save_default", "add_tailoring", "finalize",
        }
        indexed_action = re.fullmatch(
            r"(?:select_customer|remove_line|remove_tailoring):[0-9]+", action
        )
        if action not in simple_actions and indexed_action is None:
            raise DomainError("Choose a valid Billing action and try again.")
        draft = _parse_bill_items(form.get("bill_items"))
        tailoring_draft = _parse_tailoring_items(form.get("tailoring_items"))
        if action in ("open_selection", "open_tailoring", "search_customer"):
            return _render_billing(form, draft=draft, tailoring_draft=tailoring_draft)
        if action.startswith("select_customer:"):
            customer_id = action.partition(":")[2]
            selected = get_customer(get_db(), customer_id)
            prior_customer_id = form.get("customer_id", "")
            if tailoring_draft and str(selected["id"]) != str(prior_customer_id):
                raise DomainError(
                    "Remove all tailoring lines before changing the selected customer."
                )
            source = form.to_dict(flat=True)
            source["customer_id"] = str(selected["id"])
            source["customer_query"] = ""
            return _render_billing(
                source, draft=draft, tailoring_draft=tailoring_draft,
            )
        if action == "clear_customer":
            if tailoring_draft:
                raise DomainError("Remove all tailoring lines before clearing the selected customer.")
            source = form.to_dict(flat=True)
            source["customer_id"] = ""
            source["customer_query"] = ""
            return _render_billing(source, draft=draft, tailoring_draft=[])
        if action == "add_line":
            context = _selection(form)
            variant = _variant_from_context(context)
            price = parse_pkr(form.get("line_price", ""), "the unit selling price", MAX_UNIT_PRICE)
            prior_quoted = quote_sale_items(get_db(), draft) if draft else []
            candidate = draft + [
                {
                    "variant_id": variant["id"],
                    "quantity": form.get("line_quantity", ""),
                    "unit_price": price,
                }
            ]
            if len(candidate) + len(tailoring_draft) > 100:
                raise DomainError("A bill may contain up to 100 total product and tailoring items.")
            quoted = quote_sale_items(get_db(), candidate)
            source = form.to_dict(flat=True)
            source["line_quantity"] = ""
            if len(_current_fabric_lines(prior_quoted)) != len(_current_fabric_lines(quoted)):
                source["cloth_choice"] = ""
                source["cloth_source"] = ""
                source["cloth_link"] = ""
            added = quoted[-1]
            return _render_billing(
                source,
                draft=_draft_from_quote(quoted),
                tailoring_draft=tailoring_draft,
                product_confirmation={
                    "product": added["product"],
                    "description": _variant_description(added),
                    "quantity": added["quantity"],
                    "unit": added["unit"],
                },
            )
        if action.startswith("remove_line:"):
            index_text = action.partition(":")[2]
            if not index_text.isascii() or not index_text.isdigit():
                raise DomainError("Choose an existing bill line to remove.")
            index = int(index_text)
            if not 0 <= index < len(draft):
                raise DomainError("That bill line no longer exists.")
            line_number = index + 1
            linked_lines = [
                int(item["source_product_line"])
                for item in tailoring_draft
                if str(item.get("source_product_line") or "").isascii()
                and str(item.get("source_product_line") or "").isdigit()
            ]
            if line_number in linked_lines:
                raise DomainError(
                    "Remove the tailoring line linked to this product before removing the product line."
                )
            del draft[index]
            for item in tailoring_draft:
                source_line = item.get("source_product_line")
                if str(source_line or "").isascii() and str(source_line or "").isdigit():
                    source_line = int(source_line)
                    if source_line > line_number:
                        item["source_product_line"] = source_line - 1
            source = form.to_dict(flat=True)
            source["cloth_choice"] = ""
            source["cloth_source"] = ""
            source["cloth_link"] = ""
            return _render_billing(
                source, draft=draft, tailoring_draft=tailoring_draft,
                notice="Product item removed from the bill draft.",
                feedback_target="bill",
            )
        if action.startswith("remove_tailoring:"):
            index_text = action.partition(":")[2]
            if not index_text.isascii() or not index_text.isdigit():
                raise DomainError("Choose an existing tailoring line to remove.")
            index = int(index_text)
            if not 0 <= index < len(tailoring_draft):
                raise DomainError("That tailoring line no longer exists.")
            del tailoring_draft[index]
            return _render_billing(
                form, draft=draft, tailoring_draft=tailoring_draft,
                notice="Tailoring item removed from the bill draft.",
                feedback_target="bill",
            )
        if action == "save_default":
            context = _selection(form)
            variant = _variant_from_context(context)
            price = parse_pkr(
                form.get("default_price", ""), "the default selling price", MAX_UNIT_PRICE
            )
            set_default_selling_price(get_db(), variant["id"], price)
            source = form.to_dict(flat=True)
            source["line_price"] = _money_input(price)
            source["default_price"] = _money_input(price)
            return _render_billing(
                source,
                draft=draft,
                tailoring_draft=tailoring_draft,
                notice="Default selling price updated for this exact variant.",
                feedback_target="product",
            )
        if action == "add_tailoring":
            customer = _billing_customer(form)
            if customer is None:
                raise DomainError("Select an existing customer before adding tailoring.")
            selection = _tailoring_selection(form, customer)
            category = selection["category"]
            if form.get("tailoring_category") != category:
                raise DomainError("Choose one of the available tailoring garments.")
            if selection["measurement"] is None:
                raise DomainError(
                    "Save matching current measurements for this customer and garment before adding it."
                )
            if category in STANDARD_MEASUREMENT_TEMPLATES and selection["rate"] is None:
                raise DomainError(
                    f"Configure a default stitching rate for {category} before adding it."
                )
            if category in STANDARD_MEASUREMENT_TEMPLATES and form.get("tailoring_price", ""):
                raise DomainError("A standard garment's configured rate cannot be overridden per order.")
            tailoring_quantity = form.get("tailoring_quantity", "").strip()
            if (
                not re.fullmatch(r"[0-9]{1,12}", tailoring_quantity)
                or int(tailoring_quantity) < 1
            ):
                raise DomainError(
                    "Enter the tailoring quantity as a whole number greater than zero."
                )
            promised_date = _validated_promised_date(form.get("promised_date", ""))
            if tailoring_draft and any(
                item.get("promised_date") != promised_date for item in tailoring_draft
            ):
                raise DomainError(
                    "All items in one tailoring order share one promised date. Remove existing tailoring lines before changing it."
                )
            quoted_products = quote_sale_items(get_db(), draft) if draft else []
            cloth_source, source_product_line, source_sale_item_id = (
                _resolve_tailoring_cloth(form, quoted_products, customer)
            )
            stitching_rate = None
            if category == CUSTOM_GARMENT_CATEGORY:
                stitching_rate = parse_pkr(
                    form.get("tailoring_price", ""), "the custom stitching price", MAX_UNIT_PRICE
                )
            candidate = tailoring_draft + [{
                "garment_category": category,
                "custom_description": selection["custom_description"],
                "quantity": tailoring_quantity,
                "stitching_rate": stitching_rate,
                "cloth_source": cloth_source,
                "source_product_line": source_product_line,
                "source_sale_item_id": source_sale_item_id,
                "measurement_revision_id": selection["measurement"]["id"],
                "promised_date": promised_date,
                "tailor_id": form.get("tailor_id") or None,
            }]
            if len(draft) + len(candidate) > 100:
                raise DomainError("A bill may contain up to 100 total product and tailoring items.")
            quoted_tailoring = quote_tailoring_items(
                get_db(), customer["id"], candidate, quoted_products
            )
            source = form.to_dict(flat=True)
            source["tailoring_quantity"] = "1"
            source["tailoring_price"] = ""
            source["tailor_id"] = ""
            return _render_billing(
                source, draft=draft,
                tailoring_draft=_tailoring_draft_from_quote(quoted_tailoring, candidate),
                notice="Tailoring item added to the bill draft.",
                feedback_target="tailoring",
            )
        if action != "finalize":
            raise DomainError("Choose a valid billing action.")
        if not draft and not tailoring_draft:
            raise DomainError("Add at least one item before finalizing the bill.")

        quoted = quote_sale_items(get_db(), draft) if draft else []
        customer = _billing_customer(form)
        quoted_tailoring = (
            quote_tailoring_items(get_db(), customer["id"], tailoring_draft, quoted)
            if tailoring_draft and customer else []
        )
        if tailoring_draft and customer is None:
            raise DomainError("Select an existing customer before finalizing tailoring.")
        subtotal = sum(item["line_total"] for item in quoted + quoted_tailoring)
        discount = parse_pkr(form.get("discount", "0") or "0", "the bill discount")
        if discount > subtotal:
            raise DomainError("The fixed bill discount cannot exceed the subtotal.")
        grand_total = subtotal - discount
        paid_text = form.get("paid_amount", "").strip()
        paid_amount = grand_total if not paid_text else parse_pkr(paid_text, "the paid amount")
        promised_date = None
        if tailoring_draft:
            promised_date = _validated_promised_date(form.get("promised_date", ""))
            if any(item.get("promised_date") != promised_date for item in tailoring_draft):
                raise DomainError(
                    "The promised delivery date changed after a tailoring line was added. Remove and add the tailoring lines again."
                )
        result = finalize_combined_bill(
            get_db(),
            product_items=draft,
            tailoring_items=tailoring_draft,
            discount=discount,
            paid_amount=paid_amount,
            customer_id=customer["id"] if customer else None,
            order_date=datetime.now(SHOP_TIMEZONE).date().isoformat() if tailoring_draft else None,
            promised_date=promised_date,
            tailoring_notes=form.get("order_notes", ""),
            request_key=form.get("request_key", ""),
            user_id=g.user["id"],
        )
        return redirect(url_for("web.sale_detail", sale_id=result["sale_id"]), code=303)
    except DomainError as error:
        return _render_billing(
            form, draft=draft, tailoring_draft=tailoring_draft,
            error=str(error), feedback_target=_billing_feedback_target(action), status=400,
        )


@bp.route("/catalogue", methods=["GET", "POST"])
def catalogue_page():
    if request.method == "GET":
        return _render_catalogue(request.args)
    form = request.form
    action = form.get("action")
    product_id = form.get("product_id", "")
    brand_id = form.get("brand_id", "")
    article_id = form.get("article_id", "")
    colour_id = form.get("colour_id", "")
    size_id = form.get("size_id", "")
    anchor = "products-section"
    try:
        if action == "add_product":
            product_id = add_product(
                get_db(), form.get("name", ""), form.get("classification", ""), form.get("unit", "")
            )
            brand_id = ""
            article_id = ""
            colour_id = ""
            size_id = ""
            notice = "product-added"
            anchor = "product-editor"
        elif action == "confirm_unit":
            confirm_unit(get_db(), product_id, form.get("unit", ""))
            notice = "unit-confirmed"
            anchor = "product-editor"
        elif action == "add_brand":
            brand_id = add_brand(get_db(), form.get("name", ""), product_id)
            article_id = ""
            colour_id = ""
            size_id = ""
            notice = "label-added"
            anchor = "brand-editor"
        elif action == "add_article":
            article_id = add_article(get_db(), form.get("name", ""), brand_id)
            colour_id = ""
            size_id = ""
            notice = "label-added"
            anchor = "article-editor"
        elif action == "add_colour":
            colour_id = add_colour(
                get_db(), form.get("name", ""), brand_id, article_id or None
            )
            size_id = ""
            notice = "label-added"
            anchor = "colour-editor"
        elif action == "add_size":
            size_id = add_size(get_db(), form.get("name", ""), colour_id)
            notice = "label-added"
            anchor = "size-editor"
        elif action == "rename_label":
            kind = form.get("kind", "")
            rename_label(get_db(), kind, form.get("item_id"), form.get("name", ""))
            notice = "renamed"
            anchor = {
                "product": "products-section",
                "brand": "brands-section",
                "article": "articles-section",
                "colour": "colours-section",
                "size": "sizes-section",
            }.get(kind, "products-section")
        elif action == "request_delete":
            candidate = catalogue_deletion_candidate(
                get_db(), form.get("kind", ""), form.get("item_id")
            )
            return _render_catalogue(form, delete_candidate=candidate)
        elif action == "delete_label":
            if form.get("confirm_delete") != "yes":
                raise DomainError("Confirm permanent deletion before continuing.")
            kind = form.get("kind", "")
            item_id = form.get("item_id")
            delete_catalogue_item(get_db(), kind, item_id)
            notice = "deleted"
            anchor = {
                "product": "products-section",
                "brand": "brands-section",
                "article": "articles-section",
                "colour": "colours-section",
                "size": "sizes-section",
            }.get(kind, "products-section")
            if kind == "product" and str(product_id) == str(item_id):
                product_id = brand_id = article_id = colour_id = size_id = ""
            elif kind == "brand" and str(brand_id) == str(item_id):
                brand_id = article_id = colour_id = size_id = ""
            elif kind == "article" and str(article_id) == str(item_id):
                article_id = colour_id = size_id = ""
            elif kind == "colour" and str(colour_id) == str(item_id):
                colour_id = size_id = ""
            elif kind == "size" and str(size_id) == str(item_id):
                size_id = ""
        else:
            raise DomainError("Choose a valid catalogue action.")
    except DomainError as error:
        return _render_catalogue(form, error=str(error), status=400)
    return redirect(
        url_for(
            "web.catalogue_page",
            product_id=product_id,
            brand_id=brand_id,
            article_id=article_id,
            colour_id=colour_id,
            size_id=size_id,
            notice=notice,
            _anchor=anchor,
        ),
        code=303,
    )


def _customer_or_404(customer_id):
    try:
        return get_customer(get_db(), customer_id)
    except DomainError:
        abort(404, description="That customer does not exist.")


def _customer_values(source):
    return {
        key: source.get(key, "")
        for key in ("name", "primary_mobile", "alternate_mobile", "address", "notes")
    }


def _measurement_page(customer, category, *, form=None, error=None, notice=None, status=200):
    templates = {
        name: {"measurements": list(definition["measurements"]),
               "styles": list(definition["styles"])}
        for name, definition in STANDARD_MEASUREMENT_TEMPLATES.items()
    }
    revisions = get_measurement_revisions(get_db(), customer["id"], category)
    current = revisions[0] if revisions else None
    values = {}
    styles = {}
    custom_rows = []
    custom_description = ""
    notes = ""
    if current:
        values = {name: format_quantity(value) for name, value in current["measurements"].items()}
        styles = current["styles"]
        custom_rows = list(values.items())
        custom_description = current["custom_description"]
        notes = current["notes"]
    if form is not None:
        notes = form.get("notes", "")
        custom_description = form.get("custom_description", "")
        if category in templates:
            values = {
                label: form.get(f"measurement_{index}", "")
                for index, label in enumerate(templates[category]["measurements"])
            }
            styles = {
                label: form.get(f"style_{index}") == "true"
                for index, label in enumerate(templates[category]["styles"])
            }
        else:
            names = form.getlist("custom_name")
            amounts = form.getlist("custom_value")
            custom_rows = list(zip(names, amounts))
    if category == CUSTOM_GARMENT_CATEGORY and not custom_rows:
        custom_rows = [("", "")]
    return render_template(
        "measurements.html",
        customer=customer,
        templates=templates,
        custom_category=CUSTOM_GARMENT_CATEGORY,
        category=category,
        revisions=revisions,
        current=current,
        values=values,
        style_values=styles,
        custom_rows=custom_rows,
        custom_description=custom_description,
        notes=notes,
        error=error,
        notice=notice,
    ), status


@bp.route("/customers", methods=["GET", "POST"])
def customers():
    query = request.args.get("q", "") if request.method == "GET" else ""
    return_to = request.values.get("return_to", "")
    if return_to not in ("", "billing"):
        return_to = ""
    form_values = _customer_values(request.form) if request.method == "POST" else _customer_values({})
    error = None
    status = 200
    if request.method == "POST":
        try:
            saved = create_customer(get_db(), **form_values)
        except DomainError as caught:
            error = str(caught)
            status = 400
        else:
            if return_to == "billing":
                return redirect(
                    url_for("web.billing", customer_id=saved["customer_id"]), code=303
                )
            return redirect(
                url_for("web.customer_detail", customer_id=saved["customer_id"], notice="created"),
                code=303,
            )
    try:
        rows = search_customers(get_db(), query, limit=200)
    except DomainError as caught:
        rows = []
        error = str(caught)
        status = 400
    return render_template(
        "customers.html", customers=rows, search=query, form=form_values, error=error,
        return_to=return_to,
    ), status


@bp.get("/customers/<int:customer_id>")
def customer_detail(customer_id):
    customer = _customer_or_404(customer_id)
    account = get_customer_account(get_db(), customer_id)
    revisions = get_measurement_revisions(get_db(), customer_id)
    latest = {}
    for revision in revisions:
        latest.setdefault(revision["garment_category"], revision)
    return render_template(
        "customer_detail.html",
        customer=customer,
        account=account,
        latest_measurements=latest,
        tailoring_orders=list_tailoring_orders(
            get_db(), customer_id=customer_id, limit=20
        ),
        notice=CUSTOMER_NOTICES.get(request.args.get("notice")),
    )


@bp.get("/customer-balances")
def customer_balances():
    search = request.args.get("q", "")
    scope = request.args.get("scope", "outstanding")
    error = None
    status = 200
    if scope not in ("outstanding", "all"):
        error = "Choose outstanding balances or all customer accounts."
        scope = "outstanding"
        status = 400
    try:
        customers = list_customer_balances(
            get_db(), search=search, outstanding_only=scope == "outstanding", limit=200
        )
    except DomainError as caught:
        customers = []
        error = str(caught)
        status = 400
    return render_template(
        "customer_balances.html", customers=customers, search=search,
        scope=scope, error=error,
    ), status


@bp.route("/customers/<int:customer_id>/edit", methods=["GET", "POST"])
def customer_edit(customer_id):
    customer = _customer_or_404(customer_id)
    values = _customer_values(request.form if request.method == "POST" else customer)
    error = None
    status = 200
    if request.method == "POST":
        try:
            update_customer(get_db(), customer_id, **values)
        except DomainError as caught:
            error = str(caught)
            status = 400
        else:
            return redirect(
                url_for("web.customer_detail", customer_id=customer_id, notice="updated"), code=303
            )
    return render_template(
        "customer_edit.html", customer=customer, form=values, error=error
    ), status


@bp.route("/tailors", methods=["GET", "POST"])
def tailors():
    error = None
    status = 200
    if request.method == "POST":
        action = request.form.get("action", "add")
        try:
            if action == "add":
                create_tailor(
                    get_db(), request.form.get("name", ""), request.form.get("mobile", "")
                )
                notice = "Tailor added."
            elif action == "set_active":
                active_value = request.form.get("active")
                if active_value not in ("true", "false"):
                    raise DomainError("Choose whether the Tailor is active.")
                set_tailor_active(
                    get_db(), request.form.get("tailor_id"), active_value == "true"
                )
                notice = "Tailor availability updated."
            else:
                raise DomainError("Choose a valid Tailor action.")
        except DomainError as caught:
            error = str(caught)
            status = 400
        else:
            return redirect(url_for("web.tailors", notice=notice), code=303)
    return render_template(
        "tailors.html",
        tailors=list_tailors(get_db()),
        notice=request.args.get("notice"),
        error=error,
    ), status


@bp.get("/measurements")
def measurement_customers():
    query = request.args.get("q", "")
    try:
        rows = search_customers(get_db(), query, limit=200)
    except DomainError as caught:
        return render_template(
            "measurement_customers.html", customers=[], search=query, error=str(caught)
        ), 400
    return render_template(
        "measurement_customers.html", customers=rows, search=query, error=None
    )


@bp.route("/customers/<int:customer_id>/measurements", methods=["GET", "POST"])
def customer_measurements(customer_id):
    customer = _customer_or_404(customer_id)
    category = request.values.get("category", next(iter(STANDARD_MEASUREMENT_TEMPLATES)))
    wants_json = (
        request.method == "POST"
        and request.accept_mimetypes.best == "application/json"
    )
    valid_categories = set(STANDARD_MEASUREMENT_TEMPLATES) | {CUSTOM_GARMENT_CATEGORY}
    if category not in valid_categories:
        if wants_json:
            return jsonify(error="Choose one of the available measurement templates."), 400
        if request.method == "POST":
            return _measurement_page(
                customer, next(iter(STANDARD_MEASUREMENT_TEMPLATES)), form=request.form,
                error="Choose one of the available measurement templates.", status=400,
            )
        return _measurement_page(
            customer, next(iter(STANDARD_MEASUREMENT_TEMPLATES)),
            error="Choose one of the available measurement templates.", status=400,
        )
    if request.method == "GET":
        return _measurement_page(
            customer, category,
            notice=CUSTOMER_NOTICES.get(request.args.get("notice")),
        )
    try:
        if category in STANDARD_MEASUREMENT_TEMPLATES:
            definition = STANDARD_MEASUREMENT_TEMPLATES[category]
            expected_measurement_keys = {
                f"measurement_{index}" for index in range(len(definition["measurements"]))
            }
            submitted_measurement_keys = {
                key for key in request.form if key.startswith("measurement_")
            }
            if submitted_measurement_keys != expected_measurement_keys:
                raise DomainError(f"Enter exactly the confirmed numeric measurements for {category}.")
            expected_style_keys = {
                f"style_{index}" for index in range(len(definition["styles"]))
            }
            submitted_style_keys = {key for key in request.form if key.startswith("style_")}
            if not submitted_style_keys <= expected_style_keys:
                raise DomainError("The form contains an unknown style checkbox.")
            allowed_keys = {
                "csrf_token", "category", "notes"
            } | expected_measurement_keys | expected_style_keys
            if not set(request.form) <= allowed_keys:
                raise DomainError("The form contains an unknown measurement field.")
            measurements = {
                label: request.form.get(f"measurement_{index}", "")
                for index, label in enumerate(definition["measurements"])
            }
            if any(
                len(request.form.getlist(f"measurement_{index}")) != 1
                for index in range(len(definition["measurements"]))
            ):
                raise DomainError("Provide each numeric measurement exactly once.")
            styles = {}
            for index, label in enumerate(definition["styles"]):
                submitted = request.form.getlist(f"style_{index}")
                if submitted not in ([], ["true"]):
                    raise DomainError("Every style checkbox value must be true or false.")
                styles[label] = bool(submitted)
            custom_description = ""
        else:
            allowed_keys = {
                "csrf_token", "category", "custom_description", "custom_name",
                "custom_value", "notes",
            }
            if not set(request.form) <= allowed_keys:
                raise DomainError("The form contains an unknown custom measurement field.")
            names = request.form.getlist("custom_name")
            amounts = request.form.getlist("custom_value")
            if not 1 <= len(names) <= 10 or len(names) != len(amounts):
                raise DomainError("Enter between 1 and 10 complete custom measurement rows.")
            if any(not name.strip() or not amount.strip() for name, amount in zip(names, amounts)):
                raise DomainError("Complete or remove every custom measurement row.")
            normalized_names = [" ".join(name.split()).casefold() for name in names]
            if len(set(normalized_names)) != len(normalized_names):
                raise DomainError("Each custom measurement name must be unique.")
            if len(request.form.getlist("custom_description")) != 1:
                raise DomainError("Describe the custom item exactly once.")
            measurements = dict(zip(names, amounts))
            styles = None
            custom_description = request.form.get("custom_description", "")
        saved = save_measurements(
            get_db(), customer_id=customer_id, garment_category=category,
            measurements=measurements, styles=styles,
            custom_description=custom_description, notes=request.form.get("notes", ""),
        )
    except DomainError as caught:
        if wants_json:
            return jsonify(error=str(caught)), 400
        return _measurement_page(
            customer, category, form=request.form, error=str(caught), status=400
        )
    if wants_json:
        return jsonify(
            category=category,
            revision_id=saved["revision_id"],
            revision_number=saved["revision_number"],
        ), 201
    return redirect(
        url_for(
            "web.customer_measurements", customer_id=customer_id, category=category,
            notice="measurement-saved", _anchor=f"revision-{saved['revision_id']}",
        ),
        code=303,
    )


@bp.get("/customers/<int:customer_id>/measurements/<int:revision_id>")
def measurement_revision(customer_id, revision_id):
    customer = _customer_or_404(customer_id)
    revision = next(
        (item for item in get_measurement_revisions(get_db(), customer_id)
         if item["id"] == revision_id),
        None,
    )
    if revision is None:
        abort(404, description="That measurement revision does not belong to this customer.")
    return render_template("measurement_revision.html", customer=customer, revision=revision)


@bp.route("/stitching-rates", methods=["GET", "POST"])
def stitching_rates():
    error = None
    status = 200
    entered_category = request.form.get("category", "")
    entered_rate = request.form.get("rate", "")
    if request.method == "POST":
        try:
            rate = parse_pkr(entered_rate, "the default stitching rate", MAX_UNIT_PRICE)
            configure_stitching_rate(get_db(), entered_category, rate, g.user["id"])
        except DomainError as caught:
            error = str(caught)
            status = 400
        else:
            return redirect(
                url_for("web.stitching_rates", notice="rate-saved", _anchor="rate-history"),
                code=303,
            )
    current = get_current_stitching_rates(get_db())
    histories = {
        category: get_stitching_rate_history(get_db(), category)
        for category in STANDARD_MEASUREMENT_TEMPLATES
    }
    return render_template(
        "stitching_rates.html",
        categories=list(STANDARD_MEASUREMENT_TEMPLATES), current=current, histories=histories,
        error=error, notice=CUSTOMER_NOTICES.get(request.args.get("notice")),
        entered_category=entered_category, entered_rate=entered_rate,
    ), status


@bp.get("/tailoring")
def tailoring_orders():
    search = request.args.get("q", "")
    selected_status = request.args.get("status", "")
    error = None
    status_code = 200
    try:
        rows = list_tailoring_orders(
            get_db(), search=search, status=selected_status, limit=200
        )
    except DomainError as caught:
        rows = list_tailoring_orders(get_db(), limit=200)
        error = str(caught)
        selected_status = ""
        status_code = 400
    return render_template(
        "tailoring_orders.html", orders=rows, search=search,
        selected_status=selected_status, statuses=TAILORING_STATUSES, error=error,
    ), status_code


def _render_tailoring_order_detail(tailoring_order_id, *, error=None, status=200):
    try:
        order = get_tailoring_order(get_db(), tailoring_order_id)
    except DomainError:
        abort(404, description="That finalized tailoring order does not exist.")
    notice = (
        "Tailor assignment updated."
        if request.args.get("notice") == "tailor-updated" else None
    )
    return render_template(
        "tailoring_order_detail.html",
        order=order,
        tailors=list_tailors(get_db(), active_only=True),
        notice=notice,
        error=error,
    ), status


@bp.get("/tailoring/<int:tailoring_order_id>")
def tailoring_order_detail(tailoring_order_id):
    return _render_tailoring_order_detail(tailoring_order_id)


@bp.post("/tailoring/<int:tailoring_order_id>/items/<int:tailoring_item_id>/tailor")
def tailoring_item_tailor(tailoring_order_id, tailoring_item_id):
    try:
        assign_tailor(
            get_db(),
            tailoring_order_id,
            tailoring_item_id,
            request.form.get("tailor_id") or None,
            g.user["id"],
        )
    except DomainError as caught:
        return _render_tailoring_order_detail(
            tailoring_order_id, error=str(caught), status=400
        )
    return redirect(
        url_for(
            "web.tailoring_order_detail",
            tailoring_order_id=tailoring_order_id,
            notice="tailor-updated",
            _anchor=f"garment-{tailoring_item_id}",
        ),
        code=303,
    )


@bp.get("/history")
def history():
    try:
        variant_id = _optional_id(request.args.get("variant_id"))
        movements = list_movements(get_db(), variant_id=variant_id, limit=200)
    except DomainError as error:
        movements = list_movements(get_db(), limit=200)
        variant_id = None
        return render_template("history.html", movements=movements, variant_id=variant_id, error=str(error)), 400
    return render_template("history.html", movements=movements, variant_id=variant_id, error=None)


@bp.get("/sales")
def sales_history():
    search = request.args.get("q", "")
    try:
        sales = list_sales(get_db(), search=search, limit=200)
    except DomainError as error:
        return render_template("sales_history.html", sales=[], search=search, error=str(error)), 400
    return render_template("sales_history.html", sales=sales, search=search, error=None)


@bp.get("/sales/daily")
def daily_sales():
    error = None
    status = 200
    try:
        selected = _selected_day(request.args.get("date", ""))
    except DomainError as caught:
        selected = datetime.now(SHOP_TIMEZONE).date()
        error = str(caught)
        status = 400
    report = _report_local_times(sales_report(
        get_db(), _report_boundary(selected), _report_boundary(selected + timedelta(days=1))
    ))
    return render_template(
        "sales_report.html",
        mode="daily",
        selected_value=selected.isoformat(),
        heading="Daily sales",
        period_label=selected.strftime("%d %B %Y"),
        report=report,
        error=error,
    ), status


@bp.get("/sales/monthly")
def monthly_sales():
    error = None
    status = 200
    try:
        year, month = _selected_month(request.args.get("month", ""))
    except DomainError as caught:
        today = datetime.now(SHOP_TIMEZONE).date()
        year, month = today.year, today.month
        error = str(caught)
        status = 400
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    report = _report_local_times(
        sales_report(get_db(), _report_boundary(start), _report_boundary(end))
    )
    return render_template(
        "sales_report.html",
        mode="monthly",
        selected_value=f"{year:04d}-{month:02d}",
        heading="Monthly sales",
        period_label=start.strftime("%B %Y"),
        report=report,
        error=error,
    ), status


@bp.get("/sales/<int:sale_id>")
def sale_detail(sale_id):
    try:
        sale = get_sale(get_db(), sale_id)
    except DomainError:
        abort(404, description="That finalized bill does not exist.")
    return render_template("sale_detail.html", sale=sale)


@bp.route(
    "/customers/<int:customer_id>/bills/<int:sale_id>/payments/new",
    methods=["GET", "POST"],
)
def payment_new(customer_id, sale_id):
    customer = _customer_or_404(customer_id)
    try:
        sale = get_sale(get_db(), sale_id)
    except DomainError:
        abort(404, description="That finalized bill does not exist.")
    amount_text = request.form.get("amount", "") if request.method == "POST" else ""
    request_key = request.form.get("request_key", "") or uuid4().hex
    if sale["customer_id"] != customer_id:
        message = "The payment must identify a bill attached to this customer."
        if request.method == "GET":
            abort(404, description=message)
        return render_template(
            "payment_form.html", customer=customer, bill=None, amount_text=amount_text,
            request_key=request_key, error=message,
        ), 400
    if request.method == "POST":
        try:
            amount = parse_pkr(amount_text, "the payment amount")
            if amount == 0:
                raise DomainError("The payment amount must be greater than zero.")
            payment = record_payment(
                get_db(), sale_id=sale_id, customer_id=customer_id, amount=amount,
                request_key=request_key, user_id=g.user["id"],
            )
        except DomainError as caught:
            message = str(caught)
            if sale["outstanding_balance"] == 0 and "exceed" in message:
                message = "This bill is already fully paid and cannot accept another payment."
            return render_template(
                "payment_form.html", customer=customer, bill=sale,
                amount_text=amount_text, request_key=request_key, error=message,
            ), 400
        return redirect(
            url_for("web.payment_receipt", payment_id=payment["id"]), code=303
        )
    return render_template(
        "payment_form.html", customer=customer, bill=sale, amount_text=amount_text,
        request_key=request_key, error=None,
    )


@bp.get("/payments/<int:payment_id>")
def payment_receipt(payment_id):
    try:
        payment = get_payment(get_db(), payment_id)
    except DomainError:
        abort(404, description="That finalized payment does not exist.")
    return render_template("payment_receipt.html", payment=payment)
