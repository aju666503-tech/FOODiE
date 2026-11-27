"""FOODíE data model, SQLite persistence, and business rules."""

import sqlite3
import hashlib
import secrets
import hmac
from datetime import datetime, timedelta
from pathlib import Path
from payment_gateway import DemoPaymentGateway

DB_NAME = str(Path(__file__).resolve().parent / 'database' / 'canteen.db')
PBKDF2_ITERATIONS = 310_000
POLICY_VERSION = '1.1'

def now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def pw_hash(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"

def verify_password(password, stored):
    try:
        algorithm, iterations, salt_hex, digest_hex = stored.split('$', 3)
        if algorithm != 'pbkdf2_sha256':
            return False
        digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt_hex), int(iterations))
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False

def db():
    c = sqlite3.connect(DB_NAME, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    c.execute('PRAGMA journal_mode=WAL')
    return c

def init_db():
    c = db()
    c.executescript('''
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT NOT NULL,
        department TEXT,
        student_id TEXT,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS menu_items(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        category TEXT NOT NULL,
        description TEXT,
        price REAL NOT NULL,
        available INTEGER NOT NULL DEFAULT 1,
        stock INTEGER NOT NULL DEFAULT 25,
        prep_time INTEGER NOT NULL DEFAULT 5,
        calories INTEGER NOT NULL DEFAULT 400
    );

    CREATE TABLE IF NOT EXISTS orders(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_number TEXT UNIQUE NOT NULL,
        user_id INTEGER NOT NULL,
        total REAL NOT NULL,
        payment_channel TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        payment_status TEXT NOT NULL DEFAULT 'UNPAID',
        payment_reference TEXT,
        fulfillment_method TEXT NOT NULL DEFAULT 'Pickup',
        delivery_location TEXT,
        payment_timing TEXT NOT NULL DEFAULT 'Pay Later',
        FOREIGN KEY(user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS order_items(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL,
        menu_item_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL,
        price REAL NOT NULL,
        FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE,
        FOREIGN KEY(menu_item_id) REFERENCES menu_items(id)
    );

    CREATE TABLE IF NOT EXISTS logs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        action TEXT NOT NULL,
        details TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS user_notifications(
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        title TEXT NOT NULL, message TEXT NOT NULL, link TEXT, created_at TEXT NOT NULL, read_at TEXT
    );
    CREATE TABLE IF NOT EXISTS refund_requests(
        id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
        stall_id INTEGER REFERENCES stalls(id), requested_by INTEGER REFERENCES users(id), amount REAL NOT NULL DEFAULT 0,
        reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Pending' CHECK(status IN ('Pending','Approved','Rejected','Processed')),
        admin_note TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS inventory_movements(
        id INTEGER PRIMARY KEY AUTOINCREMENT, menu_item_id INTEGER NOT NULL REFERENCES menu_items(id),
        movement_type TEXT NOT NULL, quantity INTEGER NOT NULL, stock_before INTEGER NOT NULL,
        stock_after INTEGER NOT NULL, note TEXT, actor_id INTEGER REFERENCES users(id), created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_notifications_user_read ON user_notifications(user_id,read_at);
    CREATE INDEX IF NOT EXISTS idx_refunds_status ON refund_requests(status,created_at);
    CREATE TABLE IF NOT EXISTS policy_acceptances(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        policy_type TEXT NOT NULL CHECK(policy_type IN ('privacy','terms')),
        version TEXT NOT NULL,
        accepted_at TEXT NOT NULL,
        UNIQUE(user_id,policy_type,version),
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS order_view_hides(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL,
        viewer_id INTEGER NOT NULL,
        viewer_role TEXT NOT NULL,
        hidden_at TEXT NOT NULL,
        UNIQUE(order_id, viewer_id, viewer_role),
        FOREIGN KEY(order_id) REFERENCES orders(id),
        FOREIGN KEY(viewer_id) REFERENCES users(id)
    );
    ''')

    order_cols = {r['name'] for r in c.execute('PRAGMA table_info(orders)').fetchall()}
    if 'original_total' not in order_cols:
        c.execute('ALTER TABLE orders ADD COLUMN original_total REAL NOT NULL DEFAULT 0')
    if 'customer_comment' not in order_cols:
        c.execute('ALTER TABLE orders ADD COLUMN customer_comment TEXT')
    c.execute('UPDATE orders SET original_total=total WHERE original_total=0')
    menu_cols = {r['name'] for r in c.execute('PRAGMA table_info(menu_items)').fetchall()}
    for col, definition in (('stock_total','INTEGER NOT NULL DEFAULT 25'),('stock_deducted','INTEGER NOT NULL DEFAULT 0'),('low_stock_threshold','INTEGER NOT NULL DEFAULT 5')):
        if col not in menu_cols: c.execute(f'ALTER TABLE menu_items ADD COLUMN {col} {definition}')
    c.execute('UPDATE menu_items SET stock_total=stock WHERE stock_total=25 AND stock!=25 AND stock_deducted=0')
    import multi_stall

    # Seed the original FOODíE catalog before multi-stall products are added.
    if c.execute('SELECT COUNT(*) n FROM menu_items').fetchone()['n'] == 0:
        c.executemany(
            'INSERT INTO menu_items(name,category,description,price,available,stock,prep_time,calories) VALUES(?,?,?,?,1,?,?,?)',
            [
                ('Chicken Rice Meal', 'Meals', 'Crispy fried chicken with fragrant garlic rice, gravy, and pickled atchara.', 95.0, 25, 5, 580),
                ('Beef Tapa Meal', 'Meals', 'Marinated tender beef tapa served with garlic rice and sunny-side egg.', 110.0, 20, 7, 620),
                ('Pancit Canton Special', 'Meals', 'Classic stir-fried noodles with crisp vegetables and savory chicken.', 75.0, 30, 6, 440),
                ('Siomai Rice Supreme', 'Meals', 'Four pieces steamed pork & shrimp siomai with chili garlic and soy dip.', 65.0, 35, 4, 410),
                ('Sinigang Pork Rice', 'Soup Meals', 'Tender pork cuts in savory sour tamarind broth with vegetables and rice.', 120.0, 18, 8, 520),
                ('Bulalo Soup Meal', 'Soup Meals', 'Rich slow-simmered beef shank marrow soup with sweet corn cob and rice.', 135.0, 15, 8, 680),
                ('Lumpiang Shanghai (5 pcs)', 'Appetizers', 'Crispy minced pork spring rolls with sweet chili dipping sauce.', 60.0, 28, 4, 320),
                ('Crispy Calamares', 'Appetizers', 'Golden breaded squid rings with seasoned garlic dipping vinegar.', 85.0, 22, 6, 380),
                ('Traditional Leche Flan', 'Desserts', 'Velvety smooth caramel egg custard prepared with whole milk.', 45.0, 20, 2, 260),
                ('Turon with Langka (2 pcs)', 'Desserts', 'Crispy caramelized wrapper filled with ripe saba banana and jackfruit.', 35.0, 25, 3, 290),
                ('Signature Berry Iced Tea', 'Drinks', 'Canteen-brewed cold black tea infused with wild berries and calamansi.', 35.0, 40, 1, 120),
                ('Bottled Mineral Water', 'Drinks', 'Pure 500ml sealed chilled drinking mineral water bottle.', 25.0, 50, 1, 0)
            ]
        )

    multi_stall.migrate(c)
    c.execute('UPDATE menu_items SET stock_total=stock WHERE stock_total=25 AND stock!=25 AND stock_deducted=0')
    c.commit()
    c.close()

def log(uid, action, details=''):
    c = db()
    c.execute('INSERT INTO logs(user_id, action, details, created_at) VALUES(?,?,?,?)', (uid, action, details, now()))
    c.commit()
    c.close()

def authenticate(email, password):
    c = db()
    row = c.execute('SELECT * FROM users WHERE email=?', (email.strip().lower(),)).fetchone()
    c.close()
    if row and row['role'] in ('customer', 'staff', 'admin') and verify_password(password, row['password']):
        user = dict(row)
        log(user['id'], f"Logged into {user['role'].upper()} portal")
        return user
    return None

def has_admin():
    c = db()
    exists = c.execute("SELECT 1 FROM users WHERE role='admin' LIMIT 1").fetchone() is not None
    c.close()
    return exists

def create_first_admin(name, email, password):
    c = db()
    try:
        if c.execute("SELECT 1 FROM users WHERE role='admin' LIMIT 1").fetchone():
            return False, 'An administrator account has already been created.'
        c.execute(
            'INSERT INTO users(name,email,password,role,department,student_id,created_at) VALUES(?,?,?,?,?,?,?)',
            (name.strip(), email.strip().lower(), pw_hash(password), 'admin', 'FOODíE Administration', None, now())
        )
        c.commit()
        return True, None
    except sqlite3.IntegrityError:
        return False, 'That email address is already registered.'
    finally:
        c.close()

def register(name, email, password, student_id='', department='Customer', privacy_accepted=False, terms_accepted=False):
    if not privacy_accepted or not terms_accepted:
        return None, 'Please accept the Privacy Policy and Terms & Conditions.'
    c = db()
    try:
        cur = c.execute(
            'INSERT INTO users(name,email,password,role,department,student_id,created_at) VALUES(?,?,?,?,?,?,?)',
            (name.strip(), email.strip().lower(), pw_hash(password), 'customer', department, student_id.strip(), now())
        )
        uid = cur.lastrowid
        c.executemany('INSERT INTO policy_acceptances(user_id,policy_type,version,accepted_at) VALUES(?,?,?,?)',
                      [(uid,'privacy',POLICY_VERSION,now()),(uid,'terms',POLICY_VERSION,now())])
        c.commit()
        log(uid, 'Customer Account Registered')
        return uid, None
    except sqlite3.IntegrityError:
        return None, 'Email address is already registered.'
    finally:
        c.close()

def has_current_policies(uid):
    c=db()
    count=c.execute("SELECT COUNT(DISTINCT policy_type) FROM policy_acceptances WHERE user_id=? AND version=? AND policy_type IN ('privacy','terms')",(uid,POLICY_VERSION)).fetchone()[0]
    c.close()
    return count == 2


def accept_current_policies(uid):
    c=db()
    stamp=now()
    c.executemany('INSERT OR IGNORE INTO policy_acceptances(user_id,policy_type,version,accepted_at) VALUES(?,?,?,?)',
                  [(uid,'privacy',POLICY_VERSION,stamp),(uid,'terms',POLICY_VERSION,stamp)])
    c.commit(); c.close()
    log(uid, 'Accepted current Privacy Policy and Terms & Conditions', f'Version {POLICY_VERSION}')


def menu(search='', category='All'):
    c = db()
    q = 'SELECT m.*, s.name AS stall_name FROM menu_items m LEFT JOIN stalls s ON s.id=m.stall_id WHERE 1=1'
    p = []
    if search:
        q += ' AND (m.name LIKE ? OR m.description LIKE ?)'
        p += [f'%{search}%', f'%{search}%']
    if category != 'All':
        q += ' AND m.category=?'
        p.append(category)
    rows = c.execute(q + ' ORDER BY m.category, m.name', p).fetchall()
    c.close()
    return [dict(x) for x in rows]

def categories():
    return ['Meals', 'Soup Meals', 'Appetizers', 'Desserts', 'Drinks']

def save_item(item_id, name, cat, desc, price, available, stock, prep_time=5, calories=400, stall_id=None):
    c = db()
    if stall_id is not None and not c.execute('SELECT 1 FROM stalls WHERE id=?', (stall_id,)).fetchone():
        c.close()
        raise ValueError('Unknown stall assignment.')
    if item_id:
        old = c.execute('SELECT stock,stock_total,stock_deducted FROM menu_items WHERE id=?', (item_id,)).fetchone()
        if old:
            delta = int(stock) - int(old['stock'])
            total = int(old['stock_total']) + max(delta, 0)
            deducted = max(0, int(old['stock_deducted']) - min(delta, 0))
            if delta:
                c.execute('INSERT INTO inventory_movements(menu_item_id,movement_type,quantity,stock_before,stock_after,note,created_at) VALUES(?,?,?,?,?,?,?)',
                          (item_id, 'Restock' if delta > 0 else 'Manual adjustment', abs(delta), old['stock'], stock, 'Admin inventory adjustment', now()))
            c.execute('UPDATE menu_items SET name=?,category=?,description=?,price=?,available=?,stock=?,stock_total=?,stock_deducted=?,prep_time=?,calories=?,stall_id=? WHERE id=?',
                      (name, cat, desc, price, available, stock, total, deducted, prep_time, calories, stall_id, item_id))
    else:
        c.execute('INSERT INTO menu_items(name,category,description,price,available,stock,stock_total,stock_deducted,prep_time,calories,stall_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                  (name, cat, desc, price, available, stock, stock, 0, prep_time, calories, stall_id))
    c.commit()
    c.close()

def delete_item(item_id):
    c = db()
    c.execute('DELETE FROM menu_items WHERE id=?', (item_id,))
    c.commit()
    c.close()

def toggle_item(item_id):
    c = db()
    c.execute('UPDATE menu_items SET available=1-available WHERE id=?', (item_id,))
    c.commit()
    c.close()

def update_stock(item_id, delta, actor_id=None, note='Manual stock adjustment'):
    c=db(); row=c.execute('SELECT stock,stock_total,stock_deducted FROM menu_items WHERE id=?',(item_id,)).fetchone()
    if not row: c.close(); return False
    before=int(row['stock']); after=max(0,before+int(delta)); actual=after-before
    total=int(row['stock_total'])+max(actual,0); deducted=max(0,int(row['stock_deducted'])-min(actual,0))
    c.execute('UPDATE menu_items SET stock=?,stock_total=?,stock_deducted=?,available=CASE WHEN ?=0 THEN 0 ELSE available END WHERE id=?',(after,total,deducted,after,item_id))
    if actual: c.execute('INSERT INTO inventory_movements(menu_item_id,movement_type,quantity,stock_before,stock_after,note,actor_id,created_at) VALUES(?,?,?,?,?,?,?,?)',(item_id,'Restock' if actual>0 else 'Manual usage',abs(actual),before,after,note,actor_id,now()))
    c.commit(); c.close(); return True


def set_stock_left(item_id, stock_left, actor_id=None):
    c=db(); row=c.execute('SELECT stock FROM menu_items WHERE id=?',(item_id,)).fetchone(); c.close()
    return update_stock(item_id,int(stock_left)-int(row['stock']),actor_id,'Staff updated stock left') if row else False


def notify(user_id,title,message,link=None):
    if not user_id: return
    c=db(); c.execute('INSERT INTO user_notifications(user_id,title,message,link,created_at) VALUES(?,?,?,?,?)',(user_id,title,message,link,now())); c.commit(); c.close()


def notifications(user_id,limit=30):
    c=db(); rows=c.execute('SELECT * FROM user_notifications WHERE user_id=? ORDER BY id DESC LIMIT ?',(user_id,limit)).fetchall(); c.close(); return [dict(r) for r in rows]


def mark_notifications_read(user_id):
    c=db(); c.execute('UPDATE user_notifications SET read_at=? WHERE user_id=? AND read_at IS NULL',(now(),user_id)); c.commit(); c.close()


def low_stock_items(stall_ids=None):
    c=db(); q='SELECT m.*,s.name AS stall_name FROM menu_items m LEFT JOIN stalls s ON s.id=m.stall_id WHERE m.stock<=m.low_stock_threshold'; params=[]
    if stall_ids is not None:
        if not stall_ids: c.close(); return []
        q+=' AND m.stall_id IN ('+','.join('?' for _ in stall_ids)+')'; params.extend(stall_ids)
    rows=c.execute(q+' ORDER BY m.stock,m.name',params).fetchall(); c.close(); return [dict(r) for r in rows]


def sales_analytics(days=7,stall_ids=None):
    c=db(); params=[(datetime.now().date()-timedelta(days=max(1,int(days)-1))).strftime('%Y-%m-%d')]
    q="""SELECT date(o.created_at) AS sale_date,COUNT(DISTINCT o.id) AS orders,
             COALESCE(SUM(CASE WHEN o.payment_status IN ('PAID','PAID (DEMO)','PARTIALLY REFUNDED','REFUND PENDING','REFUNDED') THEN oi.price*oi.quantity ELSE 0 END),0) AS sales
             FROM orders o JOIN order_items oi ON oi.order_id=o.id JOIN stall_orders so ON so.order_id=oi.order_id AND so.stall_id=oi.stall_id AND so.status!='Cancelled' WHERE date(o.created_at)>=date(?)"""
    if stall_ids is not None:
        if not stall_ids: c.close(); return []
        q+=' AND oi.stall_id IN ('+','.join('?' for _ in stall_ids)+')'; params.extend(stall_ids)
    rows=c.execute(q+' GROUP BY date(o.created_at) ORDER BY sale_date DESC',params).fetchall(); c.close(); return [dict(r) for r in rows]


def get_item(item_id):
    c = db()
    r = c.execute('SELECT m.*,s.name AS stall_name,s.status AS stall_status FROM menu_items m LEFT JOIN stalls s ON s.id=m.stall_id WHERE m.id=?', (item_id,)).fetchone()
    c.close()
    return dict(r) if r else None

def create_order(uid, cart, payment_timing, fulfillment_method, delivery_location='', payment_provider=None, customer_comment=''):
    c = db()
    try:
        c.execute('BEGIN IMMEDIATE')
        valid=[]; total=0
        for iid, qty in cart.items():
            r=c.execute('SELECT m.*,s.status AS stall_status FROM menu_items m LEFT JOIN stalls s ON s.id=m.stall_id WHERE m.id=?',(iid,)).fetchone()
            if not r or not r['available'] or r['stall_id'] is None or r['stall_status'] not in ('Open','Busy') or int(qty)<1 or int(qty)>r['stock']:
                c.rollback(); return None
            valid.append((r,int(qty))); total += r['price']*int(qty)
        if not valid: c.rollback(); return None
        if payment_timing == 'Pay Now':
            initial_status='Received'; initial_payment_status='AWAITING ONLINE PAYMENT'
            payment_channel=f'{payment_provider} / QR-E-wallet' if payment_provider else 'Online Payment'
        else:
            initial_status='Received'; initial_payment_status='CASH DUE'; payment_channel=f'Cash on {fulfillment_method or "Pickup"}'
        order_no='ORD-'+datetime.now().strftime('%Y%m%d%H%M%S')+'-'+secrets.token_hex(2).upper()
        customer_comment=(customer_comment or '').strip()[:500]
        cur=c.execute("INSERT INTO orders(order_number,user_id,total,original_total,payment_channel,status,created_at,payment_status,payment_reference,fulfillment_method,delivery_location,payment_timing,customer_comment) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(order_no,uid,total,total,payment_channel,initial_status,now(),initial_payment_status,None,fulfillment_method,delivery_location.strip() if delivery_location else None,payment_timing,customer_comment or None))
        oid=cur.lastrowid
        for r,q in valid:
            c.execute('INSERT INTO order_items(order_id,menu_item_id,quantity,price,stall_id) VALUES(?,?,?,?,?)',(oid,r['id'],q,r['price'],r['stall_id']))
            before_stock=int(r['stock'])
            c.execute('UPDATE menu_items SET stock=stock-?,stock_deducted=stock_deducted+?,available=CASE WHEN stock-?<=0 THEN 0 ELSE available END WHERE id=?',(q,q,q,r['id']))
            c.execute('INSERT INTO inventory_movements(menu_item_id,movement_type,quantity,stock_before,stock_after,note,created_at) VALUES(?,?,?,?,?,?,?)',(r['id'],'Order deduction',q,before_stock,before_stock-q,'Customer order',now()))
        stall_totals = {}
        for r, q in valid:
            if r['stall_id'] is not None:
                stall_totals[r['stall_id']] = stall_totals.get(r['stall_id'], 0.0) + float(r['price']) * q
        for stall_id, amount in stall_totals.items():
            c.execute('INSERT INTO stall_orders(order_id,stall_id,status,created_at,updated_at) VALUES(?,?,?,?,?)',
                      (oid, stall_id, 'Received', now(), now()))
            c.execute('INSERT INTO stall_earnings(order_id,stall_id,gross_amount,fee_amount,net_amount,created_at) VALUES(?,?,?,0,?,?)',
                      (oid, stall_id, amount, amount, now()))
        c.commit()
    except Exception:
        c.rollback(); raise
    finally: c.close()
    log(uid,f'Created order {order_no}',f'₱{total:.2f} · {fulfillment_method}')
    notify(uid,'Order received',f'Your order {order_no} has been received.',f'/orders/{oid}')
    c=db(); staff_rows=c.execute('SELECT DISTINCT ss.staff_id,s.name FROM stall_orders so JOIN staff_stalls ss ON ss.stall_id=so.stall_id JOIN stalls s ON s.id=so.stall_id WHERE so.order_id=?',(oid,)).fetchall(); c.close()
    for sr in staff_rows: notify(sr['staff_id'],'New stall order',f'Order {order_no} includes items for {sr["name"]}.','/staff')
    return oid

def complete_demo_online_payment(oid, uid, provider='GCash'):
    c = db()
    row = c.execute('SELECT * FROM orders WHERE id=? AND user_id=?', (oid, uid)).fetchone()
    if not row or row['payment_status'] != 'AWAITING ONLINE PAYMENT':
        c.close()
        return False
    demo_session = DemoPaymentGateway().create_payment_session(row['order_number'], row['total'])
    reference = f"{demo_session['reference']}-{provider.upper()}"
    c.execute(
        "UPDATE orders SET payment_status='PAID (DEMO)', payment_reference=? WHERE id=?",
        (reference, oid)
    )
    c.commit()
    c.close()
    log(uid, f"Demo payment simulated for {row['order_number']}", f"Demo reference: {reference}; no funds transferred")
    return True

def set_payment_status(oid, status, staff_uid):
    allowed = {'PAID', 'PAID (DEMO)', 'UNPAID', 'PENDING', 'REFUNDED', 'CASH DUE', 'AWAITING ONLINE PAYMENT'}
    status = status.strip().upper()
    if status not in allowed:
        return False
    c = db()
    row = c.execute('SELECT order_number FROM orders WHERE id=?', (oid,)).fetchone()
    if not row:
        c.close()
        return False
    reference = None if status in ('UNPAID', 'PENDING', 'CASH DUE', 'AWAITING ONLINE PAYMENT') else f"STAFF-{secrets.token_hex(3).upper()}"
    c.execute('UPDATE orders SET payment_status=?, payment_reference=? WHERE id=?', (status, reference, oid))
    c.commit()
    c.close()
    log(staff_uid, f"Staff updated payment status for {row['order_number']} to {status}")
    return True

def confirm_stall_cash_payment(stall_order_id, staff_uid):
    """Record cash received by an assigned staff member for their stall only."""
    c = db()
    try:
        c.execute('BEGIN IMMEDIATE')
        group = c.execute("""SELECT so.id,so.order_id,so.stall_id,so.status,o.payment_status,o.order_number,o.user_id
                            FROM stall_orders so JOIN orders o ON o.id=so.order_id
                            JOIN staff_stalls ss ON ss.stall_id=so.stall_id
                            WHERE so.id=? AND ss.staff_id=?""", (stall_order_id, staff_uid)).fetchone()
        if not group or group['payment_status'] != 'CASH DUE' or group['status'] == 'Cancelled':
            c.rollback()
            return False
        if c.execute('SELECT cash_received_at FROM stall_orders WHERE id=?', (stall_order_id,)).fetchone()['cash_received_at']:
            c.rollback()
            return False
        stamp = now()
        c.execute('UPDATE stall_orders SET cash_received_at=?,cash_received_by=? WHERE id=?',
                  (stamp, staff_uid, stall_order_id))
        remaining = c.execute("""SELECT COUNT(*) AS n FROM stall_orders
                                WHERE order_id=? AND status!='Cancelled' AND cash_received_at IS NULL""",
                              (group['order_id'],)).fetchone()['n']
        if remaining == 0:
            ref = f"CASH-{secrets.token_hex(4).upper()}"
            c.execute("UPDATE orders SET payment_status='PAID',payment_reference=? WHERE id=? AND payment_status='CASH DUE'",
                      (ref, group['order_id']))
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()
    log(staff_uid, f"Cash received for {group['order_number']}", f"Stall order #{stall_order_id}")
    c=db(); status=c.execute('SELECT payment_status FROM orders WHERE id=?',(group['order_id'],)).fetchone(); c.close()
    if status and status['payment_status']=='PAID': notify(group['user_id'],'Cash payment confirmed','All active stall portions of your cash order have been confirmed. Your Digital OR is ready.',f'/orders/{group["order_id"]}')
    return True

def confirm_cash_payment(oid, staff_uid):
    c = db()
    row = c.execute('SELECT * FROM orders WHERE id=?', (oid,)).fetchone()
    if not row or row['payment_status'] != 'CASH DUE':
        c.close()
        return False
    ref = f"CASH-{secrets.token_hex(4).upper()}"
    c.execute("UPDATE orders SET payment_status='PAID', payment_reference=? WHERE id=?", (ref, oid))
    c.commit()
    c.close()
    log(staff_uid, f"Cash collected by staff for {row['order_number']}", f"Ref: {ref}")
    return True

def orders(uid=None, viewer_role=None, viewer_id=None):
    c = db()
    if uid:
        rows = c.execute(
            """SELECT o.*, u.name as customer_name FROM orders o
               JOIN users u ON u.id=o.user_id
               WHERE o.user_id=? AND NOT EXISTS (
                   SELECT 1 FROM order_view_hides h WHERE h.order_id=o.id AND h.viewer_id=? AND h.viewer_role='customer'
               ) ORDER BY o.id DESC""",
            (uid, uid)
        ).fetchall()
    elif viewer_role == 'staff' and viewer_id:
        rows = c.execute(
            """SELECT DISTINCT o.*,u.name AS customer_name FROM orders o
               JOIN users u ON u.id=o.user_id
               JOIN stall_orders so ON so.order_id=o.id
               JOIN staff_stalls ss ON ss.stall_id=so.stall_id
               WHERE ss.staff_id=? AND NOT EXISTS (
                   SELECT 1 FROM order_view_hides h WHERE h.order_id=o.id AND h.viewer_id=? AND h.viewer_role='staff'
               ) ORDER BY o.id DESC""",
            (viewer_id, viewer_id)
        ).fetchall()
    else:
        rows = c.execute(
            """SELECT o.*, u.name as customer_name FROM orders o
               JOIN users u ON u.id=o.user_id
               ORDER BY o.id DESC"""
        ).fetchall()
    c.close()
    return [dict(x) for x in rows]

def hide_order_history(viewer_id, viewer_role, order_ids):
    c = db()
    for oid in order_ids:
        c.execute('INSERT OR IGNORE INTO order_view_hides(order_id,viewer_id,viewer_role,hidden_at) VALUES(?,?,?,?)', (oid, viewer_id, viewer_role, now()))
    c.commit()
    c.close()
    log(viewer_id, f"{viewer_role.title()} cleared {len(order_ids)} orders from active screen")
    return True

def order(oid, uid=None):
    c = db()
    q = 'SELECT o.*, u.name as customer_name, u.email as customer_email FROM orders o JOIN users u ON u.id=o.user_id WHERE o.id=?'
    p = [oid]
    if uid:
        q += ' AND o.user_id=?'
        p.append(uid)
    r = c.execute(q, p).fetchone()
    if not r:
        c.close()
        return None
    items = c.execute(
        '''SELECT oi.*,m.name,m.category,s.name AS stall_name FROM order_items oi JOIN menu_items m ON m.id=oi.menu_item_id LEFT JOIN stalls s ON s.id=oi.stall_id WHERE oi.order_id=?''',
        (oid,)
    ).fetchall()
    groups = c.execute('''SELECT so.*,s.name AS stall_name,e.gross_amount,e.fee_amount,e.net_amount,e.settlement_status,rr.status AS refund_status FROM stall_orders so JOIN stalls s ON s.id=so.stall_id LEFT JOIN stall_earnings e ON e.order_id=so.order_id AND e.stall_id=so.stall_id LEFT JOIN refund_requests rr ON rr.id=(SELECT MAX(rr2.id) FROM refund_requests rr2 WHERE rr2.order_id=so.order_id AND rr2.stall_id=so.stall_id) WHERE so.order_id=? ORDER BY s.name''', (oid,)).fetchall()
    refunds = c.execute('SELECT * FROM refund_requests WHERE order_id=? ORDER BY id',(oid,)).fetchall()
    c.close()
    res = dict(r)
    res['items'] = [dict(i) for i in items]
    active_stalls={g['stall_id'] for g in groups if g['status']!='Cancelled'}
    res['active_items']=[dict(i) for i in items if i['stall_id'] in active_stalls]
    res['stall_orders'] = [dict(g) for g in groups]
    res['refund_requests'] = [dict(x) for x in refunds]
    res['refunds_processed'] = sum(float(x['amount']) for x in refunds if x['status']=='Processed')
    res['refunds_pending'] = sum(float(x['amount']) for x in refunds if x['status'] in ('Pending','Approved'))
    res['can_cancel'] = res['status'] in ('Received','Awaiting Payment') and all(g['status'] in ('Received','Cancelled') for g in res['stall_orders'])
    return res

def set_status(oid, status, staff_uid):
    allowed=('Received','Preparing','Ready','OTW','Completed','Cancelled')
    if status not in allowed: return False
    c=db()
    try:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT order_number,status,fulfillment_method FROM orders WHERE id=?',(oid,)).fetchone()
        if not row: c.rollback(); return False
        if status == 'OTW' and str(row['fulfillment_method'] or '').strip().lower() != 'delivery':
            c.rollback(); return False
        if row['status'] in ('Completed','Cancelled') and status != row['status']:
            c.rollback(); return False
        c.execute('UPDATE orders SET status=? WHERE id=?',(status,oid))
        if status=='Cancelled' and row['status']!='Cancelled':
            items=c.execute('SELECT menu_item_id,quantity FROM order_items WHERE order_id=?',(oid,)).fetchall()
            for item in items:
                c.execute('UPDATE menu_items SET stock=stock+?,stock_deducted=MAX(0,stock_deducted-?),available=1 WHERE id=?',(item['quantity'],item['quantity'],item['menu_item_id']))
        c.commit()
    except Exception:
        c.rollback(); raise
    finally: c.close()
    log(staff_uid,f"Updated Order {row['order_number']} status to {status}")
    detail=order(oid)
    if detail: notify(detail['user_id'],'Order status updated',f"Your order {row['order_number']} is now {status}.",f'/orders/{oid}')
    return True

def cancel(oid, uid):
    c=db()
    try:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute("SELECT order_number,payment_status,original_total FROM orders WHERE id=? AND user_id=? AND status IN ('Received','Awaiting Payment') AND NOT EXISTS (SELECT 1 FROM stall_orders so WHERE so.order_id=orders.id AND so.status NOT IN ('Received','Cancelled'))",(oid,uid)).fetchone()
        if not row:
            c.rollback(); return False
        portions=c.execute("SELECT so.stall_id,COALESCE(SUM(oi.price*oi.quantity),0) AS amount FROM stall_orders so JOIN order_items oi ON oi.order_id=so.order_id AND oi.stall_id=so.stall_id WHERE so.order_id=? AND so.status!='Cancelled' GROUP BY so.stall_id",(oid,)).fetchall()
        items=c.execute("SELECT oi.menu_item_id,oi.quantity FROM order_items oi LEFT JOIN stall_orders so ON so.order_id=oi.order_id AND so.stall_id=oi.stall_id WHERE oi.order_id=? AND (so.id IS NULL OR so.status!='Cancelled')",(oid,)).fetchall()
        for item in items:
            c.execute('UPDATE menu_items SET stock=stock+?,stock_deducted=MAX(0,stock_deducted-?),available=1 WHERE id=?',(item['quantity'],item['quantity'],item['menu_item_id']))
        paid=row['payment_status'] in ('PAID','PAID (DEMO)')
        if paid:
            for portion in portions:
                c.execute("INSERT INTO refund_requests(order_id,stall_id,requested_by,amount,reason,status,created_at,updated_at) VALUES(?,?,?,?,?,'Pending',?,?)",
                          (oid,portion['stall_id'],uid,portion['amount'],'Full order cancelled by customer; administrator refund review required',now(),now()))
                c.execute("UPDATE stall_earnings SET gross_amount=0,net_amount=0,settlement_status='On Hold' WHERE order_id=? AND stall_id=?",(oid,portion['stall_id']))
            c.execute("UPDATE orders SET status='Cancelled',total=0,payment_status='REFUND PENDING' WHERE id=?",(oid,))
        else:
            c.execute("UPDATE orders SET status='Cancelled',total=0,original_total=0,payment_status='CANCELLED' WHERE id=?",(oid,))
            c.execute("UPDATE stall_earnings SET gross_amount=0,net_amount=0,settlement_status='On Hold' WHERE order_id=?",(oid,))
        c.execute("UPDATE stall_orders SET status='Cancelled',updated_at=? WHERE order_id=?",(now(),oid))
        c.commit()
    except Exception:
        c.rollback(); raise
    finally: c.close()
    log(uid,f'Cancelled order {row["order_number"]}', 'Refund review created for paid order' if paid else 'Unpaid order cancelled; stock returned')
    notify(uid,'Order cancelled',f'Your order {row["order_number"]} has been cancelled.' + (' A refund review is pending.' if paid else ''),f'/orders/{oid}')
    if paid:
        c=db(); admins=c.execute("SELECT id FROM users WHERE role='admin'").fetchall(); c.close()
        for admin in admins: notify(admin['id'],'Full order refund review',f'Order {row["order_number"]} was cancelled after payment and needs refund review.','/admin')
    return True


def staff():
    c = db()
    r = c.execute("SELECT u.*,GROUP_CONCAT(s.name, ', ') AS assigned_stalls FROM users u LEFT JOIN staff_stalls ss ON ss.staff_id=u.id LEFT JOIN stalls s ON s.id=ss.stall_id WHERE u.role='staff' GROUP BY u.id ORDER BY u.name").fetchall()
    c.close()
    return [dict(x) for x in r]

def add_staff(name, email, password, dept='Food Service Operations', stall_id=None):
    c = db()
    try:
        c.execute(
            'INSERT INTO users(name,email,password,role,department,created_at) VALUES(?,?,?,?,?,?)',
            (name.strip(), email.strip().lower(), pw_hash(password), 'staff', dept, now())
        )
        staff_id = c.execute('SELECT last_insert_rowid()').fetchone()[0]
        if stall_id:
            valid_stall = c.execute('SELECT 1 FROM stalls WHERE id=?', (stall_id,)).fetchone()
            if not valid_stall:
                c.rollback()
                return False, 'Select a valid stall.'
            c.execute('INSERT INTO staff_stalls(staff_id,stall_id,assigned_at) VALUES(?,?,?)', (staff_id, stall_id, now()))
        c.commit()
        return True, None
    except sqlite3.IntegrityError:
        return False, 'Email already exists.'
    finally:
        c.close()

def remove_staff(uid):
    # Preserve historical order and audit references while disabling future sign-in.
    c = db()
    cur = c.execute("UPDATE users SET role='inactive_staff' WHERE id=? AND role='staff'", (uid,))
    c.commit()
    c.close()
    return cur.rowcount > 0

def logs():
    c = db()
    r = c.execute(
        """SELECT l.*, COALESCE(u.name, 'System') as user_name, COALESCE(u.role, 'system') as user_role
           FROM logs l LEFT JOIN users u ON u.id=l.user_id
           ORDER BY l.id DESC LIMIT 150"""
    ).fetchall()
    c.close()
    return [dict(x) for x in r]


def top_selling_items(days=30,stall_ids=None,limit=5):
    c=db(); params=[(datetime.now().date()-timedelta(days=max(1,int(days)-1))).strftime('%Y-%m-%d')]
    q="""SELECT m.name,s.name AS stall_name,SUM(oi.quantity) AS units,SUM(oi.quantity*oi.price) AS gross_sales
             FROM order_items oi JOIN orders o ON o.id=oi.order_id JOIN menu_items m ON m.id=oi.menu_item_id
             LEFT JOIN stalls s ON s.id=oi.stall_id JOIN stall_orders so ON so.order_id=oi.order_id
             AND so.stall_id=oi.stall_id AND so.status!='Cancelled'
             WHERE date(o.created_at)>=date(?) AND o.payment_status IN ('PAID','PAID (DEMO)','PARTIALLY REFUNDED','REFUND PENDING','REFUNDED')"""
    if stall_ids is not None:
        if not stall_ids: c.close(); return []
        q+=' AND oi.stall_id IN ('+','.join('?' for _ in stall_ids)+')'; params.extend(stall_ids)
    rows=c.execute(q+' GROUP BY oi.menu_item_id ORDER BY units DESC LIMIT ?',params+[int(limit)]).fetchall(); c.close(); return [dict(r) for r in rows]


def request_stall_refund(order_id, stall_order_id, user_id, reason):
    reason=(reason or '').strip()
    if len(reason)<5 or len(reason)>500: return False
    c=db()
    try:
        c.execute('BEGIN IMMEDIATE')
        group=c.execute("""SELECT so.stall_id,so.status,o.payment_status,COALESCE(SUM(oi.price*oi.quantity),0) AS amount
                          FROM stall_orders so JOIN orders o ON o.id=so.order_id
                          JOIN order_items oi ON oi.order_id=so.order_id AND oi.stall_id=so.stall_id
                          WHERE so.id=? AND so.order_id=? AND o.user_id=? GROUP BY so.id""",
                      (stall_order_id,order_id,user_id)).fetchone()
        if not group or group['status'] not in ('Received','Preparing'):
            c.rollback(); return False
        exists=c.execute("SELECT 1 FROM refund_requests WHERE order_id=? AND stall_id=? AND status IN ('Pending','Approved','Processed')",(order_id,group['stall_id'])).fetchone()
        if exists: c.rollback(); return False
        c.execute("INSERT INTO refund_requests(order_id,stall_id,requested_by,amount,reason,status,created_at,updated_at) VALUES(?,?,?,?,?,'Pending',?,?)",
                  (order_id,group['stall_id'],user_id,group['amount'],reason,now(),now()))
        # Keep the stall portion active until an administrator approves the request.
        c.commit()
    except Exception:
        c.rollback(); raise
    finally: c.close()
    notify(user_id,'Cancellation request submitted',f'Your ₱{group["amount"]:.2f} cancellation request is pending administrator review; the portion is not cancelled yet.',f'/orders/{order_id}')
    c=db(); admins=c.execute("SELECT id FROM users WHERE role='admin'").fetchall(); c.close()
    for a in admins: notify(a['id'],'Refund review required',f'Order #{order_id} has a partial cancellation/refund request.','/admin')
    return True


def review_refund(refund_id,status,note,admin_id):
    if status not in ('Approved','Rejected','Processed'): return False
    c=db()
    try:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT rr.*,o.payment_status,o.total AS order_total FROM refund_requests rr JOIN orders o ON o.id=rr.order_id WHERE rr.id=?',(refund_id,)).fetchone()
        if not row:
            c.rollback(); return False
        if status=='Approved' and row['status']=='Pending':
            group=c.execute('SELECT status FROM stall_orders WHERE order_id=? AND stall_id=?',(row['order_id'],row['stall_id'])).fetchone()
            if not group or group['status'] not in ('Received','Preparing','Cancelled'):
                c.rollback(); return False
            if group['status'] != 'Cancelled':
                c.execute("UPDATE stall_orders SET status='Cancelled',updated_at=? WHERE order_id=? AND stall_id=?",(now(),row['order_id'],row['stall_id']))
                items=c.execute('SELECT menu_item_id,quantity FROM order_items WHERE order_id=? AND stall_id=?',(row['order_id'],row['stall_id'])).fetchall()
                for item in items:
                    c.execute('UPDATE menu_items SET stock=stock+?,stock_deducted=MAX(0,stock_deducted-?),available=1 WHERE id=?',(item['quantity'],item['quantity'],item['menu_item_id']))
                c.execute("UPDATE orders SET total=MAX(0,total-?),original_total=CASE WHEN payment_status IN ('CASH DUE','UNPAID','AWAITING ONLINE PAYMENT') THEN MAX(0,total-?) ELSE original_total END WHERE id=?",(row['amount'],row['amount'],row['order_id']))
            c.execute("UPDATE stall_earnings SET gross_amount=MAX(0,gross_amount-?),net_amount=MAX(0,net_amount-?),settlement_status='On Hold' WHERE order_id=? AND stall_id=?",(row['amount'],row['amount'],row['order_id'],row['stall_id']))
            statuses=[x['status'] for x in c.execute('SELECT status FROM stall_orders WHERE order_id=?',(row['order_id'],)).fetchall()]
            if statuses and all(x=='Cancelled' for x in statuses): c.execute("UPDATE orders SET status='Cancelled' WHERE id=?",(row['order_id'],))
        elif status=='Rejected' and row['status']=='Pending':
            pass
        elif status=='Processed' and row['status']=='Approved':
            if row['payment_status'] in ('PAID','PAID (DEMO)','REFUND PENDING','PARTIALLY REFUNDED'):
                processed=c.execute("SELECT COALESCE(SUM(amount),0) FROM refund_requests WHERE order_id=? AND status='Processed'",(row['order_id'],)).fetchone()[0] + float(row['amount'])
                original=c.execute('SELECT original_total FROM orders WHERE id=?',(row['order_id'],)).fetchone()['original_total']
                new_payment='REFUNDED' if processed+0.0001>=float(original or 0) else 'PARTIALLY REFUNDED'
                c.execute('UPDATE orders SET payment_status=? WHERE id=?',(new_payment,row['order_id']))
        else:
            c.rollback(); return False
        c.execute('UPDATE refund_requests SET status=?,admin_note=?,updated_at=? WHERE id=?',(status,(note or '').strip()[:500],now(),refund_id))
        c.commit()
    except Exception:
        c.rollback(); raise
    finally: c.close()
    notify(row['requested_by'],'Refund request updated',f'Your cancellation/refund request for order #{row["order_id"]} is {status.lower()}.',f'/orders/{row["order_id"]}')
    log(admin_id,'Reviewed refund request',f'Refund #{refund_id}: {status}')
    return True
