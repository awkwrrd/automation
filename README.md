# Dockyard WMS

A generic, database-agnostic **Warehouse Management System** with a web GUI, built as the foundation for a
Shopify-connected fulfillment stack. It follows the standard enterprise WMS operating model (receipts →
directed putaway → allocation → waves → task-directed picking → pack → ship, plus cycle counting and a full
inventory audit trail). That model is common across the industry. All code, UI and naming here are original.

- **Backend:** Python 3.11+ · FastAPI · SQLAlchemy 2. Works with PostgreSQL, MySQL/MariaDB, SQL Server or SQLite.
- **Frontend:** React 18 + TypeScript (Vite). The API serves the built GUI from the same origin.
- **API docs:** interactive OpenAPI at `/docs`. Every screen in the GUI is backed by a public REST endpoint,
  so the Shopify connector (stage 2) and any scanners or RF guns use the same API.

---

## Quick start

### Option A: Docker (PostgreSQL included)
```bash
docker compose up --build
```
Open http://localhost:8000.

### Option B: Local dev
```bash
# API
cd backend
pip install -r requirements.txt
cp ../.env.example ../.env        # edit WMS_DATABASE_URL to point at your DB
uvicorn app.main:app --reload --port 8000

# GUI (second terminal), hot-reload on :5173, proxies /api to :8000
cd frontend
npm install
npm run dev
```
To serve the GUI from the API instead, run `npm run build` once. FastAPI then serves `frontend/dist` at `/`.

**Demo logins** (seeded on first start against an empty DB): `admin/admin`, `supervisor/supervisor`, `operator/operator`.
Set `WMS_SEED_DEMO_DATA=false` for a clean production database. Only the admin user is created then.

### Plugging in your database
Set `WMS_DATABASE_URL` to any SQLAlchemy URL (see `.env.example`). On startup the app creates any missing tables.
The schema stores enumerations as plain strings and uses no vendor-specific types, so it ports across engines.
Upgrading the app against an existing database adds any new (nullable) columns automatically on startup.
The test suite passes on both SQLite and PostgreSQL:
```bash
cd backend
pytest                                                                     # SQLite
WMS_DATABASE_URL=postgresql+psycopg://user:pass@localhost/wms_test pytest  # Postgres
```

---

## What's in stage 1

| Module | Capabilities |
|---|---|
| **Dashboard** | KPIs (SKUs, units, location utilization, open orders/tasks, low stock), order pipeline, 7-day in/out chart, recent activity |
| **Items** | Product master: SKU, barcode, category, supplier, cost/price, weight & dims, reorder point/qty, lot tracking, home location, Shopify product/variant/inventory-item IDs. CSV import (upsert by SKU) & export |
| **Inventory Inquiry** | On-hand by item × location × lot × status, with on-hand / allocated / available. Move, adjust (reason-coded), and status change (Available ↔ Hold / Damaged / Quarantine) |
| **Receipts / ASNs** | PO, ASN, and Return receipts with lines. Receive at the dock with lot and expiry capture, over/short visibility, close/cancel |
| **Directed putaway** | Receiving to a dock creates a PUTAWAY task with a suggested location: the item's home location first, then consolidation with existing stock, then the first empty storage location |
| **Orders** | Manual or channel (Shopify) orders with dedupe on external id. **FEFO/FIFO allocation** from pickable locations, partial allocation, unallocate, cancel |
| **Waves** | Select orders → create a wave → allocate and release them all at once |
| **Task Queue** | Pick, putaway, move and replenishment tasks in **walk-path (pick-sequence) order**. Claim/assign, scan-confirm the source location, partial confirms, **short picks** (the remainder is released automatically) |
| **Pack & Ship** | Scan-driven station: load an order, verify contents by barcode scan, record carrier/service/packages/weight, confirm shipment with tracking |
| **Cycle Counts** | Count by zone, locations or item. Blind counts (operators can't see expected qty), "found item" lines; approval posts variances as COUNT adjustments |
| **Transaction History** | Every quantity change is written to an immutable log. Filter by item, type, reference, user and date |
| **Replenishment report** | Items at or below their reorder point, with suggested order qty and cost |
| **Configuration** | Multi-warehouse, zones, locations (plus bulk generation such as aisles A–D × bays 1–10 × levels 1–4), suppliers, users |
| **Integrations** | Push events (`wave.released`, `order.released`, `putaway.created`, `task.cancelled`) to external systems such as a robotics platform, routed by warehouse and zone, as standard events or one PascalCase message per order (field renames and fixed fields configurable). Signed (HMAC), ordered, retried, with a message log. API keys + a bulk task-confirmation API for the response leg. See [docs/SOFTBOT_INTEGRATION.md](docs/SOFTBOT_INTEGRATION.md) |
| **Shopify** | Connect a store (Dev Dashboard app or existing token): import products and orders (polling, no public URL needed), cancel on Shopify cancellation, fulfillment + tracking on ship, push on-hand stock. See [docs/SHOPIFY.md](docs/SHOPIFY.md) |
| **Mock picking system** | Stand-in for KFX / AutoStore during proofs of concept: answers 200 to the outbound SOFTBOT and shows each message at http://localhost:9100. See [docs/MOCK_PICKING.md](docs/MOCK_PICKING.md) |
| **Security** | Token auth with three roles: **Operator** (floor execution), **Supervisor** (adjustments, order/wave/count control, item master), **Admin** (config & users) |

### Inventory model (important for Shopify sync)
- `qty_on_hand`: physically in the location.
- `qty_allocated`: reserved for orders. Picked stock moves to a STAGING location and *stays reserved* until it ships.
- **Available to sell** = on-hand − allocated, counting only `AVAILABLE` status and excluding staging. This number
  is what stage 2 should push to Shopify's `available` quantity. It is exposed as `available` on `GET /api/items`.

### Order lifecycle
`NEW → (PARTIALLY_)ALLOCATED → RELEASED → PICKING → PICKED → PACKED → SHIPPED` (or `CANCELLED`)

---

## Project layout
```
backend/app/
  models.py          # schema (SQLAlchemy)
  services/          # business rules: inventory engine, inbound, outbound, tasks, counts
  routers/           # REST endpoints
  seed.py            # bootstrap admin + optional demo data
backend/tests/       # end-to-end workflow tests
frontend/src/
  pages/             # one file per screen
  components/        # data grid, modals, item/location pickers, forms
```
All quantity changes go through `services/inventory.py`, so the balances and the audit log can't drift apart.

---

## Roadmap (next stages)

**Stage 2: Shopify integration** (done, see [docs/SHOPIFY.md](docs/SHOPIFY.md))
- Next: order webhooks for instant import (needs a public HTTPS URL), multiple stores/locations,
  returns from Shopify into receiving

**Hardening / later**
- Alembic migrations (replacing `create_all`) for schema evolution
- License-plate (LPN/pallet) tracking, serial numbers
- Min/max pick-face replenishment, slotting, ABC velocity classification
- Carrier rate shopping and label printing (e.g. EasyPost/Shippo), packing slips and pick-list PDFs
- Mobile/RF-optimized screens, barcode label printing for locations
- Inter-warehouse transfers, kitting/bundles, returns disposition (restock vs damage)
