import { useState, type ReactNode } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useApp } from "../context";
import type { Role } from "../types";

const I = {
  dash: "M3 3h6v8H3zM11 3h6v5h-6zM11 10h6v7h-6zM3 13h6v4H3z",
  box: "M10 2l7 4v8l-7 4-7-4V6zm0 2.2L5.2 6.8 10 9.4l4.8-2.6zM4.5 8.1v5l4.75 2.6v-5zm11 0l-4.75 2.6v5l4.75-2.6z",
  tag: "M2 3h7l9 9-7 7-9-9zm4 2.5a1.5 1.5 0 100 3 1.5 1.5 0 000-3z",
  inbound: "M10 2v9.6l3.3-3.3 1.4 1.4L10 14.4 5.3 9.7l1.4-1.4L9 11.6V2zM3 15h14v3H3z",
  outbound: "M10 14V4.4L6.7 7.7 5.3 6.3 10 1.6l4.7 4.7-1.4 1.4L11 4.4V14zM3 15h14v3H3z",
  wave: "M2 12c2-3 4-3 6 0s4 3 6 0 3-2 4-1v2c-1-1-2-1-4 1s-4 3-6 0-4-3-6 0zM2 7c2-3 4-3 6 0s4 3 6 0 3-2 4-1v2c-1-1-2-1-4 1s-4 3-6 0-4-3-6 0z",
  task: "M4 3h12v14H4zm2 3v2h2V6zm4 0v2h4V6zm-4 4v2h2v-2zm4 0v2h4v-2z",
  pack: "M2 6l8-4 8 4v8l-8 4-8-4zm8 5.2L16 8v5.4l-6 3zM4 8v5.4l5 2.5v-5.4zm6-4L5 6.5l5 2.5 5-2.5z",
  count: "M3 3h14v14H3zm2 2v10h10V5zm2 2h6v2H7zm0 4h4v2H7z",
  hist: "M10 2a8 8 0 110 16 8 8 0 010-16zm0 2a6 6 0 100 12 6 6 0 000-12zm-1 2h2v4.6l3 1.8-1 1.7-4-2.4z",
  chart: "M3 17V9h3v8zm5 0V3h3v14zm5 0v-6h3v6z",
  loc: "M10 1a6 6 0 016 6c0 4.5-6 11-6 11S4 11.5 4 7a6 6 0 016-6zm0 3.5a2.5 2.5 0 100 5 2.5 2.5 0 000-5z",
  wh: "M10 2l8 4v12h-3v-8H5v8H2V6zm-3 10h6v2H7zm0 3h6v2H7z",
  truck: "M1 4h11v9H1zm11 3h4l3 3v3h-7zM5 14a2 2 0 110 4 2 2 0 010-4zm10 0a2 2 0 110 4 2 2 0 010-4z",
  users: "M7 9a3 3 0 110-6 3 3 0 010 6zm7 0a2.5 2.5 0 110-5 2.5 2.5 0 010 5zM1 16c0-3 3-5 6-5s6 2 6 5v1H1zm13-4c2.5 0 5 1.3 5 4v1h-4v-1c0-1.6-.4-2.8-1-4z",
};
const Icon = ({ d }: { d: string }) => <svg viewBox="0 0 20 20" width="16" height="16" aria-hidden><path d={d} fill="currentColor" /></svg>;

type NavItem = { to: string; label: string; icon: string; role?: Role };
const NAV: { group: string; items: NavItem[] }[] = [
  { group: "", items: [{ to: "/", label: "Dashboard", icon: I.dash }] },
  { group: "Inventory", items: [
    { to: "/inventory", label: "Inventory Inquiry", icon: I.box },
    { to: "/items", label: "Items", icon: I.tag },
    { to: "/counts", label: "Cycle Counts", icon: I.count },
    { to: "/transactions", label: "Transaction History", icon: I.hist },
  ] },
  { group: "Inbound", items: [{ to: "/inbound", label: "Receipts / ASNs", icon: I.inbound }] },
  { group: "Outbound", items: [
    { to: "/orders", label: "Orders", icon: I.outbound },
    { to: "/waves", label: "Waves", icon: I.wave },
    { to: "/pack", label: "Pack & Ship", icon: I.pack },
  ] },
  { group: "Execution", items: [{ to: "/tasks", label: "Task Queue", icon: I.task }] },
  { group: "Reports", items: [{ to: "/reports/replenishment", label: "Replenishment", icon: I.chart }] },
  { group: "Configuration", items: [
    { to: "/config/locations", label: "Locations", icon: I.loc },
    { to: "/config/warehouses", label: "Warehouses & Zones", icon: I.wh },
    { to: "/config/suppliers", label: "Suppliers", icon: I.truck },
    { to: "/config/users", label: "Users", icon: I.users, role: "SUPERVISOR" },
  ] },
];

export default function Layout({ children }: { children?: ReactNode }) {
  const { user, meta, warehouses, warehouseId, setWarehouseId, logout, can } = useApp();
  const [navOpen, setNavOpen] = useState(false);
  const nav = useNavigate();
  return (
    <div className={`shell ${navOpen ? "nav-open" : ""}`}>
      <aside className="sidebar">
        <div className="brand">
          <svg viewBox="0 0 32 32" width="26" height="26" aria-hidden><rect width="32" height="32" rx="7" fill="var(--accent)" /><path d="M7 13l9-5 9 5v11H7z" fill="#fff" /><rect x="12.5" y="17" width="7" height="7" fill="var(--accent)" /></svg>
          <span>{meta?.app_name ?? "WMS"}</span>
        </div>
        <nav onClick={() => setNavOpen(false)}>
          {NAV.map((g) => (
            <div key={g.group || "root"} className="nav-group">
              {g.group && <div className="nav-group-label">{g.group}</div>}
              {g.items.filter((i) => !i.role || can(i.role)).map((i) => (
                <NavLink key={i.to} to={i.to} end={i.to === "/"} className="nav-link">
                  <Icon d={i.icon} /> {i.label}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <div className="sidebar-foot">v0.1 · <a href="/docs" target="_blank" rel="noreferrer">API docs</a></div>
      </aside>
      <div className="nav-scrim" onClick={() => setNavOpen(false)} />
      <div className="main">
        <header className="topbar">
          <button className="icon-btn hamburger" aria-label="Menu" onClick={() => setNavOpen((o) => !o)}>☰</button>
          <div className="wh-select">
            <span className="muted">Warehouse</span>
            <select className="input" value={warehouseId ?? ""} onChange={(e) => setWarehouseId(Number(e.target.value))}>
              {warehouses.map((w) => <option key={w.id} value={w.id}>{w.code} — {w.name}</option>)}
            </select>
          </div>
          <div className="spacer" />
          <div className="user-chip" title={user?.role}>
            <span className="avatar">{(user?.full_name || user?.username || "?").slice(0, 1).toUpperCase()}</span>
            <span className="user-meta"><b>{user?.full_name || user?.username}</b><small>{user?.role}</small></span>
          </div>
          <button className="btn btn-sm" onClick={() => { logout(); nav("/"); }}>Sign out</button>
        </header>
        <main className="content">{children ?? <Outlet />}</main>
      </div>
    </div>
  );
}
