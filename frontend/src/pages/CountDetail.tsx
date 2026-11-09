import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { useApp } from "../context";
import { Card, Confirm, ErrorBox, Field, Input, ItemPicker, LocationPicker, Modal, PageHeader, Pill, useAction, useLoad } from "../components/ui";
import type { Count, ItemRef } from "../types";

export default function CountDetail() {
  const { id } = useParams();
  const { can } = useApp();
  const { busy, run } = useAction();
  const { data: c, error, reload, setData } = useLoad(() => api.get<Count>(`/counts/${id}`), [id]);
  const [entries, setEntries] = useState<Record<number, string>>({});
  const [confirm, setConfirm] = useState<"complete" | "cancel" | null>(null);
  const [adding, setAdding] = useState(false);
  useEffect(() => {
    if (c?.lines) setEntries(Object.fromEntries(c.lines.map((l) => [l.id, l.counted_qty === null ? "" : String(l.counted_qty)])));
  }, [c]);
  const open = c?.status === "OPEN";
  const dirty = c?.lines?.some((l) => (entries[l.id] ?? "") !== (l.counted_qty === null ? "" : String(l.counted_qty)));
  const save = async () => {
    const body = (c?.lines ?? []).filter((l) => entries[l.id] !== "" && entries[l.id] !== undefined)
      .map((l) => ({ line_id: l.id, counted_qty: Number(entries[l.id]) }));
    const r = await run(() => api.post<Count>(`/counts/${id}/record`, body), "Counts saved");
    if (r) setData(r);
  };
  const variance = c?.lines?.reduce((a, l) => {
    const v = entries[l.id];
    return v === "" || v === undefined || l.expected_qty === null ? a : a + (Number(v) - l.expected_qty);
  }, 0);
  return (
    <>
      <PageHeader crumbs={<Link to="/counts">Cycle Counts</Link>} title={<>{c?.number} {c && <Pill value={c.status} />}</>}
        subtitle={c && `${c.description ?? ""}${c.blind ? " · blind count" : ""}`}
        actions={open && <>
          <button className="btn" onClick={() => setAdding(true)}>Add found item</button>
          <button className="btn btn-primary" disabled={busy || !dirty} onClick={save}>Save counts</button>
          {can("SUPERVISOR") && <>
            <button className="btn" onClick={() => setConfirm("cancel")}>Cancel count</button>
            <button className="btn btn-primary" disabled={busy || dirty} onClick={() => setConfirm("complete")} title={dirty ? "Save first" : ""}>Approve & post</button>
          </>}
        </>} />
      <ErrorBox error={error} />
      {c && (
        <Card pad={false} title={`${c.counted_lines} of ${c.line_count} lines counted`} actions={variance !== undefined && !(c.blind && !can("SUPERVISOR")) && <span className={variance ? "qty-neg" : "muted"}>Net variance: {variance > 0 ? "+" : ""}{variance}</span>}>
          <div className="table-wrap">
            <table className="grid">
              <thead><tr><th>Location</th><th>SKU</th><th>Description</th><th>Lot</th><th>Status</th><th style={{ textAlign: "right" }}>Expected</th><th style={{ textAlign: "right", width: 130 }}>Counted</th><th style={{ textAlign: "right" }}>Variance</th><th>Counted by</th></tr></thead>
              <tbody>
                {c.lines?.map((l) => {
                  const v = entries[l.id];
                  const varQ = l.adjusted_qty ?? (v !== "" && v !== undefined && l.expected_qty !== null ? Number(v) - l.expected_qty : null);
                  return (
                    <tr key={l.id}>
                      <td className="mono"><b>{l.location.code}</b></td>
                      <td><b>{l.item.sku}</b></td>
                      <td>{l.item.name}</td>
                      <td>{l.lot_number || "—"}</td>
                      <td><Pill value={l.inv_status} /></td>
                      <td style={{ textAlign: "right" }}>{l.expected_qty ?? <span className="muted">hidden</span>}</td>
                      <td style={{ textAlign: "right" }}>
                        {open ? <Input type="number" min={0} value={v ?? ""} style={{ textAlign: "right" }} onChange={(e) => setEntries({ ...entries, [l.id]: e.target.value })} />
                          : l.counted_qty}
                      </td>
                      <td style={{ textAlign: "right" }} className={varQ ? (varQ > 0 ? "qty-pos" : "qty-neg") : "muted"}>{varQ === null ? "" : varQ > 0 ? `+${varQ}` : varQ}</td>
                      <td className="muted">{l.counted_by ?? ""}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {c.lines?.length === 0 && <div className="empty">No stock expected in scope. Use "Add found item" to record anything you find.</div>}
          </div>
        </Card>
      )}
      {confirm && <Confirm busy={busy} danger={confirm === "cancel"}
        text={confirm === "complete" ? "Post all variances as inventory adjustments (against current on-hand) and close this count?" : "Cancel this count without posting?"}
        onClose={() => setConfirm(null)}
        onYes={async () => { await run(() => api.post(`/counts/${id}/${confirm}`), confirm === "complete" ? "Count posted" : "Count cancelled"); setConfirm(null); reload(); }} />}
      {adding && <AddFound countId={Number(id)} onClose={() => setAdding(false)} onDone={reload} />}
    </>
  );
}

function AddFound({ countId, onClose, onDone }: { countId: number; onClose: () => void; onDone: () => void }) {
  const { busy, run } = useAction();
  const [loc, setLoc] = useState<{ id: number; code: string } | null>(null);
  const [item, setItem] = useState<ItemRef | null>(null);
  const [qty, setQty] = useState("");
  const [lot, setLot] = useState("");
  return (
    <Modal title="Add found item" onClose={onClose} footer={<>
      <button className="btn" onClick={onClose}>Cancel</button>
      <button className="btn btn-primary" disabled={busy || !loc || !item || qty === ""} onClick={async () => {
        const r = await run(() => api.post(`/counts/${countId}/record`, [{ location_id: loc!.id, item_id: item!.id, lot_number: lot, counted_qty: Number(qty) }]), "Line added");
        if (r) { onDone(); onClose(); }
      }}>Add</button>
    </>}>
      <div className="form-grid">
        <Field label="Location" span={2}><LocationPicker value={loc} onChange={setLoc} /></Field>
        <Field label="Item" span={2}><ItemPicker value={item} onChange={setItem} /></Field>
        <Field label="Counted qty"><Input type="number" min={0} value={qty} onChange={(e) => setQty(e.target.value)} /></Field>
        <Field label="Lot"><Input value={lot} onChange={(e) => setLot(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}
