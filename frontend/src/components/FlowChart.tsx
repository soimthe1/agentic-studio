import { useNavigate } from "react-router-dom";

/** Bird's-eye flow: how an agent comes to life in Agent Studio, every decision with its yes/no path. Each box opens the
 *  place where that happens. Top band: building it; bottom band: running it. Drawn in one SVG that scales to fit. */
type Kind = "start" | "step" | "ask" | "end";
type Node = { id: string; x: number; y: number; w: number; h: number; kind: Kind; en: string; ar: string; to?: string; isNew?: boolean };
type Edge = { from: string; to: string; label?: "yes" | "no"; path?: string; lx?: number; ly?: number };

const N: Node[] = [
  { id: "a", x: 95, y: 300, w: 170, h: 78, kind: "start", en: "Say what you want|in your own words", ar: "قل ما تريد|بكلماتك", to: "/create" },
  { id: "b", x: 305, y: 300, w: 180, h: 118, kind: "ask", en: "Needs data from|your systems?", ar: "يحتاج بيانات|من أنظمتك؟" },
  { id: "c", x: 305, y: 490, w: 230, h: 72, kind: "step", en: "No system needed: chat, write,|summarise, files, web", ar: "دون نظام: محادثة، كتابة،|تلخيص، ملفات، ويب" },
  { id: "d", x: 525, y: 300, w: 170, h: 118, kind: "ask", en: "Already|connected?", ar: "متصل|مسبقاً؟", to: "/tools" },
  { id: "e", x: 525, y: 110, w: 180, h: 64, kind: "step", en: "Uses it straight away", ar: "يستخدمه فوراً" },
  { id: "f", x: 745, y: 300, w: 190, h: 118, kind: "ask", en: "Publishes its API|description?", ar: "ينشر وصف|واجهته البرمجية؟" },
  { id: "g", x: 745, y: 110, w: 210, h: 72, kind: "step", en: "Find it for me: AI reads it,|picks operations, tests live", ar: "ابحث لي: يقرأه الذكاء،|يختار العمليات، يختبر", to: "/tools", isNew: true },
  { id: "h", x: 745, y: 490, w: 210, h: 72, kind: "step", en: "Write a tool: AI writes Python|+ plain risk report", ar: "اكتب أداة: يكتب Python|مع تقرير المخاطر", to: "/tools", isNew: true },
  { id: "i", x: 965, y: 300, w: 180, h: 72, kind: "step", en: "Administrator approves|(reads code if written)", ar: "يعتمد المسؤول|(ويقرأ الشيفرة)", to: "/tools" },
  { id: "j", x: 1170, y: 300, w: 170, h: 118, kind: "ask", en: "Should it|change things?", ar: "هل يغيّر|شيئاً؟" },
  { id: "k", x: 1170, y: 110, w: 190, h: 64, kind: "step", en: "Asks a person before|every change", ar: "يطلب موافقة شخص|قبل كل تغيير", to: "/approvals" },
  { id: "l", x: 1170, y: 490, w: 170, h: 64, kind: "step", en: "Read-only", ar: "قراءة فقط" },
  { id: "m", x: 1385, y: 300, w: 190, h: 90, kind: "step", en: "When it works: chat,|schedule, alert, or|keeps watching", ar: "متى يعمل: محادثة،|جدول، تنبيه، أو|مراقبة مستمرة" },
  { id: "p", x: 140, y: 690, w: 190, h: 78, kind: "step", en: "Test run, judged|against your goal", ar: "تشغيل تجريبي يُقيَّم|مقابل هدفك", to: "/create" },
  { id: "q", x: 380, y: 690, w: 150, h: 110, kind: "ask", en: "Goal met?", ar: "تحقق الهدف؟" },
  { id: "r", x: 600, y: 690, w: 150, h: 64, kind: "step", en: "Publish", ar: "انشر", to: "/agents" },
  { id: "s", x: 850, y: 690, w: 250, h: 90, kind: "step", en: "Runs by itself: checks its work,|retries with the reason, backup|model, makes up missed runs", ar: "يعمل وحده: يراجع عمله،|يعيد المحاولة، نموذج احتياطي،|يعوّض الفائت", isNew: true },
  { id: "t", x: 1120, y: 690, w: 210, h: 78, kind: "step", en: "Learns: corrections, notes,|test questions", ar: "يتعلم: تصحيحات،|ملاحظات، أسئلة اختبار", isNew: true },
  { id: "u", x: 1365, y: 690, w: 190, h: 78, kind: "end", en: "Share · embed · MCP", ar: "مشاركة · تضمين · MCP", to: "/shared", isNew: true },
];
const E: Edge[] = [
  { from: "a", to: "b" },
  { from: "b", to: "c", label: "no" }, { from: "b", to: "d", label: "yes" },
  { from: "d", to: "e", label: "yes" }, { from: "d", to: "f", label: "no" },
  { from: "f", to: "g", label: "yes" }, { from: "f", to: "h", label: "no" },
  { from: "g", to: "i", path: "M850,110 H965 V264" }, { from: "h", to: "i", path: "M850,490 H965 V336" },
  { from: "e", to: "j", path: "M615,110 H650 V40 H1068 V300 H1085" },
  { from: "c", to: "j", path: "M420,490 H460 V580 H1068 V300 H1085" },
  { from: "i", to: "j" },
  { from: "j", to: "k", label: "yes" }, { from: "j", to: "l", label: "no" },
  { from: "k", to: "m", path: "M1265,110 H1385 V255" }, { from: "l", to: "m", path: "M1255,490 H1385 V345" },
  { from: "m", to: "p", path: "M1385,345 V630 H140 V651" },
  { from: "p", to: "q" },
  { from: "q", to: "p", label: "no", path: "M380,745 V775 H140 V729", lx: 262, ly: 790 },
  { from: "q", to: "r", label: "yes" }, { from: "r", to: "s" }, { from: "s", to: "t" }, { from: "t", to: "u" },
];

function anchor(n: Node, toward: Node): [number, number] {
  const dx = toward.x - n.x, dy = toward.y - n.y;
  if (Math.abs(dx) >= Math.abs(dy)) return [n.x + Math.sign(dx) * n.w / 2, n.y];
  return [n.x, n.y + Math.sign(dy) * n.h / 2];
}

export function FlowChart({ ar }: { ar: boolean }) {
  const nav = useNavigate();
  const byId = Object.fromEntries(N.map((n) => [n.id, n]));
  const yes = ar ? "نعم" : "Yes", no = ar ? "لا" : "No";
  return (
    <svg className="fc" viewBox="0 0 1500 810" preserveAspectRatio="xMidYMid meet" role="img"
      aria-label={ar ? "مخطط إنشاء وكيل في {{brand}}" : "How an agent is made in Agent Studio"}>
      <defs>
        <marker id="fc-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" className="fc-arrowhead" />
        </marker>
      </defs>
      <text x="16" y="28" className="fc-band">{ar ? "١ · البناء" : "1 · Build it"}</text>
      <text x="16" y="622" className="fc-band">{ar ? "٢ · التشغيل" : "2 · Run it"}</text>
      <line x1="0" y1="600" x2="1500" y2="600" className="fc-divider" />
      {E.map((e, i) => {
        const a = byId[e.from], b = byId[e.to];
        const [x1, y1] = anchor(a, b), [x2, y2] = anchor(b, a);
        const d = e.path ?? `M${x1},${y1} L${x2},${y2}`;
        const lx = e.lx ?? (x1 + (e.path ? x1 : x2)) / 2 + (Math.abs(x2 - x1) < 4 ? 14 : 0);
        const ly = e.ly ?? (y1 + y2) / 2 - (Math.abs(y2 - y1) < 4 ? 8 : 0);
        return (
          <g key={i}>
            <path d={d} className={`fc-edge ${e.label ?? ""}`} markerEnd="url(#fc-arrow)" />
            {e.label && <text x={lx} y={ly} className={`fc-label ${e.label}`} textAnchor="middle">{e.label === "yes" ? yes : no}</text>}
          </g>
        );
      })}
      {N.map((n) => {
        const lines = (ar ? n.ar : n.en).split("|");
        const shape = n.kind === "ask"
          ? <polygon points={`${n.x},${n.y - n.h / 2} ${n.x + n.w / 2},${n.y} ${n.x},${n.y + n.h / 2} ${n.x - n.w / 2},${n.y}`} />
          : <rect x={n.x - n.w / 2} y={n.y - n.h / 2} width={n.w} height={n.h} rx={n.kind === "step" ? 4 : n.h / 2} />;
        return (
          <g key={n.id} className={`fc-node ${n.kind}${n.to ? " link" : ""}`} onClick={n.to ? () => nav(n.to!) : undefined}
            role={n.to ? "link" : undefined} tabIndex={n.to ? 0 : undefined}
            onKeyDown={n.to ? (ev) => { if (ev.key === "Enter") nav(n.to!); } : undefined}>
            {shape}
            {lines.map((l, k) => (
              <text key={k} x={n.x} y={n.y + (k - (lines.length - 1) / 2) * 17 + 5} textAnchor="middle" direction={ar ? "rtl" : "ltr"}>{l}</text>
            ))}
            {n.isNew && <text x={n.x + n.w / 2 - 6} y={n.y - n.h / 2 + 14} textAnchor="end" className="fc-new">{ar ? "جديد" : "NEW"}</text>}
          </g>
        );
      })}
    </svg>
  );
}
