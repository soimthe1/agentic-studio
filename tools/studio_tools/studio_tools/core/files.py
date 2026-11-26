"""Each person's file area: everything an agent produces lands in <files.root>/<owner id>/.

The folder is the contract with the Agent Studio app (it mounts the same folder and lists/downloads a person's files),
so agents, sub-agents and people share files by name without the engine's own file store.
"""

from __future__ import annotations

import csv
import datetime as _dt
import io
import json
import re
import sqlite3
import zipfile
from pathlib import Path
from typing import Any

from .config import load_config
from .errors import ConfigError, NotAllowed

DEFAULT_ROOT = "/data/files"
DATA_FORMATS = ("sqlite", "csv", "xlsx", "json")
ARCHIVE_FORMATS = ("zip", "7z")
_SAFE = re.compile(r"[^A-Za-z0-9._ -]+")


def user_dir(owner: Any) -> Path:
    if not owner:
        raise ConfigError("this run has no owner, so it has nowhere to keep files")
    root = Path((load_config().get("files") or {}).get("root") or DEFAULT_ROOT)
    d = root / re.sub(r"[^A-Za-z0-9-]", "", str(owner))
    d.mkdir(parents=True, exist_ok=True)
    return d


def new_path(owner: Any, name: str | None, ext: str) -> Path:
    stem = _SAFE.sub("_", Path(name or "data").stem).strip("_ ")[:80] or "data"
    return user_dir(owner) / f"{stem}-{_dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.{ext}"


def resolve(owner: Any, name: str) -> Path:
    """A file of this owner by name (never a path outside the owner's folder)."""
    p = user_dir(owner) / Path(str(name).strip()).name
    if not p.is_file():
        raise NotAllowed(f"no file named '{name}' in your files")
    return p


def describe(p: Path, **extra) -> dict[str, Any]:
    return {"status": "written", "file": p.name, "format": p.suffix.lstrip("."), "bytes": p.stat().st_size, **extra}


# ------------------------------------------------------------------------------------------- datasets


def _tables(data: Any) -> dict[str, list[dict]]:
    """{"rows": [...]} or {"tables": {"name": [...]}} or a bare list -> {table: rows}."""
    if isinstance(data, list):
        data = {"rows": data}
    if not isinstance(data, dict):
        raise NotAllowed("data must be a JSON object with 'rows' (a list of objects) or 'tables'")
    tables = data.get("tables") or {data.get("table") or "data": data.get("rows")}
    out = {}
    for name, rows in tables.items():
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise NotAllowed(f"table '{name}' must be a list of objects")
        out[re.sub(r"\W", "_", str(name)) or "data"] = rows
    return out


def _columns(rows: list[dict]) -> list[str]:
    cols: list[str] = []
    for r in rows:
        cols += [k for k in r if k not in cols]
    return cols


def _cell(v: Any) -> Any:
    return v if v is None or isinstance(v, (int, float, str)) else json.dumps(v, ensure_ascii=False, default=str)


def save_dataset(owner: Any, data: Any, fmt: str, name: str | None, max_rows: int = 200_000) -> dict[str, Any]:
    fmt = (fmt or "").lower()
    if fmt not in DATA_FORMATS:
        raise NotAllowed(f"format must be one of {DATA_FORMATS}")
    tables = _tables(data)
    total = sum(len(r) for r in tables.values())
    if total > max_rows:
        raise NotAllowed(f"too many rows ({total} > {max_rows})")
    path = new_path(owner, name, fmt)
    if fmt == "sqlite":
        con = sqlite3.connect(path)
        try:
            for t, rows in tables.items():
                cols = _columns(rows)
                q = lambda c: '"' + c.replace('"', '""') + '"'  # noqa: E731
                con.execute(f"CREATE TABLE {q(t)} ({', '.join(q(c) for c in cols)})")
                con.executemany(f"INSERT INTO {q(t)} VALUES ({', '.join('?' for _ in cols)})",
                                [[_cell(r.get(c)) for c in cols] for r in rows])
            con.commit()
        finally:
            con.close()
    elif fmt == "csv":
        if len(tables) > 1:
            raise NotAllowed("csv holds one table; use sqlite or xlsx for several")
        rows = next(iter(tables.values()))
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=_columns(rows), extrasaction="ignore")
        w.writeheader()
        w.writerows({k: _cell(v) for k, v in r.items()} for r in rows)
        path.write_text(buf.getvalue(), encoding="utf-8-sig")
    elif fmt == "xlsx":
        from openpyxl import Workbook

        wb = Workbook()
        wb.remove(wb.active)
        for t, rows in tables.items():
            ws = wb.create_sheet(t[:31])
            cols = _columns(rows)
            ws.append(cols)
            for r in rows:
                ws.append([_cell(r.get(c)) for c in cols])
        wb.save(path)
    else:
        path.write_text(json.dumps(tables if len(tables) > 1 else next(iter(tables.values())), ensure_ascii=False,
                                   indent=1, default=str), encoding="utf-8")
    return describe(path, tables={t: len(r) for t, r in tables.items()})


# ------------------------------------------------------------------------------------------- archives


def archive(owner: Any, names: list[str], fmt: str, name: str | None) -> dict[str, Any]:
    fmt = (fmt or "zip").lower()
    if fmt not in ARCHIVE_FORMATS:
        raise NotAllowed(f"format must be one of {ARCHIVE_FORMATS}")
    files = [resolve(owner, n) for n in names if str(n).strip()]
    if not files:
        raise NotAllowed("name at least one of your files to bundle")
    path = new_path(owner, name or "bundle", fmt)
    if fmt == "zip":
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            for f in files:
                z.write(f, f.name)
    else:
        try:
            import py7zr
        except ImportError:
            raise NotAllowed("7z is not installed in this deployment; use zip") from None
        with py7zr.SevenZipFile(path, "w") as z:
            for f in files:
                z.write(f, f.name)
    return describe(path, contains=[f.name for f in files])
