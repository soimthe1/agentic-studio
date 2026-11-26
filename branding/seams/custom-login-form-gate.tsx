// Agent Studio: users sign in on the studio's own page (/studio-auth/login). The local Langflow form is only
// shown on the break-glass route /login?local=1 (local admin account for recovery).
import { type ReactNode, useEffect } from "react";

export interface CustomLoginFormGateProps {
  children: ReactNode;
}

export default function CustomLoginFormGate({ children }: CustomLoginFormGateProps) {
  const local = new URLSearchParams(window.location.search).get("local") === "1";
  useEffect(() => {
    if (!local) window.location.replace("/studio-auth/login");
  }, [local]);
  return local ? <>{children}</> : null;
}
