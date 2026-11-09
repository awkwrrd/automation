import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useApp } from "../context";
import { Card, DataTable, ErrorBox, PageHeader, Pager, Pill, SearchBox, Select, fmtDateTime, fmtNum, useDebounced, useLoad } from "../components/ui";
import type { Page, Txn } from "../types";

export default function Transactions() {
  const { meta } = useApp();
  const [sp] = useSearchParams();
  const itemId = sp.get("item_id") ?? "";
  const [q, setQ] = useState("");
  const [ref, setRef] = useState("");
  const [type, setType] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [offset, setOffset] = useState(0);
  const dq = useDebounced(q), dr = useDebounced(ref);
  const limit = 100;
  const { data, error, loading } = useLoad(() => api.get<Page<Txn>>("/inventory/transactions", {
    item_id: itemId, q: dq, reference: dr, txn_type: type, limit, offset,
    date_from: from ? `${from}T00:00:00` : "", date_to: to ? `${to}T23:59:59` : "",
  }), [itemId, dq, dr, type, from, to, offset]);
  return (
    <>
      <PageHeader title="Transaction History" subtitle="Complete audit trail of inventory movements" />
      <ErrorBox error={error} />
      <Card pad={false}>
        <div className="toolbar">
          <SearchBox value={q} onChange={(v) => { setQ(v); setOffset(0); }} placeholder="SKU or name" />
          <input className="input" style={{ width: 150 }} placeholder="Reference #" value={ref} onChange={(e) => { setRef(e.target.value); setOffset(0); }} />
          <Select value={type} onChange={(e) => { setType(e.target.value); setOffset(0); }} placeholder="All types" options={meta?.txn_types ?? []} />
          <input className="input" type="date" style={{ width: 150 }} value={from} onChange={(e) => { setFrom(e.target.value); setOffset(0); }} aria-label="From date" />
          <input className="input" type="date" style={{ width: 150 }} value={to} onChange={(e) => { setTo(e.target.value); setOffset(0); }} aria-label="To date" />
          {itemId && <Link className="btn btn-sm" to="/transactions">Clear item filter</Link>}
        </div>
        <DataTable rows={data?.items} loading={loading} rowKey={(t) => t.id} columns={[
          { key: "id", header: "#", render: (t) => <span className="muted">{t.id}</span> },
          { key: "t", header: "Date / time", render: (t) => fmtDateTime(t.created_at) },
          { key: "ty", header: "Type", render: (t) => <Pill value={t.txn_type} tone="info" /> },
          { key: "sku", header: "Item", render: (t) => <Link to={`/items/${t.item.id}`}><b>{t.item.sku}</b></Link> },
          { key: "from", header: "From", render: (t) => <span className="mono">{t.from_location?.code ?? ""}</span> },
          { key: "to", header: "To", render: (t) => <span className="mono">{t.to_location?.code ?? ""}</span> },
          { key: "lot", header: "Lot", render: (t) => t.lot_number },
          { key: "q", header: "Qty", align: "right", render: (t) => <span className={t.qty < 0 ? "qty-neg" : ""}>{fmtNum(t.qty)}</span> },
          { key: "st", header: "Status", render: (t) => (t.from_status && t.to_status && t.from_status !== t.to_status ? `${t.from_status} → ${t.to_status}` : t.to_status ?? "") },
          { key: "rc", header: "Reason", render: (t) => t.reason_code ?? "" },
          { key: "ref", header: "Reference", render: (t) => (t.reference_number ? <span>{t.reference_type?.toLowerCase()} {t.reference_number}</span> : "") },
          { key: "u", header: "User", render: (t) => t.username ?? "" },
        ]} />
        <Pager total={data?.total ?? 0} limit={limit} offset={offset} onChange={setOffset} />
      </Card>
    </>
  );
}
