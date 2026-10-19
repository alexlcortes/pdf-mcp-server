import tempfile
import unittest
from pathlib import Path

from pdf_mcp_server.pdf_index import PDFIndex, _find_gutter


def _word(x0: float, x1: float, top: float) -> dict:
    return {"x0": x0, "x1": x1, "top": top, "bottom": top + 10}


class FindGutterTests(unittest.TestCase):
    PAGE_WIDTH = 612

    def test_detects_two_columns_with_full_width_heading(self) -> None:
        words = [_word(200, 420, 20)]  # heading crossing the gutter
        for row in range(30):
            top = 40 + row * 12
            words += [_word(50, 120, top), _word(130, 290, top)]
            words += [_word(320, 400, top), _word(410, 560, top)]

        gutter = _find_gutter(words, self.PAGE_WIDTH)

        self.assertIsNotNone(gutter)
        x0, x1 = gutter
        self.assertGreaterEqual(x0, 290)
        self.assertLessEqual(x1, 321)

    def test_single_column_prose_has_no_gutter(self) -> None:
        words = []
        for row in range(40):
            # Word boundaries shift per line, as in justified prose.
            offset = (row * 37) % 60
            words += [
                _word(50, 200 + offset, row * 12),
                _word(205 + offset, 380, row * 12),
                _word(385, 560, row * 12),
            ]

        self.assertIsNone(_find_gutter(words, self.PAGE_WIDTH))

    def test_sparse_page_has_no_gutter(self) -> None:
        words = [_word(50, 150, 100), _word(450, 550, 100)]

        self.assertIsNone(_find_gutter(words, self.PAGE_WIDTH))


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


class _FakeCollection:
    def __init__(self, doc_ids: list[str]) -> None:
        self.doc_ids = doc_ids

    def get(self, include: list[str]) -> dict:
        return {"metadatas": [{"doc_id": doc_id} for doc_id in self.doc_ids]}

    def delete(self, where: dict) -> None:
        stale = set(where["doc_id"]["$in"])
        self.doc_ids = [d for d in self.doc_ids if d not in stale]


class PruneMissingDocumentsTests(unittest.TestCase):
    def test_removes_chunks_for_renamed_or_deleted_pdfs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_dir = Path(temp_dir)
            (pdf_dir / "FAGE.pdf").touch()

            index = object.__new__(PDFIndex)
            index.pdf_dir = pdf_dir
            index._collection = _FakeCollection(
                ["FAGE", "FAGE", "GRR6101_FAGE_Core", "removed"]
            )

            pruned = index.prune_missing_documents()

            self.assertEqual(pruned, ["GRR6101_FAGE_Core", "removed"])
            self.assertEqual(index._collection.doc_ids, ["FAGE", "FAGE"])


if __name__ == "__main__":
    unittest.main()