"""Tools written by AI (Python): what a tool's code may do is NOT limited. Safety comes from people, not from blocking:
every risky thing the code does is found and named in plain words (risk report), an administrator reads the code and
the report before anything can use it, and every method that changes something - or that the report finds risky
(shell commands, file writes, deleting, sending data) - needs a person's approval each time an agent calls it.

A tool is one Python file with one class `Tool`; each public method is one operation the agent can call:

    class Tool:
        HOSTS = ["mail.example:993"]          # systems it talks to (shown to the approver)
        SECRETS = ["MAIL_PASSWORD"]           # values typed on the Systems page, kept encrypted; self.secret("...")
        CHANGES = ["move_to_folder"]          # methods that change something (approval on every call)

        def unread(self, folder: str = "INBOX", limit: int = 20) -> list:
            '''List unread e-mails: sender, subject, date.'''

It runs in its own Python process with a time limit (so a hung or crashing tool never takes the engine down).
This file is shared: tools/studio_tools/studio_tools/core/codetool.py is an exact copy (the engine runs the tools;
tests/test_codetool.py keeps the two identical).
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

MAX_OUT = 60_000
# Libraries people brought (air-gapped: no internet): <toolkit>/wheels holds the .whl files they copied in,
# <toolkit>/site what Agent Studio installed from them. Survives engine image updates (mounted folder).
TOOLKIT = Path(os.environ.get("STUDIO_TOOLKIT_DIR", "/data/toolkit"))
# import name -> package name, where they differ (for "bring this library" guidance)
PACKAGE_OF = {"fitz": "PyMuPDF", "docx": "python-docx", "pptx": "python-pptx", "yaml": "PyYAML", "PIL": "Pillow",
              "bs4": "beautifulsoup4", "cv2": "opencv-python-headless", "sklearn": "scikit-learn", "dateutil": "python-dateutil",
              "winrm": "pywinrm", "smbclient": "smbprotocol", "ldap3": "ldap3", "Crypto": "pycryptodome", "magic": "python-magic",
              "jwt": "PyJWT", "dns": "dnspython", "serial": "pyserial", "usb": "pyusb", "OpenSSL": "pyOpenSSL", "googleapiclient": "google-api-python-client"}

# What the risk report looks for: (kind, level, plain words). Never a block - the approver decides.
_CALLS = {
    "os.system": ("shell", "high", "runs operating-system commands"), "os.popen": ("shell", "high", "runs operating-system commands"),
    "subprocess.run": ("shell", "high", "runs programs or shell commands"), "subprocess.Popen": ("shell", "high", "runs programs or shell commands"),
    "subprocess.call": ("shell", "high", "runs programs or shell commands"), "subprocess.check_output": ("shell", "high", "runs programs or shell commands"),
    "subprocess.check_call": ("shell", "high", "runs programs or shell commands"),
    "os.remove": ("delete", "high", "deletes files"), "os.unlink": ("delete", "high", "deletes files"), "os.rmdir": ("delete", "high", "deletes folders"),
    "shutil.rmtree": ("delete", "high", "deletes whole folders"), "shutil.move": ("files", "medium", "moves files"),
    "shutil.copy": ("files", "medium", "copies files"), "os.rename": ("files", "medium", "renames files"),
    "eval": ("dynamic", "high", "runs code built at run time (eval)"), "exec": ("dynamic", "high", "runs code built at run time (exec)"),
    "compile": ("dynamic", "medium", "compiles code at run time"), "__import__": ("dynamic", "medium", "loads modules by name at run time"),
    "smtplib.SMTP": ("send", "medium", "sends e-mail"), "smtplib.SMTP_SSL": ("send", "medium", "sends e-mail"),
    "os.environ.get": ("env", "medium", "reads the server's environment variables (may include secrets)"),
    "os.getenv": ("env", "medium", "reads the server's environment variables (may include secrets)"),
}
_METHOD_WORDS = {   # http client methods that send or change data
    "post": ("send", "medium", "sends data to another system (POST)"), "put": ("send", "medium", "changes data on another system (PUT)"),
    "patch": ("send", "medium", "changes data on another system (PATCH)"), "delete": ("delete", "high", "deletes data on another system (DELETE)"),
}
_IMPORTS = {"ctypes": "loads native code (ctypes)", "pickle": "reads pickled objects (can run code)", "socket": "opens raw network connections",
            "winrm": "runs commands on Windows servers remotely", "pypsrp": "runs PowerShell on Windows servers remotely",
            "paramiko": "runs commands on servers over SSH", "ftplib": "transfers files (FTP)"}
_RISKY_KINDS = {"shell", "delete", "dynamic", "send", "files", "write"}


def _dotted(node: ast.AST) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _literal_list(cls: ast.ClassDef, name: str) -> list[str]:
    for st in cls.body:
        if isinstance(st, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in st.targets):
            try:
                value = ast.literal_eval(st.value)
            except ValueError:
                return []
            return [str(v) for v in value] if isinstance(value, (list, tuple, set)) else []
    return []


def _risks_in(node: ast.AST) -> list[dict]:
    out = []
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            name = _dotted(n.func)
            hit = _CALLS.get(name) or _CALLS.get(name.split(".", 1)[-1] if name.count(".") > 1 else "")
            if not hit and isinstance(n.func, ast.Attribute) and n.func.attr in _METHOD_WORDS and name.split(".")[0] in ("httpx", "requests", "client", "c", "session", "s", "http"):
                hit = _METHOD_WORDS[n.func.attr]
            if not hit and name in ("open", "io.open") and len(n.args) > 1 and isinstance(n.args[1], ast.Constant) and any(m in str(n.args[1].value) for m in "wax+"):
                hit = ("write", "medium", "writes files on the server")
            if not hit and name.endswith(("write_text", "write_bytes", "unlink", "mkdir")):
                hit = ("delete" if name.endswith("unlink") else "write", "high" if name.endswith("unlink") else "medium",
                       "deletes files" if name.endswith("unlink") else "writes files on the server")
            texts = [c.value.lower() for c in ast.walk(n) if isinstance(c, ast.Constant) and isinstance(c.value, str)]
            if hit and hit[0] == "shell" and any("powershell" in s or "pwsh" in s for s in texts):
                hit = ("shell", "high", "runs PowerShell commands")
            if hit:
                out.append({"kind": hit[0], "level": hit[1], "text": hit[2], "line": n.lineno})
    return out


def inspect_code(code: str) -> dict:
    """The tool's operations, declared hosts/secrets/changes and a plain risk report. ok=False only when the file is
    not a valid tool at all (syntax error, no class Tool, no documented method) - never because of what it does."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return {"ok": False, "error": f"The code does not parse: {exc.msg} (line {exc.lineno})."}
    cls = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Tool"), None)
    if cls is None:
        return {"ok": False, "error": "The code needs one class named Tool."}
    declared = set(_literal_list(cls, "CHANGES"))
    risks: list[dict] = []
    for n in ast.walk(tree):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            for alias in (n.names if isinstance(n, ast.Import) else [ast.alias(name=n.module or "")]):
                root = alias.name.split(".")[0]
                if root in _IMPORTS:
                    risks.append({"kind": "import", "level": "high" if root in ("ctypes", "pickle", "winrm", "pypsrp", "paramiko") else "medium",
                                  "text": _IMPORTS[root], "line": n.lineno})
    methods = []
    for fn in cls.body:
        if not isinstance(fn, ast.FunctionDef) or fn.name.startswith("_"):
            continue
        found = _risks_in(fn)
        risks += [{**r, "method": fn.name} for r in found]
        args = [a.arg for a in fn.args.args[1:]]
        defaults = len(fn.args.defaults)
        methods.append({"name": fn.name, "args": args, "required": args[:len(args) - defaults] if defaults else args,
                        "doc": (ast.get_docstring(fn) or "").strip().splitlines()[0][:200] if ast.get_docstring(fn) else "",
                        # approval on every call: declared as a change, or the report found something risky in it
                        "change": fn.name in declared or any(r["kind"] in _RISKY_KINDS for r in found)})
    init = next((f for f in cls.body if isinstance(f, ast.FunctionDef) and f.name == "__init__"), None)
    if init and len(init.args.args) - 1 > len(init.args.defaults):
        return {"ok": False, "error": "Tool() must work without arguments: use self.user, self.files_dir and "
                                      "self.secret(...) instead of constructor arguments."}
    if not methods:
        return {"ok": False, "error": "The Tool class needs at least one public method (one per operation)."}
    if any(not m["doc"] for m in methods):
        return {"ok": False, "error": "Every method needs a one-line docstring saying what it does (the agent reads it)."}
    risks += [{"kind": "module", "level": r["level"], "text": r["text"], "line": r["line"]}
              for r in _risks_in(ast.Module(body=[n for n in tree.body if n is not cls], type_ignores=[]))]
    level = "high" if any(r["level"] == "high" for r in risks) else "medium" if risks else "low"
    return {"ok": True, "methods": methods, "hosts": _literal_list(cls, "HOSTS"), "secrets": _literal_list(cls, "SECRETS"),
            "risks": sorted(risks, key=lambda r: (r["level"] != "high", r["line"])), "level": level}


def missing_imports(code: str) -> list[dict]:
    """Top-level modules the code imports that are not installed here (bundled or brought): [{module, package}]."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    roots = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            roots |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
            roots.add(n.module.split(".")[0])
    site = str(TOOLKIT / "site")
    if (TOOLKIT / "site").is_dir() and site not in sys.path:
        sys.path.append(site)
    gone = []
    for r in sorted(roots):
        try:
            found = importlib.util.find_spec(r) is not None
        except (ImportError, ValueError):
            found = False
        if not found:
            gone.append({"module": r, "package": PACKAGE_OF.get(r, r)})
    return gone


def bring_steps(packages: list[str], python: str = "3.12") -> str:
    """Exact steps to bring libraries into an air-gapped server (shown to the person)."""
    names = " ".join(packages)
    return (f"Missing: {', '.join(packages)}. On any PC with internet run:\n"
            f"  pip download {names} --only-binary=:all: --platform manylinux2014_x86_64 --python-version {python} -d agent-studio-wheels\n"
            "Copy every file from the agent-studio-wheels folder into data/toolkit/wheels on the Agent Studio server, then press "
            "'Install' on the Systems page (Libraries). Nothing is downloaded: Agent Studio installs only from those files. "
            "A library that is plain Python can also be copied as a folder (or unzipped) straight into data/toolkit/site.")


_RUNNER = r"""
import json, sys, traceback
job = json.loads(sys.stdin.read())
sys.path[:0] = job.get("paths") or []
scope = {"__name__": "studio_tool"}
try:
    exec(compile(job["code"], "tool.py", "exec"), scope)
    tool = scope["Tool"]()
    tool.user = job.get("user") or ""            # the person the agent works for (may be empty)
    tool.files_dir = job.get("files_dir") or ""  # that person's own files folder (read and write their files here)
    secrets = job.get("secrets") or {}
    tool.secret = lambda name: secrets[name] if name in secrets else (_ for _ in ()).throw(KeyError(f"no value saved for {name}"))
    result = getattr(tool, job["method"])(**(job.get("args") or {}))
    out = {"ok": True, "result": result}
except Exception as exc:
    out = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-1500:]}
sys.stdout.write("\n@@STUDIO-RESULT@@" + json.dumps(out, default=str))
"""


def run(code: str, method: str, args: dict | None = None, secrets: dict | None = None, timeout: float = 60,
        python: str | None = None, user: str = "", files_dir: str = "") -> dict:
    """Run one method of a tool in its own Python process (time limit; its own crash or hang stays there)."""
    info = inspect_code(code)
    if not info["ok"]:
        return {"ok": False, "error": info["error"]}
    if method not in {m["name"] for m in info["methods"]}:
        return {"ok": False, "error": f"The tool has no operation '{method}'."}
    paths = [str(TOOLKIT / "site")] if (TOOLKIT / "site").is_dir() else []
    job = json.dumps({"code": code, "method": method, "args": args or {}, "secrets": secrets or {}, "paths": paths,
                      "user": user, "files_dir": files_dir}, default=str)
    try:
        p = subprocess.run([python or sys.executable, "-I", "-c", _RUNNER], input=job, capture_output=True, text=True,
                           timeout=timeout, encoding="utf-8")
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"The tool did not finish within {int(timeout)} s and was stopped."}
    printed, _, tail = p.stdout.rpartition("\n@@STUDIO-RESULT@@")
    try:
        out = json.loads(tail)
    except ValueError:
        return {"ok": False, "error": "The tool stopped without a result.", "trace": (p.stderr or p.stdout)[-1500:]}
    text = json.dumps(out.get("result"), default=str) if out.get("ok") else ""
    if len(text) > MAX_OUT:
        out["result"], out["truncated"] = text[:MAX_OUT], True
    if printed.strip():
        out["printed"] = printed.strip()[-2000:]
    return out


if __name__ == "__main__":
    demo = '''
import subprocess
class Tool:
    HOSTS = ["mail:993"]
    SECRETS = ["PW"]
    CHANGES = ["archive"]
    def count(self, n: int = 2) -> list:
        """Count to n."""
        return list(range(n))
    def shell(self, cmd: str) -> str:
        """Run a command."""
        return subprocess.run(["pwsh", "-c", cmd], capture_output=True, text=True).stdout
    def archive(self, uid: str) -> str:
        """Archive one mail."""
        return self.secret("PW")[:0] + uid
'''
    i = inspect_code(demo)
    assert i["ok"] and i["level"] == "high" and i["hosts"] == ["mail:993"] and i["secrets"] == ["PW"]
    by = {m["name"]: m for m in i["methods"]}
    assert not by["count"]["change"] and by["shell"]["change"] and by["archive"]["change"]
    assert any(r["text"] == "runs PowerShell commands" for r in i["risks"])
    assert run(demo, "count", {"n": 3}) == {"ok": True, "result": [0, 1, 2]}
    assert run(demo, "archive", {"uid": "7"}, {"PW": "x"})["result"] == "7"
    assert "no value saved" in run(demo, "archive", {"uid": "7"})["error"]
    assert not inspect_code("x = 1")["ok"] and not inspect_code("def f(:")["ok"]
    bad_init = "class Tool:\n    def __init__(self, owner):\n        pass\n    def a(self):\n        '''A.'''\n"
    assert "without arguments" in inspect_code(bad_init)["error"]
    who = "class Tool:\n    def who(self):\n        '''Who.'''\n        return [self.user, self.files_dir]"
    assert run(who, "who", user="u1", files_dir="/f/u1")["result"] == ["u1", "/f/u1"]
    gone = missing_imports("import json, surely_not_a_module_x\nfrom fitz import open")
    assert {"module": "surely_not_a_module_x", "package": "surely_not_a_module_x"} in gone and all(g["module"] != "json" for g in gone)
    assert all(g["package"] == "PyMuPDF" for g in gone if g["module"] == "fitz")
    assert "pip download PyMuPDF" in bring_steps(["PyMuPDF"])
    assert "within 1 s" in run("import time\nclass Tool:\n    def wait(self):\n        '''Wait.'''\n        time.sleep(5)", "wait", timeout=1)["error"]
    print("codetool ok")
