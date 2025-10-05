# scripts/index_writer.py

import argparse
from ..domain.faiss_embeddings import Embedder, SimpleDocument
from ..infra.vector.faiss_store import FAISSVectorStore
from typing import List


def load_raw_documents(input_path: str) -> List[SimpleDocument]:
    # TODO: JSONL 등에서 SimpleDocument 리스트로 로드
    pass

def build_index(
    docs: List[SimpleDocument],
    dim: int,
    index_path: str,
    docs_path: str,
    model_name: str,
):
    # TODO: 임베딩 + 벡터스토어 추가 + 저장
    pass

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=str, required=True)
    parser.add_argument("--index_path", type=str, default="index.faiss")
    parser.add_argument("--docs_path", type=str, default="index_docs.json")
    parser.add_argument("--model", type=str, default="BAAI/bge-m3")
    parser.add_argument("--dim", type=int, default=1024)

    args = parser.parse_args()

    docs = load_raw_documents(args.input)
    build_index(docs, args.dim, args.index_path, args.docs_path, args.model)


if __name__ == "__main__":
    main()
