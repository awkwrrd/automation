import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useApp } from "../context";
import { Card, DataTable, Field, Input, PageHeader, Pill, Select, fmtNum, useAction, useLoad, useToast } from "../components/ui";
import type { Item, Order, Page } from "../types";

const CARRIERS = ["UPS", "FedEx", "USPS", "DHL", "Other"];

export default function PackShip() {
  const { warehouseId } = useApp();
  const [sp, setSp] = useSearchParams();
  const toast = useToast();
  const { busy, run } = useAction();
  const [scan, setScan] = useState(sp.get("order") ?? "");
  const [order, setOrder] = useState<Order | null>(null);
  const [verified, setVerified] = useState<Record<number, number>>({});
  const [itemScan, setItemScan] = useState("");
  const [pack, setPack] = useState({ carrier: "UPS", service: "Ground", packages: "1", weight: "" });
  const [tracking, setTracking] = useState("");
  const queue = useLoad(() => api.get<Page<Order>>("/orders", { warehouse_id: warehouseId, status: "PICKED,PACKED", limit: 50 }), [warehouseId, order?.status]);

  const load = async (num: string) => {
    if (!num.trim()) return;
    const res = await run(() => api.get<Page<Order>>("/orders", { q: num.trim(), limit: 5 }));
    const hit = res?.items.find((o) => o.number.toLowerCase() === num.trim().toLowerCase() || o.external_id === num.trim()) ?? res?.items[0];
    if (!hit) { toast.err(`Order ${num} not found`); setOrder(null); return; }
    const full = await api.get<Order>(`/orders/${hit.id}`);
    setOrder(full);
    setVerified({});
    setTracking("");
    setSp({ order: full.number }, { replace: true });
    const s = full.shipments?.find((x) => x.status === "PACKED");
    if (s) setPack({ carrier: s.carrier ?? "UPS", service: s.service ?? "", packages: String(s.packages), weight: s.weight ?? "" });
  };
  useEffect(() => { if (sp.get("order")) load(sp.get("order")!); /* eslint-disable-next-line */ }, []);

  const verifyItem = async (code: string) => {
    if (!order || !code.trim()) return;
    const it = await run(() => api.get<Item>("/items/lookup", { code }));
    setItemScan("");
    if (!it) return;
    const line = order.lines?.find((l) => l.item.id === it.id);
    if (!line) { toast.err(`${it.sku} is not on this order`); return; }
    const cur = verified[line.id] ?? 0;
    if (cur >= line.qty_picked) { toast.err(`All ${line.qty_picked} × ${it.sku} already verified`); return; }
    setVerified({ ...verified, [line.id]: cur + 1 });
  };

  const allVerified = order?.lines?.every((l) => (verified[l.id] ?? 0) >= l.qty_picked) ?? false;
  const totalPicked = order?.lines?.reduce((a, l) => a + l.qty_picked, 0) ?? 0;

  return (
    <div className="station">
      <PageHeader title="Pack & Ship" subtitle="Scan an order, verify contents, pack, then confirm shipment" />
      <Card>
        <form onSubmit={(e) => { e.preventDefault(); load(scan); }} style={{ display: "flex", gap: 8 }}>
          <input className="input scan-input" autoFocus placeholder="Scan / enter order #" value={scan} onChange={(e) => setScan(e.target.value)} />
          <button className="btn btn-primary" style={{ height: 46 }} disabled={busy}>Load</button>
        </form>
      </Card>
      {order && (
        <Card title={<>{order.number} <Pill value={order.status} /> <span className="muted" style={{ fontWeight: 400 }}>· {order.customer_name} · {[order.ship_city, order.ship_state].filter(Boolean).join(", ")}</span></>}
          actions={<Link to={`/orders/${order.id}`}>Order detail</Link>}>
          {!["PICKED", "PACKED"].includes(order.status) && (
            <div className="error-box">This order is <b>{order.status}</b>. Orders must be fully picked before packing{order.status === "SHIPPED" ? " — this one has already shipped." : "."}</div>
          )}
          {order.status === "PICKED" && (
            <form onSubmit={(e) => { e.preventDefault(); verifyItem(itemScan); }} style={{ display: "flex", gap: 8, marginBottom: 12 }}>
              <input className="input mono" placeholder="Scan item barcode / SKU to verify (optional)" value={itemScan} onChange={(e) => setItemScan(e.target.value)} />
              <button className="btn">Verify</button>
              <button type="button" className="btn" onClick={() => setVerified(Object.fromEntries((order.lines ?? []).map((l) => [l.id, l.qty_picked])))}>Verify all</button>
            </form>
          )}
          <DataTable rows={order.lines} rowKey={(l) => l.id} columns={[
            { key: "sku", header: "SKU", render: (l) => <b>{l.item.sku}</b> },
            { key: "n", header: "Description", render: (l) => l.item.name },
            { key: "o", header: "Ordered", align: "right", render: (l) => l.qty_ordered },
            { key: "p", header: "Picked", align: "right", render: (l) => <span className={l.qty_picked < l.qty_ordered ? "qty-neg" : ""}>{l.qty_picked}</span> },
            ...(order.status === "PICKED" ? [{ key: "v", header: "Verified", align: "right" as const, render: (l: NonNullable<Order["lines"]>[number]) => (
              <span className={(verified[l.id] ?? 0) >= l.qty_picked ? "qty-pos" : ""}>{verified[l.id] ?? 0}/{l.qty_picked}</span>) }] : []),
          ]} />
          {order.status === "PICKED" && (
            <>
              <div className="form-section">Pack</div>
              <div className="form-grid">
                <Field label="Carrier"><Select value={pack.carrier} onChange={(e) => setPack({ ...pack, carrier: e.target.value })} options={CARRIERS.map((c) => ({ value: c, label: c }))} /></Field>
                <Field label="Service"><Input value={pack.service} onChange={(e) => setPack({ ...pack, service: e.target.value })} /></Field>
                <Field label="Packages"><Input type="number" min={1} value={pack.packages} onChange={(e) => setPack({ ...pack, packages: e.target.value })} /></Field>
                <Field label="Total weight (lb)"><Input type="number" step="0.01" value={pack.weight} onChange={(e) => setPack({ ...pack, weight: e.target.value })} /></Field>
              </div>
              <div className="actions" style={{ marginTop: 14 }}>
                <button className="btn btn-primary" disabled={busy || totalPicked === 0} onClick={async () => {
                  const r = await run(() => api.post(`/orders/${order.id}/pack`, { carrier: pack.carrier, service: pack.service || null, packages: Number(pack.packages) || 1, weight: pack.weight || null }), "Packed");
                  if (r) load(order.number);
                }}>Confirm pack</button>
                {!allVerified && <span className="muted">Contents not fully verified</span>}
              </div>
            </>
          )}
          {order.status === "PACKED" && (
            <>
              <div className="form-section">Ship</div>
              <form className="form-grid" onSubmit={async (e) => {
                e.preventDefault();
                const r = await run(() => api.post(`/orders/${order.id}/ship`, { tracking_number: tracking || null, carrier: pack.carrier }), `Order ${order.number} shipped`);
                if (r) load(order.number);
              }}>
                <Field label="Carrier"><Select value={pack.carrier} onChange={(e) => setPack({ ...pack, carrier: e.target.value })} options={CARRIERS.map((c) => ({ value: c, label: c }))} /></Field>
                <Field label="Tracking number" span={2}><Input autoFocus className="input mono" value={tracking} onChange={(e) => setTracking(e.target.value)} /></Field>
                <Field label="&nbsp;"><button className="btn btn-primary" disabled={busy}>Confirm shipment</button></Field>
              </form>
            </>
          )}
        </Card>
      )}
      <Card title="Ready for pack / ship" pad={false}>
        <DataTable rows={queue.data?.items} loading={queue.loading} rowKey={(o) => o.id} empty="Nothing waiting" onRowClick={(o) => { setScan(o.number); load(o.number); }} columns={[
          { key: "n", header: "Order", render: (o) => <b>{o.number}</b> },
          { key: "e", header: "Channel ref", render: (o) => o.external_id ?? "" },
          { key: "c", header: "Customer", render: (o) => o.customer_name ?? "" },
          { key: "m", header: "Method", render: (o) => o.ship_method ?? "" },
          { key: "u", header: "Units", align: "right", render: (o) => fmtNum(o.units) },
          { key: "s", header: "Status", render: (o) => <Pill value={o.status} /> },
        ]} />
      </Card>
    </div>
  );
}
