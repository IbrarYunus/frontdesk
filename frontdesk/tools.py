"""The agent's tools. Every rule about money, ownership and timing is checked here, not in the prompt."""

import json
import math
import re
from dataclasses import dataclass
from datetime import date

from . import config

REASONS = ["changed_mind", "damaged", "wrong_item"]


def _tool(name: str, description: str, properties: dict) -> dict:
    return {
        "name": name,
        "description": description,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
    }


ORDER_ID = {"type": "string", "description": "Order number, for example HO-1001"}

TOOLS = [
    _tool("list_orders", "List the signed-in customer's orders with status and items. Call this first when the customer has not given an order number.", {}),
    _tool("get_order", "Get one order: status, dates, address, tracking, items, and any refunds already paid.", {"order_id": ORDER_ID}),
    _tool(
        "search_policy",
        "Search the shop's written policies (returns, refunds, shipping, cancellations, warranty, escalation). Call this before stating any rule to the customer.",
        {"query": {"type": "string", "description": "What you need to know, in plain words"}},
    ),
    _tool(
        "cancel_order",
        "Cancel an order. Only works while the order is still processing.",
        {"order_id": ORDER_ID},
    ),
    _tool(
        "update_shipping_address",
        "Change where an order will be delivered. Only works while the order is still processing.",
        {"order_id": ORDER_ID, "new_address": {"type": "string", "description": "Full postal address"}},
    ),
    _tool(
        "issue_refund",
        "Refund specific items on a delivered order. You choose the items and the reason; the system works out the amount and checks the policy. "
        "Refunds above the approval limit pause until a supervisor decides, and the result tells you what they decided.",
        {
            "order_id": ORDER_ID,
            "skus": {"type": "array", "items": {"type": "string"}, "description": "SKUs of the items to refund"},
            "reason": {"type": "string", "enum": REASONS},
        },
    ),
    _tool(
        "escalate_to_human",
        "Hand the conversation to a human supervisor. Use for injuries, legal threats, chargebacks, lost parcels, warranty repairs, or a customer who will not accept a policy answer.",
        {
            "priority": {"type": "string", "enum": ["normal", "high", "urgent"]},
            "summary": {"type": "string", "description": "What the supervisor needs to know, including the order number"},
        },
    ),
]

WRITE_TOOLS = {"cancel_order", "update_shipping_address", "issue_refund", "escalate_to_human"}


@dataclass
class Outcome:
    status: str  # ok | refused | needs_approval
    content: dict | list | str

    @property
    def text(self) -> str:
        return self.content if isinstance(self.content, str) else json.dumps(self.content)


def _refuse(rule: str) -> Outcome:
    return Outcome("refused", rule)


def _own_order(db, customer_id: str, order_id: str):
    row = db.execute("SELECT * FROM orders WHERE id = ?", (order_id.strip().upper(),)).fetchone()
    # Same message for "missing" and "someone else's", so order numbers cannot be probed.
    if row is None or row["customer_id"] != customer_id:
        return None
    return row


def _order_view(db, order) -> dict:
    items = db.execute("SELECT sku, name, price, final_sale FROM order_items WHERE order_id = ?", (order["id"],)).fetchall()
    refunds = db.execute("SELECT sku, amount, reason FROM refunds WHERE order_id = ?", (order["id"],)).fetchall()
    view = {key: order[key] for key in ("id", "status", "placed_on", "shipped_on", "delivered_on", "shipping_address", "tracking")}
    view["currency"] = "GBP"
    view["today"] = config.TODAY.isoformat()
    if order["delivered_on"]:
        view["days_since_delivery"] = (config.TODAY - date.fromisoformat(order["delivered_on"])).days
    view["items"] = [{**dict(item), "final_sale": bool(item["final_sale"])} for item in items]
    view["refunds_already_paid"] = [dict(refund) for refund in refunds]
    return view


NOT_FOUND = "No order with that number on this customer's account."


def list_orders(db, customer_id: str) -> Outcome:
    orders = db.execute("SELECT * FROM orders WHERE customer_id = ? ORDER BY placed_on DESC", (customer_id,)).fetchall()
    return Outcome("ok", [_order_view(db, order) for order in orders])


def get_order(db, customer_id: str, order_id: str) -> Outcome:
    order = _own_order(db, customer_id, order_id)
    return Outcome("ok", _order_view(db, order)) if order else _refuse(NOT_FOUND)


def cancel_order(db, customer_id: str, order_id: str) -> Outcome:
    order = _own_order(db, customer_id, order_id)
    if not order:
        return _refuse(NOT_FOUND)
    if order["status"] != "processing":
        return _refuse(f"Order is {order['status']}. Only processing orders can be cancelled.")
    db.execute("UPDATE orders SET status = 'cancelled' WHERE id = ?", (order["id"],))
    return Outcome("ok", {"order_id": order["id"], "status": "cancelled", "note": "Payment is returned in full automatically."})


def update_shipping_address(db, customer_id: str, order_id: str, new_address: str) -> Outcome:
    order = _own_order(db, customer_id, order_id)
    if not order:
        return _refuse(NOT_FOUND)
    if order["status"] != "processing":
        return _refuse(f"Order is {order['status']}. The address can only change while an order is processing.")
    if len(new_address.strip()) < 10:
        return _refuse("That does not look like a full postal address.")
    db.execute("UPDATE orders SET shipping_address = ? WHERE id = ?", (new_address.strip(), order["id"]))
    return Outcome("ok", {"order_id": order["id"], "shipping_address": new_address.strip()})


def issue_refund(db, customer_id: str, order_id: str, skus: list[str], reason: str, approved_by: str | None = None) -> Outcome:
    order = _own_order(db, customer_id, order_id)
    if not order:
        return _refuse(NOT_FOUND)
    if order["status"] != "delivered":
        return _refuse(f"Order is {order['status']}. Only delivered orders can be refunded here; cancel it or escalate instead.")
    if reason not in REASONS or not skus:
        return _refuse("Give at least one SKU and a valid reason.")

    days = (config.TODAY - date.fromisoformat(order["delivered_on"])).days
    limit = config.CHANGE_OF_MIND_DAYS if reason == "changed_mind" else config.DAMAGED_DAYS
    if days > limit:
        return _refuse(f"Delivered {days} days ago. The window for a {reason} refund is {limit} days.")

    items = {row["sku"]: row for row in db.execute("SELECT * FROM order_items WHERE order_id = ?", (order["id"],))}
    refunded = {row["sku"] for row in db.execute("SELECT sku FROM refunds WHERE order_id = ?", (order["id"],))}
    for sku in set(skus):
        if sku not in items:
            return _refuse(f"{sku} is not on order {order['id']}.")
        if sku in refunded:
            return _refuse(f"{sku} was already refunded. An item can be refunded once.")
        if items[sku]["final_sale"] and reason == "changed_mind":
            return _refuse(f"{items[sku]['name']} is final sale and cannot be refunded for change of mind.")

    amount = round(sum(items[sku]["price"] for sku in set(skus)), 2)
    if amount > config.APPROVAL_THRESHOLD and not approved_by:
        return Outcome("needs_approval", {
            "order_id": order["id"], "skus": sorted(set(skus)), "reason": reason, "amount": amount,
            "items": [items[sku]["name"] for sku in sorted(set(skus))], "days_since_delivery": days,
        })

    for sku in set(skus):
        db.execute(
            "INSERT INTO refunds (order_id, sku, amount, reason, approved_by) VALUES (?,?,?,?,?)",
            (order["id"], sku, items[sku]["price"], reason, approved_by or "auto"),
        )
    return Outcome("ok", {"order_id": order["id"], "refunded": amount, "approved_by": approved_by or "auto", "arrives_in": "5 to 7 business days"})


def escalate_to_human(db, customer_id: str, priority: str, summary: str) -> Outcome:
    cursor = db.execute("INSERT INTO escalations (customer_id, priority, summary) VALUES (?,?,?)", (customer_id, priority, summary))
    return Outcome("ok", {"ticket": cursor.lastrowid, "priority": priority, "response_time": "within one business day"})


# --- policy search -------------------------------------------------------

_WORD = re.compile(r"[a-z]+")


def _sections() -> list[dict]:
    sections = []
    for path in sorted((config.ROOT / "policies").glob("*.md")):
        title, heading, lines = path.stem, "", []
        for line in path.read_text().splitlines() + ["## "]:
            if line.startswith("# "):
                title = line[2:].strip()
            elif line.startswith("## "):
                if lines and "".join(lines).strip():
                    sections.append({"policy": title, "section": heading, "text": "\n".join(lines).strip()})
                heading, lines = line[3:].strip(), []
            else:
                lines.append(line)
    return sections


def _stems(text: str) -> set[str]:
    # Six-letter prefixes are a crude stemmer: "returned" and "returns" both match "return".
    return {word[:6] for word in _WORD.findall(text.lower())}


def search_policy(query: str, k: int = 3) -> Outcome:
    sections = _sections()
    docs = [_stems(f"{s['policy']} {s['section']} {s['text']}") for s in sections]
    scored = []
    for section, doc in zip(sections, docs):
        score = sum(math.log(len(docs) / sum(term in d for d in docs)) for term in _stems(query) & doc)
        if score > 0:
            scored.append((score, section))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return Outcome("ok", [section for _, section in scored[:k]] or "No policy section matches. Escalate rather than guess.")


def execute(db, customer_id: str, name: str, tool_input: dict, approved_by: str | None = None) -> Outcome:
    if name == "list_orders":
        return list_orders(db, customer_id)
    if name == "get_order":
        return get_order(db, customer_id, **tool_input)
    if name == "search_policy":
        return search_policy(**tool_input)
    if name == "cancel_order":
        return cancel_order(db, customer_id, **tool_input)
    if name == "update_shipping_address":
        return update_shipping_address(db, customer_id, **tool_input)
    if name == "issue_refund":
        return issue_refund(db, customer_id, approved_by=approved_by, **tool_input)
    if name == "escalate_to_human":
        return escalate_to_human(db, customer_id, **tool_input)
    return _refuse(f"Unknown tool {name}.")
