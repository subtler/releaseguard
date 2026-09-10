"""ReleaseGuard command-line interface."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from releaseguard.adapters.git_local import RepositoryAccessError
from releaseguard.bootstrap import build_analyzer
from releaseguard.domain.policy import DeterministicRiskPolicy
from releaseguard.evaluation.policy import PolicyEvaluator
from releaseguard.evaluation.retrieval import RetrievalEvaluator


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI parser."""
    parser = argparse.ArgumentParser(prog="releaseguard")
    subparsers = parser.add_subparsers(dest="command", required=True)
    analyze = subparsers.add_parser("analyze", help="analyze a local Git comparison")
    analyze.add_argument("--repository", required=True, type=Path)
    analyze.add_argument("--base-ref", required=True)
    analyze.add_argument("--head-ref", required=True)
    evaluate = subparsers.add_parser("evaluate", help="run the versioned policy evaluation suite")
    evaluate.add_argument("--dataset", type=Path, default=Path("evals/deterministic_policy.json"))
    evaluate.add_argument("--min-status-accuracy", type=float, default=1.0)
    evaluate.add_argument("--min-category-f1", type=float, default=1.0)
    evaluate_retrieval = subparsers.add_parser(
        "evaluate-retrieval", help="run the frozen hybrid-retrieval benchmark"
    )
    evaluate_retrieval.add_argument("--dataset", type=Path, default=Path("evals/retrieval.json"))
    evaluate_retrieval.add_argument("--top-k", type=int, default=3)
    evaluate_retrieval.add_argument("--min-recall-at-k", type=float, default=1.0)
    evaluate_retrieval.add_argument("--min-mrr", type=float, default=1.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process status."""
    args = build_parser().parse_args(argv)
    if args.command == "analyze":
        try:
            report = build_analyzer().execute(args.repository, args.base_ref, args.head_ref)
        except (RepositoryAccessError, ValidationError) as exc:
            print(f"analysis failed: {exc}", file=sys.stderr)
            return 1
        print(report.model_dump_json(indent=2))
        return 0
    if args.command == "evaluate":
        try:
            policy_result = PolicyEvaluator(DeterministicRiskPolicy()).evaluate_file(
                args.dataset,
                min_status_accuracy=args.min_status_accuracy,
                min_category_f1=args.min_category_f1,
            )
        except (OSError, ValueError, ValidationError) as exc:
            print(f"evaluation failed: {exc}", file=sys.stderr)
            return 1
        print(policy_result.model_dump_json(indent=2))
        return 0 if policy_result.passed else 1
    if args.command == "evaluate-retrieval":
        try:
            retrieval_result = RetrievalEvaluator().evaluate_file(
                args.dataset,
                top_k=args.top_k,
                min_recall_at_k=args.min_recall_at_k,
                min_mean_reciprocal_rank=args.min_mrr,
            )
        except (OSError, ValueError, ValidationError) as exc:
            print(f"retrieval evaluation failed: {exc}", file=sys.stderr)
            return 1
        print(retrieval_result.model_dump_json(indent=2))
        return 0 if retrieval_result.passed else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
