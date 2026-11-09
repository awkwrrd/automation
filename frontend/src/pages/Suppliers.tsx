import { useState } from "react";
import { api } from "../api";
import { useApp } from "../context";
import { FormModal } from "../components/FormModal";
import { Card, DataTable, PageHeader, Pill, useLoad } from "../components/ui";
import type { Supplier } from "../types";

export default function Suppliers() {
  const { can } = useApp();
  const [edit, setEdit] = useState<Partial<Supplier> | null>(null);
  const { data, loading, reload } = useLoad(() => api.get<Supplier[]>("/suppliers"), []);
  return (
    <>
      <PageHeader title="Suppliers" subtitle="Vendors you receive from" actions={can("SUPERVISOR") && <button className="btn btn-primary" onClick={() => setEdit({ active: true })}>New supplier</button>} />
      <Card pad={false}>
        <DataTable rows={data} loading={loading} rowKey={(s) => s.id} onRowClick={can("SUPERVISOR") ? (s) => setEdit(s) : undefined} columns={[
          { key: "code", header: "Code", render: (s) => <b>{s.code}</b> },
          { key: "name", header: "Name" },
          { key: "contact_name", header: "Contact", render: (s) => s.contact_name ?? "—" },
          { key: "email", header: "Email", render: (s) => s.email ?? "—" },
          { key: "phone", header: "Phone", render: (s) => s.phone ?? "—" },
          { key: "a", header: "Status", render: (s) => <Pill value={s.active ? "ACTIVE" : "INACTIVE"} tone={s.active ? "ok" : "muted"} /> },
        ]} />
      </Card>
      {edit && <FormModal title={edit.id ? `Edit ${edit.code}` : "New supplier"} initial={edit as Record<string, unknown>} onClose={() => setEdit(null)}
        fields={[{ key: "code", label: "Code", required: true }, { key: "name", label: "Name", required: true }, { key: "contact_name", label: "Contact name" },
          { key: "email", label: "Email" }, { key: "phone", label: "Phone" }, { key: "active", label: "Active", type: "checkbox" }]}
        onSubmit={async (v) => {
          const { id, ...body } = v as Record<string, unknown>;
          const r = id ? await api.put(`/suppliers/${id}`, body) : await api.post("/suppliers", body);
          reload(); return r;
        }} />}
    </>
  );
}
