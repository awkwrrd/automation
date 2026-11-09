import { useState } from "react";
import { ItemPicker, Input } from "./ui";
import type { ItemRef } from "../types";

export interface DraftLine { item: ItemRef; qty: number }

/** Simple "add item + qty" line entry used by receipt & order creation. */
export function LineEditor({ lines, setLines }: { lines: DraftLine[]; setLines: (l: DraftLine[]) => void }) {
  const [item, setItem] = useState<ItemRef | null>(null);
  const [qty, setQty] = useState("1");
  const add = () => {
    if (!item || !(Number(qty) > 0)) return;
    const existing = lines.find((l) => l.item.id === item.id);
    setLines(existing ? lines.map((l) => (l.item.id === item.id ? { ...l, qty: l.qty + Number(qty) } : l)) : [...lines, { item, qty: Number(qty) }]);
    setItem(null);
    setQty("1");
  };
  return (
    <>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 110px auto", gap: 8, marginBottom: 12 }}>
        <ItemPicker value={item} onChange={setItem} />
        <Input type="number" min={1} value={qty} onChange={(e) => setQty(e.target.value)} onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), add())} aria-label="Quantity" />
        <button type="button" className="btn" onClick={add} disabled={!item}>Add line</button>
      </div>
      <table className="grid">
        <thead><tr><th>#</th><th>SKU</th><th>Description</th><th style={{ textAlign: "right", width: 120 }}>Qty</th><th style={{ width: 40 }} /></tr></thead>
        <tbody>
          {lines.map((l, idx) => (
            <tr key={l.item.id}>
              <td className="muted">{idx + 1}</td>
              <td><b>{l.item.sku}</b></td>
              <td>{l.item.name}</td>
              <td><Input type="number" min={1} value={l.qty} style={{ textAlign: "right" }} onChange={(e) => setLines(lines.map((x) => (x === l ? { ...x, qty: Number(e.target.value) } : x)))} /></td>
              <td><button type="button" className="icon-btn" aria-label="Remove line" onClick={() => setLines(lines.filter((x) => x !== l))}>×</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      {lines.length === 0 && <div className="empty">No lines yet — search an item above and add it.</div>}
    </>
  );
}
