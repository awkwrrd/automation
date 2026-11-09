import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import { Card, DataTable, ErrorBox, Modal, PageHeader, Pager, Pill, SearchBox, Select, fmtDateTime, useAction, useDebounced, useLoad } from "../components/ui";
import type { Endpoint, OutMessage, Page } from "../types";

export default function MessageLog() {
  const [sp] = useSearchParams();
  const [endpoint, setEndpoint] = useState(sp.get("endpoint") ?? "");
  const [status, setStatus] = useState(sp.get("status") ?? "");
  const [event, setEvent] = useState("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState<OutMessage | null>(null);
  const dq = useDebounced(q);
  const limit = 100;
  const eps = useLoad(() => api.get<Endpoint[]>("/automation/endpoints"), []);
  const events = useLoad(() => api.get<{ value: string }[]>("/automation/events"), []);
  const { data, error, loading, reload } = useLoad(() => api.get<Page<OutMessage>>("/automation/messages", {
    endpoint_id: endpoint, status, event, q: dq, limit, offset,
  }), [endpoint, status, event, dq, offset]);
  return (
    <>
      <PageHeader title="Message Log" subtitle="Every event pushed to an external system, with delivery attempts and responses"
        actions={<button className="btn" onClick={reload}>Refresh</button>} />
      <ErrorBox error={error} />
      <Card pad={false}>
        <div className="toolbar">
          <SearchBox value={q} onChange={(v) => { setQ(v); setOffset(0); }} placeholder="Reference (wave / order #) or error" />
          <Select value={endpoint} onChange={(e) => { setEndpoint(e.target.value); setOffset(0); }} placeholder="All endpoints" options={(eps.data ?? []).map((e) => ({ value: e.id, label: e.name }))} />
          <Select value={event} onChange={(e) => { setEvent(e.target.value); setOffset(0); }} placeholder="All events" options={(events.data ?? []).map((e) => ({ value: e.value, label: e.value }))} />
          <Select value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }} placeholder="All statuses" options={["PENDING", "SENT", "FAILED", "CANCELLED"]} />
        </div>
        <DataTable rows={data?.items} loading={loading} rowKey={(m) => m.id} onRowClick={async (m) => setOpen(await api.get<OutMessage>(`/automation/messages/${m.id}`))}
          empty="No messages yet" columns={[
          { key: "id", header: "Delivery #", render: (m) => <b>{m.id}</b> },
          { key: "c", header: "Created", render: (m) => fmtDateTime(m.created_at) },
          { key: "ep", header: "Endpoint", render: (m) => m.endpoint_name },
          { key: "ev", header: "Event", render: (m) => <span className="mono">{m.event}</span> },
          { key: "r", header: "Reference", render: (m) => m.reference ?? "" },
          { key: "s", header: "Status", render: (m) => <Pill value={m.status} /> },
          { key: "a", header: "Attempts", align: "right", render: (m) => m.attempts },
          { key: "code", header: "HTTP", align: "right", render: (m) => m.response_code ?? "" },
          { key: "err", header: "Last error / next try", render: (m) => m.status === "PENDING" && m.attempts > 0 ? <span className="muted">{m.last_error} · retry {fmtDateTime(m.next_attempt_at)}</span> : <span className="qty-neg">{m.last_error ?? ""}</span> },
        ]} />
        <Pager total={data?.total ?? 0} limit={limit} offset={offset} onChange={setOffset} />
      </Card>
      {open && <MessageModal msg={open} onClose={() => setOpen(null)} onChanged={(m) => { setOpen(m); reload(); }} />}
    </>
  );
}

function MessageModal({ msg, onClose, onChanged }: { msg: OutMessage; onClose: () => void; onChanged: (m: OutMessage) => void }) {
  const { busy, run } = useAction();
  let pretty = msg.payload ?? "";
  try { pretty = JSON.stringify(JSON.parse(pretty), null, 2); } catch { /* raw */ }
  return (
    <Modal wide title={`Delivery #${msg.id} — ${msg.event}`} onClose={onClose} footer={<>
      {msg.status === "PENDING" && <button className="btn btn-danger" style={{ marginRight: "auto" }} disabled={busy} onClick={async () => {
        const r = await run(() => api.post<OutMessage>(`/automation/messages/${msg.id}/cancel`), "Message cancelled"); if (r) onChanged(r);
      }}>Cancel delivery</button>}
      <button className="btn" onClick={onClose}>Close</button>
      <button className="btn btn-primary" disabled={busy || msg.status === "PENDING"} onClick={async () => {
        const r = await run(() => api.post<OutMessage>(`/automation/messages/${msg.id}/retry`), "Queued for re-send"); if (r) onChanged(r);
      }}>{msg.status === "SENT" ? "Re-send" : "Retry now"}</button>
    </>}>
      <dl className="kv" style={{ marginBottom: 14 }}>
        <dt>Endpoint</dt><dd>{msg.endpoint_name}</dd>
        <dt>Status</dt><dd><Pill value={msg.status} /> after {msg.attempts} attempt(s){msg.response_code ? ` · HTTP ${msg.response_code}` : ""}</dd>
        {msg.last_error && <><dt>Last error</dt><dd className="qty-neg">{msg.last_error}</dd></>}
        <dt>Sent</dt><dd>{fmtDateTime(msg.sent_at)}</dd>
      </dl>
      <div className="field-label">Payload</div>
      <pre className="code">{pretty}</pre>
      {msg.response_body && <><div className="field-label">Response body</div><pre className="code">{msg.response_body}</pre></>}
    </Modal>
  );
}
