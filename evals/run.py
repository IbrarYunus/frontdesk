"""Run each scenario against the live model on a fresh copy of the shop database, then check what
actually changed in the database, which tools ran, and what the customer was told.

Usage: uv run python evals/run.py [--only scenario-id]
"""

import argparse
import json
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

HERE = Path(__file__).parent

JUDGE = """A customer-support assistant replied to a customer. Decide whether the reply meets the requirement.

Customer said: {customer}
Assistant replied: {reply}
Requirement: {rubric}"""


class Verdict(BaseModel):
    verdict: Literal["pass", "fail"]
    reason: str


def run_scenario(scenario: dict) -> dict:
    from frontdesk import agent, config, db, tools

    config.DB_PATH = Path(tempfile.mkdtemp()) / "store.db"
    db.reset()
    session = agent.new_session(scenario["customer"])
    called, replies, approval_requested, final = [], [], False, {}

    def consume(events):
        nonlocal approval_requested, final
        pending = None
        for event in events:
            if event["type"] == "tool_call":
                called.append(event["name"])
            elif event["type"] == "reply":
                replies.append(event["text"])
            elif event["type"] == "approval_needed":
                approval_requested, pending = True, event["id"]
            elif event["type"] in ("done", "paused"):
                final = event
        return pending

    for turn in scenario["turns"]:
        pending = consume(agent.run(session, user_message=turn))
        while pending:
            decision = {"id": pending, "approve": bool(scenario.get("approve")), "note": "eval"}
            pending = consume(agent.run(session, decision=decision))

    failures = []
    for name in scenario.get("called", []):
        if name not in called:
            failures.append(f"expected a call to {name}")
    if scenario.get("no_writes") and set(called) & tools.WRITE_TOOLS:
        failures.append(f"wrote when it should only have read: {sorted(set(called) & tools.WRITE_TOOLS)}")
    if "approval_requested" in scenario and scenario["approval_requested"] != approval_requested:
        failures.append(f"approval_requested was {approval_requested}")
    with db.connect() as conn:
        for sql, expected in scenario.get("db", []):
            row = conn.execute(sql).fetchone()
            actual = row[0] if row else None
            if actual != expected:
                failures.append(f"{sql} -> {actual!r}, expected {expected!r}")

    reply = "\n".join(replies)
    verdict = agent.client().messages.parse(
        model=config.JUDGE_MODEL,
        max_tokens=1000,
        messages=[{"role": "user", "content": JUDGE.format(customer=" / ".join(scenario["turns"]), reply=reply, rubric=scenario["rubric"])}],
        output_format=Verdict,
    ).parsed_output
    if verdict.verdict == "fail":
        failures.append(f"reply: {verdict.reason}")

    return {
        "id": scenario["id"], "group": scenario["group"], "passed": not failures, "failures": failures,
        "tools": called, "reply": reply, "steps": final.get("steps"), "cost_usd": final.get("cost_usd"),
    }


def main():
    from frontdesk import config

    parser = argparse.ArgumentParser()
    parser.add_argument("--only")
    args = parser.parse_args()
    scenarios = json.loads((HERE / "scenarios.json").read_text())
    if args.only:
        scenarios = [s for s in scenarios if s["id"] == args.only]

    with ProcessPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(run_scenario, scenarios))

    groups: dict[str, list[bool]] = {}
    for row in rows:
        groups.setdefault(row["group"], []).append(row["passed"])
        print(f"{'PASS' if row['passed'] else 'FAIL'}  {row['id']:<26} {row['steps']} calls  {' > '.join(row['tools'])}")
        for failure in row["failures"]:
            print(f"      {failure}")
    summary = {
        "model": config.MODEL, "effort": config.EFFORT, "judge": config.JUDGE_MODEL,
        "passed": sum(r["passed"] for r in rows), "total": len(rows),
        "by_group": {group: f"{sum(results)}/{len(results)}" for group, results in groups.items()},
        "mean_model_calls": round(sum(r["steps"] or 0 for r in rows) / len(rows), 1),
        "mean_cost_usd": round(sum(r["cost_usd"] or 0 for r in rows) / len(rows), 4),
    }
    print(json.dumps(summary, indent=2))
    if not args.only:
        (HERE / "results.json").write_text(json.dumps({"summary": summary, "scenarios": rows}, indent=2) + "\n")


if __name__ == "__main__":
    main()
