import asyncio
import unittest
from unittest import mock

# server builds a real PDFIndex (Chroma + embedding model) at import time.
with mock.patch("pdf_mcp_server.pdf_index.PDFIndex"):
    from pdf_mcp_server import server


class ListPdfsTests(unittest.TestCase):
    def call_list_pdfs(self, documents: list[str]):
        index = mock.Mock()
        index.list_documents.return_value = documents
        with mock.patch.object(server, "_index", index):
            content, _ = asyncio.run(server.mcp.call_tool("list_pdfs", {}))
        return content

    def test_returns_ids_in_a_single_newline_separated_block(self) -> None:
        content = self.call_list_pdfs(["BREAK", "FAGE"])

        self.assertEqual(len(content), 1)
        self.assertEqual(content[0].text, "BREAK\nFAGE")

    def test_reports_when_no_pdfs_are_available(self) -> None:
        content = self.call_list_pdfs([])

        self.assertEqual(len(content), 1)
        self.assertEqual(content[0].text, "No PDFs available.")


if __name__ == "__main__":
    unittest.main()
