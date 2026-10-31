"""Sanity check for evaluate.py: score the paper's published GPT-o1 outputs and compare
with the F1 values reported in Chou, Aydemir & Dalpiaz (RefSQ 2026), Tables 3 and 4.

    python bench/check_baseline.py
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evaluate import DATASETS, load_gold, macro, score_associations, score_classes  # noqa: E402

EXTRACTED = Path(__file__).resolve().parent.parent / \
    "vendor/VisualNarrator-v2/thesis-artifacts/Extracted_Data"
# GPT-o1 F1 per dataset as printed in the paper.
PAPER_CLASS_F1 = {"recycling": .453, "supermarket": .764, "planningpoker": .700,
                  "camperplus": .747, "grocery": .688, "sports": .682, "ticket": .648,
                  "school": .638, "fish&chips": .649}
PAPER_ASSOC_F1 = {"recycling": .578, "supermarket": .925, "planningpoker": .832,
                  "camperplus": .671, "grocery": .809, "sports": .789, "ticket": .918,
                  "school": .682, "fish&chips": .833}
OPT = re.compile(r"^\((?:opt|optional)\)\s*", re.I)


def rounds(kind: str, ds: str) -> list[list[str]]:
    files = sorted((EXTRACTED / kind / "GPT-o1" / ds).glob(f"extracted_{kind}_round*.txt"))
    return [[l.strip() for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
            for f in files]


def main() -> None:
    gold = load_gold()
    print(f"{'dataset':14} {'class F1 (ours / paper)':>24} {'assoc F1 (ours / paper)':>26}")
    cls_rows, asc_rows = [], []
    for ds in DATASETS:
        c = [score_classes([OPT.sub("", w) for w in r], ds, gold) for r in rounds("class", ds)]
        a = [score_associations([tuple(OPT.sub("", w).split("-", 1)) for w in r if "-" in w],
                                ds, gold) for r in rounds("association", ds)]
        cm, am = macro(c), macro(a)
        cls_rows.append(cm)
        asc_rows.append(am)
        print(f"{ds:14} {cm['f1']:>14.3f} / {PAPER_CLASS_F1[ds]:.3f} "
              f"{am['f1']:>16.3f} / {PAPER_ASSOC_F1[ds]:.3f}")
    print(f"{'macro':14} {macro(cls_rows)['f1']:>14.3f} / 0.663 "
          f"{macro(asc_rows)['f1']:>16.3f} / 0.782")


if __name__ == "__main__":
    main()
