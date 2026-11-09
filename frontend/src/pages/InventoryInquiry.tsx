import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useApp } from "../context";
import { AdjustModal, MoveModal, StatusModal, type Prefill } from "../components/InventoryActions";
import { Card, DataTable, ErrorBox, PageHeader, Pager, Pill, SearchBox, Select, fmtDate, fmtNum, useDebounced, useLoad } from "../components/ui";
import type { Balance, Page, Zone } from "../types";

export default function InventoryInquiry() {
  const { warehouseId, meta, can } = useApp();
  const [q, setQ] = useState("");
  const [locQ, setLocQ] = useState("");
  const [zone, setZone] = useState("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const [modal, setModal] = useState<null | { kind: "adjust" | "move" | "status"; prefill?: Prefill }>(null);
  const dq = useDebounced(q), dl = useDebounced(locQ);
  const limit = 100;
  const zones = useLoad(() => api.get<Zone[]>("/zones", { warehouse_id: warehouseId }), [warehouseId]);
  const { data, error, loading, reload } = useLoad(() => api.get<Page<Balance>>("/inventory/balances", {
    warehouse_id: warehouseId, q: dq, location: dl, zone_id: zone, status, limit, offset,
  }), [warehouseId, dq, dl, zone, status, offset]);
  const pre = (b: Balance): Prefill => ({ item: b.item, location: b.location, lot: b.lot_number, status: b.status, qty: b.qty_available });
  const totals = data?.items.reduce((a, b) => ({ oh: a.oh + b.qty_on_hand, al: a.al + b.qty_allocated }), { oh: 0, al: 0 });
  return (
    <>
      <PageHeader title="Inventory Inquiry" subtitle="On-hand inventory by item, location, lot and status" actions={<>
        <button className="btn" onClick={() => setModal({ kind: "move" })}>Move</button>
        {can("SUPERVISOR") && <button className="btn btn-primary" onClick={() => setModal({ kind: "adjust" })}>Adjust</button>}
      </>} />
      <ErrorBox error={error} />
      <Card pad={false}>
        <div className="toolbar">
          <SearchBox value={q} onChange={(v) => { setQ(v); setOffset(0); }} placeholder="SKU, name or barcode" />
          <input className="input mono" style={{ width: 160 }} placeholder="Location" value={locQ} onChange={(e) => { setLocQ(e.target.value); setOffset(0); }} />
          <Select value={zone} onChange={(e) => { setZone(e.target.value); setOffset(0); }} placeholder="All zones" options={(zones.data ?? []).map((z) => ({ value: z.id, label: `${z.code} — ${z.name}` }))} />
          <Select value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }} placeholder="All statuses" options={meta?.inventory_statuses ?? []} />
          {totals && <span className="muted" style={{ marginLeft: "auto", fontSize: 12.5 }}>Page totals: <b>{fmtNum(totals.oh)}</b> on hand · <b>{fmtNum(totals.al)}</b> allocated</span>}
        </div>
        <DataTable rows={data?.items} loading={loading} rowKey={(b) => b.id} columns={[
          { key: "sku", header: "SKU", render: (b) => <Link to={`/items/${b.item.id}`}><b>{b.item.sku}</b></Link> },
          { key: "name", header: "Description", render: (b) => b.item.name },
          { key: "loc", header: "Location", render: (b) => <span className="mono">{b.location.code}</span> },
          { key: "zone", header: "Zone", render: (b) => b.zone_code ?? "—" },
          { key: "lot", header: "Lot", render: (b) => b.lot_number || <span className="muted">—</span> },
          { key: "exp", header: "Expires", render: (b) => (b.expiration_date ? fmtDate(b.expiration_date) : <span className="muted">—</span>) },
          { key: "status", header: "Status", render: (b) => <Pill value={b.status} /> },
          { key: "oh", header: "On hand", align: "right", render: (b) => <b>{fmtNum(b.qty_on_hand)}</b> },
          { key: "al", header: "Allocated", align: "right", render: (b) => (b.qty_allocated ? fmtNum(b.qty_allocated) : <span className="muted">0</span>) },
          { key: "av", header: "Available", align: "right", render: (b) => fmtNum(b.qty_available) },
          { key: "act", header: "", align: "right", render: (b) => (
            <span className="actions" style={{ justifyContent: "flex-end", flexWrap: "nowrap" }}>
              <button className="btn btn-sm" onClick={() => setModal({ kind: "move", prefill: pre(b) })} disabled={b.qty_available <= 0}>Move</button>
              {can("SUPERVISOR") && <button className="btn btn-sm" onClick={() => setModal({ kind: "adjust", prefill: pre(b) })}>Adjust</button>}
              {can("SUPERVISOR") && <button className="btn btn-sm" onClick={() => setModal({ kind: "status", prefill: pre(b) })} disabled={b.qty_available <= 0}>Status</button>}
            </span>
          ) },
        ]} />
        <Pager total={data?.total ?? 0} limit={limit} offset={offset} onChange={setOffset} />
      </Card>
      {modal?.kind === "adjust" && <AdjustModal prefill={modal.prefill} onClose={() => setModal(null)} onDone={reload} />}
      {modal?.kind === "move" && <MoveModal prefill={modal.prefill} onClose={() => setModal(null)} onDone={reload} />}
      {modal?.kind === "status" && modal.prefill && <StatusModal prefill={modal.prefill} onClose={() => setModal(null)} onDone={reload} />}
    </>
  );
}
