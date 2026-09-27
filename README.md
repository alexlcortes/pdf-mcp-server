# pdf-mcp-server

A local [Model Context Protocol](https://modelcontextprotocol.io) (MCP) server that lets Claude Desktop semantically search and read a local PDF file to answer questions about it.

## Why

Claude can't read large local files directly. This server exposes a small set of tools — list, summarize, search, and read specific pages — that Claude calls on demand while chatting with you, so it can answer questions grounded in the actual contents of your PDF instead of guessing.

## How it works

1. On first search of a document, the server extracts text per page (`pdfplumber`, falling back to `pypdf`), cleans up extraction artifacts, and splits it into overlapping chunks.
2. Each chunk is embedded locally using `sentence-transformers` (`all-MiniLM-L6-v2` — no API key, runs offline) and stored in a persistent [Chroma](https://www.trychroma.com/) vector database (`.index/`), keyed by document + content hash so it only re-indexes when the PDF actually changes.
3. Claude calls `search_pdf` with a natural-language query, gets back the most semantically relevant chunks (with page numbers), and uses that to answer your question.

## Tools exposed

| Tool | Purpose |
|---|---|
| `list_pdfs` | List available documents (filenames without `.pdf`) |
| `search_pdf(document, query, max_results)` | Semantic search over chunks, returns text + page range + relevance score |
| `get_pdf_page(document, page_number)` | Raw extracted text of one page |
| `get_pdf_summary(document, max_pages)` | Text of the first few pages, for a quick overview |
| `get_pdf_page_count(document)` | Total page count |

## Quick Start

1. **Install dependencies**
   ```bash
   uv sync
   ```
2. **Add your PDF**
   Copy the PDF you want to query into `pdfs/` (this folder is gitignored — PDFs are your own content, not part of the repo).
3. **Test it locally with MCP Inspector** (a browser UI for calling tools directly, before involving Claude)
   ```bash
   uv run mcp dev src/pdf_mcp_server/server.py
   ```
   Open the URL printed in the terminal, click **Connect**, then go to the **Tools** tab and try `list_pdfs` to confirm your PDF is detected. Stop this process (Ctrl+C) once you're done testing.
4. **Find your absolute project path and `uv` path** (needed for the next step)
   ```bash
   pwd            # your project path
   which uv       # your uv path
   ```
5. **Register the server with Claude Desktop**
   Add an entry to `~/Library/Application Support/Claude/claude_desktop_config.json` (create the file if it doesn't exist) using the absolute paths from step 4 — see [Connecting to Claude Desktop](#connecting-to-claude-desktop) below for the exact JSON.
6. **Fully quit and reopen Claude Desktop**
   It only reads the config file at launch, so a config edit while it's running won't take effect until you restart.
7. **Verify the connection**
   In Claude Desktop, check the tools/plug icon in the chat UI — `pdf-reader` should appear as a connected server with its tools listed. Ask Claude a question about your PDF to confirm it calls `search_pdf` and answers using real content.

## Running locally (for testing)


Use the MCP Inspector to call tools manually in a browser before wiring into Claude Desktop:
```bash
uv run mcp dev src/pdf_mcp_server/server.py
```

## Connecting to Claude Desktop

Add this to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS), using **absolute paths** since Claude Desktop launches the server with its own working directory and minimal environment:

```json
{
  "mcpServers": {
    "pdf-reader": {
      "command": "/absolute/path/to/uv",
      "args": [
        "--directory", "/absolute/path/to/pdf-mcp-server",
        "run", "pdf-mcp-server"
      ],
      "env": {
        "PDF_DIR": "/absolute/path/to/pdf-mcp-server/pdfs",
        "PDF_MCP_INDEX_DIR": "/absolute/path/to/pdf-mcp-server/.index"
      }
    }
  }
}
```

Fully quit and reopen Claude Desktop afterward — it only reads this file at launch.

## Known limitations (v1)

- Chunking is fixed-size (character-based), not section-aware — a chunk can span unrelated content (e.g. a short lore blurb next to an unrelated stat table).
- Text extraction from rotated/sidebar layout elements (e.g. character sheet forms) can come out in a garbled reading order — this is a limitation of coordinate-based PDF text extraction, not specific to this tool.
- Designed for a single large PDF for now; multi-document support is planned.
