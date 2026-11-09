import {
  createContext, useCallback, useContext, useEffect, useRef, useState,
  type ReactNode, type InputHTMLAttributes, type SelectHTMLAttributes,
} from "react";
import { api } from "../api";
import { useApp } from "../context";
import type { ItemRef, Location, Page, Item } from "../types";

// ------------------------------------------------------------------ formatting
export const fmtNum = (n: number | null | undefined) => (n ?? 0).toLocaleString();
export const fmtDate = (s: string | null | undefined) => (s ? new Date(s.endsWith("Z") || s.length <= 10 ? s : s + "Z").toLocaleDateString() : "—");
export const fmtDateTime = (s: string | null | undefined) =>
  s ? new Date(s.endsWith("Z") ? s : s + "Z").toLocaleString([], { dateStyle: "short", timeStyle: "short" }) : "—";
export const fmtMoney = (s: string | number | null | undefined) =>
  s === null || s === undefined || s === "" ? "—" : Number(s).toLocaleString(undefined, { style: "currency", currency: "USD" });
export const label = (s: string) => s.replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());

// ------------------------------------------------------------------ data loading
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const seq = useRef(0);
  const reload = useCallback(async () => {
    const my = ++seq.current;
    setLoading(true);
    try {
      const d = await fn();
      if (my === seq.current) { setData(d); setError(null); }
    } catch (e) {
      if (my === seq.current) setError((e as Error).message);
    } finally {
      if (my === seq.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => { reload(); }, [reload]);
  return { data, error, loading, reload, setData };
}

export function useDebounced<T>(value: T, ms = 300) {
  const [v, setV] = useState(value);
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t); }, [value, ms]);
  return v;
}

// ------------------------------------------------------------------ toasts
type Toast = { id: number; kind: "ok" | "err"; text: string };
const ToastCtx = createContext<{ ok: (t: string) => void; err: (t: string) => void }>({ ok: () => {}, err: () => {} });
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((kind: Toast["kind"], text: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, kind, text }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === "err" ? 6000 : 3000);
  }, []);
  const value = { ok: useCallback((t: string) => push("ok", t), [push]), err: useCallback((t: string) => push("err", t), [push]) };
  return (
    <ToastCtx.Provider value={value}>
      {children}
      <div className="toasts" role="status">
        {toasts.map((t) => <div key={t.id} className={`toast toast-${t.kind}`}>{t.text}</div>)}
      </div>
    </ToastCtx.Provider>
  );
}

/** Wrap an async action with busy state + toast on error/success. */
export function useAction() {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const run = useCallback(async <T,>(fn: () => Promise<T>, success?: string): Promise<T | undefined> => {
    setBusy(true);
    try {
      const r = await fn();
      if (success) toast.ok(success);
      return r;
    } catch (e) {
      toast.err((e as Error).message);
      return undefined;
    } finally {
      setBusy(false);
    }
  }, [toast]);
  return { busy, run };
}

// ------------------------------------------------------------------ layout bits
export function PageHeader({ title, subtitle, actions, crumbs }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; crumbs?: ReactNode }) {
  return (
    <div className="page-header">
      <div>
        {crumbs && <div className="crumbs">{crumbs}</div>}
        <h1>{title}</h1>
        {subtitle && <div className="subtitle">{subtitle}</div>}
      </div>
      {actions && <div className="actions">{actions}</div>}
    </div>
  );
}

export function Card({ title, actions, children, className = "", pad = true }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; pad?: boolean }) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="card-head"><h2>{title}</h2>{actions && <div className="actions">{actions}</div>}</header>
      )}
      <div className={pad ? "card-body" : ""}>{children}</div>
    </section>
  );
}

const STATUS_TONE: Record<string, string> = {
  NEW: "info", OPEN: "info", PLANNED: "info", AVAILABLE: "ok",
  PARTIALLY_ALLOCATED: "warn", RECEIVING: "warn", IN_PROGRESS: "warn", PICKING: "warn", HOLD: "warn",
  ALLOCATED: "accent", RELEASED: "accent", PICKED: "accent", PACKED: "accent",
  SENT: "ok", FAILED: "bad", PENDING: "warn",
  SHIPPED: "ok", RECEIVED: "ok", COMPLETE: "ok", COMPLETED: "ok", CLOSED: "muted",
  CANCELLED: "muted", DAMAGED: "bad", QUARANTINE: "bad",
};
export function Pill({ value, tone, raw }: { value: string; tone?: string; raw?: boolean }) {
  return <span className={`pill pill-${tone ?? STATUS_TONE[value] ?? "muted"}`}>{raw ? value : label(value)}</span>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function ErrorBox({ error }: { error: string | null }) {
  return error ? <div className="error-box">{error}</div> : null;
}

export function Stat({ label: l, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: string }) {
  return (
    <div className={`stat ${tone ? "stat-" + tone : ""}`}>
      <div className="stat-label">{l}</div>
      <div className="stat-value">{value}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  );
}

// ------------------------------------------------------------------ table
export interface Column<T> {
  key: string;
  header: ReactNode;
  render?: (row: T) => ReactNode;
  align?: "right" | "center";
  width?: string | number;
}

export function DataTable<T>({ columns, rows, rowKey, onRowClick, loading, empty = "No records found", selected, onSelect, rowClass }: {
  columns: Column<T>[]; rows: T[] | undefined | null; rowKey: (r: T) => string | number; onRowClick?: (r: T) => void;
  loading?: boolean; empty?: ReactNode; selected?: Set<number | string>; onSelect?: (s: Set<number | string>) => void;
  rowClass?: (r: T) => string;
}) {
  const list = rows ?? [];
  const allSelected = !!selected && list.length > 0 && list.every((r) => selected.has(rowKey(r)));
  return (
    <div className={`table-wrap ${loading ? "is-loading" : ""}`}>
      <table className="grid">
        <thead>
          <tr>
            {onSelect && (
              <th style={{ width: 32 }}>
                <input type="checkbox" aria-label="Select all" checked={allSelected} onChange={() => {
                  const s = new Set(selected);
                  list.forEach((r) => (allSelected ? s.delete(rowKey(r)) : s.add(rowKey(r))));
                  onSelect(s);
                }} />
              </th>
            )}
            {columns.map((c) => (
              <th key={c.key} style={{ textAlign: c.align, width: c.width }}>{c.header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {list.map((r) => {
            const k = rowKey(r);
            return (
              <tr key={k} onClick={onRowClick ? () => onRowClick(r) : undefined}
                className={`${onRowClick ? "clickable" : ""} ${selected?.has(k) ? "selected" : ""} ${rowClass?.(r) ?? ""}`}>
                {onSelect && (
                  <td onClick={(e) => e.stopPropagation()}>
                    <input type="checkbox" aria-label="Select row" checked={!!selected?.has(k)} onChange={() => {
                      const s = new Set(selected);
                      s.has(k) ? s.delete(k) : s.add(k);
                      onSelect(s);
                    }} />
                  </td>
                )}
                {columns.map((c) => (
                  <td key={c.key} style={{ textAlign: c.align }}>
                    {c.render ? c.render(r) : String((r as Record<string, unknown>)[c.key] ?? "")}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
      {!loading && list.length === 0 && <Empty>{empty}</Empty>}
      {loading && list.length === 0 && <Empty>Loading…</Empty>}
    </div>
  );
}

export function Pager({ total, limit, offset, onChange }: { total: number; limit: number; offset: number; onChange: (o: number) => void }) {
  if (total <= limit) return <div className="pager"><span>{fmtNum(total)} record{total === 1 ? "" : "s"}</span></div>;
  return (
    <div className="pager">
      <span>{fmtNum(offset + 1)}–{fmtNum(Math.min(offset + limit, total))} of {fmtNum(total)}</span>
      <button className="btn btn-sm" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>‹ Prev</button>
      <button className="btn btn-sm" disabled={offset + limit >= total} onClick={() => onChange(offset + limit)}>Next ›</button>
    </div>
  );
}

// ------------------------------------------------------------------ modal
export function Modal({ title, onClose, children, footer, wide }: { title: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${wide ? "modal-wide" : ""}`} role="dialog" aria-modal="true">
        <header className="modal-head"><h3>{title}</h3><button className="icon-btn" onClick={onClose} aria-label="Close">×</button></header>
        <div className="modal-body">{children}</div>
        {footer && <footer className="modal-foot">{footer}</footer>}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ form fields
/** `group` renders a <div> instead of <label>, for fields holding several inputs/buttons (avoids nested labels). */
export function Field({ label: l, children, hint, span, group }: { label: ReactNode; children: ReactNode; hint?: ReactNode; span?: number; group?: boolean }) {
  const Tag = group ? "div" : "label";
  return (
    <Tag className="field" style={span ? { gridColumn: `span ${span}` } : undefined}>
      <span className="field-label">{l}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </Tag>
  );
}

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input className="input" {...props} />;
}

export function Select({ options, placeholder, ...props }: SelectHTMLAttributes<HTMLSelectElement> & { options: (string | { value: string | number; label: string })[]; placeholder?: string }) {
  return (
    <select className="input" {...props}>
      {placeholder !== undefined && <option value="">{placeholder}</option>}
      {options.map((o) => typeof o === "string"
        ? <option key={o} value={o}>{label(o)}</option>
        : <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
}

export function SearchBox({ value, onChange, placeholder = "Search…" }: { value: string; onChange: (v: string) => void; placeholder?: string }) {
  return (
    <div className="search">
      <svg viewBox="0 0 20 20" width="14" height="14" aria-hidden><path d="M8.5 3a5.5 5.5 0 014.38 8.83l3.65 3.64-1.06 1.06-3.64-3.65A5.5 5.5 0 118.5 3zm0 1.5a4 4 0 100 8 4 4 0 000-8z" fill="currentColor" /></svg>
      <input className="input" value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

// ------------------------------------------------------------------ async pickers
function useOutside(ref: React.RefObject<HTMLElement>, cb: () => void) {
  useEffect(() => {
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) cb(); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [ref, cb]);
}

export function ItemPicker({ value, onChange, autoFocus, placeholder = "Scan or search SKU / name / barcode" }: {
  value: ItemRef | null; onChange: (i: ItemRef | null) => void; autoFocus?: boolean; placeholder?: string;
}) {
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const [opts, setOpts] = useState<Item[]>([]);
  const ref = useRef<HTMLDivElement>(null);
  const q = useDebounced(text, 200);
  useOutside(ref, useCallback(() => setOpen(false), []));
  useEffect(() => {
    if (!open) return;
    api.get<Page<Item>>("/items", { q, limit: 12, active: true }).then((p) => setOpts(p.items)).catch(() => setOpts([]));
  }, [q, open]);
  if (value) {
    return (
      <div className="picked">
        <span><b>{value.sku}</b> <span className="muted">{value.name}</span></span>
        <button type="button" className="icon-btn" onClick={() => onChange(null)} aria-label="Clear">×</button>
      </div>
    );
  }
  return (
    <div className="picker" ref={ref}>
      <input className="input" autoFocus={autoFocus} value={text} placeholder={placeholder}
        onFocus={() => setOpen(true)} onChange={(e) => { setText(e.target.value); setOpen(true); }}
        onKeyDown={async (e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            const exact = opts.find((o) => o.sku.toLowerCase() === text.trim().toLowerCase() || o.barcode === text.trim());
            const pick = exact ?? (opts.length === 1 ? opts[0] : null);
            if (pick) { onChange(pick); setOpen(false); }
          }
        }} />
      {open && opts.length > 0 && (
        <ul className="picker-menu">
          {opts.map((o) => (
            <li key={o.id} onMouseDown={() => { onChange(o); setOpen(false); setText(""); }}>
              <b>{o.sku}</b> <span className="muted">{o.name}</span><span className="picker-meta">{fmtNum(o.available)} avail</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function LocationPicker({ value, onChange, placeholder = "Scan or search location", filter }: {
  value: { id: number; code: string } | null; onChange: (l: { id: number; code: string } | null) => void;
  placeholder?: string; filter?: Record<string, string | boolean>;
}) {
  const { warehouseId } = useApp();
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const [opts, setOpts] = useState<Location[]>([]);
  const ref = useRef<HTMLDivElement>(null);
  const q = useDebounced(text, 200);
  useOutside(ref, useCallback(() => setOpen(false), []));
  const filterKey = JSON.stringify(filter ?? {});
  useEffect(() => {
    if (!open) return;
    api.get<Page<Location>>("/locations", { q, limit: 15, active: true, warehouse_id: warehouseId, ...JSON.parse(filterKey) })
      .then((p) => setOpts(p.items)).catch(() => setOpts([]));
  }, [q, open, warehouseId, filterKey]);
  if (value) {
    return (
      <div className="picked">
        <span className="mono"><b>{value.code}</b></span>
        <button type="button" className="icon-btn" onClick={() => onChange(null)} aria-label="Clear">×</button>
      </div>
    );
  }
  return (
    <div className="picker" ref={ref}>
      <input className="input mono" value={text} placeholder={placeholder}
        onFocus={() => setOpen(true)} onChange={(e) => { setText(e.target.value); setOpen(true); }}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            const exact = opts.find((o) => o.code.toLowerCase() === text.trim().toLowerCase()) ?? (opts.length === 1 ? opts[0] : null);
            if (exact) { onChange(exact); setOpen(false); }
          }
        }} />
      {open && opts.length > 0 && (
        <ul className="picker-menu">
          {opts.map((o) => (
            <li key={o.id} onMouseDown={() => { onChange(o); setOpen(false); setText(""); }}>
              <b className="mono">{o.code}</b> <span className="muted">{label(o.location_type)}{o.zone ? ` · ${o.zone.code}` : ""}</span>
              <span className="picker-meta">{o.units ? `${fmtNum(o.units)} units` : "empty"}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function Confirm({ text, onYes, onClose, busy, danger }: { text: ReactNode; onYes: () => void; onClose: () => void; busy?: boolean; danger?: boolean }) {
  return (
    <Modal title="Please confirm" onClose={onClose} footer={<>
      <button className="btn" onClick={onClose}>Cancel</button>
      <button className={`btn ${danger ? "btn-danger" : "btn-primary"}`} disabled={busy} onClick={onYes}>Confirm</button>
    </>}>
      <p>{text}</p>
    </Modal>
  );
}
