# FOODíE Testing Notes — 2026-11-27 development update

## Passed checks
- Python syntax compilation: `app.py`, `model.py`, `multi_stall.py`, and `tests/test_model.py`.
- Jinja template syntax parsing: all HTML templates, including notifications, error, admin, staff, and order-detail templates.
- SQLite model test suite: **23 tests passed**. Coverage includes cash-on-pickup confirmation, multi-stall fulfillment and receipt gating, delivery-only OTW status, inventory total/deducted/left tracking, restocking and cancellation reversal, in-app order notifications, low-stock alerts, and admin-approved partial cancellation with the remaining amount updated, and full paid-order cancellation/refund status transitions.
- Catalog check: 26 products across 11 stalls; all products have a stall assignment.
- Existing role/stall isolation and order-stock validation tests continue to pass.
- ZIP archive integrity checked after packaging.

## Not verified in this environment
- Live Flask HTTP/browser testing and visual browser inspection. Flask is not installed in this build environment and package network access is unavailable. Install project dependencies using `pip install -r requirements.txt` on the target Windows machine, then test the workflows in a browser.
- Real GCash/Maya processing, automatic split payouts, and actual refunds are not integrated. Refund status is a workflow record only.
- Error logging is local file logging; centralized monitoring, alerting, and production hosting configuration still require deployment work.

## Recommended manual acceptance test
1. Sign in as admin and inspect a product showing Total, Deducted, and Left. Place one order for one unit and confirm the deducted count increases by one and stock left decreases by one.
2. Cancel an eligible order and confirm stock left is restored and deducted decreases.
3. Restock a product and confirm Total Stock increases by the restocked quantity.
4. Set a low-stock threshold and reduce stock to that level; verify the alert appears on the assigned staff dashboard and admin dashboard.
5. Place an order and verify the customer receives an in-app order notification and the assigned stall staff receives a new-order notification.
6. Update a stall order status and verify the customer receives a notification.
7. Submit a partial cancellation request for one stall. Verify it remains pending and the amount owed does not change until admin approval. Approve it and verify the cancelled stall portion is removed from the amount owed and stock is restored.
8. Cancel a fully paid eligible order and verify it creates refund-review records for its active stall portions. Approve and process each record, then verify the order becomes Refunded.
9. For a paid order, verify the admin refund workflow records review status. Complete any real refund outside FOODíE before marking it Processed.
10. Check daily sales and best-selling products in both the admin and assigned staff dashboards.
11. Confirm that OTW is offered only for delivery orders; pickup orders should show Ready for pickup and then Completed with no OTW timeline step.
12. Download a database backup and confirm the downloaded SQLite file opens successfully. For production, also verify the daily backup is copied to off-host storage.
13. Repeat role-isolation checks: staff cannot view or modify another stall's products or fulfillment groups.


## Policy review and staff notification update

- Policy version bumped to 1.1 so existing customer accounts must acknowledge the revised documents.
- Registration and updated-policy acceptance require server-recorded review confirmations for both documents, in addition to checked acknowledgement boxes.
- The policy reader enables its confirmation control only after the end-of-document marker is reached; confirmation is sent to the server with CSRF protection and unlocks the matching checkbox in the originating account form.
- Staff checkout notification routing is covered by `test_checkout_notifies_only_staff_assigned_to_order_stalls`.
- Staff dashboard notification panel polls the authenticated unread-notification endpoint every 10 seconds.
- Validation: 23 model tests passed; all Jinja templates parsed; Python compilation and JavaScript syntax checks passed. Flask is not installed in this build environment, so live HTTP/browser interaction still requires local verification.


## Customer food comment and policy return flow
- Policy confirmation now attempts to close the opened policy tab and return the user to the account page; a fallback redirect preserves the server-side review flag if the browser blocks closing the tab.
- The review-confirm control is now a compact check-mark button.
- Checkout accepts an optional food note (maximum 500 characters). The note is stored on the parent order and included in assigned-stall dashboard queue and history records.
- `test_customer_food_comment_is_saved_and_visible_to_assigned_staff` verifies persistence and visibility to assigned staff.
