import { useTranslation } from "react-i18next";
import type { Agent } from "../api";

/** Runtime watchkeeper verdict for one agent: the "is my agent working well?" answer, with its reason. */
export function HealthBadge({ health }: { health: Agent["health"] }) {
  const { t } = useTranslation();
  if (!health) return null;
  const cls = health.status === "working_well" ? "ok" : health.status === "needs_attention" ? "err" : "";
  return <span className={`badge health ${cls}`} title={health.reason}>{t(`health.agent.${health.status}`)}</span>;
}
