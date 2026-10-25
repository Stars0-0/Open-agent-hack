"""Generate three disconnected systems (orders, payments, refunds) with planted causes of a revenue gap.

Writes CSVs to data/sample/ and the true per-cause amounts to data/ground_truth.json (used by tests only,
never read by the agent). Usage: python scripts/make_data.py [seed]
"""
import csv
import json
import os
import random
import sys
from datetime import date, timedelta

OUT = os.path.join(os.path.dirname(__file__), "..", "data")
MONTH = ("2026-03-01", "2026-04-01")


def d(s): return date.fromisoformat(s)


def make(seed: int = 7):
    rng = random.Random(seed)
    orders, payments, refunds = [], [], []
    oid = 0
    start, end = d("2026-02-01"), d("2026-05-01")
    day = start
    while day < end:
        for _ in range(rng.randint(8, 14)):
            oid += 1
            amount = round(rng.uniform(20, 300), 2)
            cancelled = rng.random() < 0.07
            orders.append([oid, rng.randint(1, 400), "cancelled" if cancelled else "delivered", day.isoformat(), amount])
            if not cancelled:
                lag = 0 if rng.random() < 0.8 else rng.randint(1, 4)  # a few pay late: month-boundary timing
                payments.append([len(payments) + 1, oid, (day + timedelta(days=lag)).isoformat(), amount])
                if rng.random() < 0.05:
                    refunds.append([len(refunds) + 1, oid, (day + timedelta(days=lag + rng.randint(1, 10))).isoformat(),
                                    round(amount * rng.choice([0.5, 1.0]), 2)])
        day += timedelta(days=1)

    in_m = lambda s: MONTH[0] <= s < MONTH[1]
    order_m = {o[0]: o for o in orders if in_m(o[3])}
    pay_by_order = {p[1]: p for p in payments}
    sales = sum(o[4] for o in order_m.values())
    finance = sum(p[3] for p in payments if in_m(p[2])) - sum(r[3] for r in refunds if in_m(r[2]))
    cancelled = sum(o[4] for o in order_m.values() if o[2] == "cancelled")
    refund_m = sum(r[3] for r in refunds if in_m(r[2]))
    timing = (sum(o[4] for o in order_m.values() if o[0] in pay_by_order and not in_m(pay_by_order[o[0]][2]))
              - sum(p[3] for p in payments if in_m(p[2]) and not in_m(orders[p[1] - 1][3])))
    truth = {"month": "2026-03", "sales_revenue": round(sales, 2), "finance_revenue": round(finance, 2),
             "gap": round(sales - finance, 2),
             "causes": {"cancelled_orders": round(cancelled, 2), "month_boundary_timing": round(timing, 2),
                        "refunds": round(refund_m, 2)}}

    os.makedirs(os.path.join(OUT, "sample"), exist_ok=True)
    for name, header, rows in [("orders", ["order_id", "customer_id", "status", "order_date", "amount"], orders),
                               ("payments", ["payment_id", "order_id", "paid_date", "amount"], payments),
                               ("refunds", ["refund_id", "order_id", "refund_date", "amount"], refunds)]:
        with open(os.path.join(OUT, "sample", f"{name}.csv"), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)
    with open(os.path.join(OUT, "ground_truth.json"), "w") as f:
        json.dump(truth, f, indent=2)
    return truth


if __name__ == "__main__":
    print(json.dumps(make(int(sys.argv[1]) if len(sys.argv) > 1 else 7), indent=2))
