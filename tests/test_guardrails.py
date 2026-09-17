"""The rules must hold whatever the model asks for. None of these tests call the API."""

import pytest

from frontdesk import db, tools


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "store.db"
    db.reset(path)
    with db.connect(path) as connection:
        yield connection


def refund_total(conn, order_id):
    return conn.execute("SELECT COALESCE(SUM(amount), 0) FROM refunds WHERE order_id = ?", (order_id,)).fetchone()[0]


def test_small_refund_inside_the_window_is_paid_and_the_code_sets_the_amount(conn):
    outcome = tools.issue_refund(conn, "C1", "HO-1001", ["BEANIE-02"], "changed_mind")
    assert outcome.status == "ok" and outcome.content["refunded"] == 38.0
    assert refund_total(conn, "HO-1001") == 38.0


def test_refund_above_the_limit_waits_for_a_supervisor_and_pays_nothing(conn):
    outcome = tools.issue_refund(conn, "C2", "HO-1004", ["JACKET-DN"], "changed_mind")
    assert outcome.status == "needs_approval" and outcome.content["amount"] == 240.0
    assert refund_total(conn, "HO-1004") == 0
    approved = tools.issue_refund(conn, "C2", "HO-1004", ["JACKET-DN"], "changed_mind", approved_by="supervisor")
    assert approved.status == "ok" and refund_total(conn, "HO-1004") == 240.0


def test_change_of_mind_after_30_days_is_refused(conn):
    assert tools.issue_refund(conn, "C2", "HO-1005", ["BOOT-HK"], "changed_mind").status == "refused"


def test_damaged_item_is_covered_for_90_days(conn):
    assert tools.issue_refund(conn, "C2", "HO-1006", ["STOVE-01"], "damaged").status == "ok"


def test_final_sale_is_refused_for_change_of_mind_but_not_for_damage(conn):
    assert tools.issue_refund(conn, "C3", "HO-1007", ["SHELL-CL"], "changed_mind").status == "refused"
    assert tools.issue_refund(conn, "C3", "HO-1007", ["SHELL-CL"], "damaged").status == "ok"


def test_an_item_is_refunded_once(conn):
    assert tools.issue_refund(conn, "C3", "HO-1008", ["FILTER-01"], "damaged").status == "refused"
    assert refund_total(conn, "HO-1008") == 55.0


def test_another_customers_order_looks_the_same_as_a_missing_one(conn):
    theirs = tools.get_order(conn, "C1", "HO-1009")
    missing = tools.get_order(conn, "C1", "HO-9999")
    assert theirs.status == missing.status == "refused" and theirs.text == missing.text
    assert tools.issue_refund(conn, "C1", "HO-1009", ["HARNESS-01"], "damaged").status == "refused"


def test_shipped_orders_cannot_be_cancelled_or_redirected(conn):
    assert tools.cancel_order(conn, "C1", "HO-1003").status == "refused"
    assert tools.update_shipping_address(conn, "C1", "HO-1003", "1 New Street, Leeds LS1 1AA").status == "refused"
    assert tools.cancel_order(conn, "C1", "HO-1002").status == "ok"


def test_policy_search_finds_the_right_section():
    sections = tools.search_policy("can I return a clearance item").content
    assert sections[0]["section"] == "Final sale"
