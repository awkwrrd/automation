import { Route, Routes } from "react-router-dom";
import { useApp } from "./context";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import InventoryInquiry from "./pages/InventoryInquiry";
import Items from "./pages/Items";
import ItemDetail from "./pages/ItemDetail";
import Transactions from "./pages/Transactions";
import InboundList from "./pages/InboundList";
import InboundDetail from "./pages/InboundDetail";
import InboundNew from "./pages/InboundNew";
import Orders from "./pages/Orders";
import OrderDetail from "./pages/OrderDetail";
import OrderNew from "./pages/OrderNew";
import Waves from "./pages/Waves";
import PackShip from "./pages/PackShip";
import Tasks from "./pages/Tasks";
import Counts from "./pages/Counts";
import CountDetail from "./pages/CountDetail";
import Replenishment from "./pages/Replenishment";
import Locations from "./pages/Locations";
import Warehouses from "./pages/Warehouses";
import Suppliers from "./pages/Suppliers";
import Users from "./pages/Users";
import Integrations from "./pages/Integrations";
import MessageLog from "./pages/MessageLog";

export default function App() {
  const { user, ready } = useApp();
  if (!ready) return <div className="boot">Loading…</div>;
  if (!user) return <Login />;
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="inventory" element={<InventoryInquiry />} />
        <Route path="items" element={<Items />} />
        <Route path="items/:id" element={<ItemDetail />} />
        <Route path="transactions" element={<Transactions />} />
        <Route path="inbound" element={<InboundList />} />
        <Route path="inbound/new" element={<InboundNew />} />
        <Route path="inbound/:id" element={<InboundDetail />} />
        <Route path="orders" element={<Orders />} />
        <Route path="orders/new" element={<OrderNew />} />
        <Route path="orders/:id" element={<OrderDetail />} />
        <Route path="waves" element={<Waves />} />
        <Route path="pack" element={<PackShip />} />
        <Route path="tasks" element={<Tasks />} />
        <Route path="counts" element={<Counts />} />
        <Route path="counts/:id" element={<CountDetail />} />
        <Route path="reports/replenishment" element={<Replenishment />} />
        <Route path="config/locations" element={<Locations />} />
        <Route path="config/warehouses" element={<Warehouses />} />
        <Route path="config/suppliers" element={<Suppliers />} />
        <Route path="config/users" element={<Users />} />
        <Route path="config/integrations" element={<Integrations />} />
        <Route path="config/messages" element={<MessageLog />} />
        <Route path="*" element={<div className="empty">Page not found</div>} />
      </Route>
    </Routes>
  );
}
