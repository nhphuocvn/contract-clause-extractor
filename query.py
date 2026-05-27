"""Ask a natural-language question against the indexed contract portfolio.

Embeds the question, retrieves the most relevant chunks from ChromaDB, then
answers via GPT-4o-mini with explicit source citations.
"""

import argparse
import os
import sys
from typing import TypedDict

from dotenv import load_dotenv
from openai import OpenAI

from index import EMBEDDING_MODEL, get_collection

load_dotenv()


ANSWER_MODEL = "gpt-4o-mini"
DEFAULT_TOP_K = 5


SYSTEM_PROMPT = (
    "You answer questions about a portfolio of commercial contracts. Use only the "
    "excerpts provided. Cite the sources you rely on using the [N] markers shown. "
    "When comparing contracts, name them explicitly. If the excerpts do not contain "
    "the answer, say so plainly rather than guessing."
)


class Citation(TypedDict):
    index: int
    contract: str
    section_number: int
    section_title: str
    distance: float


class Answer(TypedDict):
    question: str
    answer: str
    citations: list[Citation]


def answer_question(
    client: OpenAI,
    collection,
    question: str,
    top_k: int = DEFAULT_TOP_K,
) -> Answer:
    """Run a RAG query: embed → search → generate with citations."""
    q_resp = client.embeddings.create(model=EMBEDDING_MODEL, input=question)
    q_emb = q_resp.data[0].embedding

    results = collection.query(
        query_embeddings=[q_emb],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )

    docs = results["documents"][0]
    metas = results["metadatas"][0]
    distances = results["distances"][0]

    if not docs:
        return Answer(
            question=question,
            answer="No indexed contracts found. Run `python index.py contracts/` first.",
            citations=[],
        )

    context_lines = []
    for i, (doc, meta) in enumerate(zip(docs, metas)):
        cite_label = (
            f"[{i + 1}] {meta['contract_name']} — "
            f"Section {meta['section_number']}: {meta['section_title']}"
        )
        context_lines.append(f"{cite_label}\n{doc}")
    context = "\n\n---\n\n".join(context_lines)

    user_prompt = (
        f"Excerpts from the contract portfolio:\n\n{context}\n\n"
        f"Question: {question}"
    )

    completion = client.chat.completions.create(
        model=ANSWER_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0,
    )
    answer_text = completion.choices[0].message.content or ""

    citations: list[Citation] = [
        Citation(
            index=i + 1,
            contract=meta["contract_name"],
            section_number=int(meta["section_number"]),
            section_title=meta["section_title"],
            distance=float(dist),
        )
        for i, (meta, dist) in enumerate(zip(metas, distances))
    ]

    return Answer(question=question, answer=answer_text, citations=citations)


def main() -> int:
    parser = argparse.ArgumentParser(description="Ask a question against indexed contracts.")
    parser.add_argument("question", help="Natural-language question")
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K, help=f"Chunks to retrieve (default: {DEFAULT_TOP_K})")
    args = parser.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Error: OPENAI_API_KEY is not set (add it to .env).", file=sys.stderr)
        return 2

    client = OpenAI(api_key=api_key)
    collection = get_collection()
    if collection.count() == 0:
        print("Error: collection is empty. Run `python index.py contracts/` first.", file=sys.stderr)
        return 1

    result = answer_question(client, collection, args.question, top_k=args.top_k)

    print(f"\nQ: {result['question']}\n")
    print(f"A: {result['answer']}\n")
    print("Sources:")
    for c in result["citations"]:
        print(
            f"  [{c['index']}] {c['contract']} — "
            f"Section {c['section_number']}: {c['section_title']} "
            f"(distance={c['distance']:.3f})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
