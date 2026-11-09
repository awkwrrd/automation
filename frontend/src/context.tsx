import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, getToken, setToken } from "./api";
import type { Meta, Role, User, Warehouse } from "./types";

interface Ctx {
  user: User | null;
  meta: Meta | null;
  warehouses: Warehouse[];
  warehouseId: number | null;
  setWarehouseId: (id: number) => void;
  login: (u: string, p: string) => Promise<void>;
  logout: () => void;
  can: (r: Role) => boolean;
  refreshWarehouses: () => Promise<void>;
  ready: boolean;
}

const AppCtx = createContext<Ctx>(null as unknown as Ctx);
export const useApp = () => useContext(AppCtx);
const RANK: Record<Role, number> = { OPERATOR: 1, SUPERVISOR: 2, ADMIN: 3 };

export function AppProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [warehouseId, setWh] = useState<number | null>(() => {
    try { return Number(localStorage.getItem("wms_wh")) || null; } catch { return null; }
  });
  const [ready, setReady] = useState(false);

  const refreshWarehouses = useCallback(async () => {
    const list = await api.get<Warehouse[]>("/warehouses");
    setWarehouses(list);
    setWh((cur) => (cur && list.some((w) => w.id === cur) ? cur : list[0]?.id ?? null));
  }, []);

  const bootstrap = useCallback(async () => {
    try {
      setMeta(await api.get<Meta>("/meta"));
      if (getToken()) {
        setUser(await api.get<User>("/auth/me"));
        await refreshWarehouses();
      }
    } catch { setToken(null); setUser(null); }
    setReady(true);
  }, [refreshWarehouses]);

  useEffect(() => { bootstrap(); }, [bootstrap]);
  useEffect(() => {
    const h = () => setUser(null);
    window.addEventListener("wms:logout", h);
    return () => window.removeEventListener("wms:logout", h);
  }, []);
  useEffect(() => { if (meta) document.title = meta.app_name; }, [meta]);

  const login = async (username: string, password: string) => {
    const res = await api.post<{ token: string; user: User }>("/auth/login", { username, password });
    setToken(res.token);
    setUser(res.user);
    await refreshWarehouses();
  };
  const logout = () => { setToken(null); setUser(null); };
  const setWarehouseId = (id: number) => {
    setWh(id);
    try { localStorage.setItem("wms_wh", String(id)); } catch { /* ignore */ }
  };
  const can = (r: Role) => !!user && RANK[user.role] >= RANK[r];

  return (
    <AppCtx.Provider value={{ user, meta, warehouses, warehouseId, setWarehouseId, login, logout, can, refreshWarehouses, ready }}>
      {children}
    </AppCtx.Provider>
  );
}
