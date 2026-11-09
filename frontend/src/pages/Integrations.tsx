import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useApp } from "../context";
import { Card, Confirm, DataTable, Field, Input, Modal, PageHeader, Pill, Select, fmtDateTime, useAction, useLoad } from "../components/ui";
import type { ApiKey, Endpoint, OutMessage, User, Zone } from "../types";

type EventDef = { value: string; description: string };

export default function Integrations() {
  const { can } = useApp();
  const admin = can("ADMIN");
  const { busy, run } = useAction();
  const eps = useLoad(() => api.get<Endpoint[]>("/automation/endpoints"), []);
  const keys = useLoad(() => (admin ? api.get<ApiKey[]>("/automation/api-keys") : Promise.resolve([])), [admin]);
  const [edit, setEdit] = useState<Partial<Endpoint> | null>(null);
  const [testResult, setTestResult] = useState<OutMessage | null>(null);
  const [newKey, setNewKey] = useState(false);
  const [revoke, setRevoke] = useState<ApiKey | null>(null);
  return (
    <>
      <PageHeader title="Integrations" subtitle="Push warehouse events (wave releases, picks, putaways) to external systems such as a robotics platform, and issue API keys so they can confirm work back"
        actions={<Link className="btn" to="/config/messages">Message log</Link>} />
      <Card title="Outbound endpoints" pad={false} actions={admin && <button className="btn btn-sm btn-primary" onClick={() => setEdit({ events: ["wave.released", "order.released", "task.cancelled"], auth_type: "NONE", timeout_seconds: 10, max_attempts: 8, assign_tasks: true, active: true, zone_ids: [], extra_headers: {} })}>New endpoint</button>}>
        <DataTable rows={eps.data} loading={eps.loading} rowKey={(e) => e.id} onRowClick={admin ? (e) => setEdit(e) : undefined}
          empty="No endpoints yet. Create one to start pushing events." columns={[
          { key: "name", header: "Name", render: (e) => <b>{e.name}</b> },
          { key: "url", header: "URL", render: (e) => <span className="mono" style={{ fontSize: 12 }}>{e.url}</span> },
          { key: "ev", header: "Events", render: (e) => e.events.join(", ") || <span className="muted">none</span> },
          { key: "z", header: "Zones", render: (e) => (e.zone_ids.length ? `${e.zone_ids.length} zone(s)` : "All") },
          { key: "q", header: "Queue", render: (e) => <>{e.pending > 0 && <Pill value={`${e.pending} pending`} tone="warn" raw />} {e.failed > 0 && <Link to={`/config/messages?endpoint=${e.id}&status=FAILED`} onClick={(ev) => ev.stopPropagation()}><Pill value={`${e.failed} failed`} tone="bad" raw /></Link>}{!e.pending && !e.failed && <span className="muted">clear</span>}</> },
          { key: "last", header: "Last delivery", render: (e) => fmtDateTime(e.last_sent_at) },
          { key: "a", header: "Status", render: (e) => <Pill value={e.active ? "ACTIVE" : "INACTIVE"} tone={e.active ? "ok" : "muted"} /> },
          { key: "t", header: "", align: "right", render: (e) => admin && (
            <button className="btn btn-sm" disabled={busy || !e.active} onClick={async (ev) => {
              ev.stopPropagation();
              const r = await run(() => api.post<OutMessage>(`/automation/endpoints/${e.id}/test`));
              if (r) { setTestResult(r); eps.reload(); }
            }}>Send test</button>) },
        ]} />
      </Card>
      {admin && (
        <Card title="API keys" pad={false} actions={<button className="btn btn-sm btn-primary" onClick={() => setNewKey(true)}>New API key</button>}>
          <div className="notice" style={{ margin: 12 }}>
            External systems call the WMS with <code>X-API-Key: wms_…</code>. A key acts as the user it's linked to, so link it to a dedicated service user (e.g. an OPERATOR named <i>softbot</i>).
          </div>
          <DataTable rows={keys.data} loading={keys.loading} rowKey={(k) => k.id} empty="No API keys" columns={[
            { key: "n", header: "Name", render: (k) => <b>{k.name}</b> },
            { key: "p", header: "Key", render: (k) => <span className="mono">{k.prefix}…</span> },
            { key: "u", header: "Acts as user", render: (k) => k.username },
            { key: "c", header: "Created", render: (k) => fmtDateTime(k.created_at) },
            { key: "l", header: "Last used", render: (k) => fmtDateTime(k.last_used_at) },
            { key: "s", header: "Status", render: (k) => <Pill value={k.active ? "ACTIVE" : "REVOKED"} tone={k.active ? "ok" : "muted"} raw /> },
            { key: "r", header: "", align: "right", render: (k) => k.active && <button className="btn btn-sm btn-danger" onClick={() => setRevoke(k)}>Revoke</button> },
          ]} />
        </Card>
      )}
      {edit && <EndpointEditor ep={edit} onClose={() => setEdit(null)} onSaved={eps.reload} />}
      {testResult && (
        <Modal title="Test result" onClose={() => setTestResult(null)} footer={<button className="btn btn-primary" onClick={() => setTestResult(null)}>OK</button>}>
          <p><Pill value={testResult.status} /> {testResult.response_code ? `HTTP ${testResult.response_code}` : ""} {testResult.last_error && <span className="qty-neg">{testResult.last_error}</span>}</p>
          {testResult.response_body && <><div className="field-label">Response body</div><pre className="code">{testResult.response_body}</pre></>}
        </Modal>
      )}
      {newKey && <NewKey onClose={() => setNewKey(false)} onDone={keys.reload} />}
      {revoke && <Confirm danger busy={busy} text={<>Revoke API key <b>{revoke.name}</b>? Systems using it will immediately get 401 errors.</>}
        onClose={() => setRevoke(null)} onYes={async () => { await run(() => api.post(`/automation/api-keys/${revoke.id}/revoke`), "Key revoked"); setRevoke(null); keys.reload(); }} />}
    </>
  );
}

function EndpointEditor({ ep, onClose, onSaved }: { ep: Partial<Endpoint>; onClose: () => void; onSaved: () => void }) {
  const { warehouses } = useApp();
  const { busy, run } = useAction();
  const events = useLoad(() => api.get<EventDef[]>("/automation/events"), []);
  const [f, setF] = useState({
    name: ep.name ?? "", url: ep.url ?? "https://", warehouse_id: ep.warehouse_id ? String(ep.warehouse_id) : "",
    events: ep.events ?? [], zone_ids: ep.zone_ids ?? [], auth_type: ep.auth_type ?? "NONE", auth_header: ep.auth_header ?? "X-API-Key",
    auth_value: "", signing_secret: "", clear_signing_secret: false,
    extra_headers: Object.keys(ep.extra_headers ?? {}).length ? JSON.stringify(ep.extra_headers, null, 2) : "",
    timeout_seconds: String(ep.timeout_seconds ?? 10), max_attempts: String(ep.max_attempts ?? 8),
    assign_tasks: ep.assign_tasks ?? true, active: ep.active ?? true, payload_format: ep.payload_format ?? "STANDARD",
    field_names: Object.keys(ep.field_names ?? {}).length ? JSON.stringify(ep.field_names, null, 2) : "",
    static_fields: Object.keys(ep.static_fields ?? {}).length ? JSON.stringify(ep.static_fields, null, 2) : "",
  });
  const [preview, setPreview] = useState<string | null>(null);
  const [del, setDel] = useState(false);
  const zones = useLoad(() => (f.warehouse_id ? api.get<Zone[]>("/zones", { warehouse_id: f.warehouse_id }) : Promise.resolve([])), [f.warehouse_id]);
  const jsonOk = (txt: string) => { try { if (txt.trim()) { const v = JSON.parse(txt); return typeof v === "object" && !Array.isArray(v) && v !== null; } return true; } catch { return false; } };
  const headersOk = jsonOk(f.extra_headers), namesOk = jsonOk(f.field_names), staticsOk = jsonOk(f.static_fields);
  const toggle = <T,>(list: T[], v: T) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);
  const genSecret = () => {
    const bytes = crypto.getRandomValues(new Uint8Array(24));
    setF({ ...f, signing_secret: "whsec_" + Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join(""), clear_signing_secret: false });
  };
  const buildBody = () => ({
      name: f.name, url: f.url, warehouse_id: f.warehouse_id ? Number(f.warehouse_id) : null, events: f.events,
      zone_ids: f.warehouse_id ? f.zone_ids : [], auth_type: f.auth_type, auth_header: f.auth_header || null,
      auth_value: f.auth_value || null, signing_secret: f.signing_secret || null, clear_signing_secret: f.clear_signing_secret,
      extra_headers: f.extra_headers.trim() ? JSON.parse(f.extra_headers) : {}, timeout_seconds: Number(f.timeout_seconds),
      max_attempts: Number(f.max_attempts), assign_tasks: f.assign_tasks, active: f.active,
      payload_format: f.payload_format, field_names: f.field_names.trim() ? JSON.parse(f.field_names) : {},
      static_fields: f.static_fields.trim() ? JSON.parse(f.static_fields) : {},
  });
  const save = async () => {
    const body = buildBody();
    const r = await run(() => (ep.id ? api.put(`/automation/endpoints/${ep.id}`, body) : api.post("/automation/endpoints", body)), "Endpoint saved");
    if (r) { onSaved(); onClose(); }
  };
  const needsSecret = f.auth_type !== "NONE" && !ep.auth_value_hint;
  const valid = f.name && /^https?:\/\/.+/.test(f.url) && headersOk && namesOk && staticsOk && (!needsSecret || f.auth_value) && f.events.length > 0;
  return (
    <Modal wide title={ep.id ? `Edit endpoint ${ep.name}` : "New outbound endpoint"} onClose={onClose} footer={<>
      {ep.id && <button className="btn btn-danger" style={{ marginRight: "auto" }} onClick={() => setDel(true)}>Delete</button>}
      <button className="btn" onClick={onClose}>Cancel</button>
      <button className="btn btn-primary" disabled={busy || !valid} onClick={save}>Save endpoint</button>
    </>}>
      <div className="form-grid">
        <Field label="Name *" hint="Shown on tasks sent to this system"><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="SOFTBOT" /></Field>
        <Field group label="Status"><label className="check"><input type="checkbox" checked={f.active} onChange={(e) => setF({ ...f, active: e.target.checked })} /> Active</label></Field>
        <Field label="URL *" span={2} hint="The WMS POSTs JSON here. Use https:// outside your local network."><Input className="input mono" value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} /></Field>

        <div className="form-section">What to send</div>
        <Field label="Message format" span={2} hint={f.payload_format === "ORDER"
          ? "One flat message per order: OrderNumber, Category, Customer, ShipTo, Lines[] (Sku, Quantity, UnitType, dimensions, Tasks[]). Test sends a sample order (IsTest = true)."
          : "One message per event, fields nested under \"data\" (see docs/SOFTBOT_INTEGRATION.md)."}>
          <Select value={f.payload_format} onChange={(e) => setF({ ...f, payload_format: e.target.value as Endpoint["payload_format"] })} options={[
            { value: "STANDARD", label: "Standard event (snake_case, per event)" }, { value: "ORDER", label: "Per order (PascalCase: Lines, UnitType, Category…)" }]} />
        </Field>
        <Field group label="Events *" span={2}>
          <div style={{ display: "grid", gap: 6 }}>
            {(events.data ?? []).map((ev) => (
              <label key={ev.value} className="check"><input type="checkbox" checked={f.events.includes(ev.value)} onChange={() => setF({ ...f, events: toggle(f.events, ev.value) })} />
                <span className="mono">{ev.value}</span> <span className="muted">— {ev.description}</span></label>
            ))}
          </div>
        </Field>
        <Field label="Warehouse"><Select value={f.warehouse_id} onChange={(e) => setF({ ...f, warehouse_id: e.target.value, zone_ids: [] })} placeholder="All warehouses" options={warehouses.map((w) => ({ value: w.id, label: `${w.code} — ${w.name}` }))} /></Field>
        <Field group label="Task ownership" hint="Marks sent tasks as assigned to this system so floor staff leave them alone">
          <label className="check"><input type="checkbox" checked={f.assign_tasks} onChange={(e) => setF({ ...f, assign_tasks: e.target.checked })} /> Assign sent tasks to this endpoint</label>
        </Field>
        <Field group label="Zones" span={2} hint={f.warehouse_id ? "Only tasks picked from (or put away to) these zones are sent. None ticked = all zones." : "Choose a warehouse to filter by zone"}>
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
            {(zones.data ?? []).map((z) => (
              <label key={z.id} className="check"><input type="checkbox" checked={f.zone_ids.includes(z.id)} onChange={() => setF({ ...f, zone_ids: toggle(f.zone_ids, z.id) })} /> {z.code} <span className="muted">{z.name}</span></label>
            ))}
          </div>
        </Field>

        <Field label="Rename fields (JSON)" hint={namesOk ? 'Renames keys at any depth, e.g. {"Lines": "OrderLines", "Sku": "ItemCode"}' : "Must be a JSON object"}>
          <textarea className="input mono" rows={3} value={f.field_names} onChange={(e) => setF({ ...f, field_names: e.target.value })} style={!namesOk ? { borderColor: "var(--bad)" } : undefined} />
        </Field>
        <Field label="Always include (JSON)" hint={staticsOk ? 'Added to every message, e.g. {"SendToPaccurate": true}' : "Must be a JSON object"}>
          <textarea className="input mono" rows={3} value={f.static_fields} onChange={(e) => setF({ ...f, static_fields: e.target.value })} style={!staticsOk ? { borderColor: "var(--bad)" } : undefined} />
        </Field>
        <Field group label="" span={2}>
          <div><button type="button" className="btn" disabled={busy || !namesOk || !staticsOk} onClick={async () => {
            const r = await run(() => api.post<unknown>("/automation/endpoints/preview", { ...buildBody(), name: f.name || "preview", url: /^https?:\/\/.+/.test(f.url) ? f.url : "http://preview" }));
            if (r) setPreview(JSON.stringify(r, null, 2));
          }}>Preview message</button> <span className="muted" style={{ fontSize: 12 }}>Shows the test message exactly as it will be sent with these settings</span></div>
        </Field>

        <div className="form-section">Security</div>
        <Field label="Authentication">
          <Select value={f.auth_type} onChange={(e) => setF({ ...f, auth_type: e.target.value as Endpoint["auth_type"] })} options={[
            { value: "NONE", label: "None" }, { value: "BEARER", label: "Bearer token" }, { value: "HEADER", label: "API key header" }, { value: "BASIC", label: "Basic (user:password)" }]} />
        </Field>
        {f.auth_type === "HEADER" ? <Field label="Header name"><Input value={f.auth_header} onChange={(e) => setF({ ...f, auth_header: e.target.value })} /></Field> : <div />}
        {f.auth_type !== "NONE" && (
          <Field label={f.auth_type === "BASIC" ? "user:password" : "Token / key"} span={2} hint={ep.auth_value_hint ? `Stored: ${ep.auth_value_hint} — leave blank to keep` : undefined}>
            <Input type="password" autoComplete="new-password" value={f.auth_value} onChange={(e) => setF({ ...f, auth_value: e.target.value })} />
          </Field>
        )}
        <Field group label="Signing secret (HMAC-SHA256)" span={2}
          hint={ep.has_signing_secret && !f.signing_secret && !f.clear_signing_secret ? "A secret is stored — leave blank to keep it. Copy any new secret now; it is not shown again." : "Your receiver verifies X-WMS-Signature with this. Copy it now; it is not shown again after saving."}>
          <div style={{ display: "flex", gap: 8 }}>
            <Input className="input mono" value={f.signing_secret} onChange={(e) => setF({ ...f, signing_secret: e.target.value, clear_signing_secret: false })} placeholder={ep.has_signing_secret ? "(unchanged)" : "(none)"} />
            <button type="button" className="btn" onClick={genSecret}>Generate</button>
            {ep.has_signing_secret && <button type="button" className="btn" onClick={() => setF({ ...f, signing_secret: "", clear_signing_secret: true })}>Remove</button>}
          </div>
        </Field>

        <div className="form-section">Delivery</div>
        <Field label="Timeout (seconds)"><Input type="number" min={1} max={120} value={f.timeout_seconds} onChange={(e) => setF({ ...f, timeout_seconds: e.target.value })} /></Field>
        <Field label="Max attempts" hint="Retries back off: 10s, 20s, 40s … up to 15 min"><Input type="number" min={1} max={50} value={f.max_attempts} onChange={(e) => setF({ ...f, max_attempts: e.target.value })} /></Field>
        <Field label="Extra headers (JSON)" span={2} hint={headersOk ? 'e.g. {"X-Site": "DC1"}' : "Invalid JSON"}>
          <textarea className="input mono" rows={3} value={f.extra_headers} onChange={(e) => setF({ ...f, extra_headers: e.target.value })} style={!headersOk ? { borderColor: "var(--bad)" } : undefined} />
        </Field>
      </div>
      {preview && (
        <Modal wide title="Message preview" onClose={() => setPreview(null)} footer={<>
          <button className="btn" onClick={() => navigator.clipboard?.writeText(preview)}>Copy</button>
          <button className="btn btn-primary" onClick={() => setPreview(null)}>Close</button></>}>
          <pre className="code" style={{ maxHeight: "60vh" }}>{preview}</pre>
        </Modal>
      )}
      {del && <Confirm danger busy={busy} text="Delete this endpoint and its message history? Tasks already sent keep their assignment." onClose={() => setDel(false)}
        onYes={async () => { const r = await run(() => api.del(`/automation/endpoints/${ep.id}`), "Endpoint deleted"); setDel(false); if (r !== undefined) { onSaved(); onClose(); } }} />}
    </Modal>
  );
}

function NewKey({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const { busy, run } = useAction();
  const users = useLoad(() => api.get<User[]>("/users"), []);
  const [name, setName] = useState("");
  const [userId, setUserId] = useState("");
  const [created, setCreated] = useState<ApiKey | null>(null);
  if (created) {
    return (
      <Modal title="API key created" onClose={onClose} footer={<button className="btn btn-primary" onClick={onClose}>Done</button>}>
        <div className="error-box">Copy this key now. It will not be shown again.</div>
        <pre className="code" style={{ userSelect: "all" }}>{created.key}</pre>
        <button className="btn" onClick={() => navigator.clipboard?.writeText(created.key ?? "")}>Copy to clipboard</button>
        <p className="muted">Send it as <code>X-API-Key: {created.prefix}…</code> (or <code>Authorization: Bearer …</code>).</p>
      </Modal>
    );
  }
  return (
    <Modal title="New API key" onClose={onClose} footer={<>
      <button className="btn" onClick={onClose}>Cancel</button>
      <button className="btn btn-primary" disabled={busy || !name || !userId} onClick={async () => {
        const k = await run(() => api.post<ApiKey>("/automation/api-keys", { name, user_id: Number(userId) }));
        if (k) { setCreated(k); onDone(); }
      }}>Create key</button>
    </>}>
      <div className="form-grid">
        <Field label="Key name"><Input value={name} onChange={(e) => setName(e.target.value)} placeholder="softbot-prod" /></Field>
        <Field label="Acts as user" hint="Create a dedicated OPERATOR user first (Configuration → Users)">
          <Select value={userId} onChange={(e) => setUserId(e.target.value)} placeholder="Select…" options={(users.data ?? []).filter((u) => u.active).map((u) => ({ value: u.id, label: `${u.username} (${u.role})` }))} />
        </Field>
      </div>
    </Modal>
  );
}
