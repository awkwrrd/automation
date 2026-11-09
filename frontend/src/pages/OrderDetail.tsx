import { Fragment, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { useApp } from "../context";
import { Card, Confirm, DataTable, ErrorBox, PageHeader, Pill, fmtDateTime, fmtNum, label, useAction, useLoad } from "../components/ui";
import type { Order, Page, Task } from "../types";

const FLOW = ["NEW", "ALLOCATED", "RELEASED", "PICKING", "PICKED", "PACKED", "SHIPPED"];

export function StatusFlow({ status }: { status: string }) {
  const norm = status === "PARTIALLY_ALLOCATED" ? "ALLOCATED" : status;
  const idx = FLOW.indexOf(norm);
  if (status === "CANCELLED") return <div className="status-flow"><span className="current">Cancelled</span></div>;
  return (
    <div className="status-flow">
      {FLOW.map((s, i) => <span key={s} className={i < idx ? "done" : i === idx ? "current" : ""}>{status === "PARTIALLY_ALLOCATED" && s === "ALLOCATED" ? "Partially allocated" : label(s)}</span>)}
    </div>
  );
}

export default function OrderDetail() {
  const { id } = useParams();
  const { can } = useApp();
  const { busy, run } = useAction();
  const { data: o, error, reload } = useLoad(() => api.get<Order>(`/orders/${id}`), [id]);
  const tasks = useLoad(() => api.get<Page<Task>>("/tasks", { order_id: id, limit: 200 }), [id]);
  const [confirm, setConfirm] = useState<string | null>(null);
  const act = async (action: string, msg: string) => {
    await run(() => api.post(`/orders/${id}/${action}`), msg);
    reload(); tasks.reload();
  };
  const s = o?.status ?? "";
  const sup = can("SUPERVISOR");
  const short = o?.lines?.some((l) => l.qty_allocated < l.qty_ordered && !["SHIPPED", "CANCELLED"].includes(s));
  return (
    <>
      <PageHeader crumbs={<Link to="/orders">Orders</Link>} title={<>{o?.number} {o && <Pill value={s} />}</>}
        subtitle={o && <>{o.channel}{o.external_id ? ` ${o.external_id}` : ""} · created {fmtDateTime(o.created_at)}{o.wave ? ` · wave ${o.wave.number}` : ""}</>}
        actions={o && sup && <>
          {["NEW", "PARTIALLY_ALLOCATED", "PICKED"].includes(s) && short && <button className="btn" disabled={busy} onClick={() => act("allocate", "Allocation run")}>Allocate</button>}
          {["NEW", "PARTIALLY_ALLOCATED", "ALLOCATED"].includes(s) && <button className="btn btn-primary" disabled={busy} onClick={() => act("release", "Released to floor")}>Release to pick</button>}
          {["PARTIALLY_ALLOCATED", "ALLOCATED", "RELEASED", "PICKING"].includes(s) && <button className="btn" disabled={busy} onClick={() => setConfirm("deallocate")}>Unallocate</button>}
          {!["SHIPPED", "CANCELLED"].includes(s) && <button className="btn btn-danger" disabled={busy} onClick={() => setConfirm("cancel")}>Cancel order</button>}
          {s === "PICKED" && <Link className="btn btn-primary" to={`/pack?order=${o.number}`}>Pack</Link>}
          {s === "PACKED" && <Link className="btn btn-primary" to={`/pack?order=${o.number}`}>Ship</Link>}
        </>} />
      <ErrorBox error={error} />
      {o && (
        <>
          <StatusFlow status={s} />
          <div className="grid-3">
            <Card title="Lines" pad={false}>
              <table className="grid">
                <thead><tr><th>#</th><th>SKU</th><th>Description</th><th style={{ textAlign: "right" }}>Ordered</th><th style={{ textAlign: "right" }}>Allocated</th><th style={{ textAlign: "right" }}>Picked</th><th style={{ textAlign: "right" }}>Shipped</th></tr></thead>
                <tbody>
                  {o.lines?.map((l) => (
                    <Fragment key={l.id}>
                      <tr>
                        <td className="muted">{l.line_no}</td>
                        <td><Link to={`/items/${l.item.id}`}><b>{l.item.sku}</b></Link></td>
                        <td>{l.item.name}</td>
                        <td style={{ textAlign: "right" }}><b>{l.qty_ordered}</b></td>
                        <td style={{ textAlign: "right" }} className={l.qty_allocated < l.qty_ordered && !["SHIPPED", "CANCELLED"].includes(s) ? "qty-neg" : ""}>{l.qty_allocated}</td>
                        <td style={{ textAlign: "right" }}>{l.qty_picked}</td>
                        <td style={{ textAlign: "right" }}>{l.qty_shipped}</td>
                      </tr>
                      {l.allocations.filter((a) => a.status !== "CANCELLED").map((a) => (
                        <tr key={`a${a.id}`} style={{ background: "var(--surface-2)" }}>
                          <td />
                          <td colSpan={2} className="muted" style={{ fontSize: 12 }}>↳ allocated from <span className="mono">{a.location.code}</span>{a.lot_number ? ` · lot ${a.lot_number}` : ""}</td>
                          <td />
                          <td style={{ textAlign: "right", fontSize: 12 }}>{a.qty}</td>
                          <td style={{ textAlign: "right", fontSize: 12 }}>{a.qty_picked}</td>
                          <td style={{ fontSize: 12 }}><Pill value={a.status} /></td>
                        </tr>
                      ))}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </Card>
            <Card title="Ship to">
              <div><b>{o.ship_name || o.customer_name}</b></div>
              <div>{o.ship_address1}</div>
              {o.ship_address2 && <div>{o.ship_address2}</div>}
              <div>{[o.ship_city, o.ship_state, o.ship_postal_code].filter(Boolean).join(", ")}</div>
              <div>{o.ship_country}</div>
              <dl className="kv" style={{ marginTop: 14 }}>
                <dt>Category</dt><dd>{o.category ?? "—"}</dd>
                <dt>Method</dt><dd>{o.ship_method ?? "—"}</dd>
                <dt>Priority</dt><dd>{o.priority}</dd>
                {o.customer_email && <><dt>Email</dt><dd>{o.customer_email}</dd></>}
                {o.customer_phone && <><dt>Phone</dt><dd>{o.customer_phone}</dd></>}
                {o.notes && <><dt>Notes</dt><dd>{o.notes}</dd></>}
                {o.shopify_order_id && <><dt>Shopify</dt><dd>
                  {o.shopify_fulfillment_status ? <Pill value={o.shopify_fulfillment_status === "DONE" ? "FULFILLED" : o.shopify_fulfillment_status} tone={o.shopify_fulfillment_status === "DONE" ? "ok" : o.shopify_fulfillment_status === "FAILED" ? "bad" : "warn"} /> : <span className="muted">not shipped yet</span>}
                  {o.shopify_fulfillment_error && <div className="qty-neg" style={{ fontSize: 12 }}>{o.shopify_fulfillment_error}</div>}
                  {o.shopify_fulfillment_status === "FAILED" && sup && <div><button className="btn btn-sm" style={{ marginTop: 6 }} disabled={busy} onClick={async () => { await run(() => api.post(`/shopify/orders/${o.id}/retry-fulfillment`), "Fulfillment queued for retry"); reload(); }}>Retry Shopify fulfillment</button></div>}
                </dd></>}
              </dl>
            </Card>
          </div>
          <div className="grid-2">
            <Card title="Pick tasks" pad={false}>
              <DataTable rows={tasks.data?.items} rowKey={(t) => t.id} empty="No tasks — release the order to create picks" columns={[
                { key: "id", header: "#", render: (t) => t.id },
                { key: "sku", header: "SKU", render: (t) => t.item.sku },
                { key: "from", header: "From", render: (t) => <span className="mono">{t.from_location?.code}</span> },
                { key: "qty", header: "Qty", align: "right", render: (t) => `${t.qty_done}/${t.qty}` },
                { key: "st", header: "Status", render: (t) => <Pill value={t.status} /> },
                { key: "by", header: "By", render: (t) => t.completed_by ?? t.assigned_to ?? "" },
              ]} />
            </Card>
            <Card title="Shipments" pad={false}>
              <DataTable rows={o.shipments} rowKey={(x) => x.id} empty="Not packed yet" columns={[
                { key: "n", header: "Shipment", render: (x) => <b>{x.number}</b> },
                { key: "c", header: "Carrier", render: (x) => [x.carrier, x.service].filter(Boolean).join(" ") || "—" },
                { key: "t", header: "Tracking", render: (x) => <span className="mono">{x.tracking_number ?? "—"}</span> },
                { key: "p", header: "Pkgs", align: "right", render: (x) => fmtNum(x.packages) },
                { key: "s", header: "Status", render: (x) => <Pill value={x.status} /> },
                { key: "d", header: "Shipped", render: (x) => fmtDateTime(x.shipped_at) },
              ]} />
            </Card>
          </div>
        </>
      )}
      {confirm && <Confirm danger busy={busy}
        text={confirm === "cancel" ? "Cancel this order? Reservations are released and open picks cancelled. Any already-picked stock stays in staging for you to move back." : "Release all un-picked reservations and cancel open pick tasks?"}
        onClose={() => setConfirm(null)}
        onYes={async () => { await act(confirm, confirm === "cancel" ? "Order cancelled" : "Unallocated"); setConfirm(null); }} />}
    </>
  );
}
