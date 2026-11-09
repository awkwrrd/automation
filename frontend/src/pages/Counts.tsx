import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useApp } from "../context";
import { Card, DataTable, ErrorBox, Field, Input, ItemPicker, LocationPicker, Modal, PageHeader, Pager, Pill, Select, fmtDateTime, useAction, useLoad } from "../components/ui";
import { Progress } from "./InboundList";
import type { Count, ItemRef, Page, Zone } from "../types";

export default function Counts() {
  const nav = useNavigate();
  const { warehouseId, can } = useApp();
  const [status, setStatus] = useState("OPEN");
  const [offset, setOffset] = useState(0);
  const [creating, setCreating] = useState(false);
  const limit = 50;
  const { data, error, loading } = useLoad(() => api.get<Page<Count>>("/counts", { warehouse_id: warehouseId, status, limit, offset }), [warehouseId, status, offset]);
  return (
    <>
      <PageHeader title="Cycle Counts" subtitle="Count locations, zones or items and post variances as adjustments"
        actions={can("SUPERVISOR") && <button className="btn btn-primary" onClick={() => setCreating(true)}>New count</button>} />
      <ErrorBox error={error} />
      <Card pad={false}>
        <div className="toolbar">
          <Select value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }} placeholder="All statuses" options={["OPEN", "COMPLETED", "CANCELLED"]} />
        </div>
        <DataTable rows={data?.items} loading={loading} rowKey={(c) => c.id} onRowClick={(c) => nav(`/counts/${c.id}`)} columns={[
          { key: "n", header: "Count #", render: (c) => <b>{c.number}</b> },
          { key: "d", header: "Description", render: (c) => c.description ?? "—" },
          { key: "b", header: "Type", render: (c) => (c.blind ? "Blind" : "Standard") },
          { key: "p", header: "Progress", width: 180, render: (c) => <Progress done={c.counted_lines} total={c.line_count} /> },
          { key: "s", header: "Status", render: (c) => <Pill value={c.status} /> },
          { key: "by", header: "Created by", render: (c) => c.created_by ?? "" },
          { key: "c", header: "Created", render: (c) => fmtDateTime(c.created_at) },
        ]} />
        <Pager total={data?.total ?? 0} limit={limit} offset={offset} onChange={setOffset} />
      </Card>
      {creating && <NewCount onClose={() => setCreating(false)} />}
    </>
  );
}

function NewCount({ onClose }: { onClose: () => void }) {
  const { warehouseId } = useApp();
  const nav = useNavigate();
  const { busy, run } = useAction();
  const [scope, setScope] = useState("zone");
  const [zone, setZone] = useState("");
  const [locs, setLocs] = useState<{ id: number; code: string }[]>([]);
  const [item, setItem] = useState<ItemRef | null>(null);
  const [desc, setDesc] = useState("");
  const [blind, setBlind] = useState(true);
  const zones = useLoad(() => api.get<Zone[]>("/zones", { warehouse_id: warehouseId }), [warehouseId]);
  const valid = (scope === "zone" && zone) || (scope === "locations" && locs.length) || (scope === "item" && item);
  return (
    <Modal title="New cycle count" onClose={onClose} footer={<>
      <button className="btn" onClick={onClose}>Cancel</button>
      <button className="btn btn-primary" disabled={busy || !valid} onClick={async () => {
        const c = await run(() => api.post<Count>("/counts", {
          warehouse_id: warehouseId, description: desc || null, blind,
          zone_id: scope === "zone" ? Number(zone) : null, location_ids: scope === "locations" ? locs.map((l) => l.id) : null,
          item_id: scope === "item" ? item?.id : null,
        }), "Count created");
        if (c) nav(`/counts/${c.id}`);
      }}>Create count</button>
    </>}>
      <div className="form-grid">
        <Field label="Count by"><Select value={scope} onChange={(e) => setScope(e.target.value)} options={[{ value: "zone", label: "Zone" }, { value: "locations", label: "Specific locations" }, { value: "item", label: "Item (all locations)" }]} /></Field>
        <Field label="Description"><Input value={desc} onChange={(e) => setDesc(e.target.value)} /></Field>
        {scope === "zone" && <Field label="Zone" span={2}><Select value={zone} onChange={(e) => setZone(e.target.value)} placeholder="Select…" options={(zones.data ?? []).map((z) => ({ value: z.id, label: `${z.code} — ${z.name}` }))} /></Field>}
        {scope === "item" && <Field label="Item" span={2}><ItemPicker value={item} onChange={setItem} /></Field>}
        {scope === "locations" && (
          <Field label="Locations" span={2} hint={locs.length ? locs.map((l) => l.code).join(", ") : "Add one or more"}>
            <LocationPicker value={null} onChange={(l) => l && !locs.some((x) => x.id === l.id) && setLocs([...locs, l])} />
          </Field>
        )}
        <Field group label="" span={2}><label className="check"><input type="checkbox" checked={blind} onChange={(e) => setBlind(e.target.checked)} /> Blind count (operators don't see expected quantities)</label></Field>
      </div>
    </Modal>
  );
}
