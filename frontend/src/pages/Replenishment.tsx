import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { Card, DataTable, ErrorBox, PageHeader, Pager, fmtMoney, fmtNum, useLoad } from "../components/ui";
import type { Item, Page } from "../types";
import { useState } from "react";

export default function Replenishment() {
  const nav = useNavigate();
  const [offset, setOffset] = useState(0);
  const limit = 100;
  const { data, error, loading } = useLoad(() => api.get<Page<Item>>("/items", { low_stock: true, active: true, sort: "available", limit, offset }), [offset]);
  const suggest = (i: Item) => Math.max(i.reorder_qty, i.reorder_point - i.available + i.reorder_qty);
  const totalCost = data?.items.reduce((a, i) => a + suggest(i) * Number(i.unit_cost ?? 0), 0) ?? 0;
  return (
    <>
      <PageHeader title="Replenishment" subtitle="Items at or below their reorder point (available-to-sell, excluding held / staged stock)"
        actions={<span className="muted">Suggested PO value: <b>{fmtMoney(totalCost)}</b></span>} />
      <ErrorBox error={error} />
      <Card pad={false}>
        <DataTable rows={data?.items} loading={loading} rowKey={(i) => i.id} onRowClick={(i) => nav(`/items/${i.id}`)} empty="Nothing to reorder 🎉" columns={[
          { key: "sku", header: "SKU", render: (i) => <b>{i.sku}</b> },
          { key: "name", header: "Description" },
          { key: "cat", header: "Category", render: (i) => i.category ?? "—" },
          { key: "oh", header: "On hand", align: "right", render: (i) => fmtNum(i.on_hand) },
          { key: "av", header: "Available", align: "right", render: (i) => <b className="qty-neg">{fmtNum(i.available)}</b> },
          { key: "rop", header: "Reorder pt", align: "right", render: (i) => fmtNum(i.reorder_point) },
          { key: "roq", header: "Reorder qty", align: "right", render: (i) => fmtNum(i.reorder_qty) },
          { key: "sug", header: "Suggested order", align: "right", render: (i) => <b>{fmtNum(suggest(i))}</b> },
          { key: "cost", header: "Est. cost", align: "right", render: (i) => fmtMoney(suggest(i) * Number(i.unit_cost ?? 0)) },
        ]} />
        <Pager total={data?.total ?? 0} limit={limit} offset={offset} onChange={setOffset} />
      </Card>
    </>
  );
}
