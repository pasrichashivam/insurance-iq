"""Backtrack a RAG answer to its sources.

Shows exactly which PDF chunks (file + page + text) the retriever returns for a question, i.e. the evidence the LLM
was given. Run from the backend/ folder (needs the PDFs indexed and GOOGLE_API_KEY, same as the app):

    python -m rag.trace_sources "How many days does Florida allow to accept or deny a claim?"
    python -m rag.trace_sources "authority limits" multiquery
    python -m rag.trace_sources "authority limits" contextual
"""
import sys

from rag.retrieval import STRATEGIES


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    question = sys.argv[1]
    strategy = sys.argv[2] if len(sys.argv) > 2 else "similarity"
    docs = STRATEGIES[strategy](question)
    print(f"{len(docs)} chunk(s) retrieved with '{strategy}' for: {question}\n")
    for i, d in enumerate(docs, 1):
        page = d.metadata.get("page")
        print(f"--- [{i}] source={d.metadata.get('source')}  page={'?' if page is None else page + 1}")
        print(d.page_content.strip(), "\n")


if __name__ == "__main__":
    main()
