# FOODíE — Responsive Web Application

A Flask + SQLite responsive ordering platform evolved from the supplied FOODíE Tkinter/MVC application. The existing Python data model and PBKDF2-HMAC-SHA256 password hashing were retained and adapted for web sessions. The SQLite catalog retains the 12 original products and adds 14 starter products for the seven remaining stalls, using editable estimated prices in Philippine pesos. The shipped database contains no user accounts or order history.

## Requirements
- Windows 11
- Python 3.10 or newer (3.11+ recommended)
- Internet access for initial dependency installation (Google Fonts are optional; local layout works without them)

## Install and run on Windows
1. Extract `FOODiE_Responsive_Web_Application.zip`.
2. Open the extracted `FOODiE_Responsive_Web_Application` folder.
3. Double-click `run_foodie.bat`. It creates a local `.venv`, installs Flask and Waitress, and starts the server.
4. Open **http://127.0.0.1:5000** on the same PC.
5. On first launch, choose **Set up the first administrator** on the sign-in page. Use a valid email and a password of at least 10 characters containing uppercase, lowercase, and a number. The setup route becomes unavailable after the first administrator is created.

### Manual start
```powershell
py -3 -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python app.py
```
For a production-style local run, use Waitress:
```powershell
.venv\Scripts\python -c "from waitress import serve; from app import app; serve(app, host='0.0.0.0', port=5000)"
```

## Mobile on the same Wi-Fi network
1. Connect the phone and Windows PC to the same Wi-Fi network.
2. Find the PC's local IPv4 address with `ipconfig` (for example `192.168.1.25`).
3. Allow Python/Waitress through Windows Defender Firewall on a **Private** network if prompted.
4. On the phone, open `http://PC-IP:5000` (replace PC-IP with the actual address).

## Install as a PWA
- The app includes a web manifest, app icon, and service worker. On Android Chrome, open the site and use **Install app** / **Add to Home screen** from the browser menu.
- On iOS Safari, use **Share → Add to Home Screen**.
- Desktop Chromium browsers may show an install icon in the address bar.
- Browser PWA installation and service-worker support generally require HTTPS, except localhost. For installation from another device on a LAN, configure HTTPS on a trusted host/reverse proxy; ordinary local HTTP access still works for ordering.
- The service worker caches the application shell and falls back to the cached home page during network loss. Checkout, login, and order updates require an active connection.

## Roles and features
- **Customer:** self-registration, menu search/category filtering, session cart, pickup/delivery selection, cash or simulated GCash/Maya/QR, order tracking, order history.
- **Staff:** stall-specific order queue, fulfillment status changes, inventory monitoring with total/deducted/left counts, low-stock alerts, and availability controls for assigned products. The **On the way (OTW)** status is available only for delivery orders; pickup orders move from Ready to Completed. Server-side checks prevent access to other stalls' order groups.
- **Administrator:** platform-wide dashboard, 11-stall directory, product/staff assignment, customer management, per-stall earnings allocations, inventory alerts, daily sales analytics, best-selling products, cancellation/refund review, downloadable database backup, and activity log.
- **Customer:** one checkout can contain products from multiple stalls. FOODíE creates separate fulfillment queues and earnings allocations for each stall while showing combined order tracking with individual stall progress.
- **Privacy and terms:** customer registration requires acknowledgement of the Privacy Policy and Terms & Conditions. Existing customers are prompted to acknowledge the current policy version on their next sign-in.
- **First administrator:** one-time setup while no admin exists. No default credentials are shipped.

## Multi-stall setup and database migration
- The first application request performs additive, repeat-safe SQLite migrations. It creates the 11 confirmed stalls, staff-to-stall assignments, stall fulfillment records, per-stall earnings allocations, and policy acceptance records.
- The migration preserves existing users, products, orders, and order history. It does not drop or replace existing tables. Back up `database/canteen.db` before replacing/updating an existing installation.
- The original 12 products are retained and assigned to their existing stall categories. Fourteen additional starter products are seeded for Belgian Waffle, Nescafe, Jamaican, Grill Pot, Babs Sisig, Halfway, and Korean Stall. Their prices are estimates for demonstration and can be edited by an administrator. Product and price details should be confirmed with each stall before any real launch.
- Existing staff accounts need a stall assignment. An administrator can open the staff account's Edit panel and select its stall.
- A staff account currently has one assigned stall. The schema supports more than one assignment if the operational policy later requires it.
- Earnings records show gross amount, fee amount, net allocation, payment state, and settlement status. An administrator may record a settlement reference after independently verifying a transfer; the application does not send money or prove that a transfer occurred. Cancelled stall allocations are placed on hold and excluded from the remaining active allocation.

## Demo payments
GCash, Maya, and QR are simulated only. **Demo Payment Only — No Real Money Will Be Charged.** No real payment credentials are requested or stored and no payment provider is contacted. The `payment_gateway.py` module remains an integration boundary for a future approved provider.

## Data and configuration
- SQLite database: `database/canteen.db`.
- Original model and demo payment adapter: `model.py`, `payment_gateway.py`.
- Flask routes/session/access control: `app.py`.
- Templates and responsive assets: `frontend/`.
- Set `FOODIE_SECRET_KEY` to a long random secret before deployment. When `FOODIE_ENV=production`, startup fails if the secret is missing.
- For HTTPS deployments set `FOODIE_HTTPS=1` so session cookies are marked Secure.
- Daily SQLite backups are created automatically on the first request each day (set `FOODIE_AUTO_BACKUP=0` to disable); the app retains the latest seven automatic backups. Admins can also download a current backup from the dashboard. Store additional copies outside the application host for disaster recovery.
- Application errors are written to `logs/foodie.log`; security response headers are enabled. Never expose the SQLite database, logs, or backup folder through a public static route.

## Security and deployment notes
The application uses HTTP-only, SameSite session cookies, CSRF tokens on form submissions, server-side role checks, parameterized SQLite statements, password hashing, and transactional stock validation/order creation. This is a solid local/small deployment foundation, not a substitute for a production security review. Before public deployment, configure HTTPS, a stable secret key, off-host backup storage, centralized error monitoring, rate limiting, account recovery, and a defined data-retention/request process. The included file log is basic error logging, not a managed monitoring service. The included Privacy Policy and Terms are project drafts and require review/approval by the responsible canteen or institution. A real payment provider is not integrated; automatic split payouts, signed webhook verification, refunds, and settlement transfers remain future work.

## Validation status
See `TESTING_NOTES.md` for the checks completed and the integration/browser tests that still need to be run after dependency installation. Repeatable isolated database tests are in `tests/`.

## FOODíE refreshed visual update

The customer-facing web interface now uses the approved three-color identity:
- Deep red: `#A90D1B` for the brand, navigation, and primary actions.
- Warm cream: `#FFF8EF` for the page background and light surfaces.
- Golden yellow: `#F4B942` for highlights, selected navigation, and accents.

The menu retains twelve locally stored food photographs in `frontend/static/images/products/`. The fourteen new starter products currently use a temporary catalog-image fallback until individual product photos are supplied or an image upload workflow is added. The product names, categories, descriptions, prices, inventory, checkout, and order-management logic remain connected to the existing SQLite database.

### Run locally (Windows)
1. Extract the ZIP file.
2. Open the extracted `FOODiE_Responsive_Web_Application` folder.
3. Run `run_foodie.bat`, or install the packages in `requirements.txt` and run `python app.py`.
4. Open the local address shown in the terminal (normally `http://127.0.0.1:5000`).

The interface is responsive for desktop and mobile browsers and retains the existing PWA manifest and service worker. On first use after this update, refresh the page once if an older cached version is displayed.

## Latest FOODíE catalog and staff workspace update (2026-11-27)
- Added individual locally stored food photos for the 14 starter products at `frontend/static/images/products/13.webp` through `26.webp`.
- Updated the Digital Order Receipt to show one clean line per item: quantity, food name, and line price. The Return to menu link now returns directly to the menu home page.
- Added administrator stall creation and safe removal. A stall with linked products, staff assignments, or order history is closed rather than hard-deleted, preserving historical records.
- Staff accounts now have a dedicated work-focused navigation, assigned-stall overview, incoming customer order queue, completed/cancelled customer order history, assigned product inventory, stock adjustment, availability control, and stall-level sales figures.
- Staff access remains restricted server-side to the stall(s) assigned to their account.
- Prices for the 14 added products remain estimates and must be confirmed with the respective stalls before launch.


### Cash-on-pickup workflow

Cash orders immediately create an order summary for the customer. Each assigned stall staff member confirms cash only after physically receiving their stall's portion. For multi-stall cash orders, the Digital OR is unlocked only after every non-cancelled stall portion is confirmed. The customer can then open and print/save the Digital OR from order details. Cash confirmation is a staff-recorded acknowledgement; it is not a payment processor transaction.


## Inventory, notifications, analytics, and refunds (2026-11-27)
- Inventory now records **Total Stock**, **Deducted**, and **Stock Left**. New products start with an initial total; editing/restocking adjusts the remaining stock and ledger consistently. For example, 40 total with one unit deducted displays 40 / 1 / 39. Customer orders increase the deducted count; cancellations return stock and reverse the deducted count. Manual restocking increases total stock, while manual usage reduces stock left and increases deducted.
- Inventory movements are recorded in an audit ledger. Admins can set a per-product low-stock threshold; staff see alerts for their assigned stalls and admins see all low-stock items.
- In-app notifications are created for new customer orders, new stall work, fulfillment status changes, cash collection completion, and cancellation/refund review updates. These are in-app notifications, not SMS, email, or push notifications.
- Admin and staff dashboards show a seven-day daily paid-sales summary and 30-day best-selling products. Demo-paid values are still simulated and should be interpreted separately from real collections.
- Customers can submit a partial cancellation request for eligible stall portions. The request remains pending until an admin approves or rejects it. Approval cancels that portion, returns stock, reduces the remaining order amount, and places its stall allocation on hold. For already-paid orders, the refund still must be completed manually through the actual payment provider; FOODíE only records the review and status.
- Staff-initiated cancellation of a paid stall portion creates a pending refund review record. Cash-due orders have the cancelled portion removed from the amount owed.
- The app requires `FOODIE_SECRET_KEY` when `FOODIE_ENV=production`, adds security response headers, writes errors to `logs/foodie.log`, and provides daily/on-demand SQLite backups.


## Policy review and staff order notifications

- Customer registration requires the Privacy Policy and Terms & Conditions to be opened, scrolled to the end, and explicitly confirmed before their acknowledgement checkboxes are enabled. The server records each review confirmation in the signed session and checks it again when the account form is submitted.
- Existing customers are prompted to review the updated policy version (1.1) before continuing. The policy documents are project drafts and must be reviewed by the responsible canteen/institution before public use.
- When checkout creates an order, the model creates a `New stall order` notification for each staff account assigned to each stall included in that checkout. Staff see unread notifications in the dashboard; the panel polls every 10 seconds and links to the staff order queue. The existing notification center and header unread count remain available.


## Customer policy review and food instructions
- After a customer reaches the end of a policy and confirms review, the policy tab attempts to close and returns focus to the registration / policy-acceptance page. The matching acknowledgement checkbox is unlocked there. If the browser does not allow the tab to close, it redirects back to the originating account flow while preserving the review confirmation.
- Checkout includes an optional 500-character food-instruction note. It is stored on the order and displayed in the assigned stall staff dashboard for every stall included in that checkout.


## Public school-demo deployment (free)

This project includes `render.yaml`, a `Procfile`, and `DEPLOYMENT_GUIDE.md` for deploying a temporary public demo on Render Free. The deployment uses Gunicorn and HTTPS settings. Read the guide before publishing. Render Free services sleep after inactivity and have an ephemeral filesystem, so the bundled SQLite demo data can reset after restarts, spin-downs, or redeployments. Do not use this setup for real customer information or live canteen operations.
