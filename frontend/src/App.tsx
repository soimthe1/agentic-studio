import { createContext, useContext, useEffect, useState } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { api, type Me } from "./api";
import { Sidebar } from "./components/Sidebar";
import { Failed, Loading } from "./components/Status";
import { useLoad } from "./components/useLoad";
import { AgentRun } from "./pages/AgentRun";
import { Agents } from "./pages/Agents";
import { Approvals } from "./pages/Approvals";
import { Create } from "./pages/Create";
import { Dashboard } from "./pages/Dashboard";
import { Files } from "./pages/Files";
import { Health } from "./pages/Health";
import { Tools } from "./pages/Tools";
import { Skills } from "./pages/Skills";
import { Activity } from "./pages/Activity";
import { ExecutionDetail, Executions } from "./pages/Executions";
import { Settings } from "./pages/Settings";
import { Steps } from "./pages/Steps";
import { SharedAgents, SharedChat } from "./pages/Shared";
import { Capabilities } from "./pages/Capabilities";

const MeContext = createContext<Me | null>(null);
export const useMe = () => useContext(MeContext);

export type Theme = "dark" | "light";
export function getTheme(): Theme {
  try {
    return (localStorage.getItem("agent_studio.theme") as Theme) || "dark";
  } catch {
    return "dark";
  }
}
export function setTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem("agent_studio.theme", theme);
  } catch {
    /* not remembered in private mode */
  }
}


/** Neon look (glows + constellation background): a personal choice, off by default. */
export function getNeon(): boolean {
  try {
    return localStorage.getItem("agent_studio.neon") === "on";
  } catch {
    return false;
  }
}
export function setNeon(on: boolean) {
  document.documentElement.dataset.neon = on ? "on" : "off";
  try {
    localStorage.setItem("agent_studio.neon", on ? "on" : "off");
  } catch {
    /* not remembered in private mode */
  }
}

export default function App() {
  const me = useLoad(api.me);
  const [, rerender] = useState(0);
  const loc = useLocation();
  const embed = loc.pathname.startsWith("/chat/") && new URLSearchParams(loc.search).get("embed") === "1";

  useEffect(() => { setTheme(getTheme()); setNeon(getNeon()); }, []);

  if (me.loading) return <Loading />;
  if (me.error || !me.data) return <Failed message={me.error || ""} retry={me.reload} />;

  return (
    <MeContext.Provider value={me.data}>
      <div className={`shell${embed ? " embed" : ""}`}>
        {!embed && <Sidebar me={me.data} />}
        <main className="main">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/agents" element={<Agents />} />
            <Route path="/shared" element={<SharedAgents />} />
            <Route path="/chat/:id" element={<SharedChat />} />
            <Route path="/capabilities" element={<Capabilities />} />
            <Route path="/agents/:id/run" element={<AgentRun />} />
            <Route path="/create" element={<Create />} />
            <Route path="/create/:id" element={<Create />} />
            <Route path="/agents/:id/steps" element={<Steps />} />
            <Route path="/approvals" element={<Approvals />} />
            <Route path="/executions" element={<Executions />} />
            <Route path="/files" element={<Files />} />
            <Route path="/system" element={<Health />} />
            <Route path="/tools" element={<Tools />} />
            <Route path="/skills" element={<Skills />} />
            <Route path="/activity" element={<Activity />} />
            <Route path="/executions/:sessionId" element={<ExecutionDetail />} />
            <Route path="/settings" element={<Settings onChange={() => rerender((n) => n + 1)} />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </MeContext.Provider>
  );
}
