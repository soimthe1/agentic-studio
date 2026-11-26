"""DOCX / XLSX generation from an admin-provided template + data, written into the configured output folder.

PDF is not offered: the engine image has no pure-python PDF *writer* (pypdf can only read/merge existing PDFs).
Templates use Jinja2 placeholders (``{{ name }}``) rendered in a sandbox; a paragraph or cell whose whole text is
``[[rows]]`` marks where the ``rows`` table goes (otherwise it is appended).
"""

from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path
from typing import Any

from .errors import ConfigError, NotAllowed

FORMATS = ("docx", "xlsx")
ROWS_MARKER = "[[rows]]"
_SAFE_NAME = re.compile(r"[^A-Za-z0-9_\-]+")
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _env():
    from jinja2.sandbox import SandboxedEnvironment

    return SandboxedEnvironment(autoescape=False)


def _render(env, text: str, data: dict[str, Any]) -> str:
    if "{{" not in text and "{%" not in text:
        return text
    try:
        return env.from_string(text).render(**data)
    except Exception as exc:  # jinja TemplateError / SecurityError
        raise NotAllowed(f"template placeholder error: {type(exc).__name__}: {exc}") from None


def _dirs(cfg: dict[str, Any]) -> tuple[Path, Path | None]:
    out = cfg.get("output_dir")
    if not out:
        raise ConfigError("documents.output_dir is not configured in tools.yaml")
    tdir = cfg.get("template_dir")
    return Path(out), (Path(tdir) if tdir else None)


def _template(tdir: Path | None, name: str | None, fmt: str) -> Path | None:
    if not name:
        return None
    if tdir is None:
        raise ConfigError("documents.template_dir is not configured in tools.yaml")
    if Path(name).name != name or name.startswith("."):
        raise NotAllowed("template must be a plain file name from the template folder")
    allowed = {p.name for p in tdir.glob(f"*.{fmt}")} if tdir.is_dir() else set()
    if name not in allowed:
        raise NotAllowed(f"template '{name}' not found (available {fmt} templates: {', '.join(sorted(allowed)) or 'none'})")
    return tdir / name


def _out_path(out_dir: Path, filename: str | None, fmt: str) -> Path:
    stem = _SAFE_NAME.sub("_", Path(filename or "document").stem).strip("_")[:80] or "document"
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{stem}-{stamp}.{fmt}"


def _rows(data: dict[str, Any], max_rows: int) -> tuple[list[str], list[list[Any]]]:
    rows = data.get("rows") or []
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise NotAllowed("'rows' must be a list of objects")
    if len(rows) > max_rows:
        raise NotAllowed(f"too many rows ({len(rows)} > {max_rows})")
    cols: list[str] = []
    for r in rows:
        cols += [str(c) for c in r if str(c) not in cols]
    return cols, [[r.get(c) for c in cols] for r in rows]


def generate(cfg: dict[str, Any], *, fmt: str, data: dict[str, Any], template: str | None = None,
             filename: str | None = None) -> dict[str, Any]:
    fmt = (fmt or "").lower()
    if fmt == "pdf":
        raise NotAllowed("PDF output is not available in v1 (no pure-python PDF writer in the engine image); "
                         "use docx or xlsx")
    if fmt not in FORMATS:
        raise NotAllowed(f"format must be one of {FORMATS}")
    if not isinstance(data, dict):
        raise NotAllowed("data must be a JSON object")
    out_dir, tdir = _dirs(cfg)
    tpl = _template(tdir, template, fmt)
    cols, rows = _rows(data, int(cfg.get("max_rows", 5000)))
    scalars = {k: v for k, v in data.items() if k != "rows"}
    path = _out_path(out_dir, filename, fmt)
    (_docx if fmt == "docx" else _xlsx)(tpl, path, data, scalars, cols, rows)
    return {"status": "written", "format": fmt, "path": str(path), "filename": path.name,
            "bytes": path.stat().st_size, "rows": len(rows)}


# ------------------------------------------------------------------------------------------------- DOCX


def _docx(tpl, path, data, scalars, cols, rows) -> None:
    import docx

    env = _env()
    doc = docx.Document(str(tpl)) if tpl else docx.Document()
    marker = None
    if tpl:
        for p in _all_paragraphs(doc):
            if p.text.strip() == ROWS_MARKER:
                marker = p
                continue
            new = _render(env, p.text, data)
            if new != p.text and p.runs:
                p.runs[0].text = new
                for r in p.runs[1:]:
                    r.text = ""
    else:
        doc.add_heading(str(scalars.get("title", "Report")), level=1)
        for k, v in scalars.items():
            if k != "title":
                doc.add_paragraph(f"{k}: {v}")
    if cols:
        table = doc.add_table(rows=1, cols=len(cols))
        try:
            table.style = "Table Grid"
        except Exception:  # template without that style
            pass
        for i, c in enumerate(cols):
            table.rows[0].cells[i].text = c
        for r in rows:
            cells = table.add_row().cells
            for i, v in enumerate(r):
                cells[i].text = "" if v is None else str(v)
        if marker is not None:
            marker._p.addnext(table._tbl)
            marker._p.getparent().remove(marker._p)
    doc.save(str(path))


def _all_paragraphs(doc):
    yield from doc.paragraphs
    for t in doc.tables:
        for row in t.rows:
            for cell in row.cells:
                yield from cell.paragraphs
    for s in doc.sections:
        for part in (s.header, s.footer):
            yield from part.paragraphs


# ------------------------------------------------------------------------------------------------- XLSX


def _safe_cell(cell, value: Any) -> None:
    """Data from the LLM must never become a formula (CSV/XLSX formula injection)."""
    if isinstance(value, (dict, list)):
        value = str(value)
    cell.value = value
    if isinstance(value, str) and value.startswith(_FORMULA_START):
        cell.data_type = "s"


def _xlsx(tpl, path, data, scalars, cols, rows) -> None:
    import openpyxl

    env = _env()
    wb = openpyxl.load_workbook(str(tpl)) if tpl else openpyxl.Workbook()
    start = None
    if tpl:
        for ws in wb.worksheets:
            for row in ws.iter_rows():
                for cell in row:
                    if isinstance(cell.value, str):
                        if cell.value.strip() == ROWS_MARKER:
                            start = (ws, cell.row, cell.column)
                            cell.value = None
                        elif "{{" in cell.value or "{%" in cell.value:
                            _safe_cell(cell, _render(env, cell.value, data))
        ws = wb.active
    else:
        ws = wb.active
        ws.title = "Data" if cols else "Summary"
        if cols and scalars:
            summary = wb.create_sheet("Summary")
        else:
            summary = ws
        for k, v in scalars.items():
            r = summary.max_row + 1 if summary.max_row > 1 or summary["A1"].value else 1
            _safe_cell(summary.cell(row=r, column=1), str(k))
            _safe_cell(summary.cell(row=r, column=2), v)
    if cols:
        if start is None:
            r0 = ws.max_row + 2 if (tpl or not cols) and ws.max_row > 1 else 1
            start = (ws, r0, 1)
        ws, r0, c0 = start
        for i, c in enumerate(cols):
            _safe_cell(ws.cell(row=r0, column=c0 + i), c)
        for j, rv in enumerate(rows, start=1):
            for i, v in enumerate(rv):
                _safe_cell(ws.cell(row=r0 + j, column=c0 + i), v)
    wb.save(str(path))
