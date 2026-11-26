# Showcase: Policy Q&A

The agent shown in the main README's screenshots, made entirely from plain words. Recreate it in about five minutes on
your own install. Everything here was produced by the app itself; nothing was hand-coded.

| File | What it is |
|---|---|
| `sample-leave-policy.pdf` | A neutral two-page sample policy (made with the bundled PDF library) |
| `read_pdf_summary.py` | The tool **Agentic Studio wrote** for this (version 2, after one **Change**): `list_pdfs()` and `get_pdf_info(filename)`. Risk report: low |

## Recreate it

1. **Files** → **Add a file** → `sample-leave-policy.pdf`.
2. **Create agent** → write:

   > I want to ask questions about policy documents in my files, such as sample-leave-policy.pdf. Find the right PDF,
   > read it and answer from its text, quoting the rule you used.

3. No tool reads PDFs yet, so the plan card says so. Choose **Write a tool**. The studio writes a PDF reader, tries it
   and lists its risks. An administrator opens **Systems** → **Review code and risks** → **Approve**.
   (Your tool will be written fresh, so it may differ from `read_pdf_summary.py`; compare them to see what changed.)
4. If the first version cannot list your files, use **Change** on the tool: *"Add an operation that lists the PDF files
   in the person's files (name and size), so the right file can be found"*, then approve version 2.
5. Back on the draft: name it **Policy Q&A**, **Create**. The studio proves it with one of its own sample questions;
   the proof should say *met*.
6. **Publish**, **Share** (anyone signed in can now use `/chat/<id>`), and on the agent's chat add a test question:
   - Question: *In sample-leave-policy.pdf, how many unused leave days can be carried over?*
   - A good answer contains: *Up to 10 unused days can be carried into the next year*
7. Ask it: *How many days of annual leave do employees get?* → *30 working days per year*, quoting rule 1.

Optional know-how (**Know-how** → **New skill**, in your words): *"When answering from policy documents: find the PDF
by name first, read it, quote the exact rule and the page it is on, and say clearly when the document does not cover
the question instead of guessing."*
