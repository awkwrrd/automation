import { useEffect, useState } from "react";
import { api } from "../api";
import { useApp } from "../context";
import { Card, DataTable, ErrorBox, Field, Input, LocationPicker, Modal, PageHeader, Pager, Pill, Select, fmtDateTime, useAction, useLoad } from "../components/ui";
import type { Page, ShopifyStore, SyncRun } from "../types";

type Loc = { id: string; name: string; active: boolean };
const KIND_LABEL: Record<string, string> = { TEST: "Connection test", PRODUCTS: "Product import", ORDERS: "Order sync", FULFILLMENTS: "Fulfillments", INVENTORY: "Inventory push", STOCK_IMPORT: "Starting stock import" };

function summaryText(r: SyncRun) {
  if (r.error) return <span className="qty-neg">{r.error}</span>;
  if (!r.summary) return "";
  if (r.kind === "TEST") return `${r.summary.shop} · ${(r.summary.locations as Loc[] | undefined)?.length ?? 0} location(s)`;
  if (r.kind === "PRODUCTS" && r.summary.variants_found === 0) return <span className="qty-neg">Shopify returned no products</span>;
  if (r.kind === "ORDERS" && r.summary.checked === 0) return <span className="qty-neg">Shopify returned no orders in range</span>;
  return Object.entries(r.summary).filter(([k, v]) => typeof v === "number" && v && k !== "pages").map(([k, v]) => `${v} ${k.replace(/_/g, " ")}`).join(" · ") || "no changes";
}

export default function Shopify() {
  const { can } = useApp();
  const admin = can("ADMIN");
  const { busy, run } = useAction();
  const store = useLoad(() => api.get<ShopifyStore | null>("/shopify/store"), []);
  const [offset, setOffset] = useState(0);
  const runs = useLoad(() => api.get<Page<SyncRun>>("/shopify/runs", { limit: 25, offset }), [offset]);
  const lastTest = useLoad(() => api.get<Page<SyncRun>>("/shopify/runs", { kind: "TEST", status: "OK", limit: 1 }), []);
  const [open, setOpen] = useState<SyncRun | null>(null);
  const [stockModal, setStockModal] = useState(false);
  const [stockLoc, setStockLoc] = useState<{ id: number; code: string } | null>(null);
  const s = store.data;
  const locations = ((lastTest.data?.items[0]?.summary?.locations as Loc[] | undefined) ?? []);
  const missing = (lastTest.data?.items[0]?.summary?.missing_scopes as string[] | undefined) ?? [];

  const refresh = () => { store.reload(); runs.reload(); lastTest.reload(); };
  const action = async (path: string, params?: Record<string, string | boolean | number>) => {
    const r = await run(() => api.post<SyncRun>(path, undefined, params));
    if (r) { refresh(); if (r.status === "ERROR" || (r.summary?.messages?.length ?? 0) > 0 || r.kind === "TEST") setOpen(r); }
  };

  return (
    <>
      <PageHeader title="Shopify" subtitle="Import products and orders from your store, send fulfillments with tracking back, and keep Shopify's stock levels in step with the warehouse" />
      <ErrorBox error={store.error} />
      {s?.last_error && <div className="error-box">Last error — {s.last_error}</div>}
      {admin ? <Connection store={s} locations={locations} missing={missing} onSaved={refresh} onTest={() => action("/shopify/test")} busy={busy} />
        : !s && <Card><p className="muted">Not connected. An admin can connect a store here.</p></Card>}
      {s && (
        <Card title="Sync" actions={<span className="muted" style={{ fontSize: 12.5 }}>
          {s.active ? <>Automatic every {s.poll_minutes} min · last {fmtDateTime(s.last_sync_at)}</> : "Automatic sync is off"}</span>}>
          <div className="stats" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))" }}>
            <ActionTile title="Products" text="Create/update WMS items from Shopify variants (matched by variant, then SKU)."
              button="Import products" busy={busy} onClick={() => action("/shopify/import-products")} />
            <ActionTile title="Orders" text={s.orders_cursor ? `Up to Shopify changes at ${fmtDateTime(s.orders_cursor)}` : `Orders created since ${fmtDateTime(s.orders_since)}`}
              button="Sync orders now" busy={busy} onClick={() => action("/shopify/sync-orders")} />
            <ActionTile title="Fulfillments" text={<>{s.pending_fulfillments} waiting · {s.failed_fulfillments ? <span className="qty-neg">{s.failed_fulfillments} failed</span> : "0 failed"}</>}
              button="Send now" busy={busy} onClick={() => action("/shopify/fulfillments")} />
            <ActionTile title="Inventory" text={s.push_inventory ? "Pushes changed on-hand quantities." : "Automatic push is off (turn on below once stock is counted)."}
              button="Push changes" busy={busy} onClick={() => action("/shopify/push-inventory")}
              extra={<button className="btn btn-sm" disabled={busy} onClick={() => action("/shopify/push-inventory", { full: true })}>Push all</button>} />
            {admin && <ActionTile title="Starting stock" text="One-time: copy Shopify's on-hand quantities into a WMS location, for products that have no WMS stock yet."
              button="Import stock from Shopify…" busy={busy} onClick={() => setStockModal(true)} />}
          </div>
        </Card>
      )}
      {stockModal && (
        <Modal title="Import starting stock from Shopify" onClose={() => setStockModal(false)} footer={<>
          <button className="btn" onClick={() => setStockModal(false)}>Cancel</button>
          <button className="btn btn-primary" disabled={busy || !stockLoc} onClick={async () => {
            setStockModal(false); await action("/shopify/import-stock", { location_id: stockLoc!.id });
          }}>Import</button>
        </>}>
          <p style={{ marginTop: 0 }}>Reads each product's <b>on-hand</b> quantity at the mapped Shopify location and adds it to the WMS location below (reason <code>SHOPIFY_IMPORT</code>).</p>
          <ul className="muted" style={{ fontSize: 13, paddingLeft: 18 }}>
            <li>Only products with <b>no stock in the WMS</b> yet are imported, so running it twice doesn't double up.</li>
            <li>Run <b>Import products</b> first. Lot-tracked products are skipped (receive them with their lot).</li>
            <li>Choose a pickable bin to pick from it straight away, or a staging/dock location and move stock afterwards.</li>
          </ul>
          <Field label="Put the stock in location"><LocationPicker value={stockLoc} onChange={setStockLoc} /></Field>
        </Modal>
      )}
      <Card title="Sync log" pad={false} actions={<button className="btn btn-sm" onClick={runs.reload}>Refresh</button>}>
        <DataTable rows={runs.data?.items} loading={runs.loading} rowKey={(r) => r.id} onRowClick={setOpen} empty="Nothing has run yet" columns={[
          { key: "t", header: "Started", render: (r) => fmtDateTime(r.started_at) },
          { key: "k", header: "Job", render: (r) => KIND_LABEL[r.kind] ?? r.kind },
          { key: "tr", header: "Trigger", render: (r) => <span className="muted">{r.trigger.toLowerCase()}</span> },
          { key: "s", header: "Result", render: (r) => <Pill value={r.status === "OK" ? "OK" : r.status} tone={r.status === "OK" ? "ok" : r.status === "ERROR" ? "bad" : "warn"} raw /> },
          { key: "sum", header: "Summary", render: (r) => <>{summaryText(r)}{(r.summary?.messages?.length ?? 0) > 0 && <span className="muted"> · {r.summary!.messages!.length} note(s)</span>}</> },
        ]} />
        <Pager total={runs.data?.total ?? 0} limit={25} offset={offset} onChange={setOffset} />
      </Card>
      {open && (
        <Modal wide title={`${KIND_LABEL[open.kind] ?? open.kind} — ${open.status}`} onClose={() => setOpen(null)} footer={<button className="btn btn-primary" onClick={() => setOpen(null)}>Close</button>}>
          {open.error && <div className="error-box">{open.error}</div>}
          {open.kind === "TEST" && open.summary && (
            <dl className="kv" style={{ marginBottom: 12 }}>
              <dt>Store</dt><dd>{String(open.summary.shop)} ({String(open.summary.domain)})</dd>
              <dt>Locations</dt><dd>{(open.summary.locations as Loc[]).map((l) => l.name).join(", ") || "—"}</dd>
              <dt>Granted scopes</dt><dd style={{ fontSize: 12 }}>{(open.summary.scopes as string[]).join(", ")}</dd>
              {(open.summary.missing_scopes as string[]).length > 0 && <><dt>Missing scopes</dt><dd className="qty-neg" style={{ fontSize: 12 }}>{(open.summary.missing_scopes as string[]).join(", ")}</dd></>}
            </dl>
          )}
          {(open.summary?.messages?.length ?? 0) > 0 && <><div className="field-label">Notes</div><pre className="code">{open.summary!.messages!.join("\n")}</pre></>}
          {open.summary && open.kind !== "TEST" && <><div className="field-label">Details</div><pre className="code">{JSON.stringify({ ...open.summary, messages: undefined }, null, 2)}</pre></>}
        </Modal>
      )}
    </>
  );
}

function ActionTile({ title, text, button, onClick, busy, extra }: { title: string; text: React.ReactNode; button: string; onClick: () => void; busy: boolean; extra?: React.ReactNode }) {
  return (
    <div className="stat" style={{ boxShadow: "none", display: "flex", flexDirection: "column", gap: 8 }}>
      <div className="stat-label" style={{ fontWeight: 650, color: "var(--text)" }}>{title}</div>
      <div className="stat-sub" style={{ flex: 1 }}>{text}</div>
      <div className="actions"><button className="btn btn-sm btn-primary" disabled={busy} onClick={onClick}>{button}</button>{extra}</div>
    </div>
  );
}

function Connection({ store, locations, missing, onSaved, onTest, busy }: { store: ShopifyStore | null | undefined; locations: Loc[]; missing: string[]; onSaved: () => void; onTest: () => void; busy: boolean }) {
  const { warehouses } = useApp();
  const { busy: saving, run } = useAction();
  const blank = { shop_domain: "", auth_mode: "CLIENT_CREDENTIALS", client_id: "", client_secret: "", access_token: "", api_version: "2026-10",
    warehouse_id: "", shopify_location_id: "", active: false, poll_minutes: "5", import_orders: true, orders_since: new Date().toISOString().slice(0, 10),
    import_test_orders: true, fulfill_on_ship: true, notify_customer: true, push_inventory: false };
  const [f, setF] = useState(blank);
  useEffect(() => {
    if (store) setF({ ...blank, ...store, client_id: store.client_id ?? "", client_secret: "", access_token: "",
      warehouse_id: store.warehouse_id ? String(store.warehouse_id) : "", shopify_location_id: store.shopify_location_id ?? "",
      poll_minutes: String(store.poll_minutes), orders_since: store.orders_since ? store.orders_since.slice(0, 10) : "" });
    else if (warehouses[0]) setF((x) => ({ ...x, warehouse_id: String(warehouses[0].id) }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [store, warehouses]);
  const cc = f.auth_mode === "CLIENT_CREDENTIALS";
  const needSecret = cc ? !store?.has_client_secret && !f.client_secret : !store?.has_access_token && !f.access_token;
  const valid = f.shop_domain && (!cc || f.client_id) && !needSecret;
  const save = async () => {
    const r = await run(() => api.put("/shopify/store", {
      ...f, client_id: f.client_id || null, client_secret: f.client_secret || null, access_token: f.access_token || null,
      warehouse_id: f.warehouse_id ? Number(f.warehouse_id) : null, shopify_location_id: f.shopify_location_id || null,
      poll_minutes: Number(f.poll_minutes) || 5, orders_since: f.orders_since ? `${f.orders_since}T00:00:00` : null,
    }), "Shopify settings saved");
    if (r) onSaved();
  };
  const chk = (k: keyof typeof f, label: string, hint?: string) => (
    <Field group label="" hint={hint}><label className="check"><input type="checkbox" checked={!!f[k]} onChange={(e) => setF({ ...f, [k]: e.target.checked })} /> {label}</label></Field>
  );
  return (
    <Card title={store ? <>Connection <Pill value={store.shop_domain} tone="ok" raw /></> : "Connect your store"} actions={<>
      {store && <button className="btn btn-sm" disabled={busy || saving} onClick={onTest}>Test connection</button>}
      <button className="btn btn-sm btn-primary" disabled={saving || !valid} onClick={save}>Save</button>
    </>}>
      {!store && <div className="notice">Create an app in the Shopify <b>Dev Dashboard</b> (same organization as your store), give it the scopes below, install it on the store, then paste its Client ID and secret here. See <code>docs/SHOPIFY.md</code>.</div>}
      {missing.length > 0 && <div className="error-box">The app is missing scopes: <b>{missing.join(", ")}</b>. Add them to a new app version in the Dev Dashboard, reinstall/approve on the store, then test again.</div>}
      <div className="form-grid">
        <Field label="Store domain *" hint="your-store.myshopify.com"><Input value={f.shop_domain} onChange={(e) => setF({ ...f, shop_domain: e.target.value })} placeholder="your-store.myshopify.com" /></Field>
        <Field label="Authentication">
          <Select value={f.auth_mode} onChange={(e) => setF({ ...f, auth_mode: e.target.value })} options={[
            { value: "CLIENT_CREDENTIALS", label: "Dev Dashboard app (client ID + secret)" }, { value: "ACCESS_TOKEN", label: "Existing custom app token (shpat_…)" }]} />
        </Field>
        {cc ? <>
          <Field label="Client ID *"><Input className="input mono" value={f.client_id} onChange={(e) => setF({ ...f, client_id: e.target.value })} /></Field>
          <Field label="Client secret *" hint={store?.has_client_secret ? "Stored — leave blank to keep" : undefined}><Input type="password" autoComplete="new-password" value={f.client_secret} onChange={(e) => setF({ ...f, client_secret: e.target.value })} /></Field>
        </> : <Field label="Admin API access token *" span={2} hint={store?.has_access_token ? "Stored — leave blank to keep" : undefined}><Input type="password" autoComplete="new-password" value={f.access_token} onChange={(e) => setF({ ...f, access_token: e.target.value })} /></Field>}
        <Field label="API version" hint="Shopify supports each version for 12 months"><Input className="input mono" value={f.api_version} onChange={(e) => setF({ ...f, api_version: e.target.value })} /></Field>
        {store?.token_expires_at && <Field label="Current token"><span className="muted" style={{ paddingTop: 8 }}>valid until {fmtDateTime(store.token_expires_at)} (renewed automatically)</span></Field>}

        <div className="form-section">Mapping</div>
        <Field label="Orders go to warehouse *"><Select value={f.warehouse_id} onChange={(e) => setF({ ...f, warehouse_id: e.target.value })} placeholder="Select…" options={warehouses.map((w) => ({ value: w.id, label: `${w.code} — ${w.name}` }))} /></Field>
        <Field label="Shopify location for this warehouse" hint={locations.length ? "Stock levels are pushed to this location" : "Save, then Test connection to load your locations"}>
          {locations.length
            ? <Select value={f.shopify_location_id} onChange={(e) => setF({ ...f, shopify_location_id: e.target.value })} placeholder="— not mapped —" options={locations.map((l) => ({ value: l.id, label: `${l.name}${l.active ? "" : " (inactive)"}` }))} />
            : <Input className="input mono" value={f.shopify_location_id} onChange={(e) => setF({ ...f, shopify_location_id: e.target.value })} placeholder="gid://shopify/Location/…" />}
        </Field>

        <div className="form-section">What to sync</div>
        <Field label="Import orders created since" hint="Changing this re-scans from that date (no duplicates)"><Input type="date" value={f.orders_since} onChange={(e) => setF({ ...f, orders_since: e.target.value })} /></Field>
        <Field label="Check every (minutes)"><Input type="number" min={1} value={f.poll_minutes} onChange={(e) => setF({ ...f, poll_minutes: e.target.value })} /></Field>
        {chk("import_orders", "Import orders")}
        {chk("import_test_orders", "Include test orders", "Dev-store orders are usually test orders")}
        {chk("fulfill_on_ship", "Create Shopify fulfillment when an order ships")}
        {chk("notify_customer", "Email the customer their tracking")}
        {chk("push_inventory", "Push stock levels to Shopify", "Overwrites Shopify on-hand at the mapped location with the WMS quantity. Turn on only after the WMS stock is correct.")}
        {chk("active", "Run automatically in the background")}
      </div>
    </Card>
  );
}
