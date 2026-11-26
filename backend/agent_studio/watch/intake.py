"""Intake watchkeeper: the exact details a person wrote are read without AI, so the plan cannot lose them.

Facts: named servers/instances (WEB02, SQLPROD01, INTDB, web01.example.org), times ("7am", "07:30"), file formats
(SQLite, CSV, Excel, JSON, zip, 7z, Word), web addresses, e-mail addresses, notification channels by name.
After the designer has planned, check() compares: every fact must show up in the plan (as a capability, in the
instructions or in a question). Lost facts are put back deterministically where possible and always reported.
"""

from __future__ import annotations

import re

HOST = re.compile(r"\b(?=[A-Z0-9_-]*\d)(?=[A-Z0-9_-]*[A-Z])[A-Z][A-Z0-9_-]{2,}\b|\b[a-z0-9-]+(?:\.[a-z0-9-]+){1,}\.(?:local|lan|internal|ae|com|net|org|mil)\b")
NAMED_UPPER = re.compile(r"\b[A-Z]{4,}\d*\b")           # INTDB, SQLPROD (all-caps names people use for systems)
TIME = re.compile(r"\b(?:[01]?\d|2[0-3])(?::[0-5]\d)?\s?(?:am|pm)\b|\b(?:[01]?\d|2[0-3]):[0-5]\d\b", re.I)
URL = re.compile(r"https?://[^\s,;)>\]]+", re.I)
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
FORMATS = {
    "sqlite": ("save_data", r"\bsqlite\b|قاعدة بيانات sqlite"), "csv": ("save_data", r"\bcsv\b"),
    "excel": ("save_data", r"\bexcel\b|\bxlsx\b|إكسل"), "json": ("save_data", r"\bjson\b"),
    "zip": ("bundle_files", r"\bzip\b|\barchive\b|أرشيف"), "7z": ("bundle_files", r"\b7z\b|\b7-zip\b"),
    "word": ("document", r"\bword\b|\bdocx\b|وورد"),
}
COMMON_UPPER = {"SQL", "IIS", "API", "HTTP", "HTTPS", "JSON", "CSV", "PDF", "AD", "UTC", "AM", "PM", "Agent Studio", "ZIP", "OK", "STATUS",
                "EXCEL", "WORD", "SQLITE", "RSS", "URL", "LLM", "AI"}

FILLER = re.compile(r"^\s*(?:hi|hello|hey|dear\s+\w+|please|kindly|can you|could you|i want you to|i would like you to)[,\s]+", re.I)


def clean(text: str) -> str:
    """Remove greeting noise at the start and repeated spaces; the meaning is never changed."""
    out = (text or "").strip()
    while True:
        new = FILLER.sub("", out, count=1)
        if new == out:
            break
        out = new
    return re.sub(r"[ \t]+", " ", out).strip() or (text or "").strip()


def facts(text: str, channels: list[str] | None = None) -> dict:
    hosts = {h for h in HOST.findall(text or "")} | {u for u in NAMED_UPPER.findall(text or "")}
    hosts = sorted(h for h in hosts if h.upper() not in COMMON_UPPER)
    low = (text or "").lower()
    return {
        "targets": hosts,
        "times": sorted(set(TIME.findall(text or ""))),
        "formats": sorted(f for f, (_, rx) in FORMATS.items() if re.search(rx, low)),
        "urls": sorted(set(URL.findall(text or ""))),
        "emails": sorted(set(EMAIL.findall(text or ""))),
        # a channel id as people write it: ops_chat = "ops_chat", "ops chat", "ops-chat", "opschat"
        "channels": sorted(c for c in channels or []
                           if re.search(r"\b" + r"[ _-]?".join(map(re.escape, re.split(r"[_\-\s]+", c.lower()))) + r"\b", low)),
    }


_DOW = {"sunday": 0, "monday": 1, "tuesday": 2, "wednesday": 3, "thursday": 4, "friday": 5, "saturday": 6}


def schedule_from(text: str) -> tuple[str, str] | None:
    """Common timing phrases -> (cron, the person's phrase). None when the text names no clear schedule."""
    low = (text or "").lower()
    hour, minute = None, 0
    m = re.search(r"\b(?:at\s+)?([01]?\d|2[0-3])(?::([0-5]\d))?\s?(am|pm)\b", low) or re.search(r"\bat\s+([01]?\d|2[0-3]):([0-5]\d)\b", low)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2) or 0)
        if len(m.groups()) > 2 and m.group(3) == "pm" and hour < 12:
            hour += 12
        if len(m.groups()) > 2 and m.group(3) == "am" and hour == 12:
            hour = 0
    if re.search(r"\bevery hour\b|\bhourly\b", low):
        return f"{minute} * * * *", "every hour"
    if re.search(r"first day of (every|each|the) month|\bmonthly\b|every month", low):
        return f"{minute} {hour if hour is not None else 0} 1 * *", "on the first day of every month"
    day = next((d for d in _DOW if re.search(rf"\b(every|on|each)\s+{d}s?\b", low)), None)
    if day:
        return f"{minute} {hour if hour is not None else 8} * * {_DOW[day]}", f"every {day.title()}"
    if re.search(r"every (morning|day|evening|night)|\bdaily\b|each (morning|day)", low):
        default = 8 if "morning" in low else 18 if "evening" in low else 22 if "night" in low else 8
        return f"{minute} {hour if hour is not None else default} * * *", "every day" + (f" at {hour:02d}:{minute:02d}" if hour is not None else "")
    return None


def check(plan: dict, prefs: dict, found: dict, said: str = "") -> tuple[dict, dict, list[dict]]:
    """Make the plan keep every exact detail. Returns (plan, prefs, findings)."""
    findings: list[dict] = []
    caps = list(prefs.get("capabilities") or [])
    text = " ".join([plan.get("instructions") or "", plan.get("understood") or "", " ".join(plan.get("goals") or []),
                     " ".join(q["text"] + " " + " ".join(q["options"]) for q in plan.get("questions") or [])]).lower()
    for fmt in found.get("formats", []):
        cap = FORMATS[fmt][0]
        if cap not in caps:
            caps.append(cap)
            findings.append({"level": "info", "text": f"You asked for {fmt}: added '{cap.replace('_', ' ')}' so the file is really made."})
        if fmt not in text:
            plan["instructions"] = (plan.get("instructions") or "") + f"\nThe person asked for {fmt} output: produce exactly that format."
    lost = [t for t in found.get("targets", []) if t.lower() not in text]
    if lost:
        plan["instructions"] = (plan.get("instructions") or "") + "\nWork on exactly these, as the person named them: " + ", ".join(lost) + "."
        findings.append({"level": "info", "text": "Kept the names you gave: " + ", ".join(lost) + "."})
    if found.get("urls") and "web_read" not in caps:
        caps.append("web_read")
        findings.append({"level": "info", "text": "You gave web addresses: added reading the web."})
    for url in found.get("urls", []):
        if url.lower() not in text:
            plan["instructions"] = (plan.get("instructions") or "") + f"\nUse this address: {url}"
    if found.get("channels"):
        prefs["channel"] = prefs.get("channel") or found["channels"][0]
    timing = schedule_from(said)
    if timing and (prefs.get("trigger") not in ("schedule", "watch") or not prefs.get("cron")):
        kind = "watch" if prefs.get("trigger") == "watch" else "schedule"   # "keep watching every 10 minutes"
        plan["trigger"], plan["cron"], plan["schedule_text"] = kind, timing[0], timing[1]
        prefs.update(trigger=kind, cron=timing[0], schedule_text=timing[1])
        plan["suggestions"] = [x for x in plan.get("suggestions") or [] if "schedule" not in x.lower()]
        findings.append({"level": "info", "text": f"You said when it should run: set to {timing[1]} ({timing[0]})."})
    prefs["capabilities"] = caps
    return plan, prefs, findings


if __name__ == "__main__":
    f = facts("Hi, please check WEB02 and SQLPROD01 every day at 7am and give me a SQLite file plus a zip; post to ops_chat",
              ["ops_chat"])
    assert f["targets"] == ["SQLPROD01", "WEB02"] and f["times"] == ["7am"] and f["formats"] == ["sqlite", "zip"], f
    assert f["channels"] == ["ops_chat"]
    for said in ("tell me in the ops chat", "post to Ops-Chat", "send it to opschat"):
        assert facts(said, ["ops_chat"])["channels"] == ["ops_chat"], said
    assert facts("tell the operations team", ["ops_chat"])["channels"] == []
    assert clean("Hi, please check WEB02") == "check WEB02"
    assert schedule_from("every morning at 7am check WEB02") == ("0 7 * * *", "every day at 07:00")
    assert schedule_from("on the first day of every month collect") == ("0 0 1 * *", "on the first day of every month")
    assert schedule_from("every Monday at 9:30am") == ("30 9 * * 1", "every Monday")
    assert schedule_from("tell me how SQL is doing when I ask") is None
    p, pr, fi = check({"instructions": "check health", "goals": []}, {"capabilities": ["iis_health"], "trigger": "chat"}, f)
    assert "save_data" in pr["capabilities"] and "bundle_files" in pr["capabilities"] and "WEB02" in p["instructions"]
    print("intake ok")
