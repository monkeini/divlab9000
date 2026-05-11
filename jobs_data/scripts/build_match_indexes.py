from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

DEFAULT_EMBEDDING_MODEL = "BAAI/bge-base-en-v1.5"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build local CV/job matching indexes.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild even if the corpus is unchanged.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_EMBEDDING_MODEL,
        help=f"SentenceTransformer model name. Defaults to {DEFAULT_EMBEDDING_MODEL}.",
    )
    return parser.parse_args()


def main() -> None:
    from jobs_api.database import connect
    from jobs_api.matching import ensure_indexes

    args = parse_args()
    with connect() as connection:
        result = ensure_indexes(connection, force=args.force, model_name=args.model)
    verb = "Built" if result.built else "Skipped current"
    print(
        f"{verb} matching indexes for {result.job_count} jobs "
        f"using {result.model_name} ({result.fingerprint})."
    )
    print(f"Metadata: {result.metadata_path}")


if __name__ == "__main__":
    main()
