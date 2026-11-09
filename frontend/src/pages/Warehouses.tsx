import { useState } from "react";
import { api } from "../api";
import { useApp } from "../context";
import { FormModal, type FieldDef } from "../components/FormModal";
import { Card, DataTable, PageHeader, Pill, label, useLoad } from "../components/ui";
import type { Warehouse, Zone } from "../types";

const WH_FIELDS: FieldDef[] = [
  { key: "code", label: "Code", required: true }, { key: "name", label: "Name", required: true },
  { key: "address1", label: "Address", span: 2 }, { key: "city", label: "City" }, { key: "state", label: "State" },
  { key: "postal_code", label: "Postal code" }, { key: "country", label: "Country" },
  { key: "shopify_location_id", label: "Shopify location ID", hint: "Used by the Shopify integration" },
  { key: "active", label: "Active", type: "checkbox" },
];

export default function Warehouses() {
  const { warehouseId, meta, can, refreshWarehouses, warehouses } = useApp();
  const [whEdit, setWhEdit] = useState<Partial<Warehouse> | null>(null);
  const [zEdit, setZEdit] = useState<Partial<Zone> | null>(null);
  const zones = useLoad(() => api.get<Zone[]>("/zones", { warehouse_id: warehouseId }), [warehouseId]);
  const admin = can("ADMIN");
  const current = warehouses.find((w) => w.id === warehouseId);
  return (
    <>
      <PageHeader title="Warehouses & Zones" subtitle="Sites (facilities) and the functional zones inside them" />
      <Card title="Warehouses" pad={false} actions={admin && <button className="btn btn-sm btn-primary" onClick={() => setWhEdit({ active: true })}>New warehouse</button>}>
        <DataTable rows={warehouses} rowKey={(w) => w.id} onRowClick={admin ? (w) => setWhEdit(w) : undefined} columns={[
          { key: "code", header: "Code", render: (w) => <b>{w.code}</b> },
          { key: "name", header: "Name" },
          { key: "addr", header: "Address", render: (w) => [w.address1, w.city, w.state, w.postal_code].filter(Boolean).join(", ") },
          { key: "shop", header: "Shopify location", render: (w) => w.shopify_location_id ?? <span className="muted">not mapped</span> },
          { key: "a", header: "Status", render: (w) => <Pill value={w.active ? "ACTIVE" : "INACTIVE"} tone={w.active ? "ok" : "muted"} /> },
        ]} />
      </Card>
      <Card title={`Zones — ${current?.code ?? ""}`} pad={false} actions={admin && <button className="btn btn-sm btn-primary" onClick={() => setZEdit({ zone_type: "STORAGE" })}>New zone</button>}>
        <DataTable rows={zones.data} rowKey={(z) => z.id} onRowClick={admin ? (z) => setZEdit(z) : undefined} columns={[
          { key: "code", header: "Code", render: (z) => <b>{z.code}</b> },
          { key: "name", header: "Name" },
          { key: "type", header: "Type", render: (z) => label(z.zone_type) },
        ]} />
      </Card>
      {whEdit && <FormModal title={whEdit.id ? `Edit ${whEdit.code}` : "New warehouse"} fields={WH_FIELDS} initial={whEdit as Record<string, unknown>} onClose={() => setWhEdit(null)}
        onSubmit={async (v) => {
          const { id, ...body } = v as Record<string, unknown>;
          const r = id ? await api.put(`/warehouses/${id}`, body) : await api.post("/warehouses", body);
          await refreshWarehouses(); return r;
        }} />}
      {zEdit && <FormModal title={zEdit.id ? `Edit zone ${zEdit.code}` : "New zone"} initial={zEdit as Record<string, unknown>} onClose={() => setZEdit(null)}
        fields={[{ key: "code", label: "Code", required: true }, { key: "name", label: "Name", required: true },
          { key: "zone_type", label: "Type", type: "select", options: meta?.zone_types ?? [], required: true }]}
        onSubmit={async (v) => {
          const { id, ...rest } = v as Record<string, unknown>;
          const body = { ...rest, warehouse_id: warehouseId };
          const r = id ? await api.put(`/zones/${id}`, body) : await api.post("/zones", body);
          zones.reload(); return r;
        }} />}
    </>
  );
}
