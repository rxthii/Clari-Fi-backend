import re

RULES = {
    "Dining": ("restaurant", "cafe", "coffee", "food", "swiggy", "zomato", "dining", "bakery", "tokai"),
    "Groceries": ("grocery", "groceries", "supermarket", "market", "fresh", "mart", "bigbasket"),
    "Transport": ("uber", "ola", "taxi", "metro", "fuel", "petrol", "bus", "train", "transport"),
    "Shopping": ("amazon", "flipkart", "shopping", "mall", "store", "retail"),
    "Bills & Utilities": ("electric", "water", "internet", "utility", "bill", "mobile", "recharge", "gas"),
    "Health": ("pharmacy", "hospital", "clinic", "medical", "health"),
    "Income": ("salary", "payroll", "interest", "refund", "deposit"),
}

ICONS = {"Dining": "restaurant", "Groceries": "shopping_basket", "Transport": "directions_car", "Shopping": "shopping_bag", "Bills & Utilities": "receipt", "Health": "health_and_safety", "Income": "payments", "Other": "payments"}


def categorize(description: str, counterparty: str = "") -> str:
    text = re.sub(r"[^a-z0-9 ]", " ", f"{description} {counterparty}".lower())
    for category, keywords in RULES.items():
        if any(word in text for word in keywords): return category
    return "Other"


def untrusted_text(value: str, limit: int = 300) -> str:
    return "".join(c for c in str(value) if c.isprintable() and c not in "\x00\x1b")[:limit]

