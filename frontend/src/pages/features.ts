// Everything Agent Studio can do, for the Capabilities page. Plain words first, the technical term small (tech).
// Keep it true: add a feature here when it ships, remove it when it goes.
export type Feature = { en: string; ar: string; den: string; dar: string; to?: string; tech?: string; isNew?: boolean };
export type Group = { id: string; icon: "builder" | "tools" | "approvals" | "run" | "trace" | "catalog" | "agents" | "database" | "settings"; en: string; ar: string; items: Feature[] };

export const GROUPS: Group[] = [
  { id: "create", icon: "builder", en: "Create by conversation", ar: "الإنشاء بالمحادثة", items: [
    { en: "Describe it in your own words", ar: "صِفه بكلماتك", den: "English or Arabic; Agent Studio works out goals, systems, timing and how to answer.", dar: "بالعربية أو الإنجليزية؛ يستنتج {{brand}} الأهداف والأنظمة والتوقيت وطريقة الإجابة.", to: "/create", tech: "NL agent designer" },
    { en: "It asks only what it must", ar: "يسأل فقط عند الضرورة", den: "A few plain choices instead of settings; every choice can be changed on the card.", dar: "خيارات بسيطة قليلة بدلاً من الإعدادات، ويمكن تغيير كل خيار.", to: "/create" },
    { en: "Templates by team", ar: "قوالب حسب الفريق", den: "Ready-made descriptions, plus agents colleagues shared.", dar: "أوصاف جاهزة، إضافة إلى الوكلاء الذين شاركهم الزملاء.", to: "/create", isNew: true },
    { en: "Proof before publishing", ar: "إثبات قبل النشر", den: "A test run is judged against the goal; you see what is missing and how to fix it.", dar: "يُقيَّم تشغيل تجريبي مقابل الهدف، وترى ما ينقص وكيف تصلحه.", tech: "goal judge" },
    { en: "Duplicate check", ar: "كشف التكرار", den: "Warns when an agent doing the same thing already exists.", dar: "ينبّه عند وجود وكيل يقوم بالعمل نفسه." },
    { en: "Readiness check", ar: "فحص الجاهزية", den: "Missing sign-ins, offline systems or switched-off internet are shown before building.", dar: "تظهر بيانات الدخول الناقصة أو الأنظمة المتوقفة قبل البناء." },
    { en: "Answer style and format", ar: "أسلوب الإجابة وشكلها", den: "Short, detailed, report, a table, or fixed fields (JSON) for other systems.", dar: "مختصر، مفصل، تقرير، جدول، أو حقول ثابتة (JSON) لأنظمة أخرى.", tech: "structured output", isNew: true },
    { en: "Effort per run", ar: "الجهد في كل تشغيل", den: "Quick, normal or deep: how many tool calls an agent may make in one run.", dar: "سريع أو عادي أو معمّق: عدد استدعاءات الأدوات المسموح بها في التشغيل.", tech: "run limits", isNew: true },
    { en: "Steps view", ar: "عرض الخطوات", den: "See how an agent is built, in plain words, without any engine canvas.", dar: "شاهد كيف بُني الوكيل بكلمات بسيطة دون لوحة المحرك.", to: "/agents" },
  ] },
  { id: "systems", icon: "tools", en: "Connect any system", ar: "ربط أي نظام", items: [
    { en: "A tool from the system's own description", ar: "أداة من وصف النظام نفسه", den: "Reads OpenAPI, agent_studio.yaml or Agent Studio.md and lists what it can read and change.", dar: "يقرأ OpenAPI أو agent_studio.yaml ويعرض ما يمكن قراءته وتغييره.", to: "/tools", tech: "contract learning" },
    { en: "Tried for real before approval", ar: "يُجرَّب فعلياً قبل الاعتماد", den: "Read operations run live; an administrator approves with the results in front of them.", dar: "تُشغَّل عمليات القراءة فعلياً، ويعتمدها المسؤول وأمامه النتائج.", to: "/tools" },
    { en: "Reuse first", ar: "إعادة الاستخدام أولاً", den: "Systems already connected are offered before anything new; no duplicate tools.", dar: "تُعرض الأنظمة المتصلة قبل أي جديد؛ لا أدوات مكررة." },
    { en: "Discover known systems", ar: "اكتشاف الأنظمة المعروفة", den: "Checks the administrator's list of addresses for published contracts.", dar: "يفحص قائمة العناوين المعتمدة بحثاً عن عقود منشورة.", to: "/tools" },
    { en: "Sign-ins typed on the page", ar: "بيانات الدخول من الصفحة", den: "User id and password checked at once and kept encrypted; never in files.", dar: "يُتحقق من اسم المستخدم وكلمة المرور فوراً وتُحفظ مشفّرة.", to: "/tools", tech: "vault" },
    { en: "Read-only databases", ar: "قواعد بيانات للقراءة فقط", den: "Guarded SQL that can never change data.", dar: "استعلامات SQL محمية لا تغيّر البيانات أبداً.", tech: "SQL guard" },
    { en: "Web reading switch", ar: "مفتاح قراءة الويب", den: "Internet access per deployment, off by default.", dar: "الوصول إلى الإنترنت لكل نشر، ومغلق افتراضياً." },
    { en: "Starter ideas per system", ar: "أفكار بداية لكل نظام", den: "Agent ideas from a system's real operations.", dar: "أفكار وكلاء من عمليات النظام الفعلية.", to: "/tools" },
  ] },
  { id: "safe", icon: "approvals", en: "Acts safely", ar: "يعمل بأمان", items: [
    { en: "A person approves every change", ar: "موافقة بشرية على كل تغيير", den: "Agents propose; nothing changes a system until someone approves.", dar: "يقترح الوكيل، ولا يتغير شيء حتى يوافق شخص.", to: "/approvals", tech: "human in the loop" },
    { en: "Approved building blocks only", ar: "مكونات معتمدة فقط", den: "Every built agent is checked against the approved list before it is saved.", dar: "يُفحص كل وكيل مقابل القائمة المعتمدة قبل حفظه.", tech: "build check" },
    { en: "Secrets never leave an answer", ar: "لا أسرار في الإجابات", den: "Passwords, tokens, keys, card numbers and Emirates IDs are hidden in answers and notifications.", dar: "تُخفى كلمات المرور والرموز والمفاتيح وأرقام البطاقات والهوية في الإجابات والإشعارات.", tech: "guardrail", isNew: true },
    { en: "Notifications to approved channels", ar: "إشعارات لقنوات معتمدة", den: "Agents pick a channel name, never an address.", dar: "يختار الوكيل اسم القناة، لا العنوان." },
    { en: "Engine console for named admins only", ar: "لوحة المحرك لمسؤولين محددين", den: "Everyone else works in Agent Studio; the raw engine stays closed.", dar: "يعمل الجميع في {{brand}}، وتبقى لوحة المحرك مغلقة." },
  ] },
  { id: "runs", icon: "run", en: "Runs by itself", ar: "يعمل من تلقاء نفسه", items: [
    { en: "Chat", ar: "محادثة", den: "Ask it anything within its job.", dar: "اسأله أي شيء ضمن مهمته.", to: "/agents" },
    { en: "On a schedule", ar: "حسب جدول", den: "Every weekday at 7, every Monday, first of the month…", dar: "كل يوم عمل في السابعة، كل اثنين، أول كل شهر…", tech: "cron" },
    { en: "When an alert arrives", ar: "عند وصول تنبيه", den: "Another system calls it and it acts.", dar: "يستدعيه نظام آخر فيتصرف.", tech: "webhook" },
    { en: "Keeps watching", ar: "يراقب باستمرار", den: "Looks again and acts only on what is new or changed.", dar: "ينظر مجدداً ويتصرف فقط على الجديد أو المتغير.", tech: "watch trigger" },
    { en: "Publish, pause, retire, restore", ar: "نشر وإيقاف وأرشفة واستعادة", den: "Versions kept; any earlier version can go live again.", dar: "تُحفظ الإصدارات، ويمكن إعادة أي إصدار سابق.", to: "/agents" },
    { en: "Re-run with the same question", ar: "إعادة التشغيل بالسؤال نفسه", den: "From any run, ask the agent again in one click.", dar: "من أي تشغيل، اسأل الوكيل مجدداً بنقرة.", to: "/executions", isNew: true },
  ] },
  { id: "heal", icon: "trace", en: "Checks and heals itself", ar: "يتحقق ويصلح نفسه", items: [
    { en: "Checks its own work", ar: "يراجع عمله", den: "Plans, acts, checks every goal against tool results, tries once more another way, then answers.", dar: "يخطط وينفذ ويتحقق من كل هدف ثم يحاول بطريقة أخرى قبل الإجابة.", tech: "plan-act-check", isNew: true },
    { en: "Goal check on every run", ar: "فحص الهدف في كل تشغيل", den: "Runs it does by itself are judged; a miss is retried with what was missing.", dar: "تُقيَّم تشغيلاته الذاتية، ويُعاد ما فشل مع ذكر الناقص.", tech: "reflexion", isNew: true },
    { en: "Retries failures with the reason", ar: "يعيد المحاولة مع ذكر السبب", den: "A failed run is tried again, told why it failed, before anyone is alerted.", dar: "يُعاد التشغيل الفاشل مع ذكر السبب قبل تنبيه أحد.", isNew: true },
    { en: "Backup model", ar: "نموذج احتياطي", den: "When the model server is down, agents think with the backup and switch back when it returns.", dar: "عند توقف خادم النموذج، يعمل الوكلاء بالاحتياطي ثم يعودون.", tech: "model failover", isNew: true },
    { en: "Makes up missed runs", ar: "يعوّض التشغيلات الفائتة", den: "A scheduled run that never happened is run once.", dar: "يُشغَّل مرة واحدة أي تشغيل مجدول لم يحدث.", isNew: true },
    { en: "Pauses an agent that keeps failing", ar: "يوقف الوكيل كثير الفشل", den: "After 3 failures in a row its owner is told; never for a model outage.", dar: "بعد 3 إخفاقات متتالية يُبلَّغ مالكه؛ ولا يحدث ذلك بسبب توقف النموذج.", isNew: true },
    { en: "Failure and sign-in alerts", ar: "تنبيهات الفشل وبيانات الدخول", den: "One plain message when a run fails or a saved sign-in stops working.", dar: "رسالة واضحة عند فشل تشغيل أو توقف بيانات دخول." },
    { en: "Health on every agent", ar: "حالة كل وكيل", den: "Working well or needs attention, from its real runs and schedule.", dar: "يعمل جيداً أو يحتاج انتباهاً، من تشغيلاته وجدوله.", to: "/agents" },
  ] },
  { id: "learn", icon: "catalog", en: "Learns", ar: "يتعلم", items: [
    { en: "Corrections apply at once", ar: "التصحيحات فورية", den: "'Not right? Tell it how' changes its instructions right away.", dar: "«ليست صحيحة؟ أخبره كيف» يغيّر تعليماته فوراً.", to: "/agents" },
    { en: "Suggests its own improvements", ar: "يقترح تحسينات بنفسه", den: "A goal still missed after a retry becomes a suggestion; the owner decides.", dar: "الهدف الفائت بعد إعادة المحاولة يصبح اقتراحاً، والمالك يقرر.", isNew: true },
    { en: "Remembers between runs", ar: "يتذكر بين التشغيلات", den: "Keeps short notes about its systems; wrong notes can be removed.", dar: "يحتفظ بملاحظات قصيرة عن أنظمته، ويمكن حذف الخاطئ منها.", tech: "long-term memory", isNew: true },
    { en: "Remembers your chats", ar: "يتذكر محادثاتك", den: "Optional per agent; you can make it forget.", dar: "اختياري لكل وكيل، ويمكنك جعله ينسى.", tech: "memory" },
    { en: "Know-how", ar: "المعرفة المؤسسية", den: "Your organisation's ways of working, approved once and followed by every agent.", dar: "أساليب العمل المعتمدة، يتبعها كل وكيل.", to: "/skills", tech: "skills" },
    { en: "Test questions", ar: "أسئلة اختبار", den: "Save questions with what a good answer contains; run them after every change.", dar: "احفظ أسئلة مع ما يجب أن تتضمنه الإجابة، وشغّلها بعد كل تغيير.", tech: "evaluation set", isNew: true },
  ] },
  { id: "team", icon: "agents", en: "Works with others", ar: "يعمل مع الآخرين", items: [
    { en: "Agents ask other agents", ar: "وكلاء يسألون وكلاء", den: "A coordinator uses other published agents as helpers.", dar: "يستخدم المنسق وكلاء منشورين آخرين كمساعدين.", tech: "multi-agent" },
    { en: "Hands over the whole request", ar: "يسلّم الطلب كاملاً", den: "When a request belongs to another agent, it passes everything over and says who answered.", dar: "عندما يخص الطلب وكيلاً آخر، يسلّمه كاملاً ويذكر من أجاب.", tech: "handoff", isNew: true },
    { en: "Share with everyone", ar: "المشاركة مع الجميع", den: "A share link anyone signed in can chat with; they cannot change the agent.", dar: "رابط مشاركة يستطيع أي مستخدم المحادثة عبره دون تعديل الوكيل.", to: "/shared", isNew: true },
    { en: "Put a chat in another page", ar: "ضع المحادثة في صفحة أخرى", den: "An iframe snippet for internal portals.", dar: "شيفرة iframe للبوابات الداخلية.", tech: "embed", isNew: true },
    { en: "Use agents from other tools", ar: "استخدم الوكلاء من أدوات أخرى", den: "Every published agent is offered over MCP with personal access keys.", dar: "كل وكيل منشور متاح عبر MCP بمفاتيح وصول شخصية.", to: "/agents", tech: "MCP server" },
    { en: "Use other tools' servers", ar: "استخدم خوادم أدوات أخرى", den: "Connect outside MCP servers and give agents their tools.", dar: "اربط خوادم MCP خارجية وامنح أدواتها للوكلاء.", to: "/tools", tech: "MCP client" },
  ] },
  { id: "files", icon: "database", en: "Files and reports", ar: "الملفات والتقارير", items: [
    { en: "Excel and data sets", ar: "Excel ومجموعات البيانات", den: "Collected records saved as tables.", dar: "تُحفظ السجلات المجمعة كجداول.", to: "/files" },
    { en: "Word reports", ar: "تقارير Word", den: "Findings written up as a document.", dar: "تُكتب النتائج في مستند.", to: "/files" },
    { en: "Archives", ar: "ملفات مضغوطة", den: "Bundles of files in one zip.", dar: "حزم ملفات في ملف مضغوط واحد.", to: "/files" },
  ] },
  { id: "oversight", icon: "settings", en: "Oversight and security", ar: "الرقابة والأمان", items: [
    { en: "Every run, step by step", ar: "كل تشغيل خطوة بخطوة", den: "What it asked, which tools it used, what came back, what it answered.", dar: "ماذا سُئل، وأي أدوات استخدم، وماذا عاد، وبماذا أجاب.", to: "/executions", tech: "trace" },
    { en: "AI use per agent", ar: "استخدام الذكاء الاصطناعي لكل وكيل", den: "Runs and model tokens per agent over the last 7 days.", dar: "التشغيلات ورموز النموذج لكل وكيل خلال 7 أيام.", to: "/", tech: "usage", isNew: true },
    { en: "System health", ar: "صحة النظام", den: "Models, systems, channels, app and engine, with re-check.", dar: "النماذج والأنظمة والقنوات والتطبيق والمحرك، مع إعادة الفحص.", to: "/system" },
    { en: "Activity log", ar: "سجل النشاط", den: "Who did what and when, exportable.", dar: "من فعل ماذا ومتى، قابل للتصدير.", to: "/activity", tech: "audit" },
    { en: "Directory sign-in and roles", ar: "الدخول بالدليل والأدوار", den: "Active Directory sign-in; user, builder and administrator roles.", dar: "الدخول عبر Active Directory؛ أدوار مستخدم ومنشئ ومسؤول.", tech: "AD + RBAC" },
    { en: "Your own models, inside your network", ar: "نماذجك داخل شبكتك", den: "Runs on local models; no telemetry, no cloud calls.", dar: "يعمل على نماذج محلية؛ بلا تتبع ولا اتصالات سحابية.", to: "/system", tech: "air-gapped" },
    { en: "Your brand, open source", ar: "علامتك، مفتوح المصدر", den: "Name, logo and colours are settings; Apache-2.0.", dar: "الاسم والشعار والألوان إعدادات؛ رخصة Apache-2.0.", to: "/settings" },
  ] },
];
