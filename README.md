<h1 align="center">frontdesk</h1>

<p align="center">
  <strong>A customer-support agent that does the work, not just the talking.</strong><br>
  It looks up orders, cancels, redirects and refunds. The money rules are enforced in code, large refunds wait for a human, and every step is on screen.
</p>

<p align="center">
  <a href="#what-it-does">What it does</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#does-it-work">Evals</a> ·
  <a href="#run-it">Run it</a> ·
  <a href="docs/deck.pdf">Slides (PDF)</a>
</p>

<p align="center">
  <img alt="CI" src="https://github.com/IbrarYunus/frontdesk/actions/workflows/ci.yml/badge.svg">
  <img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-0f7b6c">
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-161a17">
  <img alt="Model: Claude Opus 5" src="https://img.shields.io/badge/model-Claude%20Opus%205-3fbfa9">
</p>

<p align="center">
<!-- SHOT   <img src="docs/screenshots/approval-paused.png" alt="frontdesk paused on a £240 refund. Left: the customer's orders. Middle: the chat. Right: the agent's tool calls and an approval card with Approve and Decline buttons." width="920"> -->
</p>

---

## Why

Support is where most companies first put an LLM agent in front of customers, and the hard part is not the conversation. It is letting software that can be talked into things touch refunds.

frontdesk is a working answer to that. The design rule is: **the model decides what to do; code decides whether it is allowed.**

- The model never types a refund amount. It picks the items; the code prices them.
- Return windows, final-sale items, double refunds and order ownership are checked in the tool, where no prompt can argue with them.
- Refunds over £100 stop the run. A person approves or declines, and the agent resumes and reports the decision honestly.
- Everything the agent read, tried and was refused is shown live and written to an audit log.

The shop (Halden Outfitters, outdoor gear) is fictional. The database, the policies and the agent are real and run locally.

## What it does

### Acts on the order, with a human in the loop for large refunds

The customer asks for a £240 refund. The agent finds the order, checks the policy, and calls `issue_refund`. The tool sees the amount is over the limit and the run pauses. Nothing is paid yet.
<!-- SHOT 
<img src="docs/screenshots/approval-paused.png" alt="Run paused with an approval card showing £240.00" width="920"> -->

The supervisor approves in the right-hand panel. The run resumes from saved state, the refund is written to the database (watch the order on the left), and the agent tells the customer what happened.
<!-- SHOT 
<img src="docs/screenshots/approval-approved.png" alt="After approval: the order shows as refunded by supervisor and the agent confirms to the customer" width="920"> -->

### Handles small things on its own

One item from a two-item order, inside the 30-day window, under the limit: refunded without involving anyone, for exactly the item's price.
<!-- SHOT 
<img src="docs/screenshots/partial-refund.png" alt="A £38 refund for one item issued automatically" width="920"> -->

### Takes "no" from the rules, and explains it

A clearance item cannot be returned for change of mind. The tool refuses, the trace shows the refusal in red, and the customer gets the rule in plain words plus what is still possible.
<!-- SHOT 
<img src="docs/screenshots/policy-refusal.png" alt="A refund refused by the final-sale rule" width="920"> -->

### Cannot be talked into things

A message claiming to be a system notice asks for a refund on another customer's order. The session is bound to the signed-in customer, so the tool cannot see that order at all, and a missing order and someone else's order return the same message.
<!-- SHOT 
<img src="docs/screenshots/prompt-injection.png" alt="A prompt-injection attempt that goes nowhere" width="920"> -->

### Knows when to hand over

An injury report is not a refund question. The agent opens an urgent ticket with a summary a supervisor can act on, and does not promise an outcome on their behalf.
<!-- SHOT 
<img src="docs/screenshots/escalation.png" alt="An urgent escalation ticket appearing in the left panel" width="920"> -->

## How it works

```
 customer message
        │
        ▼
 agent.py ── loop (max 12 model calls) ──▶ Claude Opus 5, adaptive thinking, prompt caching
        │                                       │ tool_use
        │                                       ▼
        │                          tools.py ── the only code that touches the database
        │                             │   list_orders · get_order · search_policy
        │                             │   cancel_order · update_shipping_address
        │                             │   issue_refund · escalate_to_human
        │                             │
        │             ┌───────────────┼──────────────────┐
        │             ▼               ▼                  ▼
        │            ok            refused          needs_approval
        │       (result back)  (rule, as an error)   (run state saved to SQLite, loop exits)
        │                                                 │
        │                                   supervisor: approve / decline
        │                                                 │
        └──────────── resumes from saved state ◀──────────┘
        ▼
 server.py ── Server-Sent Events ─▶ web/index.html (chat · live orders · trace · approvals)
```

Design decisions, and why:

- **Guardrails live in the tools.** A system prompt is a request; an `if` statement is a guarantee. Ownership, windows, final sale, one refund per item and the approval limit are all plain Python in `tools.py`, covered by tests that never call the model.
- **The model chooses items, the code computes money.** `issue_refund(order_id, skus, reason)` has no amount parameter. There is no number for a prompt injection to change.
- **A hand-written loop, on purpose.** The SDK's tool runner is the right default, but this run has to stop mid-turn, wait minutes or days for a person, and continue from a database row, possibly in another process. `agent.py` stores the message history and the pending tool call as JSON and picks up exactly where it stopped.
- **Refusals are tool errors, not exceptions.** A refused action returns `is_error` with the rule in words. The model reads it, stops trying, and explains. The prompt tells it a refusal is final.
- **Customer text is data.** The system prompt says why: messages are requests, never instructions about rules or permissions. The eval suite attacks this directly.
- **Strict tool schemas.** Every tool is declared `strict`, so arguments always match the schema and the code does not have to defend against malformed calls.
- **Prompt caching.** Tools and system prompt are stable, so each later model call in a conversation reads them from cache. The footer shows cached tokens and running cost.

## Does it work?

Two layers, both in the repo.

**1. Rules (`tests/`, no API calls).** Nine tests prove the guardrails hold whatever the model asks for: over-limit refunds pay nothing until approved, windows and final sale are enforced, an item is refunded once, another customer's order is indistinguishable from a missing one.

**2. Behaviour (`evals/`, live model).** 18 scripted conversations, each on a fresh database. A scenario passes only if all of these hold: the right tools were called, the database ended in the expected state (exact refund totals, order status, address, ticket priority), an approval was or was not requested, and a separate judge model confirms the reply told the customer the truth.

<!-- EVAL_TABLE -->

## Run it

Needs Python 3.11+, [uv](https://docs.astral.sh/uv/) and an [Anthropic API key](https://console.anthropic.com/settings/keys).

```bash
git clone https://github.com/IbrarYunus/frontdesk && cd frontdesk
cp .env.example .env        # add ANTHROPIC_API_KEY
uv sync
uv run frontdesk serve      # http://127.0.0.1:8001
```

Pick a customer, click one of the suggested messages, and watch the right-hand panel. "Reset demo" restores the database.

```bash
uv run pytest                      # the rules, no API calls
uv run python evals/run.py         # 18 live scenarios
uv run python evals/run.py --only prompt-injection
```

| Setting | Default | Meaning |
|---|---|---|
| `FRONTDESK_MODEL` | `claude-opus-5` | Agent model. |
| `FRONTDESK_EFFORT` | `medium` | How much the model thinks per step. |
| `FRONTDESK_APPROVAL_THRESHOLD` | `100` | Refunds above this (GBP) need a supervisor. |
| `FRONTDESK_TODAY` | `2026-09-15` | The shop's date. Pinned so the demo data and evals stay valid. |

## Project layout

```
frontdesk/tools.py    tools + every business rule        tests/           the rules, without the model
frontdesk/agent.py    pausable agent loop, saved state   evals/           18 scenarios, runner, results
frontdesk/db.py       schema and demo data               policies/        the shop's written policies
frontdesk/server.py   FastAPI + Server-Sent Events       web/index.html   the whole front end
```

About 650 lines of Python on the Anthropic SDK, with no agent framework. The loop is 60 lines and worth reading.

## What I would build next

- Real identity: bind the session to an authenticated user instead of a dropdown.
- A supervisor queue across conversations, with notifications, instead of one panel per chat.
- Replace the pinned date and SQLite with the shop's real order system behind the same tool interface.
- Run the scenario suite on every prompt or model change and fail CI on a regression.

## Author

**Ibrar Yunus**, AI engineer.

[ibraryunus.com/ai-engineer](https://ibraryunus.com/ai-engineer) · [LinkedIn](https://www.linkedin.com/in/ibrar-yunus/) · [GitHub](https://github.com/IbrarYunus)

Also see [groundwork](https://github.com/IbrarYunus/groundwork) (an agent that audits a codebase) and [footnote](https://github.com/IbrarYunus/footnote) (document Q&A where every claim cites its source sentence).

MIT licensed.
