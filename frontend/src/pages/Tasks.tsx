import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useApp } from "../context";
import { Card, DataTable, ErrorBox, Field, Input, ItemPicker, LocationPicker, Modal, PageHeader, Pager, Pill, SearchBox, Select, fmtDateTime, useAction, useDebounced, useLoad } from "../components/ui";
import type { ItemRef, Page, Task } from "../types";

export default function Tasks() {
  const { warehouseId, meta, user, can } = useApp();
  const [sp] = useSearchParams();
  const [type, setType] = useState(sp.get("type") ?? "");
  const [state, setState] = useState("open");
  const [mine, setMine] = useState(false);
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [doing, setDoing] = useState<Task | null>(null);
  const [creating, setCreating] = useState(false);
  const { busy, run } = useAction();
  const dq = useDebounced(q);
  const limit = 100;
  const wave = sp.get("wave") ?? "";
  const { data, error, loading, reload } = useLoad(() => api.get<Page<Task>>("/tasks", {
    warehouse_id: warehouseId, task_type: type, open_only: state === "open", status: state === "open" || state === "" ? "" : state,
    assigned_to: mine ? user?.username : "", q: dq, wave_id: wave, limit, offset,
  }), [warehouseId, type, state, mine, dq, wave, offset]);
  return (
    <>
      <PageHeader title="Task Queue" subtitle="Putaway, pick, move and replenishment work — open tasks are sorted in walk-path (pick sequence) order"
        actions={can("SUPERVISOR") && <button className="btn" onClick={() => setCreating(true)}>New move task</button>} />
      <ErrorBox error={error} />
      <Card pad={false}>
        <div className="toolbar">
          <SearchBox value={q} onChange={(v) => { setQ(v); setOffset(0); }} placeholder="SKU, reference, location" />
          <Select value={type} onChange={(e) => { setType(e.target.value); setOffset(0); }} placeholder="All types" options={meta?.task_types ?? []} />
          <Select value={state} onChange={(e) => { setState(e.target.value); setOffset(0); }} options={[{ value: "open", label: "Open" }, { value: "COMPLETE", label: "Complete" }, { value: "CANCELLED", label: "Cancelled" }, { value: "", label: "All" }]} />
          <label className="check"><input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} /> Assigned to me</label>
          {wave && <Link className="btn btn-sm" to="/tasks">Clear wave filter</Link>}
        </div>
        <DataTable rows={data?.items} loading={loading} rowKey={(t) => t.id} empty="No tasks — queue is clear" columns={[
          { key: "id", header: "Task", render: (t) => <b>#{t.id}</b> },
          { key: "ty", header: "Type", render: (t) => <Pill value={t.task_type} tone={t.task_type === "PICK" ? "accent" : "info"} /> },
          { key: "from", header: "From", render: (t) => <span className="mono"><b>{t.from_location?.code ?? "—"}</b></span> },
          { key: "to", header: "To", render: (t) => <span className="mono">{t.to_location?.code ?? <span className="muted">choose</span>}</span> },
          { key: "sku", header: "Item", render: (t) => <span><b>{t.item.sku}</b>{t.lot_number && <span className="muted"> · {t.lot_number}</span>}</span> },
          { key: "qty", header: "Qty", align: "right", render: (t) => (t.qty_done ? `${t.qty_done}/${t.qty}` : t.qty) },
          { key: "ref", header: "Reference", render: (t) => (t.order_id ? <Link to={`/orders/${t.order_id}`}>{t.reference_number}</Link> : t.reference_number ?? "") },
          { key: "pri", header: "Pri", align: "center", render: (t) => t.priority },
          { key: "asg", header: "Assigned", render: (t) => t.dispatch_endpoint_id && !t.completed_by ? <Pill raw value={`→ ${t.assigned_to}`} tone="accent" /> : t.completed_by ?? t.assigned_to ?? <span className="muted">—</span> },
          { key: "st", header: "Status", render: (t) => <Pill value={t.status} /> },
          { key: "c", header: "Created", render: (t) => <span className="muted">{fmtDateTime(t.created_at)}</span> },
          { key: "a", header: "", align: "right", render: (t) => ["OPEN", "IN_PROGRESS"].includes(t.status) && (
            <span className="actions" style={{ justifyContent: "flex-end", flexWrap: "nowrap" }}>
              {t.assigned_to !== user?.username && <button className="btn btn-sm" disabled={busy} onClick={async () => { await run(() => api.post(`/tasks/${t.id}/assign`, { assigned_to: user?.username })); reload(); }}>Claim</button>}
              <button className="btn btn-sm btn-primary" onClick={() => setDoing(t)}>Execute</button>
            </span>
          ) },
        ]} />
        <Pager total={data?.total ?? 0} limit={limit} offset={offset} onChange={setOffset} />
      </Card>
      {doing && <ExecuteTask task={doing} onClose={() => setDoing(null)} onDone={reload} />}
      {creating && <NewMoveTask onClose={() => setCreating(false)} onDone={reload} />}
    </>
  );
}

function ExecuteTask({ task, onClose, onDone }: { task: Task; onClose: () => void; onDone: () => void }) {
  const { can } = useApp();
  const { busy, run } = useAction();
  const remaining = task.qty - task.qty_done;
  const [qty, setQty] = useState(String(remaining));
  const [scanFrom, setScanFrom] = useState("");
  const [dest, setDest] = useState<{ id: number; code: string } | null>(task.to_location);
  const isPick = task.task_type === "PICK";
  const fromOk = !scanFrom || scanFrom.trim().toUpperCase() === task.from_location?.code.toUpperCase();
  const submit = async () => {
    const r = await run(() => api.post(`/tasks/${task.id}/complete`, { qty: Number(qty), to_location_id: dest?.id ?? null }),
      isPick && Number(qty) < remaining ? `Short pick recorded (${qty}/${remaining})` : "Task confirmed");
    if (r) { onDone(); onClose(); }
  };
  return (
    <Modal title={`${task.task_type} task #${task.id}`} onClose={onClose} footer={<>
      {can("SUPERVISOR") && <button className="btn btn-danger" style={{ marginRight: "auto" }} disabled={busy} onClick={async () => {
        const r = await run(() => api.post(`/tasks/${task.id}/cancel`), "Task cancelled"); if (r) { onDone(); onClose(); }
      }}>Cancel task</button>}
      <button className="btn" onClick={onClose}>Close</button>
      <button className="btn btn-primary" disabled={busy || !dest || !fromOk || Number(qty) < (isPick ? 0 : 1) || Number(qty) > remaining} onClick={submit}>Confirm</button>
    </>}>
      {task.dispatch_endpoint_id && (
        <div className="notice">This task was sent to <b>{task.assigned_to}</b>. Confirm it here only if you are overriding the automation (e.g. picked manually).</div>
      )}
      <dl className="kv" style={{ marginBottom: 16 }}>
        <dt>Item</dt><dd><b>{task.item.sku}</b> — {task.item.name}</dd>
        {task.lot_number && <><dt>Lot</dt><dd>{task.lot_number}</dd></>}
        <dt>Go to</dt><dd className="mono" style={{ fontSize: 18 }}><b>{task.from_location?.code}</b></dd>
        <dt>Quantity</dt><dd><b>{remaining}</b>{task.qty_done ? ` (of ${task.qty}, ${task.qty_done} done)` : ""}</dd>
        {task.reference_number && <><dt>Reference</dt><dd>{task.reference_number}</dd></>}
      </dl>
      <div className="form-grid">
        <Field label="Confirm source location" hint={fromOk ? "Optional scan check" : "Does not match task location"}>
          <Input className="input mono" value={scanFrom} onChange={(e) => setScanFrom(e.target.value)} placeholder={task.from_location?.code} style={!fromOk ? { borderColor: "var(--bad)" } : undefined} />
        </Field>
        <Field label={isPick ? "Quantity picked" : "Quantity moved"} hint={isPick ? "Less than requested = short pick" : undefined}>
          <Input type="number" min={0} max={remaining} value={qty} onChange={(e) => setQty(e.target.value)} />
        </Field>
        <Field label={isPick ? "Drop to staging location" : "Destination location"} span={2}>
          <LocationPicker value={dest} onChange={setDest} filter={isPick ? { location_type: "STAGING" } : undefined} />
        </Field>
      </div>
    </Modal>
  );
}

function NewMoveTask({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const { busy, run } = useAction();
  const [item, setItem] = useState<ItemRef | null>(null);
  const [from, setFrom] = useState<{ id: number; code: string } | null>(null);
  const [to, setTo] = useState<{ id: number; code: string } | null>(null);
  const [qty, setQty] = useState("");
  const [type, setType] = useState("MOVE");
  const [lot, setLot] = useState("");
  return (
    <Modal title="New move / replenishment task" onClose={onClose} footer={<>
      <button className="btn" onClick={onClose}>Cancel</button>
      <button className="btn btn-primary" disabled={busy || !item || !from || !(Number(qty) > 0)} onClick={async () => {
        const r = await run(() => api.post("/tasks", { item_id: item!.id, from_location_id: from!.id, to_location_id: to?.id ?? null, qty: Number(qty), task_type: type, lot_number: lot }), "Task created");
        if (r) { onDone(); onClose(); }
      }}>Create task</button>
    </>}>
      <div className="form-grid">
        <Field label="Type"><Select value={type} onChange={(e) => setType(e.target.value)} options={["MOVE", "REPLENISH"]} /></Field>
        <Field label="Quantity"><Input type="number" min={1} value={qty} onChange={(e) => setQty(e.target.value)} /></Field>
        <Field label="Item" span={2}><ItemPicker value={item} onChange={setItem} /></Field>
        <Field label="From"><LocationPicker value={from} onChange={setFrom} filter={{ empty: false }} /></Field>
        <Field label="To" hint="Blank = system suggestion"><LocationPicker value={to} onChange={setTo} /></Field>
        <Field label="Lot number"><Input value={lot} onChange={(e) => setLot(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}
