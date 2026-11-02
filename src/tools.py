"""Deterministic tools the LLM can call. All prices/stock/status come from here, never from the model."""
import json
import re
import unicodedata
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import pandas as pd

DATA = Path(__file__).resolve().parent.parent / "data"

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]", " ", s)

products = pd.read_csv(DATA / "products.csv")
categories = pd.read_csv(DATA / "categories.csv")
promotions = pd.read_csv(DATA / "promotions.csv")
orders = pd.read_csv(DATA / "orders.csv", dtype={"tracking_code": str})
order_items = pd.read_csv(DATA / "order_items.csv")
customers = pd.read_csv(DATA / "customers.csv")
products = products.merge(categories[["category_id", "name"]].rename(columns={"name": "category"}), on="category_id")
active_promos = promotions[promotions.is_active == 1].drop_duplicates("product_id")[["product_id", "discount_percent", "description"]]
products = products.merge(active_promos, on="product_id", how="left")
products["_search"] = (products["name"] + " " + products["category"] + " " + products["description_x"]).map(_norm)

# Policy manual split into numbered sections ("4.1 Direito de Arrependimento ...") for simple retrieval.
_policy_text = (DATA / "policies.txt").read_text(encoding="utf-8")
POLICY_SECTIONS = [s.strip() for s in re.split(r"\n(?=\d+(?:\.\d+)?\.? [A-ZÁÉÍÓÚÂÊÔÃÕÇ])", _policy_text) if s.strip()]

def _product_view(r) -> dict:
    d = {"product_id": int(r.product_id), "name": r["name"], "category": r.category,
         "price_brl": float(r.price_brl),
         "in_stock": int(r.stock_quantity) > 0 and r.status == "active",
         "stock_quantity": int(r.stock_quantity), "status": r.status,
         "description": r["description_x"], "specs": json.loads(r.specs)}
    if pd.notna(r.discount_percent):
        d["promotion"] = {"name": r["description_y"],
                          "discount_percent": int(r.discount_percent),
                          "promo_price_brl": _sale_price(r.price_brl, r.discount_percent)}
    return d


def _sale_price(price, discount) -> float:
    return float((Decimal(str(price)) * (1 - Decimal(str(discount)) / 100))
                 .quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def search_products(query: str = "", category: str = "", max_price: float | None = None,
                    min_price: float | None = None, only_available: bool = False, limit: int = 10) -> str:
    """Search the catalog by keywords/category/price range."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise ValueError("limit must be an integer between 1 and 50")
    if min_price is not None and max_price is not None and min_price > max_price:
        raise ValueError("min_price must not exceed max_price")
    df = products
    for tok in _norm(query).split():
        df = df[df._search.str.contains(rf"\b{re.escape(tok)}", regex=True)]
    if category:
        for tok in _norm(category).split():
            df = df[df.category.map(_norm).str.contains(rf"\b{re.escape(tok)}", regex=True)]
    # Budget searches use the current sale price; PIX is a separate payment rule.
    prices = df.apply(lambda r: _sale_price(r.price_brl, r.discount_percent)
                      if pd.notna(r.discount_percent) else float(r.price_brl), axis=1)
    if max_price is not None:
        df = df[prices <= max_price]
    if min_price is not None:
        df = df[prices.loc[df.index] >= min_price]
    if only_available:
        df = df[(df.stock_quantity > 0) & (df.status == "active")]
    df = df.loc[prices.loc[df.index].sort_values().index]
    return json.dumps({"count": len(df), "results": [_product_view(r) for _, r in df.head(limit).iterrows()]}, ensure_ascii=False)

def get_order_status(order_id: int, customer_email_or_phone: str) -> str:
    """Order status. Requires the customer's email or phone (LGPD: don't leak orders to strangers)."""
    o = orders[orders.order_id == int(order_id)]
    failure = {"error": "identity check failed: order/email/phone does not match"}
    if o.empty:
        return json.dumps(failure)
    o = o.iloc[0]
    c = customers[customers.customer_id == o.customer_id].iloc[0]
    given = customer_email_or_phone.strip().casefold()
    digits = re.sub(r"\D", "", customer_email_or_phone)
    phone_matches = (re.fullmatch(r"[+\d\s().-]+", given) is not None
                     and bool(digits) and digits == re.sub(r"\D", "", c.phone))
    if not (given == c.email.strip().casefold() or phone_matches):
        return json.dumps(failure)
    items = order_items[order_items.order_id == o.order_id].merge(products[["product_id", "name"]], on="product_id")
    res = {k: (None if pd.isna(v) else v) for k, v in o.drop("customer_id").to_dict().items()}
    res["customer_first_name"] = c["name"].split()[0]
    res["items"] = items[["name", "quantity"]].to_dict("records")
    return json.dumps(res, ensure_ascii=False, default=str)

def search_policies(query: str, k: int = 3) -> str:
    """Keyword-overlap retrieval over the policy manual sections (small doc -> no vector DB needed)."""
    if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= 10:
        raise ValueError("k must be an integer between 1 and 10")
    stopwords = {"para", "como", "qual", "quais", "uma", "com", "por", "que", "dos", "das"}
    q = {w for w in _norm(query).split() if len(w) > 2} - stopwords
    scored = [(len(q & set(_norm(s).split())), s) for s in POLICY_SECTIONS]
    scored.sort(key=lambda pair: -pair[0])
    return json.dumps({"sections": [s for score, s in scored if score > 0][:k]}, ensure_ascii=False)

def get_today() -> str:
    return date.today().isoformat()

TOOLS = {"search_products": search_products, "get_order_status": get_order_status,
         "search_policies": search_policies, "get_today": get_today}

TOOL_SCHEMAS = [
    {"type": "function", "function": {"name": "search_products",
        "description": "Search the store catalog (price, stock, status, active promotion). Use for ANY question about products, prices or availability.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "keywords, e.g. 'Takamine GD20' or 'nylon'. Empty for all."},
            "category": {"type": "string", "description": "Guitarras, Baixos, Baterias, Teclados, Violões, Sopro, Cordas Orquestrais, Ukuleles"},
            "max_price": {"type": "number"}, "min_price": {"type": "number"},
            "only_available": {"type": "boolean"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50}}}}},
    {"type": "function", "function": {"name": "get_order_status",
        "description": "Get status, tracking code and items of an order. Ask the customer for order number AND email or phone first.",
        "parameters": {"type": "object", "properties": {"order_id": {"type": "integer"},
            "customer_email_or_phone": {"type": "string"}}, "required": ["order_id", "customer_email_or_phone"]}}},
    {"type": "function", "function": {"name": "search_policies",
        "description": "Search the store policy manual: opening hours, address, payment/installments, returns, exchanges, shipping, promotions, warranty, privacy.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"},
            "k": {"type": "integer", "minimum": 1, "maximum": 10}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "get_today", "description": "Today's date (ISO), for deadlines like the 7-day return window.",
        "parameters": {"type": "object", "properties": {}}}},
]
