import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useApp } from "../context";
import { Card, DataTable, ErrorBox, Field, Input, Modal, PageHeader, Pager, Pill, SearchBox, Select, fmtDate, fmtNum, label, useAction, useDebounced, useLoad } from "../components/ui";
import type { Order, Page, Wave } from "../types";

const WAVEABLE = ["NEW", "PARTIALLY_ALLOCATED", "ALLOCATED"];

export default function Orders() {
  const nav = useNavigate();
  const [sp] = useSearchParams();
  const { warehouseId, meta, can } = useApp();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState(sp.get("status") ?? "open");
  const [offset, setOffset] = useState(0);
  const [sel, setSel] = useState<Set<number | string>>(new Set());
  const [waveModal, setWaveModal] = useState(false);
  const dq = useDebounced(q);
  const limit = 50;
  const wave = sp.get("wave") ?? "";
  const { data, error, loading, reload } = useLoad(() => api.get<Page<Order>>("/orders", {
    warehouse_id: warehouseId, q: dq, status: status === "open" ? "" : status, open_only: status === "open" && !wave, wave_id: wave, limit, offset,
  }), [warehouseId, dq, status, wave, offset]);
  const selectedOrders = (data?.items ?? []).filter((o) => sel.has(o.id));
  const canWave = selectedOrders.length > 0 && selectedOrders.every((o) => WAVEABLE.includes(o.status) && !o.wave);
  return (
    <>
      <PageHeader title="Orders" subtitle="Customer orders to fulfil" actions={<>
        {can("SUPERVISOR") && <button className="btn" disabled={!canWave} onClick={() => setWaveModal(true)} title="Select unwaved NEW/ALLOCATED orders">Create wave ({selectedOrders.length})</button>}
        <Link className="btn btn-primary" to="/orders/new">New order</Link>
      </>} />
      <ErrorBox error={error} />
      <Card pad={false}>
        <div className="toolbar">
          <SearchBox value={q} onChange={(v) => { setQ(v); setOffset(0); }} placeholder="Order #, Shopify #, customer" />
          <Select value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); setSel(new Set()); }} options={[
            { value: "open", label: "All open" }, { value: "", label: "All statuses" },
            ...(meta?.order_statuses ?? []).map((s) => ({ value: s, label: label(s) })),
          ]} />
        </div>
        <DataTable rows={data?.items} loading={loading} rowKey={(o) => o.id} onRowClick={(o) => nav(`/orders/${o.id}`)}
          selected={can("SUPERVISOR") ? sel : undefined} onSelect={can("SUPERVISOR") ? setSel : undefined} columns={[
          { key: "number", header: "Order #", render: (o) => <b>{o.number}</b> },
          { key: "ext", header: "Channel ref", render: (o) => (o.external_id ? <span>{o.external_id} <span className="muted">· {o.channel.toLowerCase()}</span></span> : <span className="muted">{o.channel.toLowerCase()}</span>) },
          { key: "cust", header: "Customer", render: (o) => o.customer_name ?? "—" },
          { key: "dest", header: "Ship to", render: (o) => [o.ship_city, o.ship_state].filter(Boolean).join(", ") || "—" },
          { key: "pri", header: "Pri", align: "center", render: (o) => o.priority },
          { key: "lines", header: "Lines", align: "right", render: (o) => o.line_count },
          { key: "units", header: "Units", align: "right", render: (o) => fmtNum(o.units) },
          { key: "wave", header: "Wave", render: (o) => o.wave?.number ?? "" },
          { key: "status", header: "Status", render: (o) => <Pill value={o.status} /> },
          { key: "created", header: "Created", render: (o) => fmtDate(o.created_at) },
        ]} />
        <Pager total={data?.total ?? 0} limit={limit} offset={offset} onChange={setOffset} />
      </Card>
      {waveModal && <CreateWave orderIds={selectedOrders.map((o) => o.id)} onClose={() => setWaveModal(false)} onDone={() => { setSel(new Set()); reload(); }} />}
    </>
  );
}

function CreateWave({ orderIds, onClose, onDone }: { orderIds: number[]; onClose: () => void; onDone: () => void }) {
  const { warehouseId } = useApp();
  const { busy, run } = useAction();
  const nav = useNavigate();
  const [desc, setDesc] = useState("");
  const [release, setRelease] = useState(true);
  const submit = async () => {
    const w = await run(() => api.post<Wave>("/waves", { warehouse_id: warehouseId, order_ids: orderIds, description: desc || null }));
    if (!w) return;
    if (release) {
      const res = await run(() => api.post<{ tasks_created: number; orders_not_released: string[] }>(`/waves/${w.id}/release`),
        `Wave ${w.number} released`);
      if (res?.orders_not_released.length) alert(`No stock to release for: ${res.orders_not_released.join(", ")}`);
    }
    onDone(); onClose(); nav("/waves");
  };
  return (
    <Modal title={`Create wave from ${orderIds.length} order(s)`} onClose={onClose} footer={<>
      <button className="btn" onClick={onClose}>Cancel</button>
      <button className="btn btn-primary" disabled={busy} onClick={submit}>Create wave</button>
    </>}>
      <div className="form-grid">
        <Field label="Description" span={2}><Input value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="e.g. Morning ground orders" /></Field>
        <Field label="" span={2}><label className="check"><input type="checkbox" checked={release} onChange={(e) => setRelease(e.target.checked)} /> Allocate & release immediately (creates pick tasks)</label></Field>
      </div>
    </Modal>
  );
}
