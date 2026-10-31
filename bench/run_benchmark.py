"""Run the pipeline on the 9 user-story datasets and score it.

    python bench/run_benchmark.py --rounds 1                 # full pipeline + single-pass baseline
    python bench/run_benchmark.py --variants full --datasets ticket --rounds 1
    python bench/run_benchmark.py --plan                     # print the request count, no API calls

Two protocols per variant:
- e2e:  classes and associations both extracted by the pipeline (the realistic setting);
- gold: associations extracted given the gold class list (the paper's protocol, comparable
        with its association numbers).

Raw outputs go to <out>/<variant>/<dataset>/<protocol>_r<round>.json; re-running skips
outputs that already exist, so an interrupted run can be resumed with the same --out.
"""

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bench"))
from evaluate import (DATASETS, gold_class_names, load_gold, macro,  # noqa: E402
                      score_associations, score_classes)
from ontoextract import Config, Pipeline, make_llm  # noqa: E402

STORIES = ROOT / "vendor/VisualNarrator-v2/data/user_stories"
VARIANTS = {
    "full": dict(samples=5, verify=True),
    "single": dict(samples=1, verify=False),
}
# GPT-o1 macro averages from Chou, Aydemir & Dalpiaz (RefSQ 2026), Tables 3-4.
PAPER = {"class": {"f0.5": .637, "f1": .663, "f2": .699},
         "assoc_gold": {"f0.5": .754, "f1": .782, "f2": .819}}


def requests_per_run(samples: int, verify: bool) -> dict:
    merge = 1 if samples > 1 else 0
    v = 1 if verify else 0
    return {"e2e": 2 * samples + merge + 2 * v, "gold": samples + v}


def run_one(args, variant: str, ds: str, protocol: str, rnd: int, gold: dict) -> Path:
    path = args.out / variant / ds / f"{protocol}_r{rnd}.json"
    if path.exists():
        return path
    text = (STORIES / f"{ds}.txt").read_text(encoding="utf-8")
    cfg = Config(kernel="legacy", attributes=False, workers=args.workers, min_support=args.min_support,
                 **VARIANTS[variant])
    llm = make_llm(args.backend, args.model, args.effort, args.max_tokens,
                   fallback=not args.no_fallback)
    given = gold_class_names(ds, gold) if protocol == "gold" else None
    result = Pipeline(text, llm, cfg).run(given_classes=given)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    cost = result["meta"]["cost_usd_estimate"]
    cost_text = f"~${cost:.2f}" if cost is not None else "subscription; cash cost not estimated"
    print(f"  {variant:6} {ds:13} {protocol:4} r{rnd}: {len(result['classes'])} classes, "
          f"{len(result['relations'])} relations, {cost_text}",
          file=sys.stderr)
    return path


def score(args, gold: dict) -> str:
    """Scores every saved output and writes scores.json and summary.md."""
    rows = []
    for path in sorted(args.out.glob("*/*/*_r*.json")):
        variant, ds = path.parent.parent.name, path.parent.name
        protocol, rnd = path.stem.split("_r")
        result = json.loads(path.read_text(encoding="utf-8"))
        rel = [(r["source"], r["target"]) for r in result["relations"]]
        row = {"variant": variant, "dataset": ds, "protocol": protocol, "round": int(rnd),
               "cost": result["meta"]["cost_usd_estimate"],
               "assoc": score_associations(rel, ds, gold)}
        if protocol == "e2e":
            row["class"] = score_classes([c["name"] for c in result["classes"]], ds, gold)
        rows.append(row)
    (args.out / "scores.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2))

    def avg(variant, protocol, key, ds=None):
        sel = [r[key] for r in rows if r["variant"] == variant and r["protocol"] == protocol
               and key in r and (ds is None or r["dataset"] == ds)]
        if ds is not None:
            return macro(sel)
        per_ds = [macro([r[key] for r in rows if r["variant"] == variant and r["dataset"] == d
                         and r["protocol"] == protocol and key in r]) for d in DATASETS]
        return macro([m for m in per_ds if m])

    variants = sorted({r["variant"] for r in rows})
    lines = [f"# Benchmark results ({args.out.name})", "",
             "Macro averages over datasets (each dataset averaged over its rounds). "
             "P = precision (validity), R = recall (completeness).", "",
             "| Setting | P | R | F0.5 | F1 | F2 | Datasets | Cost |", "|---|---|---|---|---|---|---|---|"]

    def line(label, m, n, cost):
        cost_text = f"${cost:.2f}" if cost is not None else "not estimated"
        return (f"| {label} | {m['precision']:.3f} | {m['recall']:.3f} | {m['f0.5']:.3f} "
                f"| {m['f1']:.3f} | {m['f2']:.3f} | {n} | {cost_text} |")

    for v in variants:
        for proto, key, label in [("e2e", "class", "classes"),
                                  ("e2e", "assoc", "associations, end to end"),
                                  ("gold", "assoc", "associations, given gold classes")]:
            m = avg(v, proto, key)
            if not m:
                continue
            sel = [r for r in rows if r["variant"] == v and r["protocol"] == proto]
            lines.append(line(f"{v}: {label}", m, len({r['dataset'] for r in sel}),
                              None if any(r["cost"] is None for r in sel) else sum(r["cost"] for r in sel)))
    lines += ["", "Paper reference (GPT-o1, same benchmark and scoring): classes F1 "
              f"{PAPER['class']['f1']}, associations given gold classes F1 {PAPER['assoc_gold']['f1']}. "
              "The paper reports no end-to-end association score.", "",
              "## Per dataset (F1)", "",
              "| Dataset | " + " | ".join(f"{v} class | {v} assoc e2e | {v} assoc gold" for v in variants) + " |",
              "|---|" + "---|" * (3 * len(variants))]
    for ds in DATASETS:
        cells = []
        for v in variants:
            for proto, key in [("e2e", "class"), ("e2e", "assoc"), ("gold", "assoc")]:
                m = avg(v, proto, key, ds)
                cells.append(f"{m['f1']:.3f}" if m else "–")
        lines.append(f"| {ds} | " + " | ".join(cells) + " |")
    summary = "\n".join(lines) + "\n"
    (args.out / "summary.md").write_text(summary, encoding="utf-8")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--datasets", default="all", help="comma-separated, or 'all'")
    ap.add_argument("--variants", default="full,single", help=f"from {list(VARIANTS)}")
    ap.add_argument("--protocols", default="e2e,gold")
    ap.add_argument("--rounds", type=int, default=1)
    ap.add_argument("--backend", default="codex", choices=["auto", "codex", "api", "claude-code"])
    ap.add_argument("--model", default=None)
    ap.add_argument("--effort", default="high")
    ap.add_argument("--min-support", type=float, default=0.5)
    ap.add_argument("--max-tokens", type=int, default=32000)
    ap.add_argument("--workers", type=int, default=4, help="parallel requests per stage")
    ap.add_argument("--parallel-runs", type=int, default=2, help="pipeline runs at once")
    ap.add_argument("--no-fallback", action="store_true")
    ap.add_argument("--out", type=Path,
                    default=ROOT / "runs" / datetime.now().strftime("%Y%m%d-%H%M%S"))
    ap.add_argument("--plan", action="store_true", help="print the request count and exit")
    ap.add_argument("--score-only", action="store_true", help="re-score saved outputs")
    args = ap.parse_args()

    datasets = DATASETS if args.datasets == "all" else args.datasets.split(",")
    variants = args.variants.split(",")
    protocols = args.protocols.split(",")
    jobs = [(v, ds, p, r) for v in variants for ds in datasets for p in protocols
            for r in range(1, args.rounds + 1)]

    if args.plan:
        total = sum(requests_per_run(**VARIANTS[v])[p] for v, _, p, _ in jobs)
        print(f"{len(jobs)} pipeline runs, {total} model requests")
        return
    gold = load_gold()
    if not args.score_only:
        print(f"running {len(jobs)} pipeline runs -> {args.out}", file=sys.stderr)
        with ThreadPoolExecutor(args.parallel_runs) as pool:
            futures = [pool.submit(run_one, args, *job, gold) for job in jobs]
            errors = 0
            for f in futures:
                try:
                    f.result()
                except Exception as e:  # keep the other runs going; re-run resumes
                    errors += 1
                    print(f"  run failed: {type(e).__name__}: {e}", file=sys.stderr)
        if errors:
            print(f"{errors} runs failed; re-run with --out {args.out} to resume", file=sys.stderr)
    print(score(args, gold))


if __name__ == "__main__":
    main()
