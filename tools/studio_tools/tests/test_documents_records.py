import sqlite3

import pytest

from studio_tools.core.documents import generate
from studio_tools.core.errors import NotAllowed
from studio_tools.core.records import write_record

ROWS = [{"server": "WEB01", "cpu": 91}, {"server": "WEB02", "cpu": 40}]


@pytest.fixture
def docs(tmp_path):
    tdir = tmp_path / "templates"
    tdir.mkdir()
    return {"output_dir": str(tmp_path / "out"), "template_dir": str(tdir), "max_rows": 100}


def test_docx_without_template(docs):
    import docx

    out = generate(docs, fmt="docx", data={"title": "Weekly", "period": "W45", "rows": ROWS}, filename="../../evil")
    assert out["filename"].startswith("evil-") and out["filename"].endswith(".docx")
    d = docx.Document(out["path"])
    assert d.paragraphs[0].text == "Weekly"
    assert d.tables[0].rows[1].cells[0].text == "WEB01"


def test_docx_template_placeholders_and_rows_marker(docs, tmp_path):
    import docx

    t = docx.Document()
    t.add_paragraph("Report for {{ period }}")
    t.add_paragraph("[[rows]]")
    t.add_paragraph("End")
    t.save(str(tmp_path / "templates" / "weekly.docx"))
    out = generate(docs, fmt="docx", data={"period": "W45", "rows": ROWS}, template="weekly.docx")
    d = docx.Document(out["path"])
    assert [p.text for p in d.paragraphs] == ["Report for W45", "End"]
    assert len(d.tables) == 1 and d.tables[0].rows[2].cells[1].text == "40"


def test_template_must_be_registered(docs):
    with pytest.raises(NotAllowed):
        generate(docs, fmt="docx", data={}, template="../secret.docx")
    with pytest.raises(NotAllowed, match="not found"):
        generate(docs, fmt="docx", data={}, template="missing.docx")


def test_template_sandbox(docs, tmp_path):
    import docx

    t = docx.Document()
    t.add_paragraph("{{ ''.__class__.__mro__[1].__subclasses__() }}")
    t.save(str(tmp_path / "templates" / "evil.docx"))
    with pytest.raises(NotAllowed, match="placeholder error"):
        generate(docs, fmt="docx", data={}, template="evil.docx")


def test_xlsx_and_formula_injection(docs):
    import openpyxl

    out = generate(docs, fmt="xlsx", data={"title": "=HYPERLINK(\"http://x\")",
                                           "rows": [{"a": "=1+1", "b": 2}, {"a": "@SUM(A1)", "b": 3}]})
    wb = openpyxl.load_workbook(out["path"])
    data = wb["Data"]
    assert data["A2"].value == "=1+1" and data["A2"].data_type == "s"
    assert data["A3"].data_type == "s" and data["B3"].value == 3
    assert wb["Summary"]["B1"].data_type == "s"


def test_pdf_and_bad_inputs(docs):
    with pytest.raises(NotAllowed, match="PDF"):
        generate(docs, fmt="pdf", data={})
    with pytest.raises(NotAllowed, match="too many rows"):
        generate(docs, fmt="xlsx", data={"rows": [{"a": i} for i in range(101)]})


# ---------------------------------------------------------------------------------------------- record_write

@pytest.fixture
def notes(tmp_path, write_cfg):
    path = tmp_path / "ops.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE incident_notes (server TEXT, note TEXT, created_by TEXT)")
    con.commit()
    con.close()
    write_cfg({"sql": {
        "ops": {"dialect": "sqlite", "database": str(path), "allow_write": True,
                "writable_tables": {"incident_notes": {"columns": ["server", "note"]}}},
        "ro": {"dialect": "sqlite", "database": str(path), "writable_tables": ["incident_notes"]},
    }})

    def count():
        c = sqlite3.connect(path)
        try:
            return c.execute("SELECT count(*) FROM incident_notes").fetchone()[0]
        finally:
            c.close()
    return count


REC = {"server": "WEB01", "note": "pool recycled"}


def test_record_write_dry_run_default_then_pending_then_done(notes):
    out = write_record("ops", "incident_notes", REC, approved=False, dry_run=True)
    assert out["status"] == "planned" and notes() == 0
    assert out["plan"]["sql"] == "INSERT INTO incident_notes (server, note) VALUES (:p0, :p1)"
    assert write_record("ops", "incident_notes", REC, approved=False, dry_run=False)["status"] == "pending_approval"
    assert notes() == 0
    done = write_record("ops", "incident_notes", REC, approved=True, dry_run=False)
    assert done["status"] == "done" and done["rows_inserted"] == 1 and notes() == 1


def test_record_write_requires_write_enabled_connection(notes):
    out = write_record("ro", "incident_notes", REC, approved=True, dry_run=False)
    assert out["status"] == "rejected" and notes() == 0


def test_record_write_allowlists(notes):
    with pytest.raises(NotAllowed, match="write allowlist"):
        write_record("ops", "users", REC, approved=True, dry_run=False)
    with pytest.raises(NotAllowed, match="not allowed for table"):
        write_record("ops", "incident_notes", {**REC, "created_by": "x"}, approved=True, dry_run=False)
    with pytest.raises(NotAllowed, match="invalid column"):
        write_record("ops", "incident_notes", {"note) VALUES ('x'); --": "y"}, approved=True, dry_run=False)
    with pytest.raises(NotAllowed, match="not a registered record system"):
        write_record("elsewhere", "incident_notes", REC, approved=True, dry_run=False)
    assert notes() == 0


def test_record_write_value_injection_is_bound(notes):
    evil = {"server": "WEB01'); DROP TABLE incident_notes; --", "note": "x"}
    write_record("ops", "incident_notes", evil, approved=True, dry_run=False)
    assert notes() == 1
