# Connecting Shopify

The WMS talks to Shopify's GraphQL Admin API (version **2026-10** by default). It **polls**: the WMS calls
Shopify, Shopify never calls the WMS. It therefore works from a PC or private network with no public URL.

| Direction | What | When |
|---|---|---|
| Shopify → WMS | Products/variants → **Items** (matched by variant ID, then SKU) | *Import products* button |
| Shopify → WMS | Orders → **Orders** (channel SHOPIFY, `external_id` = `#1001`) | every *N* minutes, or *Sync orders now* |
| Shopify → WMS | Order cancelled in Shopify → WMS order cancelled (if not shipped) | with the order sync |
| WMS → Shopify | Shipped order → **fulfillment with tracking** (customer emailed if enabled) | within ~30 s of shipping |
| WMS → Shopify | Stock → **on-hand** at the mapped Shopify location | every *N* minutes once enabled, or *Push* buttons |

## 1. Create the app in the Shopify Dev Dashboard

Since January 2026 Shopify no longer lets you create custom apps (and copy a token) inside the store admin.
Use the Dev Dashboard instead. Your **dev store and the app must be in the same Shopify organization**.

1. Go to <https://dev.shopify.com/dashboard/> → **Create app** → *Start from Dev Dashboard*. Name it e.g. `Dockyard WMS`.
2. Create a **version** of the app and select these Admin API **access scopes**:
   - `read_products`, `read_inventory`, `write_inventory`, `read_locations`
   - `read_orders`
   - `read_merchant_managed_fulfillment_orders`, `write_merchant_managed_fulfillment_orders`
   - optional: `read_all_orders`, only needed to import orders older than 60 days

   The Scopes box takes a comma-separated list. Paste this line:
   ```
   read_products,read_inventory,write_inventory,read_locations,read_orders,read_merchant_managed_fulfillment_orders,write_merchant_managed_fulfillment_orders
   ```
   Other fields on that page: **App URL** isn't used by the WMS. Shopify's suggested default for apps without a page in the admin is
   `https://shopify.dev/apps/default-app-home`, and any placeholder works. **Untick** *Embed app in Shopify admin*. Leave *Allowed redirection URL(s)* empty
   and *Use legacy install flow* unticked.
3. **Release** the version. Then, on the app's page, click **Install app** (top of the *Installs* card),
   choose your dev store, and click **Install**. Creating the app is not enough: without this step the
   connection test fails with `app_not_installed`.
4. Open the app's **Settings** and copy the **Client ID** and **Client secret**.

> Already have a token from a legacy custom app created before 2026 (`shpat_…`)? Choose
> *Existing custom app token* instead. It keeps working.

## 2. Connect it in the WMS (Admin)

**Sales channels → Shopify**:

1. Store domain `your-store.myshopify.com`, *Dev Dashboard app*, paste Client ID + secret → **Save**.
2. **Test connection**: shows the store name, your Shopify locations and any **missing scopes**.
3. **Mapping:** choose the WMS warehouse that receives Shopify orders and the **Shopify location** it
   corresponds to → **Save**.
4. **Import products.** Items are matched to existing WMS items by SKU, otherwise created. Variants without
   a SKU are skipped. Add SKUs in Shopify first for anything you stock.
5. Set **Import orders created since** (e.g. today), click **Sync orders now**, and check *Orders*.
6. Tick **Run automatically in the background** → **Save**.

The WMS exchanges the client ID and secret for a 24-hour token and renews it automatically.

## 3. Inventory: turn it on last

*Push stock levels to Shopify* **overwrites** Shopify's on-hand quantity at the mapped location with the WMS
quantity, so leave it off until the WMS stock is right (receive or cycle-count your real stock first).
Then use **Push all** once, and turn on the automatic push.

- Pushed quantity = WMS on-hand with status *Available* in that warehouse, including stock already picked
  but not yet shipped. Shopify then shows *available = on-hand − committed* (unfulfilled orders), so orders
  waiting in the WMS aren't double-counted.
- Held, damaged and quarantined stock is excluded.
- After the first push, only changed items are sent.
- The item must be tracked and stocked at that Shopify location. Otherwise the push notes
  "not stocked at the location" for that SKU.

## 4. How orders come across

- Imported: unfulfilled, shippable line items (`unfulfilledQuantity`). Skipped: cancelled orders, fully
  fulfilled ones, payment voided/refunded/expired, and test orders if you untick *Include test orders*.
- **Category** comes from order **tags**: tag an order `consolidation` (or any value in the Category list)
  and the WMS order gets that category, which also flows to SOFTBOT.
- A line whose product isn't in the WMS gets a placeholder item (its SKU, or `SHOPIFY-<variant id>`), so
  the order still imports. Run *Import products* to fill in its details.
- If an order is edited in Shopify while still *NEW* in the WMS, its lines and address are refreshed.
  After release, the change is only noted in the sync log for you to handle.
- Re-syncing never creates duplicates.

## 5. Troubleshooting

- **Sync log** (bottom of the Shopify page): every run with counts. Click a row for its notes or error.
- `app_not_installed`: the app was created but not installed on that store, or the store domain points at a
  different store. Use *Install app* in the Dev Dashboard.
- `shop_not_permitted`: the app and the store aren't in the same organization.
- Fulfillment **FAILED** on an order: the reason shows on the order. Fix it in Shopify (e.g. order on hold),
  then click **Retry Shopify fulfillment** on the order.
- Customer name/address blank on imported orders: request *protected customer data* access (name, email,
  phone, address) for the app in the Dev Dashboard, then reinstall.
- Run the WMS as one process (the default), so only one background sync runs.
