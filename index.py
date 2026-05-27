"""Index a folder of contracts into a local ChromaDB collection.

Splits each contract into chunks by numbered section, embeds each chunk with
OpenAI text-embedding-3-small, and stores them with contract/section metadata.
"""

import argparse
import os
import re
import sys
from pathlib import Path

import chromadb
from dotenv import load_dotenv
from openai import OpenAI

from extract import read_contract

load_dotenv()


CHROMA_PATH = "./chroma_db"
COLLECTION_NAME = "contracts"
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_BATCH = 64

# Match numbered section headers like "1. TERM AND RENEWAL" on their own line.
SECTION_HEADER = re.compile(
    r"^\s*(\d+)\.\s+([A-Z][A-Z0-9\s/&\-,]+?)\s*$",
    re.MULTILINE,
)


def chunk_contract(text: str, contract_name: str) -> list[dict]:
    """Split a contract into section-level chunks with metadata."""
    chunks: list[dict] = []
    matches = list(SECTION_HEADER.finditer(text))

    if not matches:
        return [{
            "id": f"{contract_name}::full",
            "text": text.strip(),
            "metadata": {
                "contract_name": contract_name,
                "section_number": 0,
                "section_title": "Full document",
            },
        }]

    first_start = matches[0].start()
    preamble = text[:first_start].strip()
    if preamble:
        chunks.append({
            "id": f"{contract_name}::preamble",
            "text": preamble,
            "metadata": {
                "contract_name": contract_name,
                "section_number": 0,
                "section_title": "Preamble",
            },
        })

    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        section_num = int(m.group(1))
        section_title = m.group(2).strip()
        section_text = text[start:end].strip()
        chunks.append({
            "id": f"{contract_name}::section-{section_num}",
            "text": section_text,
            "metadata": {
                "contract_name": contract_name,
                "section_number": section_num,
                "section_title": section_title,
            },
        })

    return chunks


def embed_texts(client: OpenAI, texts: list[str]) -> list[list[float]]:
    """Embed a list of texts in batches."""
    embeddings: list[list[float]] = []
    for i in range(0, len(texts), EMBEDDING_BATCH):
        batch = texts[i:i + EMBEDDING_BATCH]
        resp = client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
        embeddings.extend([d.embedding for d in resp.data])
    return embeddings


def get_collection():
    """Return the persistent Chroma collection, creating it if needed."""
    db_client = chromadb.PersistentClient(path=CHROMA_PATH)
    return db_client.get_or_create_collection(name=COLLECTION_NAME)


def index_folder(folder: Path, client: OpenAI) -> tuple[int, int]:
    """Index every supported contract in `folder`. Returns (n_chunks, n_contracts)."""
    collection = get_collection()

    paths = sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in {".txt", ".pdf", ".md"}
    )
    if not paths:
        print(f"No .txt/.pdf/.md files found in {folder}", file=sys.stderr)
        return 0, 0

    all_chunks: list[dict] = []
    for path in paths:
        print(f"  reading {path.name}...")
        try:
            text = read_contract(path)
        except Exception as exc:
            print(f"    [skip] {exc}", file=sys.stderr)
            continue
        contract_chunks = chunk_contract(text, path.name)
        all_chunks.extend(contract_chunks)
        print(f"    -> {len(contract_chunks)} chunks")

    if not all_chunks:
        return 0, 0

    print(f"\n  embedding {len(all_chunks)} chunks with {EMBEDDING_MODEL}...")
    embeddings = embed_texts(client, [c["text"] for c in all_chunks])

    print(f"  upserting into Chroma collection '{COLLECTION_NAME}'...")
    collection.upsert(
        ids=[c["id"] for c in all_chunks],
        embeddings=embeddings,
        documents=[c["text"] for c in all_chunks],
        metadatas=[c["metadata"] for c in all_chunks],
    )

    return len(all_chunks), len(paths)


def main() -> int:
    parser = argparse.ArgumentParser(description="Index a folder of contracts into ChromaDB.")
    parser.add_argument("folder", nargs="?", default="contracts", help="Folder of contracts (default: contracts/)")
    args = parser.parse_args()

    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"Error: {folder} is not a directory", file=sys.stderr)
        return 2

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Error: OPENAI_API_KEY is not set (add it to .env).", file=sys.stderr)
        return 2

    client = OpenAI(api_key=api_key)

    print(f"Indexing {folder}/ ...")
    n_chunks, n_contracts = index_folder(folder, client)

    if n_chunks == 0:
        print("Nothing indexed.")
        return 1

    collection = get_collection()
    total = collection.count()
    print(f"\nIndexed {n_chunks} chunks from {n_contracts} contract(s).")
    print(f"Collection '{COLLECTION_NAME}' now contains {total} chunks total.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
