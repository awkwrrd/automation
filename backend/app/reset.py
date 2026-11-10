"""Reset the WMS database.

  python -m app.reset            # wipe operational data, KEEP configuration (default)
  python -m app.reset --all      # drop everything and start from scratch (as on first install)
  add --yes to skip the confirmation prompt

Default (keep configuration) deletes: items, inventory, inventory history, receipts, orders, waves,
shipments, tasks, cycle counts, integration message log and Shopify sync log, and restarts document
numbers (ORD000001 ...). It keeps: users, API keys, warehouses, zones, locations, suppliers, integration
endpoints (e.g. SOFTBOT) and the Shopify connection (its order cursor is reset so orders re-import).

With Docker Compose:  docker compose exec wms python -m app.reset
"""
import argparse
import sys

from sqlalchemy import delete, update

from .db import Base, SessionLocal, engine
from .models import (
    Allocation, CycleCount, CycleCountLine, InboundLine, InboundOrder, InventoryBalance, InventoryTransaction,
    Item, NumberSequence, OutboundLine, OutboundMessage, OutboundOrder, Shipment, ShopifyStore, ShopifySyncRun,
    Task, Wave,
)

# children before parents so foreign keys are never violated
OPERATIONAL = [CycleCountLine, CycleCount, Task, Allocation, Shipment, OutboundLine, OutboundOrder, Wave,
               InboundLine, InboundOrder, InventoryTransaction, InventoryBalance, OutboundMessage, ShopifySyncRun,
               Item, NumberSequence]


def reset_operational() -> dict[str, int]:
    counts = {}
    with SessionLocal() as db:
        for model in OPERATIONAL:
            counts[model.__tablename__] = db.execute(delete(model)).rowcount or 0
        db.execute(update(ShopifyStore).values(orders_cursor=None, last_error=None, last_sync_at=None))
        db.commit()
    return counts


def reset_all() -> None:
    from .seed import seed
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)
        db.commit()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--all", action="store_true", help="drop ALL data incl. users, locations and connections")
    p.add_argument("--yes", action="store_true", help="don't ask for confirmation")
    a = p.parse_args(argv)
    what = ("EVERYTHING (users, warehouses, locations, SOFTBOT and Shopify connections, all data)" if a.all
            else "all items, inventory, orders, receipts, tasks and history (configuration is kept)")
    if not a.yes:
        print(f"This permanently deletes {what} from {engine.url.render_as_string(hide_password=True)}")
        if input("Type RESET to continue: ").strip() != "RESET":
            print("Cancelled.")
            return 1
    if a.all:
        reset_all()
        print("Database recreated. Log in with the admin user from WMS_ADMIN_USERNAME / WMS_ADMIN_PASSWORD.")
    else:
        counts = reset_operational()
        print("Deleted: " + ", ".join(f"{k}={v}" for k, v in counts.items() if v))
        print("Kept users, warehouses, zones, locations, suppliers, integration endpoints and Shopify connection.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
