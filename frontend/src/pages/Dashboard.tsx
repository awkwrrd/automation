import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useApp } from "../context";
import { Card, DataTable, ErrorBox, PageHeader, Pill, Stat, fmtDateTime, fmtNum, label, useLoad } from "../components/ui";
import type { Txn } from "../types";

interface Dash {
  skus: number; units_on_hand: number; locations_total: number; locations_used: number; open_orders: number;
  orders_by_status: Record<string, number>; open_tasks_by_type: Record<string, number>; open_receipts: number;
  shipped_orders_7d: number; received_units_7d: number; low_stock_count: number;
  low_stock: { id: number; sku: string; name: string; reorder_point: number; reorder_qty: number; available: number }[];
  throughput: { date: string; received: number; shipped: number }[]; recent_transactions: Txn[];
}

const PIPELINE = ["NEW", "PARTIALLY_ALLOCATED", "ALLOCATED", "RELEASED", "PICKING", "PICKED", "PACKED"];

export default function Dashboard() {
  const { warehouseId } = useApp();
  const nav = useNavigate();
  const { data: d, error } = useLoad(() => api.get<Dash>("/dashboard", { warehouse_id: warehouseId }), [warehouseId]);
  const openTasks = d ? Object.values(d.open_tasks_by_type).reduce((a, b) => a + b, 0) : 0;
  const max = d ? Math.max(1, ...d.throughput.flatMap((t) => [t.received, t.shipped])) : 1;
  return (
    <>
      <PageHeader title="Dashboard" subtitle="Warehouse activity at a glance" actions={<>
        <Link className="btn" to="/inbound/new">New receipt</Link>
        <Link className="btn btn-primary" to="/orders/new">New order</Link>
      </>} />
      <ErrorBox error={error} />
      {d && (
        <>
          <div className="stats">
            <Stat label="Active SKUs" value={fmtNum(d.skus)} />
            <Stat label="Units on hand" value={fmtNum(d.units_on_hand)} sub={`${fmtNum(d.received_units_7d)} received last 7d`} />
            <Stat label="Location utilization" value={`${d.locations_total ? Math.round((d.locations_used / d.locations_total) * 100) : 0}%`} sub={`${d.locations_used} of ${d.locations_total} occupied`} />
            <Stat label="Open orders" value={fmtNum(d.open_orders)} sub={`${fmtNum(d.shipped_orders_7d)} shipped last 7d`} />
            <Stat label="Open tasks" value={fmtNum(openTasks)} sub={Object.entries(d.open_tasks_by_type).map(([k, v]) => `${v} ${label(k).toLowerCase()}`).join(" · ") || "Queue clear"} />
            <Stat label="Below reorder point" value={fmtNum(d.low_stock_count)} tone={d.low_stock_count ? "warn" : undefined} sub={<Link to="/reports/replenishment">View report</Link>} />
          </div>
          <div className="grid-3">
            <Card title="Order pipeline">
              <div className="stats" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(110px, 1fr))", marginBottom: 0 }}>
                {PIPELINE.map((s) => (
                  <Link key={s} to={`/orders?status=${s}`} className="stat" style={{ textDecoration: "none", color: "inherit", boxShadow: "none" }}>
                    <div className="stat-label">{label(s)}</div>
                    <div className="stat-value" style={{ fontSize: 22 }}>{fmtNum(d.orders_by_status[s] ?? 0)}</div>
                  </Link>
                ))}
              </div>
            </Card>
            <Card title="Units in / out — 7 days" actions={<div className="legend"><span><i style={{ background: "var(--accent)" }} />Received</span><span><i style={{ background: "var(--ok)" }} />Shipped</span></div>}>
              <div className="bars">
                {d.throughput.map((t) => (
                  <div key={t.date} className="bar-group" title={`${t.date}: ${t.received} received, ${t.shipped} shipped`}>
                    <div className="bar-pair">
                      <div className="bar rcv" style={{ height: `${(t.received / max) * 100}%` }} />
                      <div className="bar shp" style={{ height: `${(t.shipped / max) * 100}%` }} />
                    </div>
                    <div className="bar-label">{new Date(t.date + "T12:00:00").toLocaleDateString([], { weekday: "short" })}</div>
                  </div>
                ))}
              </div>
            </Card>
          </div>
          <div className="grid-3">
            <Card title="Recent activity" pad={false} actions={<Link to="/transactions">All transactions</Link>}>
              <DataTable rows={d.recent_transactions} rowKey={(t) => t.id} columns={[
                { key: "t", header: "When", render: (t) => <span className="muted">{fmtDateTime(t.created_at)}</span> },
                { key: "type", header: "Type", render: (t) => <Pill value={t.txn_type} tone="info" /> },
                { key: "sku", header: "Item", render: (t) => <Link to={`/items/${t.item.id}`}>{t.item.sku}</Link> },
                { key: "loc", header: "Location", render: (t) => <span className="mono">{t.from_location?.code ?? ""}{t.from_location && t.to_location ? " → " : ""}{t.to_location?.code ?? ""}</span> },
                { key: "qty", header: "Qty", align: "right", render: (t) => fmtNum(t.qty) },
                { key: "ref", header: "Ref", render: (t) => t.reference_number ?? "" },
              ]} />
            </Card>
            <Card title="Low stock" pad={false}>
              <DataTable rows={d.low_stock} rowKey={(r) => r.id} onRowClick={(r) => nav(`/items/${r.id}`)} empty="All items above reorder point" columns={[
                { key: "sku", header: "SKU", render: (r) => <b>{r.sku}</b> },
                { key: "available", header: "Avail", align: "right", render: (r) => <span className={r.available === 0 ? "qty-neg" : ""}>{fmtNum(r.available)}</span> },
                { key: "reorder_point", header: "ROP", align: "right" },
              ]} />
            </Card>
          </div>
        </>
      )}
    </>
  );
}
