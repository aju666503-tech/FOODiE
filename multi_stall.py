"""Additive multi-stall schema and stall-scoped business operations for FOODíE."""
from datetime import datetime

STALLS = [
    ('Belgian Waffle', 'belgian-waffle'), ('Nescafe', 'nescafe'),
    ('Jamaican', 'jamaican'), ('Paotsin', 'paotsin'), ('Grill Pot', 'grill-pot'),
    ('Babs Sisig', 'babs-sisig'), ('Lutong Bahay', 'lutong-bahay'),
    ('Fruitas', 'fruitas'), ('Sweets', 'sweets'), ('Halfway', 'halfway'),
    ('Korean Stall', 'korean-stall')
]


def migrate(c):
    """Idempotent migration; adds tables/columns without deleting existing records."""
    c.executescript('''
    CREATE TABLE IF NOT EXISTS stalls(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        slug TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL DEFAULT 'Open' CHECK(status IN ('Open','Temporarily Unavailable','Closed','Busy')),
        description TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS staff_stalls(
        staff_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        stall_id INTEGER NOT NULL REFERENCES stalls(id) ON DELETE CASCADE,
        assigned_at TEXT NOT NULL,
        PRIMARY KEY(staff_id,stall_id)
    );
    CREATE TABLE IF NOT EXISTS stall_orders(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
        stall_id INTEGER NOT NULL REFERENCES stalls(id),
        status TEXT NOT NULL DEFAULT 'Received',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        cash_received_at TEXT,
        cash_received_by INTEGER REFERENCES users(id),
        UNIQUE(order_id,stall_id)
    );
    CREATE TABLE IF NOT EXISTS stall_earnings(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
        stall_id INTEGER NOT NULL REFERENCES stalls(id),
        gross_amount REAL NOT NULL,
        fee_amount REAL NOT NULL DEFAULT 0,
        net_amount REAL NOT NULL,
        settlement_status TEXT NOT NULL DEFAULT 'Pending',
        settlement_reference TEXT,
        created_at TEXT NOT NULL,
        settled_at TEXT,
        UNIQUE(order_id,stall_id)
    );
    CREATE INDEX IF NOT EXISTS idx_stall_orders_stall_status ON stall_orders(stall_id,status);
    CREATE INDEX IF NOT EXISTS idx_stall_earnings_stall_status ON stall_earnings(stall_id,settlement_status);
    ''')
    for table, column, definition in (
        ('menu_items', 'stall_id', 'INTEGER REFERENCES stalls(id)'),
        ('order_items', 'stall_id', 'INTEGER REFERENCES stalls(id)'),
        ('stall_orders', 'cash_received_at', 'TEXT'),
        ('stall_orders', 'cash_received_by', 'INTEGER REFERENCES users(id)')
    ):
        cols = {r['name'] for r in c.execute(f'PRAGMA table_info({table})').fetchall()}
        if column not in cols:
            c.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
    stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    for name, slug in STALLS:
        c.execute('INSERT OR IGNORE INTO stalls(name,slug,status,created_at) VALUES(?,?,?,?)',
                  (name, slug, 'Open', stamp))
    # Only map products where the agreed product/stall pairing is unambiguous.
    mapping = {
        'Chicken Rice Meal': 'Lutong Bahay', 'Pancit Canton Special': 'Lutong Bahay',
        'Bottled Mineral Water': 'Fruitas',
        'Siomai Rice Supreme': 'Paotsin',
        'Beef Tapa Meal': 'Lutong Bahay', 'Sinigang Pork Rice': 'Lutong Bahay',
        'Bulalo Soup Meal': 'Lutong Bahay', 'Lumpiang Shanghai (5 pcs)': 'Lutong Bahay',
        'Crispy Calamares': 'Lutong Bahay',
        'Traditional Leche Flan': 'Sweets', 'Turon with Langka (2 pcs)': 'Sweets',
        'Signature Berry Iced Tea': 'Fruitas'
    }
    for product, stall in mapping.items():
        c.execute('UPDATE menu_items SET stall_id=(SELECT id FROM stalls WHERE name=?) WHERE name=? AND stall_id IS NULL',
                  (stall, product))

    # Agreed starter products for the seven stalls that were still missing menu entries.
    # Prices are editable estimates in PHP, not verified stall quotations.
    estimated_products = [
        ('Belgian Waffle', 'Classic Belgian Waffle', 'Desserts', 'Golden Belgian waffle served warm with a light buttery finish.', 85.00, 30, 5, 320),
        ('Belgian Waffle', 'Chocolate Belgian Waffle', 'Desserts', 'Belgian waffle topped with rich chocolate sauce.', 100.00, 30, 6, 390),
        ('Nescafe', 'Hot Nescafe Coffee', 'Drinks', 'Freshly prepared hot Nescafe coffee.', 45.00, 40, 3, 90),
        ('Nescafe', 'Iced Nescafe Coffee', 'Drinks', 'Chilled Nescafe coffee served over ice.', 55.00, 40, 3, 120),
        ('Jamaican', 'Chicken Burrito', 'Meals', 'Seasoned chicken wrapped with rice and fresh fillings.', 120.00, 25, 8, 520),
        ('Jamaican', 'Beef Burrito', 'Meals', 'Savory beef wrapped with rice and fresh fillings.', 135.00, 25, 8, 580),
        ('Grill Pot', 'Pork BBQ', 'Meals', 'Grilled marinated pork barbecue served on a stick.', 85.00, 30, 8, 330),
        ('Grill Pot', 'Roasted Chicken', 'Meals', 'Tender roasted chicken with savory seasoning.', 150.00, 20, 12, 520),
        ('Babs Sisig', 'Pork Sisig', 'Meals', 'Sizzling-style chopped pork sisig with savory seasoning.', 110.00, 25, 8, 460),
        ('Babs Sisig', 'Chicken Sisig', 'Meals', 'Chopped chicken sisig with savory seasoning.', 100.00, 25, 8, 390),
        ('Halfway', 'Classic Burger', 'Meals', 'Classic burger with a seasoned patty and soft bun.', 75.00, 30, 6, 410),
        ('Halfway', 'Classic Hotdog', 'Meals', 'Hotdog in a soft bun with classic toppings.', 55.00, 30, 5, 300),
        ('Korean Stall', 'Buldak Spicy Noodles', 'Meals', 'Spicy Korean-style stir-fried noodles.', 120.00, 25, 7, 540),
        ('Korean Stall', 'Shin Ramyun', 'Soup Meals', 'Korean spicy instant noodle soup.', 95.00, 25, 6, 500),
    ]
    for stall, name, category, description, price, stock, prep_time, calories in estimated_products:
        exists = c.execute('SELECT id FROM menu_items WHERE name=? AND stall_id=(SELECT id FROM stalls WHERE name=?)',
                           (name, stall)).fetchone()
        if not exists:
            c.execute('''INSERT INTO menu_items(name,category,description,price,available,stock,prep_time,calories,stall_id)
                         VALUES(?,?,?,?,1,?,?,?,(SELECT id FROM stalls WHERE name=?))''',
                      (name, category, description, price, stock, prep_time, calories, stall))

    # Preserve stall ownership for historical line items and build their split records.
    c.execute('UPDATE order_items SET stall_id=(SELECT stall_id FROM menu_items WHERE menu_items.id=order_items.menu_item_id) WHERE stall_id IS NULL')
    old_groups = c.execute('''SELECT oi.order_id,oi.stall_id,SUM(oi.price*oi.quantity) AS amount,
                                    o.created_at,o.status
                             FROM order_items oi JOIN orders o ON o.id=oi.order_id
                             WHERE oi.stall_id IS NOT NULL GROUP BY oi.order_id,oi.stall_id''').fetchall()
    for g in old_groups:
        c.execute('INSERT OR IGNORE INTO stall_orders(order_id,stall_id,status,created_at,updated_at) VALUES(?,?,?,?,?)',
                  (g['order_id'],g['stall_id'],g['status'],g['created_at'],g['created_at']))
        c.execute('INSERT OR IGNORE INTO stall_earnings(order_id,stall_id,gross_amount,fee_amount,net_amount,created_at) VALUES(?,?,?,0,?,?)',
                  (g['order_id'],g['stall_id'],g['amount'],g['amount'],g['created_at']))


def list_stalls(db, active_only=False):
    q = 'SELECT * FROM stalls'
    if active_only:
        q += " WHERE status IN ('Open','Busy')"
    return [dict(r) for r in db.execute(q + ' ORDER BY name').fetchall()]


def assign_staff(db, staff_id, stall_id):
    valid = db.execute("SELECT 1 FROM users WHERE id=? AND role='staff'", (staff_id,)).fetchone()
    exists = db.execute('SELECT 1 FROM stalls WHERE id=?', (stall_id,)).fetchone()
    if not valid or not exists:
        return False
    db.execute('INSERT OR IGNORE INTO staff_stalls(staff_id,stall_id,assigned_at) VALUES(?,?,?)',
               (staff_id, stall_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    db.commit()
    return True


def assigned_stall_ids(db, staff_id):
    return [r['stall_id'] for r in db.execute('SELECT stall_id FROM staff_stalls WHERE staff_id=?', (staff_id,))]


def staff_groups(db, staff_id):
    rows = db.execute('''SELECT so.*,o.order_number,o.created_at AS order_created_at,o.payment_status,
                                o.payment_channel,o.fulfillment_method,o.delivery_location,o.customer_comment,
                                u.name AS customer_name,s.name AS stall_name
                         FROM stall_orders so JOIN orders o ON o.id=so.order_id
                         JOIN users u ON u.id=o.user_id JOIN stalls s ON s.id=so.stall_id
                         JOIN staff_stalls ss ON ss.stall_id=so.stall_id
                         WHERE ss.staff_id=? ORDER BY so.id DESC''', (staff_id,)).fetchall()
    result=[]
    for row in rows:
        item_rows=db.execute('''SELECT oi.quantity,oi.price,m.name FROM order_items oi
                                JOIN menu_items m ON m.id=oi.menu_item_id
                                WHERE oi.order_id=? AND oi.stall_id=? ORDER BY m.name''',
                             (row['order_id'],row['stall_id'])).fetchall()
        item_list=[dict(x) for x in item_rows]
        item=dict(row)
        item['items']=item_list
        item['stall_total']=sum(x['quantity']*x['price'] for x in item_list)
        result.append(item)
    return result


def group_detail(db, stall_order_id, staff_id):
    group = db.execute('''SELECT so.*,s.name AS stall_name,o.order_number,o.payment_status,
                                 o.payment_channel,o.fulfillment_method,o.delivery_location,o.customer_comment,
                                 u.name AS customer_name
                          FROM stall_orders so JOIN stalls s ON s.id=so.stall_id
                          JOIN orders o ON o.id=so.order_id JOIN users u ON u.id=o.user_id
                          JOIN staff_stalls ss ON ss.stall_id=so.stall_id
                          WHERE so.id=? AND ss.staff_id=?''', (stall_order_id, staff_id)).fetchone()
    if not group:
        return None
    items = db.execute('''SELECT oi.quantity,oi.price,m.name,m.category
                          FROM order_items oi JOIN menu_items m ON m.id=oi.menu_item_id
                          WHERE oi.order_id=? AND oi.stall_id=?''', (group['order_id'], group['stall_id'])).fetchall()
    result = dict(group)
    result['items'] = [dict(x) for x in items]
    return result


def update_group_status(db, stall_order_id, staff_id, status):
    allowed = {'Received','Preparing','Ready','OTW','Completed','Cancelled'}
    if status not in allowed:
        return False
    group = db.execute('''SELECT so.order_id,so.status,o.fulfillment_method FROM stall_orders so
                          JOIN orders o ON o.id=so.order_id
                          JOIN staff_stalls ss ON ss.stall_id=so.stall_id
                          WHERE so.id=? AND ss.staff_id=?''', (stall_order_id, staff_id)).fetchone()
    if not group or (group['status'] in ('Completed','Cancelled') and status != group['status']):
        return False
    # OTW is meaningful only for delivery orders; pickup orders go Ready -> Completed.
    if status == 'OTW' and str(group['fulfillment_method'] or '').strip().lower() != 'delivery':
        return False
    stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    full = db.execute('SELECT order_id,stall_id FROM stall_orders WHERE id=?', (stall_order_id,)).fetchone()
    db.execute('UPDATE stall_orders SET status=?,updated_at=? WHERE id=?', (status, stamp, stall_order_id))
    if status == 'Cancelled' and group['status'] != 'Cancelled':
        line_items = db.execute('SELECT menu_item_id,quantity FROM order_items WHERE order_id=? AND stall_id=?',
                                (full['order_id'], full['stall_id'])).fetchall()
        for item in line_items:
            db.execute('UPDATE menu_items SET stock=stock+?,stock_deducted=MAX(0,stock_deducted-?),available=1 WHERE id=?',
                       (item['quantity'], item['quantity'], item['menu_item_id']))
        refund_amount=db.execute('SELECT COALESCE(SUM(price*quantity),0) AS amount FROM order_items WHERE order_id=? AND stall_id=?',(full['order_id'],full['stall_id'])).fetchone()['amount']
        db.execute("UPDATE stall_earnings SET gross_amount=MAX(0,gross_amount-?),net_amount=MAX(0,net_amount-?),settlement_status='On Hold' WHERE order_id=? AND stall_id=?",
                   (refund_amount,refund_amount,full['order_id'], full['stall_id']))
        paid_order=db.execute('SELECT user_id,payment_status FROM orders WHERE id=?',(full['order_id'],)).fetchone()
        if paid_order and paid_order['payment_status'] in ('PAID','PAID (DEMO)'):
            db.execute("""INSERT INTO refund_requests(order_id,stall_id,requested_by,amount,reason,status,created_at,updated_at)
                        SELECT ?,?,?,?,?, 'Pending',?,? WHERE NOT EXISTS(
                          SELECT 1 FROM refund_requests WHERE order_id=? AND stall_id=? AND status IN ('Pending','Approved','Processed'))""",
                       (full['order_id'],full['stall_id'],paid_order['user_id'],refund_amount,'Cancelled by stall staff; administrator review required',stamp,stamp,full['order_id'],full['stall_id']))
            db.execute('INSERT INTO user_notifications(user_id,title,message,link,created_at) VALUES(?,?,?,?,?)',
                       (paid_order['user_id'],'Stall portion cancelled',f'A stall cancelled part of order #{full["order_id"]}. A refund review is pending.',f'/orders/{full["order_id"]}',stamp))
            admins=db.execute("SELECT id FROM users WHERE role='admin'").fetchall()
            for admin in admins:
                db.execute('INSERT INTO user_notifications(user_id,title,message,link,created_at) VALUES(?,?,?,?,?)',
                           (admin['id'],'Refund review required',f'Order #{full["order_id"]} has a staff-initiated cancellation.', '/admin',stamp))
        db.execute("""UPDATE orders SET total=(SELECT COALESCE(SUM(oi.price*oi.quantity),0)
                       FROM order_items oi JOIN stall_orders active_so ON active_so.order_id=oi.order_id
                       AND active_so.stall_id=oi.stall_id WHERE oi.order_id=? AND active_so.status!='Cancelled')
                       WHERE id=?""", (full['order_id'], full['order_id']))
        db.execute("UPDATE orders SET original_total=total WHERE id=? AND payment_status IN ('CASH DUE','UNPAID','AWAITING ONLINE PAYMENT')",(full['order_id'],))
    statuses = [r['status'] for r in db.execute('SELECT status FROM stall_orders WHERE order_id=?', (group['order_id'],))]
    terminal={'Completed','Cancelled'}
    if statuses and all(x in terminal for x in statuses):
        overall = 'Cancelled' if all(x == 'Cancelled' for x in statuses) else 'Completed'
    else:
        active=[x for x in statuses if x not in terminal]
        rank={'Received':0,'Preparing':1,'Ready':2,'OTW':3,'Completed':4,'Cancelled':4}
        overall=min(active,key=lambda x:rank.get(x,0)) if active else 'Received'
    db.execute('UPDATE orders SET status=? WHERE id=?', (overall, group['order_id']))
    db.commit()
    return True
