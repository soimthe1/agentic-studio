import os
from pypdf import PdfReader


class Tool:
    HOSTS = []
    SECRETS = []
    CHANGES = []

    def get_pdf_info(self, filename: str) -> dict:
        """Return page count and first 3000 chars of text from a PDF in the user's files."""
        if not filename or not filename.strip():
            raise ValueError("File name must be provided.")

        filename = filename.strip()
        path = os.path.join(self.files_dir, filename)

        if not os.path.isfile(path):
            raise ValueError(f"File '{filename}' not found in your files folder.")

        try:
            reader = PdfReader(path)
        except Exception as e:
            raise ValueError(f"Could not read '{filename}' as a PDF: {e}")

        page_count = len(reader.pages)

        text_parts = []
        for page in reader.pages:
            try:
                t = page.extract_text() or ""
                text_parts.append(t)
            except Exception:
                text_parts.append("")

        full_text = "\n".join(text_parts)
        return {
            "filename": filename,
            "page_count": page_count,
            "text_first_3000": full_text[:3000],
            "text_length": len(full_text),
        }

    def list_pdfs(self) -> list[dict]:
        """List all PDF files in the user's files folder with name and size in bytes."""
        if not os.path.isdir(self.files_dir):
            raise ValueError("Files folder not found.")

        results = []
        for entry in sorted(os.scandir(self.files_dir), key=lambda e: e.name.lower()):
            try:
                if entry.is_file(follow_symlinks=False) and entry.name.lower().endswith(".pdf"):
                    size = entry.stat(follow_symlinks=False).st_size
                    results.append({"name": entry.name, "size_bytes": size})
                    if len(results) >= 200:
                        break
            except OSError:
                continue
        return results
