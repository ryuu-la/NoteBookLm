# RAG behavior and reproducible evaluations

Chat searches the **entire index of selected, ready sources**, then sends a bounded set
of relevant passages to the generation model. PDF extraction is one ingestion adapter;
it is not the chat answer. A missing model connection produces a setup error, never a
substitute answer made from pasted excerpts.

## Retrieval and grounded generation

1. Route the current question independently of previous conversation. A previous
   “key ideas” request must not turn a new FastAPI question into an overview.
2. Resolve referential follow-ups against conversation; explicit new topics stand alone.
3. Search SQLite FTS/BM25 and BGE embeddings with notebook/source filters applied before
   candidate selection. Resolve spaced compound names when the joined term exists in the
   selected index. Comparison requests also search their two aspects.
4. Fuse candidate rankings, rerank a bounded shortlist with MiniLM, deduplicate identical
   text, and fit the evidence to the prompt budget. The default rerank shortlist is 16.
5. Abstain when no evidence is found. In reranked mode, reject a query when even its
   strongest candidate scores below -8. This is a conservative heuristic on MiniLM logits,
   **not a calibrated confidence probability**. Evaluate it when changing models or domains.
6. Stream a synthesized answer grounded in those passages. Citation numbers resolve to
   the exact evidence sent to the model, including grouped references such as `[1, 2]`.

New semantic imports use the embedding model's own tokenizer, with 384-token chunks and
48-token overlap, preferring nearby sentence boundaries. This avoids the previous mismatch
between 600-token chunks and the embedder's 512-token limit. Old saved indexes remain readable;
use the source's Reindex action to apply the new chunk boundaries to an existing document.
Interrupted indexes from the older chunking version restart safely rather than reusing an
incompatible ordinal checkpoint.

Indexing keeps one SQLite connection open during a job while committing progress checkpoints,
avoiding repeated last-connection WAL checkpoints. Short embedding inputs use batches of 32;
long inputs retain batches of 16 to bound memory. Cancellation still checks between 64-passage
write batches. The [before/after fixture](rag-indexing-comparison.json) measured first indexing
at **8.05 → 7.42 s**, cached reindexing at **1.03 → 0.81 s**, and peak RSS at **420 → 385.4 MB**
for 1,000 short digital pages, with 5/5 exact-record retrieval probes in both runs. These are
single-run observations on the same machine, not timings for arbitrary PDFs or OCR.

Broad overview requests distribute their bounded evidence across sources and source
positions. They are not exhaustive page-by-page summaries. The scope stays in the model
context and artifact metadata; it is not displayed as a loading banner in chat. Full-index
retrieval does not mean every passage is inserted into every prompt.

## Run the evaluations

```powershell
# Regression tests and an API-free CI gate
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe benchmarks/rag.py --keyword --output test-results/rag-keyword.json

# Actual local embeddings + reranker, plus the existing ranking benchmark
.venv/Scripts/python.exe benchmarks/rag.py
.venv/Scripts/python.exe benchmarks/retrieval.py

# Live generation + a separate model judging claim support (provider usage applies)
# Keys come from the project .env or process environment, never CLI arguments.
.venv/Scripts/python.exe benchmarks/rag.py --answers --model gemini-3.5-flash-lite --judge-model gemini-3.8-flash --output test-results/rag-live.json
```

`benchmarks/rag_cases.py` contains explicit relevance judgments and reference facts for
12 conversation cases over 8 factual topic passages and 240 repetitive archive distractors.
These prepared chunks bypass parsing and chunking; the count does not represent 248 diverse
documents or facts. This is a routing/scope regression suite, not a realistic long-document
accuracy benchmark. It covers the reported follow-up, spaced names,
pronouns, topic switches, paraphrases, two-source comparisons, limitations, and absent
answers. Additional deselected and other-notebook canaries check scope isolation.

The older benchmark has 54 questions over 40 authored passages and compares lexical,
hybrid, and reranking configurations. Recall@8 measures labeled evidence coverage; MRR
and nDCG measure ranking. [Metric definitions](https://www.sbert.net/docs/package_reference/sentence_transformer/evaluation.html).

The live mode separately records answers, generation durations, citation validity,
reference completeness, correctness, and individual claim judgments. A supported claim
must have a cited evidence number and a supporting quote that exists verbatim in that
passage. Semantic entailment is model-judged; exact quote checks alone do not establish it.
Unsupported claims and fabricated judge quotes lower the score. Reference answers list
required facts; extra source-supported detail is allowed. Abstentions are scored separately.
The claim-support summary is an average of per-answer fractions, excluding answers with no
judged claims; it is not a fraction of all factual claims. The judge may miss claims entirely.
Current live runs call the generator even when retrieval is empty, then separately report
retrieval rejection and model-judged refusal accuracy. A distinct judge model is required
unless `--allow-self-judge` explicitly opts into a non-independent diagnostic.
Quote audit failures and contradictory verdicts require review; raw verdicts are preserved.

The suite fails on scope/routing violations, a missed answerable regression, mean recall
below 0.9, or a false evidence match for either unanswerable case. Live gates additionally
require correctness and supported-claim fraction at least 0.9, completeness at least 0.8,
and valid citations on answerable cases. CI runs the keyword gate without downloading models
or using API credentials. Run hybrid and live evaluations before a retrieval/model release.

## Inspect results

Open `/benchmarks` for per-question evidence and downloadable JSON. Reports record the
fixture hash, model names, mode, timestamp, and whether answers were actually generated.
API-free runs must not be presented as measured answer accuracy.
The default output is `test-results/rag-evaluation.json`, so an API-free run cannot silently
replace the published live-answer report. Publishing to the app requires an explicit
`--output src/local_notebook/assets/rag-evaluation.json` after reviewing the intended run.

These are developer-authored regression fixtures, not held-out real-user accuracy claims.
They do not cover scanned-document OCR quality, every language, or every domain. A model
judge can be wrong; inspect its claim/quote records and retain failed reports when iterating.
The initial live report is retained under `test-results/rag-live-answers.json`; it exposed
grouped-citation parsing and inconsistent judge interpretations of additional supported facts.

The committed live run used Flash Lite for both generator and judge after the separate judge
returned provider errors. It retrieved all labeled evidence, resolved all citations, and scored
96.7% on the quote-audited supported-claim metric. Its raw correctness verdict was 10/12, but
two negative verdicts contradicted the judge's own fully-supported, complete claim assessments.
The report is deliberately marked **needs review**, with both contradictions flagged. Do not
treat this as an independent answer-accuracy score or turn it into a claimed 100% result.
Its two empty-evidence answers were fixed refusal text, not model responses: the observed
2/2 retrieval rejections do not establish LLM refusal accuracy. Its 96.7% support score also
includes a judge quote containing an ellipsis, which failed verbatim verification. The newer
audit flags that failure for review as well; the historical report retains its original
two review flags and original measurements. This run has not been replaced by a new live test.

On 2026-09-29, the API-free [hybrid regression run](benchmark-history/rag-retrieval-2026-09-29.json)
passed with Recall@8 1.0000, MRR@8 0.9500, nDCG@8 0.9631, 2/2 retrieval rejections,
and 115 ms median / 134 ms p95 retrieval. The [keyword run](benchmark-history/rag-keyword-2026-09-29.json)
also passed. These new runs do not replace or resolve the failed historical live-answer evaluation.
