"""Isolated SQLite business-logic tests; does not touch the shipped database."""
import shutil
import tempfile
import unittest
from pathlib import Path
import model

ROOT = Path(__file__).resolve().parents[1]

class FoodieModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / 'test.db'
        shutil.copy2(ROOT / 'database' / 'canteen.db', self.db_path)
        self.previous_db = model.DB_NAME
        model.DB_NAME = str(self.db_path)
        model.init_db()

    def tearDown(self):
        model.DB_NAME = self.previous_db
        self.temp.cleanup()



    def test_checkout_notifies_only_staff_assigned_to_order_stalls(self):
        uid, _ = model.register('Notification Customer', 'notification-customer@example.test', 'StrongPass123', privacy_accepted=True, terms_accepted=True)
        stall_id = model.get_item(1)['stall_id']
        ok, error = model.add_staff('Assigned Notification Staff', 'assigned-notify@example.test', 'StrongPass123', stall_id=stall_id)
        self.assertTrue(ok, error)
        ok, error = model.add_staff('Unassigned Notification Staff', 'unassigned-notify@example.test', 'StrongPass123')
        self.assertTrue(ok, error)
        c = model.db()
        try:
            assigned_id = c.execute("SELECT id FROM users WHERE email='assigned-notify@example.test'").fetchone()['id']
            unassigned_id = c.execute("SELECT id FROM users WHERE email='unassigned-notify@example.test'").fetchone()['id']
        finally:
            c.close()
        oid = model.create_order(uid, {1: 1}, 'Pay Later', 'Pickup')
        assigned = model.notifications(assigned_id)
        unassigned = model.notifications(unassigned_id)
        self.assertTrue(any(n['title'] == 'New stall order' and f"{model.order(oid, uid)['order_number']}" in n['message'] for n in assigned))
        self.assertFalse(any(n['title'] == 'New stall order' for n in unassigned))

    def test_customer_food_comment_is_saved_and_visible_to_assigned_staff(self):
        import multi_stall
        uid, _ = model.register('Comment Customer', 'comment-customer@example.test', 'StrongPass123', privacy_accepted=True, terms_accepted=True)
        stall_id = model.get_item(1)['stall_id']
        ok, error = model.add_staff('Comment Stall Staff', 'comment-staff@example.test', 'StrongPass123', stall_id=stall_id)
        self.assertTrue(ok, error)
        c = model.db()
        try:
            staff_id = c.execute("SELECT id FROM users WHERE email='comment-staff@example.test'").fetchone()['id']
        finally:
            c.close()
        note = 'Please pack the sauce separately and do not add onions.'
        oid = model.create_order(uid, {1: 1}, 'Pay Later', 'Pickup', customer_comment=note)
        self.assertEqual(model.order(oid, uid)['customer_comment'], note)
        c = model.db()
        try:
            groups = multi_stall.staff_groups(c, staff_id)
            self.assertEqual(groups[0]['customer_comment'], note)
        finally:
            c.close()

    def test_cash_pickup_receipt_requires_assigned_staff_confirmation(self):
        import multi_stall
        uid, _ = model.register('Cash Customer', 'cash-customer@example.test', 'StrongPass123', privacy_accepted=True, terms_accepted=True)
        stall_id = model.get_item(1)['stall_id']
        ok, error = model.add_staff('Belgian Staff', 'belgian-staff@example.test', 'StrongPass123', stall_id=stall_id)
        self.assertTrue(ok, error)
        ok, error = model.add_staff('Other Staff', 'other-staff@example.test', 'StrongPass123')
        self.assertTrue(ok, error)
        c = model.db()
        try:
            staff_id = c.execute("SELECT id FROM users WHERE email='belgian-staff@example.test'").fetchone()['id']
            other_id = c.execute("SELECT id FROM users WHERE email='other-staff@example.test'").fetchone()['id']
        finally:
            c.close()
        oid = model.create_order(uid, {1: 2}, 'Pay Later', 'Pickup')
        self.assertEqual(model.order(oid, uid)['payment_status'], 'CASH DUE')
        c = model.db()
        try:
            groups = multi_stall.staff_groups(c, staff_id)
            self.assertEqual(len(groups), 1)
            group_id = groups[0]['id']
        finally:
            c.close()
        self.assertFalse(model.confirm_stall_cash_payment(group_id, other_id))
        self.assertEqual(model.order(oid, uid)['payment_status'], 'CASH DUE')
        self.assertTrue(model.confirm_stall_cash_payment(group_id, staff_id))
        paid_order = model.order(oid, uid)
        self.assertEqual(paid_order['payment_status'], 'PAID')
        self.assertTrue(paid_order['payment_reference'].startswith('CASH-'))
        self.assertFalse(model.confirm_stall_cash_payment(group_id, staff_id))

    def test_multi_stall_cash_receipt_waits_until_each_stall_confirms(self):
        import multi_stall
        uid, _ = model.register('Split Cash Customer', 'split-cash@example.test', 'StrongPass123', privacy_accepted=True, terms_accepted=True)
        ok, error = model.add_staff('Paotsin Cash Staff', 'paotsin-cash@example.test', 'StrongPass123')
        self.assertTrue(ok, error)
        ok, error = model.add_staff('Lutong Cash Staff', 'lutong-cash@example.test', 'StrongPass123')
        self.assertTrue(ok, error)
        c = model.db()
        try:
            paotsin = c.execute("SELECT id FROM stalls WHERE name='Paotsin'").fetchone()['id']
            lutong = c.execute("SELECT id FROM stalls WHERE name='Lutong Bahay'").fetchone()['id']
            paotsin_staff = c.execute("SELECT id FROM users WHERE email='paotsin-cash@example.test'").fetchone()['id']
            lutong_staff = c.execute("SELECT id FROM users WHERE email='lutong-cash@example.test'").fetchone()['id']
            c.execute('UPDATE menu_items SET stall_id=? WHERE id=4', (paotsin,))
            c.execute('UPDATE menu_items SET stall_id=? WHERE id=2', (lutong,))
            c.commit()
            multi_stall.assign_staff(c, paotsin_staff, paotsin)
            multi_stall.assign_staff(c, lutong_staff, lutong)
        finally:
            c.close()
        oid = model.create_order(uid, {2: 1, 4: 1}, 'Pay Later', 'Pickup')
        c = model.db()
        try:
            p_group = multi_stall.staff_groups(c, paotsin_staff)[0]['id']
            l_group = multi_stall.staff_groups(c, lutong_staff)[0]['id']
        finally:
            c.close()
        self.assertTrue(model.confirm_stall_cash_payment(p_group, paotsin_staff))
        self.assertEqual(model.order(oid, uid)['payment_status'], 'CASH DUE')
        self.assertTrue(model.confirm_stall_cash_payment(l_group, lutong_staff))
        self.assertEqual(model.order(oid, uid)['payment_status'], 'PAID')



    def test_otw_status_is_delivery_only(self):
        import multi_stall
        uid,_=model.register('Fulfillment Customer','fulfillment@example.test','StrongPass123',privacy_accepted=True,terms_accepted=True)
        stall_id=model.get_item(1)['stall_id']
        ok,error=model.add_staff('Fulfillment Staff','fulfillment-staff@example.test','StrongPass123',stall_id=stall_id)
        self.assertTrue(ok,error)
        c=model.db()
        try:
            staff_id=c.execute("SELECT id FROM users WHERE email='fulfillment-staff@example.test'").fetchone()['id']
        finally: c.close()
        pickup_id=model.create_order(uid,{1:1},'Pay Later','Pickup')
        c=model.db()
        try: pickup_group=c.execute('SELECT id FROM stall_orders WHERE order_id=?',(pickup_id,)).fetchone()['id']
        finally: c.close()
        c=model.db()
        try:
            self.assertFalse(multi_stall.update_group_status(c,pickup_group,staff_id,'OTW'))
            self.assertTrue(multi_stall.update_group_status(c,pickup_group,staff_id,'Preparing'))
        finally: c.close()
        delivery_id=model.create_order(uid,{1:1},'Pay Later','Delivery','Campus Gate')
        c=model.db()
        try: delivery_group=c.execute('SELECT id FROM stall_orders WHERE order_id=?',(delivery_id,)).fetchone()['id']
        finally: c.close()
        c=model.db()
        try: self.assertTrue(multi_stall.update_group_status(c,delivery_group,staff_id,'OTW'))
        finally: c.close()
        self.assertEqual(model.order(delivery_id,uid)['status'],'OTW')

    def test_inventory_total_deducted_left_and_restock_tracking(self):
        uid,_=model.register('Inventory Customer','inventory@example.test','StrongPass123',privacy_accepted=True,terms_accepted=True)
        before=model.get_item(1)
        self.assertEqual(before['stock_total'],before['stock'])
        oid=model.create_order(uid,{1:1},'Pay Later','Pickup')
        after=model.get_item(1)
        self.assertEqual(after['stock'],before['stock']-1)
        self.assertEqual(after['stock_deducted'],1)
        self.assertEqual(after['stock_total'],before['stock_total'])
        self.assertTrue(model.cancel(oid,uid))
        returned=model.get_item(1)
        self.assertEqual(returned['stock'],before['stock'])
        self.assertEqual(returned['stock_deducted'],0)
        self.assertTrue(model.update_stock(1,5,note='Restocked five units'))
        restocked=model.get_item(1)
        self.assertEqual(restocked['stock_total'],before['stock_total']+5)
        self.assertEqual(restocked['stock'],before['stock']+5)

    def test_order_notifications_and_low_stock_alert(self):
        uid,_=model.register('Notify Customer','notify@example.test','StrongPass123',privacy_accepted=True,terms_accepted=True)
        oid=model.create_order(uid,{1:1},'Pay Later','Pickup')
        notes=model.notifications(uid)
        self.assertTrue(any('Order received'==n['title'] for n in notes))
        item=model.get_item(1)
        c=model.db()
        try:
            c.execute('UPDATE menu_items SET low_stock_threshold=100 WHERE id=1'); c.commit()
        finally: c.close()
        self.assertTrue(any(x['id']==1 for x in model.low_stock_items()))

    def test_partial_stall_cancellation_creates_refund_record_and_updates_due_total(self):
        import multi_stall
        uid,_=model.register('Partial Customer','partial@example.test','StrongPass123',privacy_accepted=True,terms_accepted=True)
        c=model.db()
        try:
            paotsin=c.execute("SELECT id FROM stalls WHERE name='Paotsin'").fetchone()['id']
            lutong=c.execute("SELECT id FROM stalls WHERE name='Lutong Bahay'").fetchone()['id']
            c.execute('UPDATE menu_items SET stall_id=? WHERE id=4',(paotsin,)); c.execute('UPDATE menu_items SET stall_id=? WHERE id=2',(lutong,)); c.commit()
        finally: c.close()
        oid=model.create_order(uid,{2:1,4:1},'Pay Later','Pickup')
        before=model.order(oid,uid)['total']
        c=model.db()
        try: group=c.execute("SELECT id FROM stall_orders WHERE order_id=? AND stall_id=(SELECT id FROM stalls WHERE name='Paotsin')",(oid,)).fetchone()['id']
        finally: c.close()
        self.assertTrue(model.request_stall_refund(oid,group,uid,'Customer requested cancellation'))
        pending=model.order(oid,uid)
        self.assertEqual(pending['total'],before)
        self.assertEqual(next(g for g in pending['stall_orders'] if g['id']==group)['status'],'Received')
        c=model.db()
        try: refund_id=c.execute('SELECT id FROM refund_requests WHERE order_id=?',(oid,)).fetchone()['id']
        finally: c.close()
        self.assertTrue(model.review_refund(refund_id,'Approved','Approved partial cancellation',1))
        after=model.order(oid,uid)
        self.assertLess(after['total'],before)
        self.assertEqual(after['payment_status'],'CASH DUE')
        c=model.db()
        try:
            rr=c.execute('SELECT status,amount FROM refund_requests WHERE order_id=?',(oid,)).fetchone()
            self.assertEqual(rr['status'],'Approved')
            self.assertGreater(rr['amount'],0)
        finally: c.close()


    def test_full_paid_cancellation_creates_and_completes_refund_record(self):
        uid,_=model.register('Refund Customer','refund@example.test','StrongPass123',privacy_accepted=True,terms_accepted=True)
        before=model.get_item(1)
        oid=model.create_order(uid,{1:1},'Pay Now','Pickup',payment_provider='GCash')
        self.assertTrue(model.complete_demo_online_payment(oid,uid,'GCash'))
        self.assertTrue(model.cancel(oid,uid))
        cancelled=model.order(oid,uid)
        self.assertEqual(cancelled['payment_status'],'REFUND PENDING')
        self.assertEqual(cancelled['total'],0)
        self.assertEqual(model.get_item(1)['stock'],before['stock'])
        c=model.db()
        try: refund_id=c.execute('SELECT id FROM refund_requests WHERE order_id=?',(oid,)).fetchone()['id']
        finally: c.close()
        self.assertTrue(model.review_refund(refund_id,'Approved','Approved full cancellation',1))
        self.assertTrue(model.review_refund(refund_id,'Processed','Recorded demo refund review',1))
        self.assertEqual(model.order(oid,uid)['payment_status'],'REFUNDED')

    def test_catalog_and_empty_accounts(self):
        self.assertEqual(len(model.menu()), 26)
        self.assertFalse(model.has_admin())
        c=model.db()
        try: self.assertEqual(c.execute('SELECT COUNT(*) FROM users').fetchone()[0], 0)
        finally: c.close()

    def test_first_admin_customer_and_authentication(self):
        ok, error = model.create_first_admin('Admin', 'admin@example.test', 'StrongPass123')
        self.assertTrue(ok, error)
        self.assertFalse(model.create_first_admin('Second', 'second@example.test', 'StrongPass123')[0])
        uid, error = model.register('Customer', 'customer@example.test', 'StrongPass123', privacy_accepted=True, terms_accepted=True)
        self.assertIsNone(error)
        self.assertEqual(model.authenticate('customer@example.test', 'StrongPass123')['role'], 'customer')
        self.assertIsNone(model.authenticate('customer@example.test', 'wrong-password'))

    def test_stock_order_status_and_cancellation(self):
        uid, _ = model.register('Customer', 'customer@example.test', 'StrongPass123', privacy_accepted=True, terms_accepted=True)
        before = model.get_item(1)['stock']
        oid = model.create_order(uid, {1: 2}, 'Pay Later', 'Pickup')
        self.assertIsNotNone(oid)
        self.assertEqual(model.get_item(1)['stock'], before - 2)
        model.add_staff('Kitchen Staff', 'staff@example.test', 'StrongPass123')
        c=model.db()
        try: staff_id=c.execute("SELECT id FROM users WHERE role='staff'").fetchone()[0]
        finally: c.close()
        self.assertTrue(model.set_status(oid, 'Cancelled', staff_id))
        self.assertEqual(model.get_item(1)['stock'], before)
        self.assertFalse(model.set_status(oid, 'Preparing', staff_id))

    def test_demo_payment(self):
        uid, _ = model.register('Customer', 'customer@example.test', 'StrongPass123', privacy_accepted=True, terms_accepted=True)
        oid = model.create_order(uid, {2: 1}, 'Pay Now', 'Pickup', payment_provider='GCash')
        self.assertTrue(model.complete_demo_online_payment(oid, uid, 'GCash'))
        self.assertEqual(model.order(oid, uid)['payment_status'], 'PAID (DEMO)')
        self.assertEqual(model.order(oid, uid)['status'], 'Received')
        self.assertTrue(model.sales_analytics(7))
        self.assertTrue(model.top_selling_items(30))
        self.assertFalse(model.complete_demo_online_payment(oid, uid, 'GCash'))




    def test_fresh_database_initializes_stalls_and_catalog(self):
        previous=model.DB_NAME
        with tempfile.TemporaryDirectory() as temp:
            model.DB_NAME=str(Path(temp)/'fresh.db')
            model.init_db()
            c=model.db()
            try:
                self.assertEqual(c.execute('SELECT COUNT(*) FROM stalls').fetchone()[0],11)
                self.assertEqual(c.execute('SELECT COUNT(*) FROM menu_items').fetchone()[0],26)
                self.assertEqual(c.execute('SELECT COUNT(*) FROM menu_items WHERE stall_id IS NULL').fetchone()[0],0)
            finally: c.close()
        model.DB_NAME=previous


    def test_seven_missing_stalls_receive_agreed_products_and_estimated_prices(self):
        expected = {
            'Belgian Waffle': {'Classic Belgian Waffle': 85.0, 'Chocolate Belgian Waffle': 100.0},
            'Nescafe': {'Hot Nescafe Coffee': 45.0, 'Iced Nescafe Coffee': 55.0},
            'Jamaican': {'Chicken Burrito': 120.0, 'Beef Burrito': 135.0},
            'Grill Pot': {'Pork BBQ': 85.0, 'Roasted Chicken': 150.0},
            'Babs Sisig': {'Pork Sisig': 110.0, 'Chicken Sisig': 100.0},
            'Halfway': {'Classic Burger': 75.0, 'Classic Hotdog': 55.0},
            'Korean Stall': {'Buldak Spicy Noodles': 120.0, 'Shin Ramyun': 95.0},
        }
        c=model.db()
        try:
            for stall, products in expected.items():
                rows=c.execute('''SELECT m.name,m.price FROM menu_items m JOIN stalls s ON s.id=m.stall_id
                                  WHERE s.name=?''',(stall,)).fetchall()
                actual={r['name']:r['price'] for r in rows}
                for name, price in products.items():
                    self.assertIn(name, actual, f'{name} missing from {stall}')
                    self.assertEqual(actual[name], price)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM stalls').fetchone()[0], 11)
        finally:
            c.close()

    def test_registration_requires_and_records_policy_acceptance(self):
        uid,error=model.register('No Consent','no-consent@example.test','StrongPass123')
        self.assertIsNone(uid)
        self.assertIsNotNone(error)
        uid,error=model.register('Consented','consented@example.test','StrongPass123',privacy_accepted=True,terms_accepted=True)
        self.assertIsNone(error)
        self.assertTrue(model.has_current_policies(uid))
        model.accept_current_policies(uid)
        self.assertTrue(model.has_current_policies(uid))

    def test_eleven_stalls_and_safe_repeat_migration(self):
        import multi_stall
        c=model.db()
        try:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM stalls').fetchone()[0], 11)
            multi_stall.migrate(c)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM stalls').fetchone()[0], 11)
        finally:
            c.close()

    def test_multistall_checkout_splits_fulfillment_and_earnings(self):
        import multi_stall
        uid, error = model.register('Customer', 'split@example.test', 'StrongPass123', privacy_accepted=True, terms_accepted=True)
        self.assertIsNone(error)
        ok, error = model.add_staff('Paotsin Staff', 'paotsin@example.test', 'StrongPass123')
        self.assertTrue(ok, error)
        ok, error = model.add_staff('Lutong Staff', 'lutong@example.test', 'StrongPass123')
        self.assertTrue(ok, error)
        c=model.db()
        try:
            paotsin=c.execute("SELECT id FROM stalls WHERE name='Paotsin'").fetchone()[0]
            lutong=c.execute("SELECT id FROM stalls WHERE name='Lutong Bahay'").fetchone()[0]
            paotsin_staff=c.execute("SELECT id FROM users WHERE email='paotsin@example.test'").fetchone()[0]
            lutong_staff=c.execute("SELECT id FROM users WHERE email='lutong@example.test'").fetchone()[0]
            c.execute('UPDATE menu_items SET stall_id=? WHERE id=4',(paotsin,))
            c.execute('UPDATE menu_items SET stall_id=? WHERE id=2',(lutong,))
            c.commit()
            self.assertTrue(multi_stall.assign_staff(c,paotsin_staff,paotsin))
            self.assertTrue(multi_stall.assign_staff(c,lutong_staff,lutong))
        finally:
            c.close()
        oid=model.create_order(uid,{2:1,4:2},'Pay Later','Pickup')
        self.assertIsNotNone(oid)
        details=model.order(oid,uid)
        self.assertEqual(len(details['stall_orders']),2)
        self.assertAlmostEqual(sum(x['gross_amount'] for x in details['stall_orders']), details['total'])
        c=model.db()
        try:
            paotsin_groups=multi_stall.staff_groups(c,paotsin_staff)
            lutong_groups=multi_stall.staff_groups(c,lutong_staff)
            self.assertEqual(len(paotsin_groups),1)
            self.assertEqual(paotsin_groups[0]['stall_name'],'Paotsin')
            self.assertEqual(len(lutong_groups),1)
            self.assertEqual(lutong_groups[0]['stall_name'],'Lutong Bahay')
            self.assertEqual(len(model.orders(viewer_role='staff',viewer_id=paotsin_staff)),1)
            self.assertEqual(len(model.orders(viewer_role='staff',viewer_id=lutong_staff)),1)
            self.assertIsNone(multi_stall.group_detail(c,lutong_groups[0]['id'],paotsin_staff))
            # A staff member cannot update another stall's fulfillment group.
            other_group=lutong_groups[0]['id']
            self.assertFalse(multi_stall.update_group_status(c,other_group,paotsin_staff,'Preparing'))
            own_group=paotsin_groups[0]['id']
            self.assertTrue(multi_stall.update_group_status(c,own_group,paotsin_staff,'Preparing'))
            details=model.order(oid,uid)
            self.assertEqual(details['status'],'Received')
            self.assertFalse(details['can_cancel'])
        finally:
            c.close()

    def test_existing_catalog_products_receive_stall_assignments(self):
        c=model.db()
        try:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM menu_items WHERE stall_id IS NULL').fetchone()[0], 0)
        finally:
            c.close()


    def test_stall_staff_cancellation_restores_only_assigned_items(self):
        import multi_stall
        uid,_=model.register('Customer','cancel-split@example.test','StrongPass123',privacy_accepted=True,terms_accepted=True)
        model.add_staff('Paotsin Staff','cancel-paotsin@example.test','StrongPass123')
        model.add_staff('Lutong Staff','cancel-lutong@example.test','StrongPass123')
        c=model.db()
        try:
            paotsin=c.execute("SELECT id FROM stalls WHERE name='Paotsin'").fetchone()[0]
            lutong=c.execute("SELECT id FROM stalls WHERE name='Lutong Bahay'").fetchone()[0]
            paotsin_staff=c.execute("SELECT id FROM users WHERE email='cancel-paotsin@example.test'").fetchone()[0]
            lutong_staff=c.execute("SELECT id FROM users WHERE email='cancel-lutong@example.test'").fetchone()[0]
            c.execute('UPDATE menu_items SET stall_id=? WHERE id=4',(paotsin,))
            c.execute('UPDATE menu_items SET stall_id=? WHERE id=2',(lutong,))
            c.commit()
            multi_stall.assign_staff(c,paotsin_staff,paotsin)
            multi_stall.assign_staff(c,lutong_staff,lutong)
        finally: c.close()
        before_paotsin=model.get_item(4)['stock']; before_lutong=model.get_item(2)['stock']
        oid=model.create_order(uid,{2:1,4:2},'Pay Later','Pickup')
        self.assertIsNotNone(oid)
        c=model.db()
        try:
            groups=multi_stall.staff_groups(c,paotsin_staff)
            self.assertEqual(len(groups),1)
            self.assertTrue(multi_stall.update_group_status(c,groups[0]['id'],paotsin_staff,'Cancelled'))
        finally: c.close()
        self.assertEqual(model.get_item(4)['stock'],before_paotsin)
        self.assertEqual(model.get_item(2)['stock'],before_lutong-1)


    def test_customer_cancel_after_one_stall_cancel_does_not_restore_stock_twice(self):
        import multi_stall
        uid,_=model.register('Customer','double-restore@example.test','StrongPass123',privacy_accepted=True,terms_accepted=True)
        model.add_staff('Paotsin Staff','double-paotsin@example.test','StrongPass123')
        model.add_staff('Lutong Staff','double-lutong@example.test','StrongPass123')
        c=model.db()
        try:
            paotsin=c.execute("SELECT id FROM stalls WHERE name='Paotsin'").fetchone()[0]
            lutong=c.execute("SELECT id FROM stalls WHERE name='Lutong Bahay'").fetchone()[0]
            paotsin_staff=c.execute("SELECT id FROM users WHERE email='double-paotsin@example.test'").fetchone()[0]
            c.execute('UPDATE menu_items SET stall_id=? WHERE id=4',(paotsin,))
            c.execute('UPDATE menu_items SET stall_id=? WHERE id=2',(lutong,))
            c.commit(); multi_stall.assign_staff(c,paotsin_staff,paotsin)
        finally: c.close()
        before_p=model.get_item(4)['stock']; before_l=model.get_item(2)['stock']
        oid=model.create_order(uid,{2:1,4:2},'Pay Later','Pickup')
        c=model.db()
        try:
            group=multi_stall.staff_groups(c,paotsin_staff)[0]
            self.assertTrue(multi_stall.update_group_status(c,group['id'],paotsin_staff,'Cancelled'))
        finally: c.close()
        self.assertEqual(model.get_item(4)['stock'],before_p)
        self.assertTrue(model.cancel(oid,uid))
        self.assertEqual(model.get_item(4)['stock'],before_p)
        self.assertEqual(model.get_item(2)['stock'],before_l)

    def test_closed_stall_cannot_accept_checkout(self):
        uid,_=model.register('Customer','closed-stall@example.test','StrongPass123',privacy_accepted=True,terms_accepted=True)
        c=model.db()
        try:
            c.execute("UPDATE stalls SET status='Closed' WHERE name='Lutong Bahay'")
            c.commit()
        finally: c.close()
        self.assertIsNone(model.create_order(uid,{2:1},'Pay Later','Pickup'))

    def test_overstock_order_rejected_without_mutation(self):
        uid, _ = model.register('Customer', 'customer@example.test', 'StrongPass123', privacy_accepted=True, terms_accepted=True)
        before = model.get_item(1)['stock']
        self.assertIsNone(model.create_order(uid, {1: before + 1}, 'Pay Later', 'Pickup'))
        self.assertEqual(model.get_item(1)['stock'], before)

if __name__ == '__main__':
    unittest.main()
