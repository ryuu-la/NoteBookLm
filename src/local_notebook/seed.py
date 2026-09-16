from . import storage as db
from .ingestion.jobs import add_file

SAMPLES = [
    ("The science of learning", "Small habits, stronger memories. Explore how we learn and make knowledge stick.",
     "psychology", "blue", [
         ("Retrieval practice.md", """Retrieval practice

This is an original sample study note for exploring Folio, not a published research paper.

Retrieval practice means trying to recall information before checking the answer. A student closes a textbook and writes what they remember, then compares the result with the source. This makes gaps in understanding visible. Rereading can create familiarity without demonstrating that the learner can recall the idea independently.

A useful study routine has three steps: attempt a question without notes, check the answer against the source, and correct the explanation in your own words. Feedback matters because an uncorrected mistake can persist. Questions should test both definitions and how a concept applies in a new situation.

For example, after learning about photosynthesis, explain how light energy becomes stored chemical energy without looking at the page. Then check your explanation and revisit missing steps. This activity tests understanding rather than recognition.

Retrieval practice and spaced practice complement each other. Retrieval describes what happens during a session; spacing describes when sessions happen. A quiz with feedback can combine both when a learner returns to it after a delay.
"""),
         ("Spacing and interleaving.md", """Spacing and interleaving

This is an original sample study note provided with Folio.

Spaced practice distributes study sessions across time instead of concentrating all practice in one sitting. A sample schedule reviews an idea on day one, day three, and day seven. These intervals are an illustration, not a universal optimal schedule. The useful interval depends on the learner, material, and intended retention period.

Interleaving mixes related problem types so the learner must identify which strategy fits. A mathematics session might alternate linear equations, quadratic equations, and word problems. Blocked practice repeats one type before moving to another. Interleaving can initially feel harder because the strategy is not announced by the block.

Combine spacing with retrieval: begin each session with a short closed-book explanation, check the source, then practice a related problem. Record mistakes so the next session can target them. Sustainable study routines also make time for rest and realistic breaks.
"""),
         ("A practical study system.md", """A practical study system

This original sample illustrates how a notebook can connect several sources.

Build a weekly study loop around four actions: collect reliable sources, explain the central ideas, test recall, and reflect on mistakes. A source library is useful only when the learner can find evidence and distinguish it from their own interpretation.

Good notes capture a central claim, a supporting example, and a question that remains open. Mind maps help display connections between ideas. Quizzes help identify recall gaps. Reports help synthesize a topic into an organized explanation. Each tool serves a different purpose; none replaces checking original evidence.

When studying a complex topic, compare two explanations and identify where they agree or disagree. Cite the source location for each claim. If a source does not answer a question, record the uncertainty instead of inventing an explanation.
""")]),
    ("Inside artificial intelligence", "From embeddings to grounded answers. A field guide to the ideas behind modern AI.",
     "hub", "purple", [
         ("Understanding RAG.md", """Understanding retrieval-augmented generation

This is an original introductory sample, not a benchmark or a published research source.

Retrieval-augmented generation (RAG) combines a search system with a language model. Documents are parsed into passages. An embedding model maps passages to numeric vectors. A query is embedded using the same model, and vector similarity finds semantically related passages.

Keyword search complements vector search by matching exact names, codes, and technical terms. A hybrid retriever combines both rankings. Reciprocal rank fusion adds a decreasing score based on each result's position in each ranking. A cross-encoder reranker then compares the question and candidate passage together to improve relevance ordering.

The language model receives selected passages as evidence and generates an answer. Citations should link claims to their original source locations. RAG does not guarantee truth: poor parsing, missing evidence, irrelevant retrieval, or unsupported generation can still produce errors. Evaluation should measure retrieval recall and citation support separately.

Large libraries require batching, persistent indexes, bounded memory, and cancellation. A large context window does not remove the need to choose evidence carefully. Broad summaries also require coverage across documents rather than only the nearest passages to one question.
""")]),
]


def seed() -> None:
    if db.one("SELECT value FROM settings WHERE key='sample_seeded'"):
        return
    if not db.notebooks():
        for title, description, icon, color, sources in SAMPLES:
            notebook_id = db.create_notebook(title, description, icon, color)
            for name, text in sources:
                add_file(notebook_id, name, text.encode())
        db.save_settings({"sample_seeded": True})
