import { useRef, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { api } from "../api";
import { useApp } from "../context";
import { Card, DataTable, ErrorBox, Modal, PageHeader, Pager, Pill, SearchBox, Select, fmtMoney, fmtNum, useAction, useDebounced, useLoad } from "../components/ui";
import type { Item, Page } from "../types";

export default function Items() {
  const nav = useNavigate();
  const { can } = useApp();
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("");
  const [active, setActive] = useState("true");
  const [offset, setOffset] = useState(0);
  const [importRes, setImportRes] = useState<{ created: number; updated: number; errors: string[] } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const { busy, run } = useAction();
  const dq = useDebounced(q);
  const limit = 50;
  const cats = useLoad(() => api.get<string[]>("/items/categories"), []);
  const { data, error, loading, reload } = useLoad(() => api.get<Page<Item>>("/items", { q: dq, category: cat, active, limit, offset }), [dq, cat, active, offset]);

  const onImport = async (f: File) => {
    const fd = new FormData();
    fd.append("file", f);
    const r = await run(() => api.post<{ created: number; updated: number; errors: string[] }>("/items/import", fd));
    if (r) { setImportRes(r); reload(); }
    if (fileRef.current) fileRef.current.value = "";
  };

  return (
    <>
      <PageHeader title="Items" subtitle="Product master (SKUs)" actions={<>
        <button className="btn" onClick={() => api.download("/items/export.csv", "items.csv")}>Export CSV</button>
        {can("SUPERVISOR") && <>
          <button className="btn" disabled={busy} onClick={() => fileRef.current?.click()}>Import CSV</button>
          <input ref={fileRef} type="file" accept=".csv,text/csv" hidden onChange={(e) => e.target.files?.[0] && onImport(e.target.files[0])} />
          <Link className="btn btn-primary" to="/items/new">New item</Link>
        </>}
      </>} />
      <ErrorBox error={error} />
      <Card pad={false}>
        <div className="toolbar">
          <SearchBox value={q} onChange={(v) => { setQ(v); setOffset(0); }} placeholder="SKU, name, barcode, Shopify variant id" />
          <Select value={cat} onChange={(e) => { setCat(e.target.value); setOffset(0); }} placeholder="All categories" options={(cats.data ?? []).map((c) => ({ value: c, label: c }))} />
          <Select value={active} onChange={(e) => { setActive(e.target.value); setOffset(0); }} options={[{ value: "true", label: "Active" }, { value: "false", label: "Inactive" }, { value: "", label: "All" }]} />
        </div>
        <DataTable rows={data?.items} loading={loading} rowKey={(i) => i.id} onRowClick={(i) => nav(`/items/${i.id}`)}
          rowClass={(i) => (i.reorder_point > 0 && i.available <= i.reorder_point ? "row-warn" : "")} columns={[
          { key: "sku", header: "SKU", render: (i) => <b>{i.sku}</b> },
          { key: "name", header: "Description" },
          { key: "category", header: "Category", render: (i) => i.category ?? "—" },
          { key: "loc", header: "Home loc", render: (i) => <span className="mono">{i.default_location?.code ?? "—"}</span> },
          { key: "price", header: "Price", align: "right", render: (i) => fmtMoney(i.price) },
          { key: "oh", header: "On hand", align: "right", render: (i) => fmtNum(i.on_hand) },
          { key: "al", header: "Allocated", align: "right", render: (i) => fmtNum(i.allocated) },
          { key: "av", header: "Available", align: "right", render: (i) => <b className={i.reorder_point > 0 && i.available <= i.reorder_point ? "qty-neg" : ""}>{fmtNum(i.available)}</b> },
          { key: "flags", header: "", render: (i) => <>{i.lot_tracked && <Pill value="LOT" tone="info" />} {!i.active && <Pill value="INACTIVE" tone="muted" />} {i.shopify_variant_id && <Pill value="SHOPIFY" tone="ok" />}</> },
        ]} />
        <Pager total={data?.total ?? 0} limit={limit} offset={offset} onChange={setOffset} />
      </Card>
      {importRes && (
        <Modal title="Import complete" onClose={() => setImportRes(null)} footer={<button className="btn btn-primary" onClick={() => setImportRes(null)}>OK</button>}>
          <p>Created <b>{importRes.created}</b>, updated <b>{importRes.updated}</b>.</p>
          {importRes.errors.length > 0 && <div className="error-box">{importRes.errors.map((e) => <div key={e}>{e}</div>)}</div>}
          <p className="muted">CSV columns match the export. Only <code>sku</code> and <code>name</code> are required; blank cells leave existing values unchanged.</p>
        </Modal>
      )}
    </>
  );
}
