import { useState } from "react";
import { useApp } from "../context";

export default function Login() {
  const { login, meta } = useApp();
  const [u, setU] = useState("");
  const [p, setP] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <div className="login">
      <div className="login-card">
        <svg viewBox="0 0 32 32" width="40" height="40" aria-hidden><rect width="32" height="32" rx="7" fill="var(--accent)" /><path d="M7 13l9-5 9 5v11H7z" fill="#fff" /><rect x="12.5" y="17" width="7" height="7" fill="var(--accent)" /></svg>
        <h1>{meta?.app_name ?? "WMS"}</h1>
        <div className="muted">Sign in to continue</div>
        <form onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true); setErr(null);
          try { await login(u, p); } catch (x) { setErr((x as Error).message); } finally { setBusy(false); }
        }}>
          {err && <div className="error-box" style={{ margin: 0 }}>{err}</div>}
          <label className="field"><span className="field-label">Username</span>
            <input className="input" autoFocus value={u} onChange={(e) => setU(e.target.value)} autoComplete="username" /></label>
          <label className="field"><span className="field-label">Password</span>
            <input className="input" type="password" value={p} onChange={(e) => setP(e.target.value)} autoComplete="current-password" /></label>
          <button className="btn btn-primary" disabled={busy || !u || !p}>{busy ? "Signing in…" : "Sign in"}</button>
        </form>
        <div className="demo-creds">Demo users: <b>admin</b>/admin · <b>supervisor</b>/supervisor · <b>operator</b>/operator</div>
      </div>
    </div>
  );
}
