"""Declared contract of every studio-tools v1 tool (source for the tool catalog and the Tool Advisor).

``approved`` / ``dry_run`` / ``allowed_*`` / ``acting_user`` are flow-level inputs (not tool_mode): the LLM can
never set them. Every tool returns the envelope {ok, data | error{code, message}, source, fetched_at}.
"""

from __future__ import annotations

from .spec import ToolSpec

SQL_READONLY = ToolSpec(
    name="sql_readonly",
    description=(
        "Run ONE read-only SQL query (SELECT or WITH ... SELECT) on an approved, named database connection and "
        "get back a small table. Use :name placeholders with a JSON params object for values; never paste "
        "values into the SQL text. Results are capped (truncated=true when more rows exist)."),
    side_effects="read", timeout_s=30, retry="none (a failed query is reported, not repeated)",
    connection="sql", approval_required=False,
    inputs={"connection": "str (name from tools.yaml sql:)", "sql": "str, single SELECT/WITH",
            "params": "JSON object for :name placeholders", "max_rows": "int <= connection max_rows (hard 10000)"},
    outputs={"data": "{connection, columns, rows: list[obj], row_count, truncated}", "table": "DataFrame"},
)

APP_QUERY = ToolSpec(
    name="app_query",
    description=(
        "Read findings, health, incidents, timelines or reports that an internal monitoring app has ALREADY "
        "computed (SQL Monitor, IIS Monitor, other registered apps). Pick a registered app and one of its "
        "operations; target is the server / instance / IIS node name. Never guess URLs."),
    side_effects="read", timeout_s=20, retry="GET: 1 retry on connection error / 502-504; POST reads: none",
    connection="apps", approval_required=False,
    inputs={"app": "str (registered app)", "operation": "str (per app)", "target": "str? server/instance/node",
            "filters": "JSON object of operation filters", "limit": "int <= 200"},
    outputs={"data": "JSON from the app (lists capped at limit, ~60k chars max)"},
)

APP_ACTION = ToolSpec(
    name="app_action",
    description=(
        "Request a change on a registered system (for example acknowledge a finding). Only registered actions "
        "on one target are possible. It is a dry run unless the flow has a human approval: the result is "
        "'planned', 'pending_approval', 'rejected' or 'done'. Always give a reason."),
    side_effects="write", timeout_s=60, retry="never", connection="apps", approval_required=True,
    inputs={"app": "str", "action": "str (registered)", "target": "str?", "params": "JSON object",
            "reason": "str", "approved": "bool (flow only)", "dry_run": "bool = true (flow only)"},
    outputs={"data": "{status, reason?, plan, result?}"},
)

KNOWLEDGE_SEARCH = ToolSpec(
    name="knowledge_search",
    description=(
        "Search internal documents and runbooks (the knowledge platform) and get passages or a cited answer, "
        "limited to what the requesting user may see. Currently unavailable: returns error code 'unavailable' "
        "until the platform offers delegated (on-behalf-of) access."),
    side_effects="read", timeout_s=60, retry="none (POST)", connection="knowledge", approval_required=False,
    inputs={"query": "str", "mode": "search | answer", "top_k": "int <= 10"},
    outputs={"data": "{results[]} or {answer, citations, max_level_seen, banner}"},
)

NOTIFY = ToolSpec(
    name="notify",
    description=(
        "Send a short notification (subject + body) to a registered channel (email group or internal chat "
        "room). Recipients are fixed by the channel; you only choose the channel name and severity."),
    side_effects="write", timeout_s=15, retry="never (avoids duplicate messages)", connection="notify",
    approval_required=True,  # per channel: requires_approval (default true) can be lifted by the admin
    inputs={"channel": "str", "subject": "str <= 200", "body": "str <= 20000", "severity": "info|warning|critical",
            "approved": "bool (flow only)", "dry_run": "bool = true (flow only)"},
    outputs={"data": "{status: sent|dry_run|not_approved, preview}"},
)

DOCUMENT_CREATE = ToolSpec(
    name="document_create",
    description=(
        "Create a Word (docx) or Excel (xlsx) document from structured data, optionally using a registered "
        "template. data is a JSON object; its 'rows' list (of objects) becomes a table, other keys fill "
        "{{ placeholders }}. PDF is not available."),
    side_effects="write", timeout_s=60, retry="none", connection="documents", approval_required=False,
    inputs={"format": "docx | xlsx", "data": "JSON object", "template": "str? template file name",
            "filename": "str? base name"},
    outputs={"data": "{status, format, path, filename, bytes, rows}"},
)

RECORD_WRITE = ToolSpec(
    name="record_write",
    description=(
        "Create one record (e.g. an incident note or ticket row) in a registered system: an allowlisted SQL "
        "table or a registered app record type. Dry run unless the flow has a human approval."),
    side_effects="write", timeout_s=30, retry="never", connection="sql | apps", approval_required=True,
    inputs={"system": "str (sql connection or app)", "record_type": "str (allowlisted table / record type)",
            "fields": "JSON object column/field -> scalar", "reason": "str",
            "approved": "bool (flow only)", "dry_run": "bool = true (flow only)"},
    outputs={"data": "{status, reason?, plan, rows_inserted? | result?}"},
)

BUNDLE_CHECK = ToolSpec(
    name="bundle_check",
    description="Returns the Agent Studio tools bundle version. Use to verify the bundle is installed and runnable.",
    side_effects="none", timeout_s=1, retry="n/a", connection="", approval_required=False,
    inputs={"input_value": "str"}, outputs={"result": "Message"},
)

SAVE_DATA = ToolSpec(
    name="save_data",
    description=(
        "Save rows of data as a file in the owner's files: sqlite (a database file), csv, xlsx (Excel) or json. "
        "data is {\"rows\": [{...}, ...]} for one table or {\"tables\": {\"name\": [{...}], ...}} for several. "
        "Returns the file name, which other tools (bundle, send) and people can use."),
    side_effects="write", timeout_s=120, retry="none", connection="files", approval_required=False,
    inputs={"format": "sqlite | csv | xlsx | json", "data": "JSON object", "filename": "str? base name"},
    outputs={"data": "{status, file, format, bytes, tables}"},
)

FILES_BUNDLE = ToolSpec(
    name="bundle_files",
    description="Put some of the owner's files into one zip (or 7z where installed) archive. files: names separated by commas.",
    side_effects="write", timeout_s=300, retry="none", connection="files", approval_required=False,
    inputs={"files": "str (comma-separated file names)", "format": "zip | 7z", "filename": "str?"},
    outputs={"data": "{status, file, format, bytes, contains}"},
)

WEB_READ = ToolSpec(
    name="read_web",
    description=(
        "Read a public web address (only where this deployment allows internet access). mode text = readable "
        "page text, links = the page's links, feed = RSS/Atom items or sitemap URLs, json = an API answer, "
        "raw = only save the file. save=true also keeps the downloaded file in the owner's files."),
    side_effects="read", timeout_s=30, retry="none", connection="web", approval_required=False,
    inputs={"url": "str", "mode": "text | links | feed | json | raw", "save": "bool"},
    outputs={"data": "{url, status, content_type, bytes, text | links | items | json, saved_as?}"},
)

ALL = [SQL_READONLY, APP_QUERY, APP_ACTION, KNOWLEDGE_SEARCH, NOTIFY, DOCUMENT_CREATE, RECORD_WRITE, BUNDLE_CHECK,
       SAVE_DATA, FILES_BUNDLE, WEB_READ]

CODE_TOOL = ToolSpec(
    name="code_tool",
    description=("Run one operation of an approved tool that was written for this organisation. Pick the operation "
                 "by name and give its arguments as a JSON object. Operations that change something wait for a "
                 "person's approval."),
    side_effects="write", timeout_s=60, retry="never (a tool's operation is run once per call)", connection="code",
    approval_required=True,
    inputs={"operation": "str (one of the tool's operations)", "arguments": "JSON object", "reason": "str",
            "approved": "bool (flow only)", "dry_run": "bool = true (flow only)"},
    outputs={"data": "{status: done | planned | pending_approval, operation, result}"},
)
