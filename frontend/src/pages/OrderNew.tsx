import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useApp } from "../context";
import { LineEditor, type DraftLine } from "../components/LineEditor";
import { Card, Field, Input, PageHeader, Select, useAction } from "../components/ui";
import type { Order } from "../types";

const FIELDS: [string, string, number?][] = [
  ["customer_name", "Customer name"], ["customer_email", "Email"], ["customer_phone", "Phone"],
  ["ship_name", "Ship-to name"], ["ship_address1", "Address line 1", 2], ["ship_address2", "Address line 2"],
  ["ship_city", "City"], ["ship_state", "State / province"], ["ship_postal_code", "Postal code"], ["ship_country", "Country"],
];

export default function OrderNew() {
  const { warehouseId, meta } = useApp();
  const nav = useNavigate();
  const { busy, run } = useAction();
  const [h, setH] = useState<Record<string, string>>({ channel: "MANUAL", category: "STANDARD", priority: "5", ship_country: "US", ship_method: "Ground" });
  const [lines, setLines] = useState<DraftLine[]>([]);
  const set = (k: string, v: string) => setH((x) => ({ ...x, [k]: v }));
  const save = async () => {
    const body: Record<string, unknown> = { warehouse_id: warehouseId, lines: lines.map((l) => ({ item_id: l.item.id, qty_ordered: l.qty })) };
    Object.entries(h).forEach(([k, v]) => { body[k] = v === "" ? null : v; });
    body.priority = Number(h.priority || 5);
    const o = await run(() => api.post<Order>("/orders", body), "Order created");
    if (o) nav(`/orders/${o.id}`);
  };
  return (
    <>
      <PageHeader crumbs={<Link to="/orders">Orders</Link>} title="New order" actions={
        <button className="btn btn-primary" disabled={busy || lines.length === 0} onClick={save}>Create order</button>} />
      <Card title="Order">
        <div className="form-grid">
          <Field label="Channel"><Select value={h.channel} onChange={(e) => set("channel", e.target.value)} options={["MANUAL", "SHOPIFY", "PHONE", "WHOLESALE"]} /></Field>
          <Field label="Channel order # (external id)"><Input value={h.external_id ?? ""} onChange={(e) => set("external_id", e.target.value)} /></Field>
          <Field label="Category" hint="Sent to automation, e.g. CONSOLIDATION"><Select value={h.category} onChange={(e) => set("category", e.target.value)} options={meta?.order_categories ?? ["STANDARD"]} /></Field>
          <Field label="Priority" hint="1 = highest"><Select value={h.priority} onChange={(e) => set("priority", e.target.value)} options={["1", "2", "3", "4", "5", "6", "7", "8", "9"].map((p) => ({ value: p, label: p }))} /></Field>
          <Field label="Ship method"><Input value={h.ship_method ?? ""} onChange={(e) => set("ship_method", e.target.value)} /></Field>
          <Field label="Requested ship date"><Input type="date" value={h.requested_ship_date ?? ""} onChange={(e) => set("requested_ship_date", e.target.value)} /></Field>
          <div className="form-section">Customer & ship-to</div>
          {FIELDS.map(([k, l, span]) => <Field key={k} label={l} span={span}><Input value={h[k] ?? ""} onChange={(e) => set(k, e.target.value)} /></Field>)}
          <Field label="Notes" span={2}><Input value={h.notes ?? ""} onChange={(e) => set("notes", e.target.value)} /></Field>
        </div>
      </Card>
      <Card title="Lines"><LineEditor lines={lines} setLines={setLines} /></Card>
    </>
  );
}
