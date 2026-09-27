"""MCP server exposing tools for Claude to search and read local PDF files."""

from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from pdf_mcp_server.pdf_index import PDFIndex

PDF_DIR = Path(os.environ.get("PDF_DIR", "./pdfs")).expanduser().resolve()
PERSIST_DIR = Path(
    os.environ.get("PDF_MCP_INDEX_DIR", "./.index")
).expanduser().resolve()

mcp = FastMCP("pdf-reader")
_index = PDFIndex(pdf_dir=PDF_DIR, persist_dir=PERSIST_DIR)


@mcp.tool()
def list_pdfs() -> list[str]:
    """List the PDF documents currently available to search and read."""
    return _index.list_documents()


@mcp.tool()
def search_pdf(document: str, query: str, max_results: int = 5) -> list[dict]:
    """Semantically search a PDF for chunks of text relevant to a query.

    Args:
        document: Document id as returned by list_pdfs (filename without .pdf).
        query: Natural-language question or keywords to search for.
        max_results: Maximum number of matching chunks to return (default 5).

    Returns a list of matches, each with page_start, page_end, text, and
    relevance_score (higher is more relevant).
    """
    try:
        return _index.search(document, query, max_results=max_results)
    except ValueError as exc:
        return [{"error": str(exc)}]


@mcp.tool()
def get_pdf_page(document: str, page_number: int) -> str:
    """Get the raw extracted text of a single page from a PDF.

    Args:
        document: Document id as returned by list_pdfs.
        page_number: 1-based page number.
    """
    try:
        return _index.get_page(document, page_number)
    except ValueError as exc:
        return f"Error: {exc}"


@mcp.tool()
def find_exact_text(
    document: str, phrase: str, max_results: int = 10
) -> list[dict]:
    """Find every occurrence of an exact phrase in a PDF (e.g. a proper noun:
    an item, faction, or character name). Matching ignores case and
    typographic punctuation differences (curly vs. straight quotes, dashes),
    so you don't need to guess the PDF's exact character variants.

    Use this when search_pdf's semantic search doesn't turn up a specific
    named term you're looking for, or when you need to confirm every place a
    name appears rather than just the most semantically similar excerpts.

    Args:
        document: Document id as returned by list_pdfs.
        phrase: The exact text to search for.
        max_results: Maximum number of occurrences to return (default 10).
    """
    try:
        return _index.keyword_search(document, phrase, max_results=max_results)
    except ValueError as exc:
        return [{"error": str(exc)}]


@mcp.tool()
def get_pdf_summary(document: str, max_pages: int = 3) -> str:
    """Get the text of the first few pages of a PDF, useful for a quick
    overview before doing targeted searches.

    Args:
        document: Document id as returned by list_pdfs.
        max_pages: Number of leading pages to return (default 3).
    """
    try:
        return _index.get_summary_text(document, max_pages=max_pages)
    except ValueError as exc:
        return f"Error: {exc}"


@mcp.tool()
def get_pdf_page_count(document: str) -> int:
    """Get the total number of pages in a PDF."""
    return _index.page_count(document)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
