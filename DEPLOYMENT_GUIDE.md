# FOODíE — Free school-demo deployment

This project is prepared for a **school demonstration**, not for real canteen operations or real customer data.

## Recommended free demo setup

- **Application hosting:** Render Free Web Service
- **Database for this demo:** the bundled SQLite database
- **Public address:** a free `onrender.com` subdomain assigned during deployment
- **HTTPS:** enabled by Render; the app is configured to mark session cookies Secure
- **PWA:** the existing manifest, icons, and service worker can be served over HTTPS

### Important free-hosting limitation

Render Free web services spin down after 15 minutes without incoming traffic. The first visit after sleeping can take around a minute to wake up. The free service filesystem is ephemeral: SQLite changes, uploaded files, and local logs can be lost on restart, spin-down, or redeploy. This package therefore keeps the shipped, empty-account catalog database as the demo starting point. **Do not rely on this free deployment to preserve created accounts, orders, comments, stock changes, or other data.** Recreate demo accounts and sample orders when needed. This is acceptable for a temporary school presentation, not for ongoing canteen operation.

Render also documents that its free Postgres databases expire after 30 days. This project has not been converted to PostgreSQL, so do not attach a Postgres database and assume it will work without a database migration.

## Before uploading the project

1. Create a GitHub account if you do not already have one.
2. Create a **private** repository for the school project if you prefer not to publish the source code. The deployed website itself will still be publicly reachable.
3. Extract this ZIP and upload the contents of the `FOODiE_Responsive_Web_Application` folder to the repository.
4. Keep `database/canteen.db` in the repository for the demo catalog. It currently contains no user accounts or order history.
5. Do not commit `.env`, personal data, real customer records, or real credentials.

## Deploy with Render Blueprint

1. Sign in to Render and connect the GitHub account that contains the repository.
2. In the Render dashboard, choose **New → Blueprint**.
3. Select the FOODíE repository.
4. Render detects `render.yaml`. Review the service and choose the Free instance.
5. Allow the build and deployment to finish. The configured start command uses Gunicorn, not Flask's development server.
6. Open the `onrender.com` URL shown in the Render service dashboard.
7. On first visit, use the one-time **Set up the first administrator** flow. Create a demo admin account with a unique school-demo password. Do not reuse a personal password.
8. Create demo staff accounts, assign each staff account to its stall, then create a separate customer account to test ordering.

If the Blueprint option is unavailable, create a **New → Web Service**, connect the same repository, select Python, set build command to `pip install -r requirements.txt`, and start command to `gunicorn --workers 1 --threads 4 --timeout 120 --access-logfile - --error-logfile - app:app`. Set environment variables `FOODIE_ENV=production`, `FOODIE_HTTPS=1`, and `FOODIE_AUTO_BACKUP=0`. Generate a long random value for `FOODIE_SECRET_KEY` in the Render environment settings; never paste it into source code.

## Testing after deployment

- Open the public URL on a desktop browser and a mobile phone.
- Register a customer and complete the privacy/terms review flow.
- Place a demo order and verify the order comment appears for the assigned stall staff.
- Sign in as staff and verify the assigned-stall queue and notifications.
- Sign in as admin and verify the platform dashboard.
- Confirm that GCash/Maya/QR are clearly marked as simulated. No real payment is processed.
- Try the PWA install option on a supported mobile browser if offered.

## Safety and privacy for a school demonstration

- Use fictional names, email addresses, and order details.
- Do not collect student IDs, phone numbers, addresses, or other personal information unless the school has approved the collection and privacy notice.
- Do not enter real payment credentials or claim that simulated payment is a real transaction.
- Share the public URL only for the demonstration and remove the deployment when it is no longer needed.
- The Terms and Privacy Policy included in the project are drafts, not legal approval from the school or canteen.

## When FOODíE is ever used for real operations

Do not simply reuse this free-demo deployment. First migrate SQLite to a persistent managed database (for example, PostgreSQL), configure persistent object storage for any user-uploaded files, backups, monitoring, rate limiting, account recovery, and a reviewed privacy/terms process. Choose hosting with an appropriate uptime and data-retention arrangement. The current free Render service is not suitable for real canteen transactions or durable order records.
