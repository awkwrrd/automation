import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { useApp } from "../context";
import { AdjustModal, MoveModal } from "../components/InventoryActions";
import { Card, DataTable, ErrorBox, Field, Input, LocationPicker, PageHeader, Pill, Select, Stat, fmtDate, fmtDateTime, fmtNum, useAction, useLoad } from "../components/ui";
import type { Balance, Item, Page, Supplier, Txn } from "../types";

const BLANK: Partial<Item> = { sku: "", name: "", uom: "EA", unit_type: "EACH", weight_unit: "lb", dim_unit: "in", reorder_point: 0, reorder_qty: 0, lot_tracked: false, active: true };
const NUM_FIELDS = ["unit_cost", "price", "weight", "length", "width", "height"] as const;

export default function ItemDetail() {
  const { id } = useParams();
  const isNew = id === "new";
  const nav = useNavigate();
  const { can, meta } = useApp();
  const { busy, run } = useAction();
  const [form, setForm] = useState<Partial<Item>>(BLANK);
  const [modal, setModal] = useState<"adjust" | "move" | null>(null);
  const editable = can("SUPERVISOR");
  const item = useLoad(() => (isNew ? Promise.resolve(null) : api.get<Item>(`/items/${id}`)), [id]);
  const suppliers = useLoad(() => api.get<Supplier[]>("/suppliers"), []);
  const bals = useLoad(() => (isNew ? Promise.resolve(null) : api.get<Page<Balance>>("/inventory/balances", { item_id: id, limit: 200 })), [id]);
  const txns = useLoad(() => (isNew ? Promise.resolve(null) : api.get<Page<Txn>>("/inventory/transactions", { item_id: id, limit: 25 })), [id]);
  useEffect(() => { if (item.data) setForm(item.data); }, [item.data]);

  const set = (k: keyof Item, v: unknown) => setForm((f) => ({ ...f, [k]: v }));
  const txt = (k: keyof Item, props: Record<string, unknown> = {}) => (
    <Input value={(form[k] as string | number | null) ?? ""} disabled={!editable} onChange={(e) => set(k, e.target.value)} {...props} />
  );
  const save = async () => {
    const body: Record<string, unknown> = { ...form };
    ["id", "created_at", "updated_at", "on_hand", "allocated", "available", "default_location"].forEach((k) => delete body[k]);
    NUM_FIELDS.forEach((k) => { if (body[k] === "") body[k] = null; });
    ["description", "barcode", "category", "brand", "image_url", "shopify_product_id", "shopify_variant_id", "shopify_inventory_item_id"].forEach((k) => { if (body[k] === "") body[k] = null; });
    body.reorder_point = Number(body.reorder_point || 0);
    body.reorder_qty = Number(body.reorder_qty || 0);
    body.supplier_id = body.supplier_id ? Number(body.supplier_id) : null;
    const saved = await run(() => (isNew ? api.post<Item>("/items", body) : api.put<Item>(`/items/${id}`, body)), "Item saved");
    if (saved) { if (isNew) nav(`/items/${saved.id}`, { replace: true }); else item.setData(saved); }
  };
  const refresh = () => { item.reload(); bals.reload(); txns.reload(); };
  const i = item.data;

  return (
    <>
      <PageHeader crumbs={<Link to="/items">Items</Link>} title={isNew ? "New item" : <>{form.sku} <span className="muted" style={{ fontWeight: 400 }}>· {i?.name}</span></>}
        actions={<>
          {!isNew && <button className="btn" onClick={() => setModal("move")}>Move</button>}
          {!isNew && editable && <button className="btn" onClick={() => setModal("adjust")}>Adjust</button>}
          {editable && <button className="btn btn-primary" disabled={busy || !form.sku || !form.name} onClick={save}>{isNew ? "Create item" : "Save changes"}</button>}
        </>} />
      <ErrorBox error={item.error} />
      {i && (
        <div className="stats">
          <Stat label="On hand" value={fmtNum(i.on_hand)} />
          <Stat label="Allocated" value={fmtNum(i.allocated)} />
          <Stat label="Available to sell" value={fmtNum(i.available)} tone={i.reorder_point > 0 && i.available <= i.reorder_point ? "warn" : undefined} sub={i.reorder_point ? `Reorder point ${i.reorder_point}` : undefined} />
          <Stat label="Locations" value={fmtNum(new Set(bals.data?.items.map((b) => b.location.id)).size)} />
        </div>
      )}
      <Card title="Item details">
        <div className="form-grid">
          <Field label="SKU *">{txt("sku")}</Field>
          <Field label="Description *" span={2}>{txt("name")}</Field>
          <Field label="Barcode / UPC">{txt("barcode")}</Field>
          <Field label="Category">{txt("category")}</Field>
          <Field label="Brand">{txt("brand")}</Field>
          <Field label="Supplier">
            <Select value={form.supplier_id ?? ""} disabled={!editable} onChange={(e) => set("supplier_id", e.target.value)} placeholder="—" options={(suppliers.data ?? []).map((s) => ({ value: s.id, label: s.name }))} />
          </Field>
          <Field label="Unit of measure">{txt("uom")}</Field>
          <Field label="Unit type" hint="Sent to automation, e.g. LINEAR for goods sold by length">
            <Select value={form.unit_type ?? ""} disabled={!editable} onChange={(e) => set("unit_type", e.target.value || null)} placeholder="—"
              options={[...new Set([...(meta?.unit_types ?? []), ...(form.unit_type ? [form.unit_type] : [])])]} />
          </Field>
          <div className="form-section">Pricing & replenishment</div>
          <Field label="Unit cost">{txt("unit_cost", { type: "number", step: "0.01" })}</Field>
          <Field label="Sell price">{txt("price", { type: "number", step: "0.01" })}</Field>
          <Field label="Reorder point" hint="Flag as low stock at or below this available qty">{txt("reorder_point", { type: "number", min: 0 })}</Field>
          <Field label="Reorder quantity">{txt("reorder_qty", { type: "number", min: 0 })}</Field>
          <div className="form-section">Physical</div>
          <Field label={`Weight (${form.weight_unit})`}>{txt("weight", { type: "number", step: "0.001" })}</Field>
          <Field label={`Length (${form.dim_unit})`}>{txt("length", { type: "number", step: "0.01" })}</Field>
          <Field label={`Width (${form.dim_unit})`}>{txt("width", { type: "number", step: "0.01" })}</Field>
          <Field label={`Height (${form.dim_unit})`}>{txt("height", { type: "number", step: "0.01" })}</Field>
          <div className="form-section">Warehouse handling</div>
          <Field label="Home / putaway location" hint="Directed putaway sends receipts here first">
            {editable ? <LocationPicker value={form.default_location ?? null} onChange={(l) => setForm((f) => ({ ...f, default_location: l, default_location_id: l?.id ?? null }))} /> : <Input disabled value={form.default_location?.code ?? ""} />}
          </Field>
          <Field group label="Tracking"><label className="check"><input type="checkbox" disabled={!editable} checked={!!form.lot_tracked} onChange={(e) => set("lot_tracked", e.target.checked)} /> Lot / expiry tracked</label></Field>
          <Field group label="Status"><label className="check"><input type="checkbox" disabled={!editable} checked={!!form.active} onChange={(e) => set("active", e.target.checked)} /> Active</label></Field>
          <Field label="Image URL">{txt("image_url")}</Field>
          <div className="form-section">Shopify mapping</div>
          <Field label="Product ID">{txt("shopify_product_id")}</Field>
          <Field label="Variant ID">{txt("shopify_variant_id")}</Field>
          <Field label="Inventory item ID">{txt("shopify_inventory_item_id")}</Field>
          <Field label="Notes / long description" span={2}>
            <textarea className="input" disabled={!editable} value={form.description ?? ""} onChange={(e) => set("description", e.target.value)} />
          </Field>
        </div>
      </Card>
      {!isNew && (
        <div className="grid-2">
          <Card title="Stock by location" pad={false}>
            <DataTable rows={bals.data?.items} loading={bals.loading} rowKey={(b) => b.id} empty="No stock" columns={[
              { key: "loc", header: "Location", render: (b) => <span className="mono">{b.location.code}</span> },
              { key: "lot", header: "Lot", render: (b) => b.lot_number || "—" },
              { key: "exp", header: "Expires", render: (b) => (b.expiration_date ? fmtDate(b.expiration_date) : "—") },
              { key: "st", header: "Status", render: (b) => <Pill value={b.status} /> },
              { key: "oh", header: "On hand", align: "right", render: (b) => fmtNum(b.qty_on_hand) },
              { key: "av", header: "Avail", align: "right", render: (b) => fmtNum(b.qty_available) },
            ]} />
          </Card>
          <Card title="Recent transactions" pad={false} actions={<Link to={`/transactions?item_id=${id}`}>All</Link>}>
            <DataTable rows={txns.data?.items} loading={txns.loading} rowKey={(t) => t.id} columns={[
              { key: "t", header: "When", render: (t) => <span className="muted">{fmtDateTime(t.created_at)}</span> },
              { key: "ty", header: "Type", render: (t) => <Pill value={t.txn_type} tone="info" /> },
              { key: "l", header: "Location", render: (t) => <span className="mono">{t.from_location?.code ?? ""}{t.from_location && t.to_location ? "→" : ""}{t.to_location?.code ?? ""}</span> },
              { key: "q", header: "Qty", align: "right", render: (t) => fmtNum(t.qty) },
              { key: "r", header: "Ref", render: (t) => t.reference_number ?? t.reason_code ?? "" },
            ]} />
          </Card>
        </div>
      )}
      {modal === "adjust" && i && <AdjustModal prefill={{ item: i }} onClose={() => setModal(null)} onDone={refresh} />}
      {modal === "move" && i && <MoveModal prefill={{ item: i }} onClose={() => setModal(null)} onDone={refresh} />}
    </>
  );
}
