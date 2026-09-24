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

Two documents were ingested and chunked with both strategies:

| Document | Type | Pages | Avg tokens/page |
|---|---|---|---|
| PHY121 Module One, Units 1–4 | Lecture slides | 71 | ~70 |
| MS Learn — RAG in Azure AI Search | Prose article | 8 | ~292 |

### Run 1 — 400-token target

| Document | Strategy | Chunks | Avg | Min | Max |
|---|---|---|---|---|---|
| PHY121 slides | Fixed-size (400/60) | 43 | 70.9 | 20 | 229 |
| PHY121 slides | Structure-aware (400) | 43 | 70.9 | 20 | 229 |
| MS Learn RAG | Fixed-size (400/60) | 7 | 292.3 | 226 | 375 |
| MS Learn RAG | Structure-aware (400) | 7 | 292.3 | 226 | 375 |

**Both strategies produced byte-identical output on both documents.** Retrieval confirmed
this: the query *"what is quantization of charge"* returned the same three chunks in the same
order with identical similarity scores (0.7245, 0.5423, 0.5321) under either strategy.

The cause is the same in both cases. Every page in both documents was smaller than the
400-token target — 70 tokens per slide, 292 per article page, against a 400-token ceiling.
Since chunking is applied per page, neither strategy ever had to choose a split point within
a page. Fixed-size never made a second cut, so its overlap never triggered; structure-aware
simply packed each whole page into one chunk. Both degenerated to "one chunk per page."

### Run 2 — 150-token target (same MS Learn document)

Lowering the target below the page size (226–375 tokens) forces both strategies to split
*within* pages, which is the condition under which they can actually differ.

| Strategy | Chunks | Avg | Min | Max |
|---|---|---|---|---|
| Fixed-size (150/60) | 22 | 133.9 | 75 | 150 |
| Structure-aware (150) | 17 | 119.8 | 24 | 149 |

**Size distribution.** Fixed-size clusters tightly against its 150-token ceiling (14 of 22
chunks sit at exactly 150). Structure-aware ranges from 24 to 149, because it stops wherever
a paragraph ends rather than padding to a target.

**Chunk count.** Fixed-size produced 22 chunks against structure-aware's 17 — 29% more — for
identical source content. The extra volume is the 60-token overlap duplicated across every
boundary, which inflates both the vector store and the candidate set at query time.

**Boundary quality.** This is where the strategies differ most. Every structure-aware chunk
begins at a heading or sentence start. Fixed-size chunks frequently begin mid-thought:

| Chunk | Fixed-size opening | Problem |
|---|---|---|
| 1 | `document terminology. For RAG, an information...` | Orphaned from its subject |
| 7 | `image verbalization, and analysis.` | Starts mid-list |
| 13 | `the queryable object that unifies those sources...` | Begins on "the" |
| 16 | `: Use knowledge sources that auto-generate...` | Begins on a colon |
| 21 | `AG with knowledge retrieval and Azure AI Search` | **"RAG" split mid-acronym** |

Chunk 21 is the clearest failure: the token boundary fell inside the word "RAG", leaving a
chunk that opens with "AG". Embedded as-is, that chunk's opening carries no meaning, and if
retrieved it would be shown to a user or an LLM in that broken state.

### Which produced more useful chunks, and why

**Structure-aware, but only when the target chunk size is smaller than the document's natural
unit size.**

At a 400-token target the two strategies were indistinguishable on both documents, because
the page structure had already done the chunking. At 150 tokens structure-aware was clearly
better: 29% fewer chunks to store and search, and every chunk a self-contained passage rather
than an arbitrary token window.

The general rule this establishes: **chunking strategy only matters when chunks must be cut
within a document's natural units.** Where pages, sections, or slides already fit inside the
target size, the document's own structure determines the chunks and the strategy is
irrelevant. This is worth knowing before investing in a sophisticated splitter — the first
question should be how the target size compares to the source's natural unit size.

Structure-aware is not free of trade-offs. Chunk 11 came out at just 24 tokens because a short
section ended and the packer declined to pad it with unrelated material from the next section.
That chunk is coherent but thin, and may be too sparse to retrieve well. Fixed-size would have
merged it with its neighbour, producing a fuller but less focused chunk. Fixed-size also
retains one genuine advantage: its overlap means a fact sitting on a boundary appears intact
in at least one chunk, whereas structure-aware relies on its boundaries being good ones.

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

## Tests

```bash
pip install -r requirements-dev.txt
ruff check app tests
pytest -v
```

14 tests covering upload validation (disguised files, oversized files, empty files,
unsupported extensions, filename sanitisation) and chunking invariants (target sizes
respected, overlap present, page numbers preserved, sub-threshold chunks filtered, sequential
indexes). Linting and tests run on every push via GitHub Actions.

Ruff's `B023` check caught a latent bug in the structure-aware chunker: a closure captured the
loop's `page` variable rather than its value, which would have written wrong page numbers into
citations had the flush ever been deferred. Fixed by extracting the per-page work into its own
function so the page became a proper parameter, rather than suppressing the warning.

---

## Known limitations

- Scanned PDFs are rejected rather than OCR'd.
- Chunking never spans page boundaries, so cross-page paragraphs are split.
- Sentence splitting is regex-based and mishandles abbreviations such as "Fig. 3".
- No authentication; intended for local development only.
- The comparison covers two documents. A larger and more varied corpus would test the
  strategies further, particularly documents with deep heading hierarchies.