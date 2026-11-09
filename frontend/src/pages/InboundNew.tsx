import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useApp } from "../context";
import { LineEditor, type DraftLine } from "../components/LineEditor";
import { Card, Field, Input, PageHeader, Select, useAction, useLoad } from "../components/ui";
import type { Inbound, Supplier } from "../types";

export default function InboundNew() {
  const { warehouseId, meta } = useApp();
  const nav = useNavigate();
  const { busy, run } = useAction();
  const suppliers = useLoad(() => api.get<Supplier[]>("/suppliers"), []);
  const [h, setH] = useState({ order_type: "PO", supplier_id: "", reference: "", expected_date: "", notes: "" });
  const [lines, setLines] = useState<DraftLine[]>([]);
  const save = async () => {
    const r = await run(() => api.post<Inbound>("/inbound", {
      ...h, warehouse_id: warehouseId, supplier_id: h.supplier_id ? Number(h.supplier_id) : null,
      expected_date: h.expected_date || null, reference: h.reference || null, notes: h.notes || null,
      lines: lines.map((l) => ({ item_id: l.item.id, qty_expected: l.qty })),
    }), "Receipt created");
    if (r) nav(`/inbound/${r.id}`);
  };
  return (
    <>
      <PageHeader crumbs={<Link to="/inbound">Receipts</Link>} title="New receipt" actions={
        <button className="btn btn-primary" disabled={busy || lines.length === 0 || lines.some((l) => !(l.qty > 0))} onClick={save}>Create receipt</button>} />
      <Card title="Header">
        <div className="form-grid">
          <Field label="Type"><Select value={h.order_type} onChange={(e) => setH({ ...h, order_type: e.target.value })} options={meta?.inbound_types ?? ["PO"]} /></Field>
          <Field label="Supplier"><Select value={h.supplier_id} onChange={(e) => setH({ ...h, supplier_id: e.target.value })} placeholder="—" options={(suppliers.data ?? []).map((s) => ({ value: s.id, label: s.name }))} /></Field>
          <Field label="External reference (PO #)"><Input value={h.reference} onChange={(e) => setH({ ...h, reference: e.target.value })} /></Field>
          <Field label="Expected date"><Input type="date" value={h.expected_date} onChange={(e) => setH({ ...h, expected_date: e.target.value })} /></Field>
          <Field label="Notes" span={2}><Input value={h.notes} onChange={(e) => setH({ ...h, notes: e.target.value })} /></Field>
        </div>
      </Card>
      <Card title="Lines"><LineEditor lines={lines} setLines={setLines} /></Card>
    </>
  );
}
