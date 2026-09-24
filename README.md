# Week 8 — RAG Part 1: Ingestion & Embeddings

A document ingestion pipeline: **upload → extract → chunk → embed → store**, built with
FastAPI and Chroma, including a comparison of two chunking strategies.

---

## Running it

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1        # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Interactive API docs: <http://127.0.0.1:8000/docs>

No API keys are required. Embeddings run locally by default.

---

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness check |
| POST | `/upload` | Validated file upload |
| GET | `/documents/{doc_id}/preview` | Extracted text, per page |
| GET | `/documents/{doc_id}/chunks` | Chunk preview and size statistics |
| POST | `/documents/{doc_id}/index` | Chunk, embed, and store |
| GET | `/search` | Retrieve chunks with citations |

---

## Safe ingestion

The upload endpoint accepts **files only**. It never takes a URL and never fetches one
server-side, which removes the SSRF attack surface entirely rather than trying to filter
malicious URLs.

Four controls:

1. **Content-based type detection.** File signatures are checked with `filetype`, so a
   `.exe` renamed to `.pdf` is rejected. Extensions are trusted only for `.txt` and `.md`,
   which have no signature, and those are additionally validated as UTF-8.
2. **Streaming size cap.** Files are read in 1 MB chunks and aborted at 10 MB, so an
   oversized upload never lands fully in memory. Partial files are deleted on failure.
3. **Generated filenames.** The user's filename is discarded and replaced with a UUID,
   defeating path traversal such as `../../app/main.py`.
4. **Allowlist, not blocklist.** Only `pdf`, `txt`, and `md` are permitted.

Tested rejections: fake PDF → 400, oversized file → 413, empty file → 400.

> While the server was running on localhost, endpoint-security scanning probed it with
> Log4Shell-style `${jndi:...}` payloads within minutes. All returned 404. A useful
> reminder that any open port is probed almost immediately.

---

## Extraction

Text is extracted **per page** rather than as one flat string, because page numbers must
survive into chunk metadata to support citations. Flattening first would discard that
information irrecoverably.

Pages with no extractable text are skipped. A document yielding nothing returns 422 with a
note that the PDF is likely scanned images requiring OCR — this was hit with a real scanned
document during testing, and the error path worked as designed.

---

## Chunking strategies

### A — Fixed-size with overlap

Cuts every 400 tokens with a 60-token sliding overlap, measured with `tiktoken`
(`cl100k_base`) so sizes reflect what the model actually sees rather than character counts.

- **Pro:** predictable sizes, trivial to reason about, overlap rescues facts that straddle a
  boundary.
- **Con:** cuts land arbitrarily, often mid-sentence; overlap duplicates text and inflates
  the store.

### B — Structure-aware

Splits on paragraphs, falling back to sentences, then to a hard token cut only if a single
sentence exceeds the target. Units are packed up to the target size and never split through
the middle.

- **Pro:** chunks begin and end at natural boundaries, so retrieved text reads as complete
  thoughts.
- **Con:** variable sizes; depends on the document actually having usable structure, which
  PDF extraction does not always preserve.

### Shared: page-boundary and minimum-size rules

Both strategies chunk each page independently. This splits paragraphs that span pages, but
guarantees every chunk maps to exactly one page number so citations are never wrong.

Both also discard chunks under 20 tokens. Before this filter, the test document produced 71
chunks, of which roughly 28 were footer fragments such as
`"ccodel.covenantuniversity.edu.ng 67"` — content-free text that would have been embedded,
stored, and occasionally retrieved. Filtering left 43 genuine chunks.

---

## Comparison results

**Document:** PHY121 Module One, Units 1–4 (lecture slides, 3.4 MB, 71 pages)
**Target chunk size:** 400 tokens

| Strategy | Chunks | Avg tokens | Min | Max |
|---|---|---|---|---|
| Fixed-size (400/60) | 43 | 70.9 | 20 | 229 |
| Structure-aware (400) | 43 | 70.9 | 20 | 229 |

### Retrieval test

Query: *"what is quantization of charge"*

| Rank | Page | Similarity | Fixed-size | Structure-aware |
|---|---|---|---|---|
| 1 | 13 | 0.7245 | Quantization of Charge (q = ne) | identical |
| 2 | 12 | 0.5423 | Properties of charges | identical |
| 3 | 6 | 0.5321 | Electrostatics introduction | identical |

Both strategies returned the same chunks in the same order with identical similarity
scores.

### Which produced more useful chunks, and why

**On this document, neither — and the reason is the interesting part.**

Every page of a lecture-slide deck holds only a handful of bullet points, averaging about 70
tokens. Since the 400-token target exceeds nearly every page, fixed-size chunking never
needs to make a second cut within a page, and its overlap never triggers. Structure-aware
chunking, meanwhile, simply packs the whole page into one chunk. **Both strategies degenerate
to "one chunk per page,"** producing byte-identical output and therefore identical retrieval.

The general principle: **chunking strategy only matters when the document's natural units are
larger than the target chunk size.** Where a page already fits inside one chunk, the
document's own structure has done the chunking, and the strategy is irrelevant.

This predicts where the strategies *would* diverge: dense prose with pages well over 400
tokens, or the same slides with a much smaller target size. Both are the obvious next
experiments.

Retrieval quality itself was good regardless of strategy. The top hit for the test query was
the exact slide defining quantization, including the formula, cited correctly to page 13.

---

## Vector store choice

**Chroma**, chosen because:

- It runs in-process with no server, container, or cloud account, matching the scale of this
  project (one document, 86 vectors).
- It stores text, vectors, and metadata together, with metadata filtering — which this
  project depends on, since both chunking strategies live in one collection and are compared
  by filtering on `strategy`.
- Persistence to disk means the index survives restarts.

Cosine distance is configured explicitly (`hnsw:space: cosine`), since the embedding model
produces normalised vectors where cosine similarity is the appropriate measure.

**Trade-off:** Chroma is single-node and not built for high-concurrency production traffic.
For a multi-user deployment, pgvector would be the natural move if the data already lives in
Postgres, or Azure AI Search where hybrid keyword-plus-vector search and managed scaling are
needed.

---

## Embeddings

`all-MiniLM-L6-v2` via sentence-transformers: 384 dimensions, free, runs offline, no API key
or per-token cost. Quality is more than sufficient here, and since both chunking strategies
are embedded with the *same* model, the model is a controlled constant in the comparison.

The provider is swappable to OpenAI's `text-embedding-3-small` via a single setting, with the
API key supplied through a gitignored `.env` file and never committed.

---

## Chunk metadata

| Field | Purpose |
|---|---|
| `doc_id` | Which document the chunk came from |
| `source` | Human-readable name, used in citations |
| `page` | Page number, used in citations |
| `chunk_index` | Position in document; enables fetching neighbours |
| `strategy` | Which chunking strategy produced it — enables the comparison |
| `token_count` | Analysis and size distribution |
| `content_hash` | Detects duplicate chunks across re-uploads |

IDs are `{doc_id}:{strategy}:{chunk_index}`, and writes use `upsert`, so re-indexing the same
document replaces rather than duplicates its chunks.

Search results return a formatted `citation` string (`"PHY121 Module One, p.13"`), so every
retrieved chunk carries its provenance.

---

## Known limitations

- Scanned PDFs are rejected rather than OCR'd.
- Chunking never spans page boundaries, so cross-page paragraphs are split.
- Sentence splitting is regex-based and mishandles abbreviations such as "Fig. 3".
- No authentication; intended for local development only.
- The comparison rests on a single slide-based document. Prose documents would test the
  strategies more sharply.

  ## Tests

```bash
pip install -r requirements-dev.txt
ruff check app tests
pytest -v
```

14 tests covering upload validation (disguised files, oversized files, empty files,
unsupported extensions, filename sanitisation) and chunking invariants (target sizes
respected, overlap present, page numbers preserved, sub-threshold chunks filtered,
sequential indexes). Linting and tests run automatically on every push via GitHub Actions.

Ruff's `B023` check caught a latent bug in the structure-aware chunker: a closure captured
the loop's `page` variable rather than its value, which would have produced wrong page
numbers in citations if the flush had ever been deferred. Fixed by extracting the per-page
work into its own function so the page is a proper parameter.