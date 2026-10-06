import { type ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { AuthProvider, useAuth } from "./lib/auth";
import { Console, Platform, Settings, Users } from "./pages/Admin";
import Alerts from "./pages/Alerts";
import { AiPage, Analysis, Reports } from "./pages/Analytics";
import Board from "./pages/Board";
import { Explosives, Geology } from "./pages/Catalogs";
import Fleet from "./pages/Fleet";
import Staff, { MigrationReport } from "./pages/Staff";
import Dashboard from "./pages/Dashboard";
import Dispatch from "./pages/Dispatch";
import FaceDetail from "./pages/FaceDetail";
import Faces from "./pages/Faces";
import Login from "./pages/Login";
import Mine3D from "./pages/Mine3D";
import { ImportWizard, MineSettings } from "./pages/MinePages";
import { PassportEditor, PassportList } from "./pages/Passports";
import Profile from "./pages/Profile";
import { RingDesign, StopeDetail, StopeList } from "./pages/Rings";
import Tablet from "./pages/Tablet";
import { TypicalDetail, TypicalList } from "./pages/Typical";
import Workings from "./pages/Workings";

function Guard({ children, perms }: { children: ReactNode; perms?: string[] }) {
  const { user, ready, can } = useAuth();
  if (!ready) return null;
  if (!user) return <Navigate to="/login" replace />;
  if (perms && !can(...perms)) return <Layout><div className="error">403</div></Layout>;
  return <Layout>{children}</Layout>;
}

const routes: [string, ReactNode, string[]?][] = [
  ["/", <Dashboard />],
  ["/dispatch/board", <Board />, ["dispatch.view"]],
  ["/dispatch", <Dispatch />, ["dispatch.view"]],
  ["/faces", <Faces />, ["dispatch.view", "workings.view"]],
  ["/faces/:id", <FaceDetail />, ["dispatch.view", "workings.view"]],
  ["/alerts", <Alerts />],
  ["/mine/3d", <Mine3D />],
  ["/workings", <Workings />, ["workings.view"]],
  ["/mine/import", <ImportWizard />, ["mine.settings"]],
  ["/mine", <MineSettings />, ["mine.settings"]],
  ["/passports", <PassportList />, ["passports.view"]],
  ["/passports/:id", <PassportEditor />, ["passports.view"]],
  ["/typical", <TypicalList />, ["passports.view"]],
  ["/typical/:id", <TypicalDetail />, ["passports.view"]],
  ["/rings", <StopeList />, ["passports.view"]],
  ["/stopes/:id", <StopeDetail />, ["passports.view"]],
  ["/rings/:id", <RingDesign />, ["passports.view"]],
  ["/geology", <Geology />, ["geology.view"]],
  ["/explosives", <Explosives />, ["explosives.view"]],
  ["/fleet", <Fleet />, ["fleet.view"]],
  ["/staff", <Staff />, ["staff.view"]],
  ["/migration", <MigrationReport />, ["fleet.view", "staff.view"]],
  ["/analysis", <Analysis />, ["dispatch.view", "workings.view"]],
  ["/reports", <Reports />, ["reports.view"]],
  ["/ai", <AiPage />, ["ai.use"]],
  ["/settings", <Settings />, ["system.settings"]],
  ["/users", <Users />, ["users.manage"]],
  ["/console", <Console />, ["console.use"]],
  ["/platform", <Platform />, ["alerts.admin.view", "system.settings"]],
  ["/profile", <Profile />],
];

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/tablet" element={<TabletGuard />} />
          {routes.map(([p, el, perms]) => <Route key={p} path={p} element={<Guard perms={perms}>{el}</Guard>} />)}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

function TabletGuard() {
  const { user, ready } = useAuth();
  if (!ready) return null;
  if (!user) return <Navigate to="/login" replace />;
  return <div className="content"><Tablet /></div>;
}
