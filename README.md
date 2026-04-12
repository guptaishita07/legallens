# LegalLens — RAG Foundation

This template provides a minimal setup to get React working in Vite with HMR and some ESLint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the ESLint configuration

### 2. Backend

```bash
cd backend
cp .env.example .env
# Fill in OPENAI_API_KEY (required for embeddings + LLM)

pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

On first startup, `init_db()` creates all tables and enables the pgvector extension automatically.

API docs: http://localhost:8000/docs

### 3. Frontend

```bash
cd client
npm install
npm run dev
```

Open http://localhost:5173

---

## Project structure

```
legallens/
├── backend/
│   ├── main.py                    # FastAPI app + startup
│   ├── config.py                  # Pydantic settings (reads .env)
│   ├── db/
│   │   └── database.py            # SQLAlchemy models + pgvector schema
│   ├── routers/
│   │   ├── documents.py           # Upload, list, get, delete endpoints
│   │   └── qa.py                  # Ask question, get history endpoints
│   └── services/
│       ├── pdf_service.py         # PDF parsing + semantic chunking
│       ├── embedding_service.py   # OpenAI embeddings + BM25 index
│       ├── retrieval_service.py   # Hybrid retrieval + RRF fusion
│       ├── llm_service.py         # Answer generation + faithfulness check
│       └── storage_service.py     # Local / S3 file storage
├── client/
│   └── src/
│       ├── App.jsx                # Root app + sidebar + routing
│       ├── api/client.js          # Axios API layer
│       └── components/
│           ├── UploadPanel.jsx    # Drag-and-drop PDF upload
│           ├── QAPanel.jsx        # Streaming Q&A chat with source chips
│           └── ChunksPanel.jsx    # Indexed chunk browser
└── docker-compose.yml
```

---

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/documents/upload` | Upload PDF, trigger ingestion |
| GET | `/documents/` | List all documents |
| GET | `/documents/{id}` | Get document + all chunks |
| DELETE | `/documents/{id}` | Delete document + chunks |
| POST | `/qa/{id}/ask` | Ask a question about a contract |
| GET | `/qa/{id}/history` | Get Q&A history for a document |
| GET | `/health` | Health check |

---

## The RAG pipeline — key design decisions

### Chunking strategy (pdf_service.py)

Most tutorials chunk by fixed token count. LegalLens detects legal clause headings using a regex that matches patterns like `"5. Indemnification"`, `"CLAUSE 12 — TERMINATION"`, `"Article III"`. Each detected section becomes its own chunk, keeping legal clauses semantically intact.

For oversized sections, token-aware splitting with 64-token overlap prevents context loss at boundaries.

### Hybrid retrieval (retrieval_service.py)

Two retrieval strategies are combined:

- **Dense (pgvector)**: cosine similarity on OpenAI embeddings. Handles semantic queries — "what are my liability protections?" maps to the right clause even without exact keyword matches.
- **Sparse (BM25)**: keyword scoring. Handles exact queries — "find clause 12.3" or specific legal terms like "force majeure".

**Reciprocal Rank Fusion** merges both ranked lists without score normalisation: `score += 1 / (60 + rank)` for each list. No tuning required.

### Faithfulness guardrail (llm_service.py)

After generating an answer, a second LLM call checks: "Is this answer supported by the provided context?" — returning `{ is_grounded, confidence }`. If confidence < 0.5, the user sees a safe fallback message instead of a hallucination.

---

## Environment variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENAI_API_KEY` | For embeddings + LLM | Required |
| `ANTHROPIC_API_KEY` | Use Claude as LLM instead | Optional |
| `LLM_PROVIDER` | `openai` or `anthropic` | `openai` |
| `DATABASE_URL` | PostgreSQL connection string | localhost/legallens |
| `STORAGE_BACKEND` | `local` or `s3` | `local` |
| `CHUNK_SIZE_TOKENS` | Max tokens per chunk | `512` |
| `RETRIEVAL_TOP_K` | Candidates from each retriever | `20` |
| `RERANK_TOP_N` | Chunks passed to LLM | `5` |

---

