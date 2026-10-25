Three separate systems, each loaded into Zetaris as its own source. Dates are ISO text ('YYYY-MM-DD').
Compare dates with  col >= '2026-03-01' AND col < '2026-04-01'  (no date functions, so any SQL dialect works).
EDIT the table names below to match how they appear in your Zetaris catalog (for example sales.orders).

orders    (sales system)    order_id, customer_id, status, order_date, amount
          status is 'delivered' or 'cancelled'. amount is the order value.
payments  (finance system)  payment_id, order_id, paid_date, amount
          one row per payment actually received. Cancelled orders have no payment.
refunds   (support system)  refund_id, order_id, refund_date, amount
          money returned to the customer.

Common metric definitions that disagree:
  Sales dashboard revenue  = SUM(orders.amount) for orders with order_date in the month (all statuses).
  Finance revenue          = SUM(payments.amount) with paid_date in the month MINUS SUM(refunds.amount) with refund_date in the month.
