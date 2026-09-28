"""Loads a PDF, splits it into overlapping chunks, and indexes the chunks
in a local Chroma collection using sentence-transformers embeddings so they
can be semantically searched.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import chromadb
import pdfplumber
from chromadb.utils import embedding_functions
from pypdf import PdfReader

# Smaller chunks keep a short lore blurb (e.g. a weapon's 1-2 sentence flavor
# text) from sharing an embedding with unrelated surrounding stat blocks or
# tables, at the cost of less surrounding context per chunk.
CHUNK_SIZE_CHARS = 700
CHUNK_OVERLAP_CHARS = 120
# How far past the target chunk size to look for a paragraph break before
# falling back to a sentence break, and then a hard cutoff.
_BOUNDARY_SEARCH_WINDOW = 150
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"

# Custom PDF fonts sometimes use decorative glyphs (icons/bullets) with no
# Unicode mapping; pdfminer/pdfplumber then emit a raw "(cid:N)" placeholder
# instead of the glyph. These carry no searchable meaning, so strip them.
_CID_PLACEHOLDER_RE = re.compile(r"\(cid:\d+\)\s*")


def _clean_extracted_text(text: str) -> str:
    text = _CID_PLACEHOLDER_RE.sub("", text)
    text = re.sub(r"[ \t]+\n", "\n", text)  # trailing spaces before newlines
    text = re.sub(r"\n{3,}", "\n\n", text)  # collapse excess blank lines
    return text


# Maps typographic punctuation (curly quotes, en/em dashes) to their plain
# ASCII equivalents, used only to normalize text for literal phrase matching.
# PDFs commonly use curly apostrophes (') where a typed query uses a
# straight one ('), which otherwise causes exact-phrase search to miss valid
# matches.
_NORMALIZE_FOR_MATCH = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
    }
)


def _normalize_for_match(text: str) -> str:
    return text.translate(_NORMALIZE_FOR_MATCH).lower()


@dataclass
class Chunk:
    doc_id: str
    chunk_id: str
    page_start: int
    page_end: int
    text: str


class PDFDocument:
    """Extracted, page-indexed text for a single PDF."""

    def __init__(self, doc_id: str, path: Path):
        self.doc_id = doc_id
        self.path = path
        self._pages: list[str] | None = None

    @property
    def pages(self) -> list[str]:
        if self._pages is None:
            self._pages = self._extract_pages()
        return self._pages

    def _extract_pages(self) -> list[str]:
        pages: list[str] = []
        try:
            with pdfplumber.open(self.path) as pdf:
                for page in pdf.pages:
                    pages.append(page.extract_text() or "")
        except Exception:
            pages = []

        # Fall back to pypdf per-page if pdfplumber produced nothing usable.
        if not any(text.strip() for text in pages):
            reader = PdfReader(self.path)
            pages = [page.extract_text() or "" for page in reader.pages]

        return [_clean_extracted_text(text) for text in pages]

    def full_text(self) -> str:
        return "\n\n".join(self.pages)

    def page_text(self, page_number: int) -> str:
        if page_number < 1 or page_number > len(self.pages):
            raise ValueError(
                f"Page {page_number} out of range (document has {len(self.pages)} pages)."
            )
        return self.pages[page_number - 1]


def _chunk_pages(pages: list[str]) -> list[tuple[int, int, str]]:
    """Concatenate page text with page-boundary markers, then split into
    overlapping character-based chunks, tracking which pages each chunk spans.
    """
    boundaries: list[tuple[int, int]] = []  # (char_start, page_number)
    full_text_parts: list[str] = []
    offset = 0
    for i, page_text in enumerate(pages, start=1):
        boundaries.append((offset, i))
        full_text_parts.append(page_text)
        offset += len(page_text) + 2  # account for the join separator below
    full_text = "\n\n".join(full_text_parts)

    def page_for_offset(char_offset: int) -> int:
        page = 1
        for start, page_num in boundaries:
            if start <= char_offset:
                page = page_num
            else:
                break
        return page

    chunks: list[tuple[int, int, str]] = []
    start = 0
    text_len = len(full_text)
    if text_len == 0:
        return chunks

    while start < text_len:
        end = min(start + CHUNK_SIZE_CHARS, text_len)
        if end < text_len:
            window_end = end + _BOUNDARY_SEARCH_WINDOW
            # Prefer a paragraph break (closest thing to an "entry boundary"
            # in extracted text) over an arbitrary mid-paragraph sentence cut.
            next_para = full_text.find("\n\n", end, window_end)
            if next_para != -1:
                end = next_para
            else:
                next_period = full_text.find(". ", end, window_end)
                if next_period != -1:
                    end = next_period + 1

        chunk_text = full_text[start:end].strip()
        if chunk_text:
            page_start = page_for_offset(start)
            page_end = page_for_offset(max(end - 1, start))
            chunks.append((page_start, page_end, chunk_text))

        if end >= text_len:
            break
        start = max(end - CHUNK_OVERLAP_CHARS, start + 1)

    return chunks


class PDFIndex:
    """Indexes one or more PDFs for semantic search, backed by a persistent
    Chroma collection. Documents are lazily parsed, chunked, and embedded on
    first access, and cached both in memory and on disk (Chroma persistence).
    """

    def __init__(self, pdf_dir: Path, persist_dir: Path):
        self.pdf_dir = pdf_dir
        self.persist_dir = persist_dir
        self.persist_dir.mkdir(parents=True, exist_ok=True)

        self._client = chromadb.PersistentClient(path=str(persist_dir))
        self._embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=EMBEDDING_MODEL_NAME
        )
        self._collection = self._client.get_or_create_collection(
            name="pdf_chunks", embedding_function=self._embedding_fn
        )
        self._documents: dict[str, PDFDocument] = {}
        self._indexed_doc_ids: set[str] = set()

    def _doc_id_for_path(self, path: Path) -> str:
        return re.sub(r"[^a-zA-Z0-9_-]", "_", path.stem)

    def list_documents(self) -> list[str]:
        return sorted(p.stem for p in self.pdf_dir.glob("*.pdf"))

    def _get_document(self, doc_id: str) -> PDFDocument:
        if not doc_id or "/" in doc_id or "\\" in doc_id:
            raise ValueError(f"Invalid document id '{doc_id}'.")
        if doc_id not in self.list_documents():
            raise ValueError(f"Unknown document '{doc_id}'.")
        if doc_id not in self._documents:
            path = self.pdf_dir / f"{doc_id}.pdf"
            try:
                path.resolve().relative_to(self.pdf_dir.resolve())
            except ValueError as exc:
                raise ValueError(
                    f"Document '{doc_id}' is outside the PDF directory."
                ) from exc
            self._documents[doc_id] = PDFDocument(doc_id, path)
        return self._documents[doc_id]

    def _content_hash(self, path: Path) -> str:
        return hashlib.sha1(path.read_bytes()).hexdigest()[:16]

    def ensure_indexed(self, doc_id: str) -> None:
        """Chunk and embed the document into Chroma if not already done for
        this exact file content (re-indexes automatically if the PDF changed).
        """
        document = self._get_document(doc_id)
        content_hash = self._content_hash(document.path)
        cache_key = f"{doc_id}:{content_hash}"
        if cache_key in self._indexed_doc_ids:
            return

        existing = self._collection.get(where={"doc_id": doc_id})
        if existing["ids"]:
            existing_hash = (existing["metadatas"][0] or {}).get("content_hash")
            if existing_hash == content_hash:
                self._indexed_doc_ids.add(cache_key)
                return
            # Content changed: drop stale chunks before re-indexing.
            self._collection.delete(where={"doc_id": doc_id})

        chunks = _chunk_pages(document.pages)
        if not chunks:
            self._indexed_doc_ids.add(cache_key)
            return

        ids, texts, metadatas = [], [], []
        for i, (page_start, page_end, text) in enumerate(chunks):
            ids.append(f"{doc_id}:{content_hash}:{i}")
            texts.append(text)
            metadatas.append(
                {
                    "doc_id": doc_id,
                    "content_hash": content_hash,
                    "page_start": page_start,
                    "page_end": page_end,
                }
            )
        self._collection.add(ids=ids, documents=texts, metadatas=metadatas)
        self._indexed_doc_ids.add(cache_key)

    def search(self, doc_id: str, query: str, max_results: int = 5) -> list[dict]:
        self.ensure_indexed(doc_id)
        results = self._collection.query(
            query_texts=[query],
            n_results=max_results,
            where={"doc_id": doc_id},
        )
        hits = []
        ids = results.get("ids", [[]])[0]
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
        for _id, text, meta, distance in zip(ids, docs, metas, distances):
            hits.append(
                {
                    "page_start": meta["page_start"],
                    "page_end": meta["page_end"],
                    "text": text,
                    "relevance_score": round(1 - distance, 4),
                }
            )
        return hits

    def get_page(self, doc_id: str, page_number: int) -> str:
        return self._get_document(doc_id).page_text(page_number)

    def keyword_search(
        self, doc_id: str, phrase: str, max_results: int = 10, context_chars: int = 200
    ) -> list[dict]:
        """Find literal occurrences of a phrase across every page, ignoring
        case and typographic punctuation differences (curly vs. straight
        quotes, en/em dashes vs. hyphens). Complements semantic search:
        catches exact proper nouns (named items, factions, NPCs) that a short
        flavor-text mention can cause semantic search to rank low or miss
        entirely.
        """
        document = self._get_document(doc_id)
        needle = _normalize_for_match(phrase)
        hits = []
        for page_number, page_text in enumerate(document.pages, start=1):
            haystack = _normalize_for_match(page_text)
            start = 0
            while True:
                idx = haystack.find(needle, start)
                if idx == -1:
                    break
                snippet_start = max(idx - context_chars, 0)
                snippet_end = min(idx + len(phrase) + context_chars, len(page_text))
                hits.append(
                    {
                        "page": page_number,
                        "snippet": page_text[snippet_start:snippet_end].strip(),
                    }
                )
                if len(hits) >= max_results:
                    return hits
                start = idx + len(needle)
        return hits

    def get_summary_text(self, doc_id: str, max_pages: int = 3) -> str:
        document = self._get_document(doc_id)
        return "\n\n".join(document.pages[:max_pages])

    def page_count(self, doc_id: str) -> int:
        return len(self._get_document(doc_id).pages)
