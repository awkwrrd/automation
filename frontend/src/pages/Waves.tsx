import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useApp } from "../context";
import { Card, DataTable, ErrorBox, PageHeader, Pager, Pill, Select, fmtDateTime, useAction, useLoad } from "../components/ui";
import { Progress } from "./InboundList";
import type { Page, Wave } from "../types";

export default function Waves() {
  const { warehouseId, can } = useApp();
  const { busy, run } = useAction();
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const limit = 50;
  const { data, error, loading, reload } = useLoad(() => api.get<Page<Wave>>("/waves", { warehouse_id: warehouseId, status, limit, offset }), [warehouseId, status, offset]);
  return (
    <>
      <PageHeader title="Waves" subtitle="Groups of orders released to the floor together. Create a wave by selecting orders on the Orders screen."
        actions={<Link className="btn" to="/orders?status=NEW">Select orders</Link>} />
      <ErrorBox error={error} />
      <Card pad={false}>
        <div className="toolbar">
          <Select value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }} placeholder="All statuses" options={["PLANNED", "RELEASED", "COMPLETE", "CANCELLED"]} />
        </div>
        <DataTable rows={data?.items} loading={loading} rowKey={(w) => w.id} columns={[
          { key: "n", header: "Wave", render: (w) => <b>{w.number}</b> },
          { key: "d", header: "Description", render: (w) => w.description ?? "—" },
          { key: "o", header: "Orders", align: "right", render: (w) => <Link to={`/orders?wave=${w.id}`}>{w.order_count}</Link> },
          { key: "p", header: "Picks complete", width: 200, render: (w) => (w.total_tasks ? <Progress done={w.total_tasks - w.open_tasks} total={w.total_tasks} /> : <span className="muted">—</span>) },
          { key: "s", header: "Status", render: (w) => <Pill value={w.status} /> },
          { key: "c", header: "Created", render: (w) => fmtDateTime(w.created_at) },
          { key: "r", header: "Released", render: (w) => fmtDateTime(w.released_at) },
          { key: "a", header: "", align: "right", render: (w) => <span className="actions" style={{ justifyContent: "flex-end" }}>
            {w.status === "PLANNED" && can("SUPERVISOR") && <button className="btn btn-sm btn-primary" disabled={busy} onClick={async () => {
              const r = await run(() => api.post<{ tasks_created: number; orders_not_released: string[] }>(`/waves/${w.id}/release`));
              if (r) { alert(`${r.tasks_created} pick task(s) created.${r.orders_not_released.length ? ` No stock for: ${r.orders_not_released.join(", ")}` : ""}`); reload(); }
            }}>Release</button>}
            {w.open_tasks > 0 && <Link className="btn btn-sm" to={`/tasks?wave=${w.id}`}>Picks</Link>}
          </span> },
        ]} />
        <Pager total={data?.total ?? 0} limit={limit} offset={offset} onChange={setOffset} />
      </Card>
    </>
  );
}
