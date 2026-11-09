import { useState } from "react";
import { api } from "../api";
import { useApp } from "../context";
import { FormModal, type FieldDef } from "../components/FormModal";
import { Card, DataTable, ErrorBox, Field, Input, Modal, PageHeader, Pager, Pill, SearchBox, Select, fmtNum, label, useAction, useDebounced, useLoad } from "../components/ui";
import type { Location, Page, Zone } from "../types";

export default function Locations() {
  const { warehouseId, meta, can } = useApp();
  const [q, setQ] = useState("");
  const [zone, setZone] = useState("");
  const [type, setType] = useState("");
  const [occ, setOcc] = useState("");
  const [offset, setOffset] = useState(0);
  const [edit, setEdit] = useState<Partial<Location> | null>(null);
  const [gen, setGen] = useState(false);
  const dq = useDebounced(q);
  const limit = 100;
  const zones = useLoad(() => api.get<Zone[]>("/zones", { warehouse_id: warehouseId }), [warehouseId]);
  const { data, error, loading, reload } = useLoad(() => api.get<Page<Location>>("/locations", {
    warehouse_id: warehouseId, q: dq, zone_id: zone, location_type: type, empty: occ === "" ? "" : occ === "empty", limit, offset,
  }), [warehouseId, dq, zone, type, occ, offset]);
  const zoneOpts = (zones.data ?? []).map((z) => ({ value: z.id, label: `${z.code} — ${z.name}` }));
  const fields: FieldDef[] = [
    { key: "code", label: "Location code", required: true }, { key: "zone_id", label: "Zone", type: "select", options: zoneOpts },
    { key: "location_type", label: "Type", type: "select", options: meta?.location_types ?? [], required: true },
    { key: "pick_sequence", label: "Pick / walk sequence", type: "number", hint: "Lower = earlier in pick path" },
    { key: "aisle", label: "Aisle" }, { key: "bay", label: "Bay" }, { key: "level", label: "Level" }, { key: "position", label: "Position" },
    { key: "max_units", label: "Max units", type: "number" },
    { key: "pickable", label: "Pickable (allocatable)", type: "checkbox" }, { key: "active", label: "Active", type: "checkbox" },
  ];
  return (
    <>
      <PageHeader title="Locations" subtitle="Bins, shelves, pallet positions, dock doors and staging lanes" actions={can("ADMIN") && <>
        <button className="btn" onClick={() => setGen(true)}>Bulk generate</button>
        <button className="btn btn-primary" onClick={() => setEdit({ warehouse_id: warehouseId!, location_type: "BIN", pickable: true, active: true, pick_sequence: 0 })}>New location</button>
      </>} />
      <ErrorBox error={error} />
      <Card pad={false}>
        <div className="toolbar">
          <SearchBox value={q} onChange={(v) => { setQ(v); setOffset(0); }} placeholder="Location code" />
          <Select value={zone} onChange={(e) => { setZone(e.target.value); setOffset(0); }} placeholder="All zones" options={zoneOpts} />
          <Select value={type} onChange={(e) => { setType(e.target.value); setOffset(0); }} placeholder="All types" options={meta?.location_types ?? []} />
          <Select value={occ} onChange={(e) => { setOcc(e.target.value); setOffset(0); }} placeholder="Any occupancy" options={[{ value: "empty", label: "Empty" }, { value: "occupied", label: "Occupied" }]} />
        </div>
        <DataTable rows={data?.items} loading={loading} rowKey={(l) => l.id} onRowClick={can("ADMIN") ? (l) => setEdit(l) : undefined} columns={[
          { key: "code", header: "Location", render: (l) => <b className="mono">{l.code}</b> },
          { key: "zone", header: "Zone", render: (l) => l.zone?.code ?? "—" },
          { key: "type", header: "Type", render: (l) => label(l.location_type) },
          { key: "abl", header: "Aisle / Bay / Level", render: (l) => [l.aisle, l.bay, l.level].filter(Boolean).join(" / ") || "—" },
          { key: "seq", header: "Seq", align: "right", render: (l) => l.pick_sequence },
          { key: "pick", header: "Pickable", align: "center", render: (l) => (l.pickable ? "✓" : "") },
          { key: "units", header: "Units", align: "right", render: (l) => (l.units ? <b>{fmtNum(l.units)}</b> : <span className="muted">empty</span>) },
          { key: "act", header: "Status", render: (l) => <Pill value={l.active ? "ACTIVE" : "INACTIVE"} tone={l.active ? "ok" : "muted"} /> },
        ]} />
        <Pager total={data?.total ?? 0} limit={limit} offset={offset} onChange={setOffset} />
      </Card>
      {edit && <FormModal title={edit.id ? `Edit ${edit.code}` : "New location"} fields={fields}
        initial={{ ...edit, zone_id: edit.zone_id ?? "" } as Record<string, unknown>} onClose={() => setEdit(null)}
        onSubmit={async (v) => {
          const body = { ...v, warehouse_id: warehouseId, zone_id: v.zone_id ? Number(v.zone_id) : null, pick_sequence: Number(v.pick_sequence ?? 0) };
          ["id", "zone", "units"].forEach((k) => delete (body as Record<string, unknown>)[k]);
          const r = edit.id ? await api.put(`/locations/${edit.id}`, body) : await api.post("/locations", body);
          reload(); return r;
        }} />}
      {gen && <Generate zones={zones.data ?? []} onClose={() => setGen(false)} onDone={reload} />}
    </>
  );
}

function Generate({ zones, onClose, onDone }: { zones: Zone[]; onClose: () => void; onDone: () => void }) {
  const { warehouseId, meta } = useApp();
  const { busy, run } = useAction();
  const [f, setF] = useState({ aisles: "C,D", bay_from: "1", bay_to: "10", level_from: "1", level_to: "4", zone_id: "", location_type: "BIN", pickable: true, pattern: "{aisle}-{bay:02d}-{level:02d}" });
  const aisles = f.aisles.split(",").map((a) => a.trim()).filter(Boolean);
  const count = aisles.length * Math.max(0, Number(f.bay_to) - Number(f.bay_from) + 1) * Math.max(0, Number(f.level_to) - Number(f.level_from) + 1);
  const example = f.pattern.replace("{aisle}", aisles[0] ?? "A").replace("{bay:02d}", String(f.bay_from).padStart(2, "0")).replace("{level:02d}", String(f.level_from).padStart(2, "0")).replace("{bay}", f.bay_from).replace("{level}", f.level_from);
  return (
    <Modal title="Bulk generate locations" onClose={onClose} footer={<>
      <button className="btn" onClick={onClose}>Cancel</button>
      <button className="btn btn-primary" disabled={busy || count <= 0} onClick={async () => {
        const r = await run(() => api.post<{ created: number; skipped_existing: number }>("/locations/generate", {
          warehouse_id: warehouseId, zone_id: f.zone_id ? Number(f.zone_id) : null, aisles, bay_from: Number(f.bay_from), bay_to: Number(f.bay_to),
          level_from: Number(f.level_from), level_to: Number(f.level_to), location_type: f.location_type, pickable: f.pickable, pattern: f.pattern,
        }));
        if (r) { alert(`Created ${r.created} location(s); skipped ${r.skipped_existing} existing.`); onDone(); onClose(); }
      }}>Generate {count} locations</button>
    </>}>
      <div className="form-grid">
        <Field label="Aisles (comma separated)" span={2}><Input value={f.aisles} onChange={(e) => setF({ ...f, aisles: e.target.value })} /></Field>
        <Field label="Bay from"><Input type="number" min={1} value={f.bay_from} onChange={(e) => setF({ ...f, bay_from: e.target.value })} /></Field>
        <Field label="Bay to"><Input type="number" min={1} value={f.bay_to} onChange={(e) => setF({ ...f, bay_to: e.target.value })} /></Field>
        <Field label="Level from"><Input type="number" min={1} value={f.level_from} onChange={(e) => setF({ ...f, level_from: e.target.value })} /></Field>
        <Field label="Level to"><Input type="number" min={1} value={f.level_to} onChange={(e) => setF({ ...f, level_to: e.target.value })} /></Field>
        <Field label="Zone"><Select value={f.zone_id} onChange={(e) => setF({ ...f, zone_id: e.target.value })} placeholder="—" options={zones.map((z) => ({ value: z.id, label: z.code }))} /></Field>
        <Field label="Type"><Select value={f.location_type} onChange={(e) => setF({ ...f, location_type: e.target.value })} options={meta?.location_types ?? []} /></Field>
        <Field label="Code pattern" span={2} hint={`Example: ${example}`}><Input className="input mono" value={f.pattern} onChange={(e) => setF({ ...f, pattern: e.target.value })} /></Field>
        <Field group label="" span={2}><label className="check"><input type="checkbox" checked={f.pickable} onChange={(e) => setF({ ...f, pickable: e.target.checked })} /> Pickable</label></Field>
      </div>
    </Modal>
  );
}
