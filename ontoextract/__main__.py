"""CLI: python -m ontoextract DOC [DOC ...] -o OUT_DIR

Writes <name>.json (full result, including rejected candidates and evidence) and
<name>.md (a review sheet) plus <name>.review.html (local review) per document.
Use --combine for a shared model across documents.
"""

import argparse
import json
import sys
from pathlib import Path

from .llm import make_llm
from .pipeline import Config, Pipeline
from .report import to_markdown
from .review import to_html


def read_document(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader
        return "\n".join(p.extract_text() or "" for p in PdfReader(path).pages)
    if suffix == ".docx":
        import docx  # python-docx
        return "\n".join(p.text for p in docx.Document(path).paragraphs)
    return path.read_text(encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ontoextract", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("docs", nargs="+", type=Path, help=".txt, .md, .pdf or .docx")
    ap.add_argument("-o", "--out", type=Path, default=Path("output"))
    ap.add_argument("--combine", action="store_true",
                    help="treat all documents as one system and build one model")
    ap.add_argument("--backend", default="codex", choices=["auto", "codex", "api", "claude-code"],
                    help="codex/auto: local Codex subscription (default); api and claude-code are explicit legacy options")
    ap.add_argument("--model", default=None)
    ap.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument("--kernel", choices=["direct-tbox", "legacy"], default="direct-tbox")
    ap.add_argument("--samples", type=int, default=None)
    ap.add_argument("--min-support", type=float, default=0.5)
    ap.add_argument("--no-verify", action="store_true", help="skip the model verifier in legacy mode")
    ap.add_argument("--no-attributes", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--max-tokens", type=int, default=32000)
    ap.add_argument("--no-fallback", action="store_true",
                    help="do not send server-side refusal fallbacks")
    args = ap.parse_args(argv)
    if args.samples is not None and args.samples < 1:
        ap.error("--samples must be positive")
    if args.kernel == "direct-tbox" and args.samples not in (None, 1):
        ap.error("direct-tbox uses --samples 1; choose --kernel legacy for voting")

    cfg = Config(kernel=args.kernel, samples=args.samples or (1 if args.kernel == "direct-tbox" else 5), min_support=args.min_support,
                 verify=(args.kernel == "legacy" and not args.no_verify), attributes=not args.no_attributes,
                 workers=args.workers)
    if args.combine:
        text = "\n\n".join(f"## {p.name}\n\n{read_document(p)}" for p in args.docs)
        jobs = [("combined", text)]
    else:
        jobs = [(p.stem, read_document(p)) for p in args.docs]

    args.out.mkdir(parents=True, exist_ok=True)
    total = 0.0
    for name, text in jobs:
        llm = make_llm(args.backend, args.model, args.effort, args.max_tokens,
                       fallback=not args.no_fallback)
        print(f"[{name}] extracting ({len(text):,} chars)...", file=sys.stderr)
        result = Pipeline(text, llm, cfg).run()
        result["meta"]["source"] = name
        (args.out / f"{name}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        (args.out / f"{name}.md").write_text(to_markdown(result), encoding="utf-8")
        if args.kernel == "direct-tbox":
            (args.out / f"{name}.review.html").write_text(to_html(result, text), encoding="utf-8")
        cost = result["meta"]["cost_usd_estimate"]
        total += cost or 0.0
        cost_text = f"~${cost:.2f}" if cost is not None else "subscription; cash cost not estimated"
        print(f"[{name}] {len(result['classes'])} classes, {len(result['attributes'])} attributes, "
              f"{len(result['relations'])} relations; {cost_text}", file=sys.stderr)
    print(f"done; output in {args.out}/", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
