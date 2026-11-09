import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useApp } from "../context";
import { Card, DataTable, ErrorBox, PageHeader, Pager, Pill, SearchBox, Select, fmtDate, fmtNum, label, useDebounced, useLoad } from "../components/ui";
import type { Inbound, Page } from "../types";

export const Progress = ({ done, total }: { done: number; total: number }) => (
  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
    <div className={`progress ${done >= total ? "done" : ""}`} style={{ flex: 1 }}><span style={{ width: `${total ? Math.min(100, (done / total) * 100) : 0}%` }} /></div>
    <span className="num" style={{ fontSize: 12 }}>{fmtNum(done)}/{fmtNum(total)}</span>
  </div>
);

export default function InboundList() {
  const nav = useNavigate();
  const { warehouseId, can } = useApp();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("open");
  const [offset, setOffset] = useState(0);
  const dq = useDebounced(q);
  const limit = 50;
  const { data, error, loading } = useLoad(() => api.get<Page<Inbound>>("/inbound", {
    warehouse_id: warehouseId, q: dq, status: status === "open" ? "" : status, open_only: status === "open", limit, offset,
  }), [warehouseId, dq, status, offset]);
  return (
    <>
      <PageHeader title="Receipts / ASNs" subtitle="Purchase orders, advance ship notices and returns expected at the dock"
        actions={can("SUPERVISOR") && <Link className="btn btn-primary" to="/inbound/new">New receipt</Link>} />
      <ErrorBox error={error} />
      <Card pad={false}>
        <div className="toolbar">
          <SearchBox value={q} onChange={(v) => { setQ(v); setOffset(0); }} placeholder="Receipt # or reference" />
          <Select value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }} options={[
            { value: "open", label: "Open & receiving" }, { value: "", label: "All statuses" },
            ...["OPEN", "RECEIVING", "RECEIVED", "CLOSED", "CANCELLED"].map((s) => ({ value: s, label: label(s) })),
          ]} />
        </div>
        <DataTable rows={data?.items} loading={loading} rowKey={(r) => r.id} onRowClick={(r) => nav(`/inbound/${r.id}`)} columns={[
          { key: "number", header: "Receipt #", render: (r) => <b>{r.number}</b> },
          { key: "type", header: "Type", render: (r) => r.order_type },
          { key: "ref", header: "Reference", render: (r) => r.reference ?? "—" },
          { key: "sup", header: "Supplier", render: (r) => r.supplier?.name ?? "—" },
          { key: "exp", header: "Expected", render: (r) => fmtDate(r.expected_date) },
          { key: "status", header: "Status", render: (r) => <Pill value={r.status} /> },
          { key: "prog", header: "Received", width: 180, render: (r) => <Progress done={r.qty_received} total={r.qty_expected} /> },
        ]} />
        <Pager total={data?.total ?? 0} limit={limit} offset={offset} onChange={setOffset} />
      </Card>
    </>
  );
}
