import tempfile
import unittest
from pathlib import Path

from pdf_mcp_server.pdf_index import PDFIndex


class GetDocumentTests(unittest.TestCase):
    def test_accepts_document_stem_and_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pdf_dir = root / "pdfs"
            pdf_dir.mkdir()
            (pdf_dir / "rulebook.pdf").touch()
            (root / "secret.pdf").touch()
            (pdf_dir / "linked.pdf").symlink_to(root / "secret.pdf")

            index = object.__new__(PDFIndex)
            index.pdf_dir = pdf_dir
            index._documents = {}

            document = index._get_document("rulebook")

            self.assertEqual(document.path, pdf_dir / "rulebook.pdf")
            with self.assertRaises(ValueError):
                index._get_document("../secret")
            with self.assertRaises(ValueError):
                index._get_document("linked")


if __name__ == "__main__":
    unittest.main()