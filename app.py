"""FOODíE responsive ordering platform — Flask application."""
import os, re, secrets, sqlite3, logging
from functools import wraps
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort, jsonify, send_file
import model

BASE = Path(__file__).resolve().parent
# Keep the original database in the project database directory for the web build.
model.DB_NAME = str(BASE / 'database' / 'canteen.db')
app = Flask(__name__, template_folder='frontend/templates', static_folder='frontend/static')
secret_key=os.environ.get('FOODIE_SECRET_KEY')
if not secret_key and os.environ.get('FOODIE_ENV') == 'production':
    raise RuntimeError('FOODIE_SECRET_KEY must be set in production.')
if not secret_key:
    secret_key=secrets.token_hex(32)
app.config.update(SECRET_KEY=secret_key,
                  SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                  SESSION_COOKIE_SECURE=os.environ.get('FOODIE_HTTPS', '0') == '1',
                  PERMANENT_SESSION_LIFETIME=60*60*8)

(BASE / 'logs').mkdir(exist_ok=True)
file_handler=logging.FileHandler(BASE/'logs'/'foodie.log',encoding='utf-8')
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
app.logger.addHandler(file_handler)
app.logger.setLevel(logging.INFO)

@app.after_request
def security_headers(response):
    response.headers.setdefault('X-Content-Type-Options','nosniff')
    response.headers.setdefault('X-Frame-Options','DENY')
    response.headers.setdefault('Referrer-Policy','strict-origin-when-cross-origin')
    response.headers.setdefault('Permissions-Policy','camera=(), microphone=(), geolocation=()')
    response.headers.setdefault('Content-Security-Policy', "default-src 'self' 'unsafe-inline' data:; img-src 'self' data: https:; font-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'")
    return response

def create_daily_backup():
    if os.environ.get('FOODIE_AUTO_BACKUP','1') != '1': return
    backup_dir=BASE/'backups'; backup_dir.mkdir(exist_ok=True)
    target=backup_dir/f'foodie-backup-{model.datetime.now().strftime("%Y%m%d")}.db'
    if target.exists(): return
    source=None; dest=None
    try:
        source=model.db(); dest=sqlite3.connect(str(target)); source.backup(dest)
        app.logger.info('Daily SQLite backup created: %s',target.name)
        old=sorted(backup_dir.glob('foodie-backup-*.db'),key=lambda x:x.stat().st_mtime,reverse=True)
        for item in old[7:]: item.unlink(missing_ok=True)
    except Exception:
        app.logger.exception('Daily SQLite backup failed')
        if target.exists(): target.unlink(missing_ok=True)
    finally:
        if dest: dest.close()
        if source: source.close()

@app.before_request
def setup():
    model.init_db()
    create_daily_backup()
    if 'csrf' not in session: session['csrf'] = secrets.token_urlsafe(24)

@app.context_processor
def inject():
    cart = session.get('cart', {})
    user=session.get('user')
    unread=0
    if user:
        c=model.db(); unread=c.execute('SELECT COUNT(*) FROM user_notifications WHERE user_id=? AND read_at IS NULL',(user['id'],)).fetchone()[0]; c.close()
    return {'current_user': user, 'cart_count': sum(int(v) for v in cart.values()), 'csrf_token': session.get('csrf'), 'admin_setup_available': not model.has_admin(), 'notification_count': unread}

def csrf_check():
    if request.method == 'POST' and not secrets.compare_digest(request.form.get('csrf_token',''), session.get('csrf','')):
        abort(400, 'Invalid form token. Refresh and try again.')
app.before_request_funcs.setdefault(None, []).append(csrf_check)

def login_required(fn):
    @wraps(fn)
    def wrapped(*a, **kw):
        if not session.get('user'): flash('Please sign in to continue.', 'error'); return redirect(url_for('login', next=request.path))
        fresh=user_refresh(session['user'].get('id'))
        if not fresh or fresh.get('role') not in ('customer','staff','admin'):
            session.clear(); flash('This account is no longer active.','error'); return redirect(url_for('login'))
        session['user']=fresh
        if fresh.get('role')=='customer' and not model.has_current_policies(fresh['id']) and request.endpoint not in ('policy_acceptance','logout'):
            return redirect(url_for('policy_acceptance'))
        return fn(*a, **kw)
    return wrapped

def roles(*allowed):
    def deco(fn):
        @wraps(fn)
        @login_required
        def wrapped(*a, **kw):
            if session['user']['role'] not in allowed: abort(403)
            return fn(*a, **kw)
        return wrapped
    return deco

def valid_password(p): return 10 <= len(p) <= 128 and any(x.islower() for x in p) and any(x.isupper() for x in p) and any(x.isdigit() for x in p)
def user_refresh(uid):
    c=model.db(); r=c.execute('SELECT id,name,email,role,department FROM users WHERE id=?',(uid,)).fetchone(); c.close(); return dict(r) if r else None

@app.get('/health')
def health():
    return jsonify({'status': 'ok', 'application': 'FOODiE'})


@app.get('/')
def home():
    import multi_stall
    search=request.args.get('q','').strip(); cat=request.args.get('category','All'); stall_filter=request.args.get('stall','').strip()
    c=model.db()
    stall_list=multi_stall.list_stalls(c,active_only=True)
    c.close()
    open_ids={x['id'] for x in stall_list}
    items=[x for x in model.menu(search,cat) if x['available'] and x['stock']>0 and x['stall_id'] in open_ids]
    if stall_filter:
        try: items=[x for x in items if x['stall_id']==int(stall_filter)]
        except ValueError: items=[]
    c=model.db()
    for item in items:
        row=c.execute('SELECT name,status FROM stalls WHERE id=?',(item['stall_id'],)).fetchone()
        item['stall_name']=row['name'] if row else 'Unassigned'
        item['stall_status']=row['status'] if row else 'Unavailable'
    c.close()
    return render_template('home.html',items=items,categories=model.categories(),search=search,category=cat,stalls=stall_list,stall_filter=stall_filter)

@app.get('/manifest.json')
def manifest(): return app.send_static_file('manifest.json')
@app.get('/service-worker.js')
def sw():
    from flask import send_from_directory
    return send_from_directory(BASE, 'service-worker.js', mimetype='application/javascript')

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method=='GET' and request.args.get('resume_policy') != '1':
        session['policy_reviewed'] = []
    if request.method=='POST':
        name=request.form.get('name','').strip(); email=request.form.get('email','').strip().lower(); pw=request.form.get('password',''); confirm=request.form.get('confirm','')
        if len(name)<2 or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',email): flash('Enter a valid name and email address.','error')
        elif not valid_password(pw): flash('Use at least 10 characters with uppercase, lowercase, and a number.','error')
        elif pw!=confirm: flash('Passwords do not match.','error')
        elif request.form.get('privacy_accepted')!='on' or request.form.get('terms_accepted')!='on' or not {'privacy','terms'}.issubset(set(session.get('policy_reviewed', []))): flash('Please open and review both the Privacy Policy and Terms & Conditions before accepting them.','error')
        else:
            uid,err=model.register(name,email,pw,privacy_accepted=True,terms_accepted=True)
            if err: flash(err,'error')
            else: session.clear(); session['user']=user_refresh(uid); session['cart']={}; session['csrf']=secrets.token_urlsafe(24); flash('Welcome to FOODíE!','success'); return redirect(url_for('home'))
    return render_template('auth.html', mode='register', policy_version=model.POLICY_VERSION)

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST':
        u=model.authenticate(request.form.get('email',''),request.form.get('password',''))
        if not u: flash('Invalid email or password.','error')
        else:
            session.clear(); session['user']=user_refresh(u['id']); session['cart']={}; session['csrf']=secrets.token_urlsafe(24); session.permanent=True
            if u['role']=='customer' and not model.has_current_policies(u['id']):
                return redirect(url_for('policy_acceptance'))
            next_url=request.args.get('next','')
            if not next_url.startswith('/') or next_url.startswith('//'): next_url=url_for('admin') if u['role']=='admin' else url_for('staff') if u['role']=='staff' else url_for('home')
            return redirect(next_url)
    return render_template('auth.html', mode='login')

@app.post('/logout')
@login_required
def logout(): session.clear(); return redirect(url_for('home'))

@app.route('/policy-acceptance', methods=['GET','POST'])
def policy_acceptance():
    user=session.get('user')
    if not user:
        return redirect(url_for('login'))
    fresh=user_refresh(user.get('id'))
    if not fresh or fresh.get('role')!='customer':
        return redirect(url_for('home'))
    if request.method=='GET' and request.args.get('resume_policy') != '1':
        session['policy_reviewed'] = []
    if request.method=='POST':
        if request.form.get('privacy_accepted')!='on' or request.form.get('terms_accepted')!='on' or not {'privacy','terms'}.issubset(set(session.get('policy_reviewed', []))):
            flash('Please open and review both policy documents before continuing.','error')
        else:
            model.accept_current_policies(fresh['id'])
            flash('Your policy acknowledgements have been saved.','success')
            return redirect(url_for('home'))
    return render_template('policy_acceptance.html',policy_version=model.POLICY_VERSION)


@app.get('/policy-review-status')
def policy_review_status():
    return jsonify({'reviewed':session.get('policy_reviewed', [])})

@app.post('/policy-reviewed/<policy_type>')
def policy_reviewed(policy_type):
    if policy_type not in ('privacy','terms'):
        abort(404)
    payload=request.get_json(silent=True) or {}
    if request.form.get('reviewed_to_end') != 'true':
        return jsonify({'ok':False,'message':'Please scroll to the end of the document first.'}), 400
    reviewed=set(session.get('policy_reviewed', []))
    reviewed.add(policy_type)
    session['policy_reviewed']=sorted(reviewed)
    session.modified=True
    return_url=url_for('policy_acceptance',resume_policy=1) if session.get('user',{}).get('role')=='customer' else url_for('register',resume_policy=1)
    return jsonify({'ok':True,'policy':policy_type,'reviewed':session['policy_reviewed'],'return_url':return_url})

@app.get('/privacy')
def privacy_policy():
    return render_template('privacy.html',policy_version=model.POLICY_VERSION)

@app.get('/terms')
def terms_conditions():
    return render_template('terms.html',policy_version=model.POLICY_VERSION)

@app.route('/account', methods=['GET','POST'])
@login_required
def account():
    if request.method=='POST':
        name=request.form.get('name','').strip(); email=request.form.get('email','').strip().lower()
        if len(name)<2 or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',email): flash('Enter a valid name and email address.','error')
        else:
            c=model.db()
            try:
                c.execute('UPDATE users SET name=?,email=? WHERE id=?',(name,email,session['user']['id'])); c.commit()
                session['user']=user_refresh(session['user']['id']); model.log(session['user']['id'],'Updated account profile'); flash('Profile updated.','success')
            except sqlite3.IntegrityError: flash('That email address is already in use.','error')
            finally: c.close()
    return render_template('account.html')

@app.route('/setup', methods=['GET','POST'])
def setup_admin():
    if model.has_admin(): abort(404)
    if request.method=='POST':
        name=request.form.get('name','').strip(); email=request.form.get('email','').strip().lower(); pw=request.form.get('password',''); confirm=request.form.get('confirm','')
        if len(name)<2 or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',email): flash('Enter a valid name and email.','error')
        elif not valid_password(pw): flash('Password must be 10+ characters and include uppercase, lowercase, and a number.','error')
        elif pw!=confirm: flash('Passwords do not match.','error')
        else:
            # Serialize the one-time setup to prevent two simultaneous first-admin registrations.
            c=model.db()
            try:
                c.execute('BEGIN IMMEDIATE')
                if c.execute("SELECT 1 FROM users WHERE role='admin'").fetchone(): c.rollback(); flash('Administrator setup has already been completed.','error')
                else:
                    c.execute('INSERT INTO users(name,email,password,role,department,created_at) VALUES(?,?,?,?,?,?)',(name,email,model.pw_hash(pw),'admin','FOODíE Administration',model.now())); uid=c.execute('SELECT last_insert_rowid()').fetchone()[0]; c.commit()
                    model.log(uid,'Initial administrator account created'); session['user']=user_refresh(uid); flash('Administrator account created. Welcome!','success'); return redirect(url_for('admin'))
            except sqlite3.IntegrityError: c.rollback(); flash('That email address is already registered.','error')
            finally: c.close()
    return render_template('auth.html', mode='setup')

@app.post('/cart/add/<int:item_id>')
def cart_add(item_id):
    item=model.get_item(item_id)
    if not item or not item['available'] or item['stock']<1 or item.get('stall_status') not in ('Open','Busy'): flash('This item is currently unavailable.','error')
    else:
        cart=session.get('cart',{}); key=str(item_id); qty=int(cart.get(key,0))
        if qty>=item['stock']: flash(f"Only {item['stock']} available.",'error')
        else: cart[key]=qty+1; session['cart']=cart; flash(f"{item['name']} added to your cart.",'success')
    return redirect(request.referrer or url_for('home'))

@app.route('/cart', methods=['GET','POST'])
def cart():
    if request.method=='POST':
        cartdata=session.get('cart',{}); action=request.form.get('action'); iid=request.form.get('item_id','')
        if iid in cartdata:
            if action=='remove': cartdata.pop(iid,None)
            else:
                try: q=int(request.form.get('quantity','1')); item=model.get_item(int(iid));
                except (ValueError,TypeError): q=0; item=None
                if not item or q<1: cartdata.pop(iid,None)
                else: cartdata[iid]=min(q,item['stock'])
        session['cart']=cartdata; return redirect(url_for('cart'))
    rows=[]; total=0; cartdata=session.get('cart',{})
    for k,q in cartdata.items():
        it=model.get_item(int(k))
        if it:
            it['quantity']=int(q); it['subtotal']=it['price']*int(q); rows.append(it); total+=it['subtotal']
    return render_template('cart.html', rows=rows,total=total)

@app.route('/checkout', methods=['GET','POST'])
@login_required
def checkout():
    cartdata=session.get('cart',{}); rows=[]; total=0
    for k,q in cartdata.items():
        it=model.get_item(int(k))
        if it: it['quantity']=int(q); it['subtotal']=it['price']*int(q); rows.append(it); total+=it['subtotal']
    if not rows: flash('Your cart is empty.','error'); return redirect(url_for('home'))
    if request.method=='POST':
        method=request.form.get('payment_method','Cash'); timing='Pay Now' if method in ('GCash','Maya','QR Payment') else 'Pay Later'
        fulfillment=request.form.get('fulfillment_method','Pickup'); destination=request.form.get('delivery_location','').strip(); customer_comment=request.form.get('customer_comment','').strip()[:500]
        if fulfillment not in ('Pickup','Delivery'): abort(400)
        if fulfillment=='Delivery' and len(destination)<5: flash('Please enter a complete delivery address.','error')
        elif method not in ('Cash','GCash','Maya','QR Payment'): abort(400)
        else:
            oid=model.create_order(session['user']['id'],{int(k):int(v) for k,v in cartdata.items()},timing,fulfillment,destination,payment_provider=method if timing=='Pay Now' else None,customer_comment=customer_comment)
            if not oid: flash('Some products are unavailable, out of stock, or have not yet been assigned to a stall. Please review your cart.','error')
            else:
                session['cart']={}
                if timing=='Pay Now': return redirect(url_for('payment',oid=oid))
                flash('Order received! Pay cash when your order is handed over.','success'); return redirect(url_for('order_detail',oid=oid))
    return render_template('checkout.html',rows=rows,total=total)

@app.route('/payment/<int:oid>', methods=['GET','POST'])
@login_required
def payment(oid):
    order=model.order(oid,session['user']['id'])
    if not order: abort(404)
    if request.method=='POST':
        if model.complete_demo_online_payment(oid,session['user']['id'],order['payment_channel'].split('/')[0].strip()): flash('Demo payment marked complete. No real funds were transferred.','success'); return redirect(url_for('receipt',oid=oid))
        flash('This demo payment session is no longer eligible.','error')
    return render_template('payment.html',order=order)

@app.post('/orders/<int:oid>/cancel')
@login_required
def cancel_order(oid):
    if session['user']['role']!='customer': abort(403)
    if model.cancel(oid,session['user']['id']): flash('Order cancelled. Stock has been returned.','success')
    else: flash('Only orders that have not entered preparation can be cancelled.','error')
    return redirect(url_for('order_detail',oid=oid))

@app.get('/staff/notifications/unread')
@roles('staff')
def staff_unread_notifications():
    c=model.db()
    try:
        rows=c.execute('SELECT id,title,message,link,created_at FROM user_notifications WHERE user_id=? AND read_at IS NULL ORDER BY id DESC LIMIT 20',(session['user']['id'],)).fetchall()
        return jsonify({'notifications':[dict(r) for r in rows]})
    finally:
        c.close()

@app.get('/notifications')
@login_required
def notification_center():
    model.mark_notifications_read(session['user']['id'])
    return render_template('notifications.html', notifications=model.notifications(session['user']['id']))

@app.post('/orders/<int:oid>/stall/<int:soid>/cancel-request')
@login_required
def partial_cancel_request(oid,soid):
    if session['user']['role']!='customer': abort(403)
    ok=model.request_stall_refund(oid,soid,session['user']['id'],request.form.get('reason',''))
    flash('Your cancellation request was submitted for administrator review.' if ok else 'This portion can no longer be cancelled or already has a request.', 'success' if ok else 'error')
    return redirect(url_for('order_detail',oid=oid))

@app.get('/orders')
@login_required
def history(): return render_template('orders.html',orders=model.orders(session['user']['id']))
@app.get('/orders/<int:oid>')
@login_required
def order_detail(oid):
    if session['user']['role']=='staff': abort(403)
    o=model.order(oid,session['user']['id'] if session['user']['role']=='customer' else None)
    if not o: abort(404)
    return render_template('order_detail.html',order=o)

@app.get('/orders/<int:oid>/receipt')
@login_required
def receipt(oid):
    if session['user']['role']=='staff': abort(403)
    # Customers may only access their own receipt; administrators may inspect all orders.
    uid = session['user']['id'] if session['user']['role'] == 'customer' else None
    order_data = model.order(oid, uid)
    if not order_data:
        abort(404)
    if order_data['payment_status'] not in ('PAID (DEMO)', 'PAID', 'PARTIALLY REFUNDED', 'REFUND PENDING', 'REFUNDED'):
        flash('A receipt is available after payment is confirmed.', 'error')
        return redirect(url_for('order_detail', oid=oid))
    return render_template('receipt.html', order=order_data)

@app.get('/staff')
@roles('staff','admin')
def staff():
    import multi_stall
    if session['user']['role'] == 'admin':
        return redirect(url_for('admin'))
    c = model.db()
    try:
        assigned_ids = multi_stall.assigned_stall_ids(c, session['user']['id'])
        assigned_stalls = [dict(r) for r in c.execute(
            'SELECT id,name,status FROM stalls WHERE id IN (' + ','.join('?' for _ in assigned_ids) + ') ORDER BY name',
            assigned_ids).fetchall()] if assigned_ids else []
        groups = multi_stall.staff_groups(c, session['user']['id']) if assigned_ids else []
        products = c.execute("SELECT m.* FROM menu_items m JOIN staff_stalls ss ON ss.stall_id=m.stall_id WHERE ss.staff_id=? ORDER BY m.name",
                             (session['user']['id'],)).fetchall()
        earnings = c.execute("""SELECT COALESCE(SUM(e.gross_amount),0) AS gross,
                                       COALESCE(SUM(e.fee_amount),0) AS fees,
                                       COALESCE(SUM(e.net_amount),0) AS net,
                                       COALESCE(SUM(CASE WHEN o.payment_status IN ('PAID','PARTIALLY REFUNDED','REFUND PENDING','REFUNDED') AND o.payment_channel LIKE 'Cash on%' THEN e.net_amount ELSE 0 END),0) AS paid,
                                       COALESCE(SUM(CASE WHEN o.payment_status IN ('PAID (DEMO)','PARTIALLY REFUNDED','REFUND PENDING','REFUNDED') AND o.payment_channel NOT LIKE 'Cash on%' THEN e.net_amount ELSE 0 END),0) AS demo,
                                       COALESCE(SUM(CASE WHEN e.settlement_status='Settled' AND o.payment_status='PAID' THEN e.net_amount ELSE 0 END),0) AS settled,
                                       COALESCE(SUM(CASE WHEN e.settlement_status!='Settled' AND o.payment_status='PAID' THEN e.net_amount ELSE 0 END),0) AS pending,
                                       COALESCE(SUM(CASE WHEN o.payment_status NOT IN ('PAID','PAID (DEMO)','PARTIALLY REFUNDED','REFUND PENDING','REFUNDED') THEN e.net_amount ELSE 0 END),0) AS unpaid
                                FROM stall_earnings e JOIN orders o ON o.id=e.order_id
                                JOIN staff_stalls ss ON ss.stall_id=e.stall_id WHERE ss.staff_id=?""",
                             (session['user']['id'],)).fetchone()
        active_orders = [g for g in groups if g['status'] != 'Cancelled' and (g['status'] != 'Completed' or (g['payment_status'] == 'CASH DUE' and not g.get('cash_received_at')))]
        order_history = [g for g in groups if g['status'] in ('Completed','Cancelled') and not (g['payment_status'] == 'CASH DUE' and not g.get('cash_received_at') and g['status'] != 'Cancelled')]
        unread_notifications=[dict(r) for r in c.execute('SELECT id,title,message,link,created_at FROM user_notifications WHERE user_id=? AND read_at IS NULL ORDER BY id DESC LIMIT 20',(session['user']['id'],)).fetchall()]
        return render_template('staff.html', unread_notifications=unread_notifications, orders=active_orders, order_history=order_history,
                               products=[dict(x) for x in products], earnings=dict(earnings),
                               assigned_stalls=assigned_stalls, low_stock=model.low_stock_items(assigned_ids), analytics=model.sales_analytics(7,assigned_ids), top_items=model.top_selling_items(30,assigned_ids))
    finally:
        c.close()

@app.post('/staff/product/<int:iid>/availability')
@roles('staff','admin')
def staff_product_availability(iid):
    c=model.db()
    allowed=c.execute('SELECT 1 FROM menu_items m JOIN staff_stalls ss ON ss.stall_id=m.stall_id WHERE m.id=? AND ss.staff_id=?',(iid,session['user']['id'])).fetchone()
    c.close()
    if not allowed: abort(404)
    model.toggle_item(iid); flash('Product availability updated.','success'); return redirect(url_for('staff'))

@app.post('/staff/product/<int:iid>/stock')
@roles('staff')
def staff_product_stock(iid):
    try:
        stock=int(request.form.get('stock','-1'))
        if stock<0 or stock>10000: raise ValueError()
    except ValueError:
        flash('Enter a valid stock quantity between 0 and 10,000.','error'); return redirect(url_for('staff'))
    c=model.db()
    allowed=c.execute('SELECT 1 FROM menu_items m JOIN staff_stalls ss ON ss.stall_id=m.stall_id WHERE m.id=? AND ss.staff_id=?',(iid,session['user']['id'])).fetchone()
    c.close()
    ok=model.set_stock_left(iid,stock,session['user']['id']) if allowed else False
    flash('Stock left updated. Total stock and deducted quantity were adjusted in the inventory ledger.' if ok else 'Product is not assigned to your stall.','success' if ok else 'error')
    return redirect(url_for('staff'))

@app.post('/staff/order/<int:soid>/cash-confirm')
@roles('staff')
def staff_cash_confirm(soid):
    ok = model.confirm_stall_cash_payment(soid, session['user']['id'])
    flash('Cash received and recorded.' if ok else 'Cash could not be confirmed. Check that this order belongs to your assigned stall and is still awaiting cash.', 'success' if ok else 'error')
    return redirect(url_for('staff'))


@app.post('/staff/order/<int:soid>/status')
@roles('staff')
def staff_status(soid):
    import multi_stall
    c=model.db()
    try:
        ok=multi_stall.update_group_status(c,soid,session['user']['id'],request.form.get('status',''))
    finally:
        c.close()
    if ok:
        model.log(session['user']['id'],'Updated assigned stall order status',f'Stall order #{soid}')
        c=model.db(); info=c.execute('SELECT so.order_id,o.user_id,o.order_number,so.status FROM stall_orders so JOIN orders o ON o.id=so.order_id WHERE so.id=?',(soid,)).fetchone(); c.close()
        if info: model.notify(info['user_id'],'Stall order updated',f'{info["order_number"]} is now {info["status"]} for one of your stalls.',f'/orders/{info["order_id"]}')
    flash('Order status updated.' if ok else 'Unable to update this stall order.','success' if ok else 'error')
    return redirect(url_for('staff'))

def customer_list():
    c=model.db(); rows=c.execute("SELECT id,name,email,created_at FROM users WHERE role='customer' ORDER BY id DESC").fetchall(); c.close(); return [dict(r) for r in rows]

@app.get('/admin')
@roles('admin')
def admin():
    import multi_stall
    c=model.db()
    stats={'orders':c.execute('select count(*) from orders').fetchone()[0], 'sales':c.execute("select coalesce(sum(total),0) from orders where payment_status in ('PAID','PAID (DEMO)','PARTIALLY REFUNDED','REFUND PENDING','REFUNDED')").fetchone()[0], 'products':c.execute('select count(*) from menu_items').fetchone()[0], 'customers':c.execute("select count(*) from users where role='customer'").fetchone()[0], 'staff':c.execute("select count(*) from users where role='staff'").fetchone()[0]}
    stall_list=multi_stall.list_stalls(c)
    refunds=[dict(r) for r in c.execute('''SELECT rr.*,o.order_number,s.name AS stall_name,u.name AS customer_name FROM refund_requests rr JOIN orders o ON o.id=rr.order_id LEFT JOIN stalls s ON s.id=rr.stall_id LEFT JOIN users u ON u.id=rr.requested_by ORDER BY rr.id DESC''').fetchall()]
    settlements=c.execute('''SELECT e.id,e.order_id,e.gross_amount,e.net_amount,e.settlement_status,
                                    o.order_number,o.payment_status,s.name AS stall_name
                             FROM stall_earnings e JOIN orders o ON o.id=e.order_id
                             JOIN stalls s ON s.id=e.stall_id
                             WHERE e.settlement_status='Pending' AND o.payment_status='PAID'
                             ORDER BY e.id''').fetchall()
    stall_finances=c.execute('''SELECT s.id,s.name,COALESCE(SUM(e.gross_amount),0) AS gross,
                                      COALESCE(SUM(e.fee_amount),0) AS fees,COALESCE(SUM(e.net_amount),0) AS net,
                                      COALESCE(SUM(CASE WHEN o.payment_status IN ('PAID','PARTIALLY REFUNDED','REFUND PENDING','REFUNDED') AND o.payment_channel LIKE 'Cash on%' THEN e.net_amount ELSE 0 END),0) AS paid_net,
                                      COALESCE(SUM(CASE WHEN o.payment_status IN ('PAID (DEMO)','PARTIALLY REFUNDED','REFUND PENDING','REFUNDED') AND o.payment_channel NOT LIKE 'Cash on%' THEN e.net_amount ELSE 0 END),0) AS demo_net,
                                      COALESCE(SUM(CASE WHEN e.settlement_status='Settled' AND o.payment_status='PAID' THEN e.net_amount ELSE 0 END),0) AS settled,
                                      COALESCE(SUM(CASE WHEN e.settlement_status!='Settled' AND o.payment_status='PAID' THEN e.net_amount ELSE 0 END),0) AS pending,
                                      COALESCE(SUM(CASE WHEN o.payment_status NOT IN ('PAID','PAID (DEMO)','PARTIALLY REFUNDED','REFUND PENDING','REFUNDED') THEN e.net_amount ELSE 0 END),0) AS unpaid
                               FROM stalls s LEFT JOIN stall_earnings e ON e.stall_id=s.id
                               LEFT JOIN orders o ON o.id=e.order_id
                               GROUP BY s.id ORDER BY s.name''').fetchall()
    c.close()
    return render_template('admin.html',stats=stats,products=model.menu(),orders=model.orders(),staffers=model.staff(),logs=model.logs(),customers=customer_list(),stalls=stall_list,stall_finances=[dict(x) for x in stall_finances],settlements=[dict(x) for x in settlements],low_stock=model.low_stock_items(),analytics=model.sales_analytics(7),refunds=refunds,top_items=model.top_selling_items(30))
@app.post('/admin/stall/<int:stall_id>/status')
@roles('admin')
def stall_status_update(stall_id):
    status=request.form.get('status','')
    if status not in ('Open','Temporarily Unavailable','Closed','Busy'):
        abort(400)
    c=model.db()
    cur=c.execute('UPDATE stalls SET status=? WHERE id=?',(status,stall_id))
    c.commit(); c.close()
    flash('Stall status updated.' if cur.rowcount else 'Stall not found.','success' if cur.rowcount else 'error')
    return redirect(url_for('admin'))

@app.post('/admin/stall/add')
@roles('admin')
def stall_add():
    import re
    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    if len(name) < 2 or not slug:
        flash('Enter a valid stall name.', 'error')
    else:
        c = model.db()
        try:
            c.execute('INSERT INTO stalls(name,slug,status,description,created_at) VALUES(?,?,?,?,?)',
                      (name, slug, 'Open', description, model.now()))
            c.commit(); flash('Stall added successfully.', 'success')
        except sqlite3.IntegrityError:
            flash('A stall with that name already exists.', 'error')
        finally:
            c.close()
    return redirect(url_for('admin'))

@app.post('/admin/stall/<int:stall_id>/remove')
@roles('admin')
def stall_remove(stall_id):
    c = model.db()
    try:
        used_products = c.execute('SELECT 1 FROM menu_items WHERE stall_id=? LIMIT 1', (stall_id,)).fetchone()
        used_orders = c.execute('SELECT 1 FROM stall_orders WHERE stall_id=? LIMIT 1', (stall_id,)).fetchone()
        assigned_staff = c.execute('SELECT 1 FROM staff_stalls WHERE stall_id=? LIMIT 1', (stall_id,)).fetchone()
        if used_products or used_orders or assigned_staff:
            c.execute("UPDATE stalls SET status='Closed' WHERE id=?", (stall_id,)); c.commit()
            flash('This stall has linked products, staff, or order history, so it was safely closed instead of deleted. Reassign its records first to remove it permanently.', 'error')
        else:
            cur = c.execute('DELETE FROM stalls WHERE id=?', (stall_id,)); c.commit()
            flash('Stall removed.' if cur.rowcount else 'Stall not found.', 'success' if cur.rowcount else 'error')
    finally:
        c.close()
    return redirect(url_for('admin'))

@app.post('/admin/product/save')
@roles('admin')
def product_save():
    f=request.form
    try:
        name=f.get('name','').strip(); cat=f.get('category','').strip(); desc=f.get('description','').strip(); price=float(f.get('price','0')); stock=int(f.get('stock','0')); avail=1 if f.get('available')=='on' else 0; iid=int(f['id']) if f.get('id') else None
        stall_id=int(f.get('stall_id') or 0) or None
        if len(name)<2 or not cat or price<=0 or stock<0: raise ValueError()
        model.save_item(iid,name,cat,desc,price,avail,stock,stall_id=stall_id)
        flash('Product saved.','success')
    except (ValueError,TypeError): flash('Please enter valid product details.','error')
    return redirect(url_for('admin'))
@app.post('/admin/product/<int:iid>/delete')
@roles('admin')
def product_delete(iid):
    c=model.db(); used=c.execute('select 1 from order_items where menu_item_id=? limit 1',(iid,)).fetchone(); c.close()
    if used: model.save_item(iid,model.get_item(iid)['name'],model.get_item(iid)['category'],model.get_item(iid)['description'],model.get_item(iid)['price'],0,model.get_item(iid)['stock'],stall_id=model.get_item(iid)['stall_id']); flash('Product has order history; it was disabled instead of deleted.','success')
    else: model.delete_item(iid); flash('Product deleted.','success')
    return redirect(url_for('admin'))
@app.post('/admin/settlement/<int:earning_id>/mark-settled')
@roles('admin')
def settlement_marked(earning_id):
    reference=request.form.get('settlement_reference','').strip()
    if len(reference)<4 or len(reference)>120:
        flash('Enter a valid settlement reference before marking this allocation settled.','error')
        return redirect(url_for('admin'))
    c=model.db()
    cur=c.execute('''UPDATE stall_earnings SET settlement_status='Settled',settlement_reference=?,settled_at=?
                     WHERE id=? AND settlement_status='Pending'
                     AND EXISTS(SELECT 1 FROM orders o WHERE o.id=stall_earnings.order_id AND o.payment_status='PAID')''',
                  (reference,model.now(),earning_id))
    c.commit(); c.close()
    flash('Settlement record updated. This does not transfer funds.' if cur.rowcount else 'This allocation is not eligible for settlement.','success' if cur.rowcount else 'error')
    return redirect(url_for('admin'))

@app.post('/admin/order/<int:oid>/cash-confirm')
@roles('admin')
def admin_cash_confirm(oid):
    ok=model.confirm_cash_payment(oid,session['user']['id'])
    flash('Cash payment confirmed.' if ok else 'Payment could not be confirmed.','success' if ok else 'error')
    return redirect(url_for('admin'))

@app.post('/admin/staff/create')
@roles('admin')
def staff_create():
    f=request.form; pw=f.get('password','')
    if not valid_password(pw): flash('Staff password must be 10+ characters and include uppercase, lowercase, and a number.','error')
    elif len(f.get('name','').strip())<2 or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',f.get('email','').strip()): flash('Enter a valid staff name and email address.','error')
    else:
        try: stall_id=int(f.get('stall_id') or 0) or None
        except ValueError: stall_id=None
        if not stall_id:
            flash('Choose a stall for this staff account.','error')
        else:
            ok,err=model.add_staff(f.get('name','').strip(),f.get('email','').strip(),pw,f.get('department','Food Service Operations').strip(),stall_id)
            flash('Staff account created and assigned.' if ok else (err or 'Unable to create staff account.'),'success' if ok else 'error')
    return redirect(url_for('admin'))
@app.post('/admin/staff/<int:uid>/edit')
@roles('admin')
def staff_edit(uid):
    f=request.form; name=f.get('name','').strip(); email=f.get('email','').strip().lower(); dept=f.get('department','').strip()
    try: stall_id=int(f.get('stall_id') or 0)
    except ValueError: stall_id=0
    if len(name)<2 or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',email) or not stall_id: flash('Enter valid staff details and choose a stall.','error')
    else:
        c=model.db()
        try:
            cur=c.execute("UPDATE users SET name=?,email=?,department=? WHERE id=? AND role='staff'",(name,email,dept,uid))
            if cur.rowcount and c.execute('SELECT 1 FROM stalls WHERE id=?',(stall_id,)).fetchone():
                c.execute('DELETE FROM staff_stalls WHERE staff_id=?',(uid,))
                c.execute('INSERT INTO staff_stalls(staff_id,stall_id,assigned_at) VALUES(?,?,?)',(uid,stall_id,model.now()))
            c.commit(); flash('Staff details and stall assignment updated.' if cur.rowcount else 'Staff account not found.','success' if cur.rowcount else 'error')
        except sqlite3.IntegrityError: flash('That email address is already in use.','error')
        finally: c.close()
    return redirect(url_for('admin'))

@app.post('/admin/staff/<int:uid>/deactivate')
@roles('admin')
def staff_deactivate(uid): flash('Staff account deactivated.' if model.remove_staff(uid) else 'Staff account not found.','success'); return redirect(url_for('admin'))
@app.post('/admin/customer/<int:uid>/deactivate')
@roles('admin')
def customer_deactivate(uid):
    c=model.db(); cur=c.execute("update users set role='inactive_customer' where id=? and role='customer'",(uid,)); c.commit(); c.close(); flash('Customer account deactivated.' if cur.rowcount else 'Customer not found.','success'); return redirect(url_for('admin'))

@app.errorhandler(403)
def forbidden(e): return render_template('message.html',title='Access restricted',message='You do not have permission to view this page.'),403
@app.errorhandler(404)
def missing(e): return render_template('message.html',title='Page not found',message='The page you requested could not be found.'),404

@app.errorhandler(500)
def server_error(e):
    app.logger.exception('Unhandled FOODíE server error')
    return render_template('message.html',title='Something went wrong',message='FOODíE could not complete that request. Please try again. If the issue continues, contact the administrator.'),500



@app.post('/admin/refund/<int:refund_id>/review')
@roles('admin')
def refund_review(refund_id):
    status=request.form.get('status','')
    ok=model.review_refund(refund_id,status,request.form.get('admin_note',''),session['user']['id'])
    flash('Refund record updated. For real payments, complete the refund through the actual payment provider before marking Processed.' if ok else 'Refund request could not be updated.','success' if ok else 'error')
    return redirect(url_for('admin'))

@app.post('/admin/inventory/<int:iid>/threshold')
@roles('admin')
def inventory_threshold(iid):
    try: threshold=int(request.form.get('threshold','5'))
    except ValueError: threshold=-1
    if threshold<0 or threshold>10000: flash('Enter a valid low-stock threshold.','error')
    else:
        c=model.db(); cur=c.execute('UPDATE menu_items SET low_stock_threshold=? WHERE id=?',(threshold,iid)); c.commit(); c.close()
        flash('Low-stock alert threshold saved.' if cur.rowcount else 'Product not found.','success' if cur.rowcount else 'error')
    return redirect(url_for('admin'))

@app.get('/admin/backup')
@roles('admin')
def admin_backup():
    backup_dir=BASE/'backups'; backup_dir.mkdir(exist_ok=True)
    stamp=model.datetime.now().strftime('%Y%m%d-%H%M%S')
    target=backup_dir/f'foodie-backup-{stamp}.db'
    backups=sorted(backup_dir.glob('foodie-backup-*.db'),key=lambda x:x.stat().st_mtime,reverse=True)
    for old in backups[6:]: old.unlink(missing_ok=True)
    source=model.db(); dest=sqlite3.connect(str(target))
    try: source.backup(dest)
    finally: dest.close(); source.close()
    app.logger.info('Database backup created by admin user_id=%s file=%s',session['user']['id'],target.name)
    return send_file(target,as_attachment=True,download_name=target.name,mimetype='application/vnd.sqlite3')


if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)),debug=False)
