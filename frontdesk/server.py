import json

import anthropic
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import agent, config, db, demo

app = FastAPI(title="frontdesk")
db.ensure()


class NewSession(BaseModel):
    customer_id: str


class Chat(BaseModel):
    session_id: str
    message: str = Field(min_length=1, max_length=2000)


class Decision(BaseModel):
    session_id: str
    id: str
    approve: bool
    note: str = Field(default="", max_length=300)


def _stream(events):
    def generate():
        try:
            for event in events:
                yield f"data: {json.dumps(event)}\n\n"
        except KeyError:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Unknown session. Start a new conversation.'})}\n\n"
        except anthropic.AuthenticationError:
            yield f"data: {json.dumps({'type': 'error', 'message': 'ANTHROPIC_API_KEY is missing or invalid.'})}\n\n"
        except anthropic.RateLimitError:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Rate limited by the Claude API. Try again shortly.'})}\n\n"
        except anthropic.APIStatusError as error:
            yield f"data: {json.dumps({'type': 'error', 'message': f'Claude API error {error.status_code}: {_api_message(error)}'})}\n\n"
        except anthropic.APIConnectionError:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Could not reach the Claude API.'})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


def _api_message(error: anthropic.APIStatusError) -> str:
    body = error.body if isinstance(error.body, dict) else {}
    return body.get("error", {}).get("message") or error.message


@app.get("/")
def home():
    return FileResponse(config.ROOT / "web" / "index.html")


@app.get("/api/state")
def state(customer_id: str | None = None):
    with db.connect() as conn:
        customers = [dict(row) for row in conn.execute("SELECT * FROM customers ORDER BY id")]
        orders = []
        if customer_id:
            for order in conn.execute("SELECT * FROM orders WHERE customer_id = ? ORDER BY placed_on DESC", (customer_id,)):
                items = [dict(i) for i in conn.execute("SELECT sku, name, price, final_sale FROM order_items WHERE order_id = ?", (order["id"],))]
                refunds = [dict(r) for r in conn.execute("SELECT sku, amount, reason, approved_by FROM refunds WHERE order_id = ?", (order["id"],))]
                orders.append({**dict(order), "items": items, "refunds": refunds})
        audit = [dict(row) for row in conn.execute("SELECT tool, input, outcome, detail, created_at FROM audit_log ORDER BY id DESC LIMIT 30")]
        escalations = [dict(row) for row in conn.execute("SELECT * FROM escalations ORDER BY id DESC LIMIT 10")]
    return {
        "customers": customers, "orders": orders, "audit": audit, "escalations": escalations,
        "model": demo.MODEL_NAME if config.DEMO else config.MODEL, "demo": config.DEMO, "today": config.TODAY.isoformat(), "approval_threshold": config.APPROVAL_THRESHOLD,
    }


@app.post("/api/sessions")
def create_session(body: NewSession):
    with db.connect() as conn:
        if not conn.execute("SELECT 1 FROM customers WHERE id = ?", (body.customer_id,)).fetchone():
            raise HTTPException(404, "Unknown customer")
    return {"session_id": agent.new_session(body.customer_id)}


@app.post("/api/chat")
def chat(body: Chat):
    return _stream(agent.run(body.session_id, user_message=body.message))


@app.post("/api/decide")
def decide(body: Decision):
    return _stream(agent.run(body.session_id, decision={"id": body.id, "approve": body.approve, "note": body.note}))


@app.post("/api/reset")
def reset():
    db.reset()
    return {"ok": True}
