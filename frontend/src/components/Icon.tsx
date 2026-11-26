// Brand icons from branding/kit/.../05_icons (recoloured to currentColor). Decorative: aria-hidden.
import agents from "../assets/icons/agents.svg?raw";
import approvals from "../assets/icons/approvals.svg?raw";
import builder from "../assets/icons/builder.svg?raw";
import catalog from "../assets/icons/catalog.svg?raw";
import database from "../assets/icons/database.svg?raw";
import mcp from "../assets/icons/mcp.svg?raw";
import run from "../assets/icons/run.svg?raw";
import settings from "../assets/icons/settings.svg?raw";
import tools from "../assets/icons/tools.svg?raw";
import trace from "../assets/icons/trace.svg?raw";

const ICONS = { agents, approvals, builder, catalog, database, mcp, run, settings, tools, trace };
export type IconName = keyof typeof ICONS;

export function Icon({ name, className = "ico" }: { name: IconName; className?: string }) {
  return <span className={className} aria-hidden="true" dangerouslySetInnerHTML={{ __html: ICONS[name] }} />;
}
