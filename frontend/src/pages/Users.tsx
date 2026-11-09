import { useState } from "react";
import { api } from "../api";
import { useApp } from "../context";
import { FormModal } from "../components/FormModal";
import { Card, DataTable, PageHeader, Pill, useLoad } from "../components/ui";
import type { User } from "../types";

export default function Users() {
  const { can, meta } = useApp();
  const [edit, setEdit] = useState<Partial<User> | null>(null);
  const { data, loading, reload } = useLoad(() => api.get<User[]>("/users"), []);
  const admin = can("ADMIN");
  return (
    <>
      <PageHeader title="Users" subtitle="Operators: floor execution · Supervisors: adjustments, order & count control · Admins: configuration & users"
        actions={admin && <button className="btn btn-primary" onClick={() => setEdit({ role: "OPERATOR", active: true })}>New user</button>} />
      <Card pad={false}>
        <DataTable rows={data} loading={loading} rowKey={(u) => u.id} onRowClick={admin ? (u) => setEdit(u) : undefined} columns={[
          { key: "username", header: "Username", render: (u) => <b>{u.username}</b> },
          { key: "full_name", header: "Name" },
          { key: "email", header: "Email", render: (u) => u.email ?? "—" },
          { key: "role", header: "Role", render: (u) => <Pill value={u.role} tone={u.role === "ADMIN" ? "accent" : u.role === "SUPERVISOR" ? "info" : "muted"} /> },
          { key: "a", header: "Status", render: (u) => <Pill value={u.active ? "ACTIVE" : "INACTIVE"} tone={u.active ? "ok" : "muted"} /> },
        ]} />
      </Card>
      {edit && <FormModal title={edit.id ? `Edit ${edit.username}` : "New user"} initial={{ ...edit, password: "" } as Record<string, unknown>} onClose={() => setEdit(null)}
        fields={[{ key: "username", label: "Username", required: true }, { key: "full_name", label: "Full name" }, { key: "email", label: "Email" },
          { key: "role", label: "Role", type: "select", options: meta?.roles ?? [], required: true },
          { key: "password", label: edit.id ? "New password" : "Password", type: "password", required: !edit.id, hint: edit.id ? "Leave blank to keep current" : undefined },
          { key: "active", label: "Active", type: "checkbox" }]}
        onSubmit={async (v) => {
          const { id, ...body } = v as Record<string, unknown>;
          if (body.full_name === null) body.full_name = "";
          const r = id ? await api.put(`/users/${id}`, body) : await api.post("/users", body);
          reload(); return r;
        }} />}
    </>
  );
}
