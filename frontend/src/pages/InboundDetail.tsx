import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { useApp } from "../context";
import { Card, Confirm, DataTable, ErrorBox, Field, Input, LocationPicker, Modal, PageHeader, Pill, fmtDate, fmtNum, useAction, useLoad } from "../components/ui";
import { Progress } from "./InboundList";
import type { Inbound, InboundLine, Task } from "../types";

export default function InboundDetail() {
  const { id } = useParams();
  const { can } = useApp();
  const { busy, run } = useAction();
  const { data: r, error, reload } = useLoad(() => api.get<Inbound>(`/inbound/${id}`), [id]);
  const [recv, setRecv] = useState<InboundLine | null>(null);
  const [confirm, setConfirm] = useState<"close" | "cancel" | null>(null);
  const [lastTask, setLastTask] = useState<Task | null>(null);
  const open = r && (r.status === "OPEN" || r.status === "RECEIVING" || r.status === "RECEIVED");
  return (
    <>
      <PageHeader crumbs={<Link to="/inbound">Receipts</Link>} title={<>{r?.number} {r && <Pill value={r.status} />}</>}
        subtitle={r && `${r.order_type}${r.reference ? ` · ${r.reference}` : ""}${r.supplier ? ` · ${r.supplier.name}` : ""}`}
        actions={can("SUPERVISOR") && open && <>
          {r?.qty_received === 0 && <button className="btn btn-danger" onClick={() => setConfirm("cancel")}>Cancel receipt</button>}
          <button className="btn" onClick={() => setConfirm("close")}>Close receipt</button>
        </>} />
      <ErrorBox error={error} />
      {lastTask && (
        <div className="notice">
          Received {lastTask.qty} × {lastTask.item.sku} to <b>{lastTask.from_location?.code}</b>. Putaway task #{lastTask.id} created
          {lastTask.to_location ? <> → suggested <b>{lastTask.to_location.code}</b></> : " (no suggested location — choose one at putaway)"}.{" "}
          <Link to="/tasks?type=PUTAWAY">Go to putaway tasks</Link>
        </div>
      )}
      {r && (
        <>
          <Card>
            <dl className="kv">
              <dt>Expected</dt><dd>{fmtDate(r.expected_date)}</dd>
              <dt>Progress</dt><dd style={{ maxWidth: 280 }}><Progress done={r.qty_received} total={r.qty_expected} /></dd>
              {r.notes && <><dt>Notes</dt><dd>{r.notes}</dd></>}
            </dl>
          </Card>
          <Card title="Lines" pad={false}>
            <DataTable rows={r.lines} rowKey={(l) => l.id} columns={[
              { key: "n", header: "#", render: (l) => l.line_no },
              { key: "sku", header: "SKU", render: (l) => <Link to={`/items/${l.item.id}`}><b>{l.item.sku}</b></Link> },
              { key: "name", header: "Description", render: (l) => l.item.name },
              { key: "e", header: "Expected", align: "right", render: (l) => fmtNum(l.qty_expected) },
              { key: "r", header: "Received", align: "right", render: (l) => <b className={l.qty_received > l.qty_expected ? "qty-neg" : l.qty_received === l.qty_expected ? "qty-pos" : ""}>{fmtNum(l.qty_received)}</b> },
              { key: "o", header: "Open", align: "right", render: (l) => fmtNum(Math.max(0, l.qty_expected - l.qty_received)) },
              { key: "a", header: "", align: "right", render: (l) => open && r.status !== "CLOSED" && <button className="btn btn-sm btn-primary" onClick={() => setRecv(l)}>Receive</button> },
            ]} />
          </Card>
        </>
      )}
      {recv && r && <ReceiveModal inbound={r} line={recv} onClose={() => setRecv(null)} onDone={(t) => { setLastTask(t); reload(); }} />}
      {confirm && <Confirm danger={confirm === "cancel"} busy={busy}
        text={confirm === "close" ? "Close this receipt? No further receiving will be allowed." : "Cancel this receipt?"}
        onClose={() => setConfirm(null)}
        onYes={async () => { await run(() => api.post(`/inbound/${id}/${confirm}`), confirm === "close" ? "Receipt closed" : "Receipt cancelled"); setConfirm(null); reload(); }} />}
    </>
  );
}

function ReceiveModal({ inbound, line, onClose, onDone }: { inbound: Inbound; line: InboundLine; onClose: () => void; onDone: (t: Task | null) => void }) {
  const { busy, run } = useAction();
  const [qty, setQty] = useState(String(Math.max(1, line.qty_expected - line.qty_received)));
  const [loc, setLoc] = useState<{ id: number; code: string } | null>(null);
  const [lot, setLot] = useState("");
  const [exp, setExp] = useState("");
  const [putaway, setPutaway] = useState(true);
  const submit = async () => {
    const res = await run(() => api.post<Task | null>(`/inbound/${inbound.id}/receive`, {
      line_id: line.id, qty: Number(qty), location_id: loc?.id ?? null, lot_number: lot, expiration_date: exp || null, create_putaway: putaway,
    }), "Received");
    if (res !== undefined) { onDone(res); onClose(); }
  };
  return (
    <Modal title={`Receive ${line.item.sku}`} onClose={onClose} footer={<>
      <button className="btn" onClick={onClose}>Cancel</button>
      <button className="btn btn-primary" disabled={busy || !(Number(qty) > 0)} onClick={submit}>Receive</button>
    </>}>
      <p className="muted" style={{ marginTop: 0 }}>{line.item.name} — expected {line.qty_expected}, received so far {line.qty_received}</p>
      <div className="form-grid">
        <Field label="Quantity received"><Input type="number" min={1} autoFocus value={qty} onChange={(e) => setQty(e.target.value)} /></Field>
        <Field label="Receive to location" hint="Blank = default dock door"><LocationPicker value={loc} onChange={setLoc} placeholder="Default dock" /></Field>
        <Field label="Lot number"><Input value={lot} onChange={(e) => setLot(e.target.value)} placeholder="(required if lot-tracked)" /></Field>
        <Field label="Expiration date"><Input type="date" value={exp} onChange={(e) => setExp(e.target.value)} /></Field>
        <Field label="Putaway" span={2}><label className="check"><input type="checkbox" checked={putaway} onChange={(e) => setPutaway(e.target.checked)} /> Create directed putaway task (when receiving to a dock location)</label></Field>
      </div>
    </Modal>
  );
}
