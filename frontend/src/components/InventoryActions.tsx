import { useState } from "react";
import { api } from "../api";
import { useApp } from "../context";
import { Field, Input, ItemPicker, LocationPicker, Modal, Select, useAction } from "./ui";
import type { ItemRef } from "../types";

type LocRef = { id: number; code: string };
export interface Prefill { item?: ItemRef; location?: LocRef; lot?: string; status?: string; qty?: number }

export function AdjustModal({ prefill, onClose, onDone }: { prefill?: Prefill; onClose: () => void; onDone: () => void }) {
  const { meta } = useApp();
  const { busy, run } = useAction();
  const [item, setItem] = useState<ItemRef | null>(prefill?.item ?? null);
  const [loc, setLoc] = useState<LocRef | null>(prefill?.location ?? null);
  const [dir, setDir] = useState<"add" | "remove">("add");
  const [qty, setQty] = useState("");
  const [reason, setReason] = useState("");
  const [lot, setLot] = useState(prefill?.lot ?? "");
  const [status, setStatus] = useState(prefill?.status ?? "AVAILABLE");
  const [exp, setExp] = useState("");
  const [notes, setNotes] = useState("");
  const valid = item && loc && Number(qty) > 0 && reason;
  const submit = async () => {
    const r = await run(() => api.post("/inventory/adjust", {
      item_id: item!.id, location_id: loc!.id, qty: dir === "add" ? Number(qty) : -Number(qty), reason_code: reason,
      lot_number: lot, status, expiration_date: exp || null, notes: notes || null,
    }), "Adjustment posted");
    if (r) { onDone(); onClose(); }
  };
  return (
    <Modal title="Inventory adjustment" onClose={onClose} footer={<>
      <button className="btn" onClick={onClose}>Cancel</button>
      <button className="btn btn-primary" disabled={!valid || busy} onClick={submit}>Post adjustment</button>
    </>}>
      <div className="form-grid">
        <Field label="Item" span={2}><ItemPicker value={item} onChange={setItem} autoFocus={!item} /></Field>
        <Field label="Location" span={2}><LocationPicker value={loc} onChange={setLoc} /></Field>
        <Field label="Direction"><Select value={dir} onChange={(e) => setDir(e.target.value as "add" | "remove")} options={[{ value: "add", label: "Add (+)" }, { value: "remove", label: "Remove (−)" }]} /></Field>
        <Field label="Quantity"><Input type="number" min={1} value={qty} onChange={(e) => setQty(e.target.value)} /></Field>
        <Field label="Reason code"><Select value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Select…" options={meta?.adjust_reasons ?? []} /></Field>
        <Field label="Inventory status"><Select value={status} onChange={(e) => setStatus(e.target.value)} options={meta?.inventory_statuses ?? []} /></Field>
        <Field label="Lot number"><Input value={lot} onChange={(e) => setLot(e.target.value)} placeholder="(none)" /></Field>
        {dir === "add" && <Field label="Expiration date"><Input type="date" value={exp} onChange={(e) => setExp(e.target.value)} /></Field>}
        <Field label="Notes" span={2}><Input value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}

export function MoveModal({ prefill, onClose, onDone }: { prefill?: Prefill; onClose: () => void; onDone: () => void }) {
  const { busy, run } = useAction();
  const [item, setItem] = useState<ItemRef | null>(prefill?.item ?? null);
  const [from, setFrom] = useState<LocRef | null>(prefill?.location ?? null);
  const [to, setTo] = useState<LocRef | null>(null);
  const [qty, setQty] = useState(prefill?.qty ? String(prefill.qty) : "");
  const [lot, setLot] = useState(prefill?.lot ?? "");
  const valid = item && from && to && Number(qty) > 0;
  const submit = async () => {
    const r = await run(() => api.post("/inventory/move", {
      item_id: item!.id, from_location_id: from!.id, to_location_id: to!.id, qty: Number(qty), lot_number: lot,
      status: prefill?.status ?? "AVAILABLE",
    }), "Move completed");
    if (r) { onDone(); onClose(); }
  };
  return (
    <Modal title="Move inventory" onClose={onClose} footer={<>
      <button className="btn" onClick={onClose}>Cancel</button>
      <button className="btn btn-primary" disabled={!valid || busy} onClick={submit}>Move</button>
    </>}>
      <div className="form-grid">
        <Field label="Item" span={2}><ItemPicker value={item} onChange={setItem} autoFocus={!item} /></Field>
        <Field label="From location"><LocationPicker value={from} onChange={setFrom} filter={{ empty: false }} /></Field>
        <Field label="To location"><LocationPicker value={to} onChange={setTo} /></Field>
        <Field label="Quantity" hint={prefill?.qty ? `${prefill.qty} available` : undefined}><Input type="number" min={1} value={qty} onChange={(e) => setQty(e.target.value)} /></Field>
        <Field label="Lot number"><Input value={lot} onChange={(e) => setLot(e.target.value)} placeholder="(none)" /></Field>
      </div>
    </Modal>
  );
}

export function StatusModal({ prefill, onClose, onDone }: { prefill: Prefill; onClose: () => void; onDone: () => void }) {
  const { meta } = useApp();
  const { busy, run } = useAction();
  const [to, setTo] = useState("");
  const [qty, setQty] = useState(prefill.qty ? String(prefill.qty) : "");
  const [reason, setReason] = useState("");
  const submit = async () => {
    const r = await run(() => api.post("/inventory/status", {
      item_id: prefill.item!.id, location_id: prefill.location!.id, qty: Number(qty), from_status: prefill.status,
      to_status: to, lot_number: prefill.lot ?? "", reason_code: reason || null,
    }), "Status changed");
    if (r) { onDone(); onClose(); }
  };
  return (
    <Modal title="Change inventory status" onClose={onClose} footer={<>
      <button className="btn" onClick={onClose}>Cancel</button>
      <button className="btn btn-primary" disabled={!to || !(Number(qty) > 0) || busy} onClick={submit}>Apply</button>
    </>}>
      <p className="muted" style={{ marginTop: 0 }}>
        <b>{prefill.item?.sku}</b> at <span className="mono">{prefill.location?.code}</span>{prefill.lot ? ` · lot ${prefill.lot}` : ""} — currently <b>{prefill.status}</b>
      </p>
      <div className="form-grid">
        <Field label="New status"><Select value={to} onChange={(e) => setTo(e.target.value)} placeholder="Select…" options={(meta?.inventory_statuses ?? []).filter((s) => s !== prefill.status)} /></Field>
        <Field label="Quantity"><Input type="number" min={1} value={qty} onChange={(e) => setQty(e.target.value)} /></Field>
        <Field label="Reason" span={2}><Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. QC inspection" /></Field>
      </div>
    </Modal>
  );
}
