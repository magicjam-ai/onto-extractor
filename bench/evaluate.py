"""Scoring against the Bragilovski et al. benchmark as revised by Chou, Aydemir & Dalpiaz
(RefSQ 2026, replication package VisualNarrator-v2).

This re-implements their matching rules so results are comparable with the paper:
- names are lowercased and singularized (inflect), with their keyword exceptions;
- an exact pass against gold, then silver, then a synonym pass (substring replacement
  using their synonym dictionary);
- gold elements are mandatory (missed -> false negative); silver elements are optional
  (found -> true positive, missed -> no penalty);
- for classes, unmatched subclasses of a matched "non-punish" parent are not false positives;
- associations are unordered pairs.

The gold data is read from the repository's config.py with ast.literal_eval (never executed).
"""

import ast
import re
from pathlib import Path

import inflect

CONFIG = Path(__file__).resolve().parent.parent / "vendor/VisualNarrator-v2/src/class_assoc_pipeline/config.py"
DATASETS = ["camperplus", "fish&chips", "grocery", "planningpoker", "recycling",
            "school", "sports", "supermarket", "ticket"]

_p = inflect.engine()
_KEEP = {"class", "process", "progress", "academic progress", "address", "delivery address",
         "deliveryaddres", "status", "order status", "business"}


def normalize_word(word: str) -> str:
    lowered = word.lower().strip() if isinstance(word, str) else ""
    if not lowered or lowered in _KEEP:
        return lowered
    return _p.singular_noun(lowered) or lowered


def load_gold(config_path: Path = CONFIG) -> dict:
    tree = ast.parse(config_path.read_text(encoding="utf-8"))
    wanted = {"GOLD_STANDARD_CLASS", "SILVER_STANDARD_CLASS", "GOLD_STANDARD_ASSOCIATION",
              "SILVER_STANDARD_ASSOCIATION", "SYNONYM_DICT_CLASS", "NON_PUNISH_CLASS"}
    data = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id in wanted:
            data[node.targets[0].id] = ast.literal_eval(node.value)
    missing = wanted - data.keys()
    if missing:
        raise ValueError(f"config.py lacks {missing}")
    return data


def _synonyms(gold: dict, ds: str) -> dict:
    return {normalize_word(syn): normalize_word(std)
            for std, syns in gold["SYNONYM_DICT_CLASS"].get(ds, {}).items() for syn in syns}


def _candidates(element: str, mapping: dict) -> set:
    cands = {element}
    for key, val in mapping.items():
        new = set(cands)
        for c in cands:
            if key in c:
                new.add(c.replace(key, val).strip())
        cands = new
    return cands


def metrics(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0

    def f(beta):
        return (1 + beta**2) * p * r / (beta**2 * p + r) if p + r else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": p, "recall": r,
            "f0.5": f(0.5), "f1": f(1), "f2": f(2)}


def score_classes(predicted: list[str], ds: str, gold: dict) -> dict:
    gold_set = {normalize_word(x) for x in gold["GOLD_STANDARD_CLASS"][ds]}
    silver = {normalize_word(x) for x in gold["SILVER_STANDARD_CLASS"].get(ds, [])}
    syn = _synonyms(gold, ds)
    words = [normalize_word(re.sub(r"\([^)]*\)", "", w).strip()) for w in predicted]
    words = [w for w in words if w]

    remaining_gold, remaining_silver = set(gold_set), set(silver)
    matched, unmatched, pending = [], [], []
    for w in words:  # exact pass
        variants = w.split("/") if "/" in w else [w]
        hit = next((v for v in variants if v in remaining_gold or v in remaining_silver), None)
        if hit is None:
            pending.append(w)
            continue
        (remaining_gold if hit in remaining_gold else remaining_silver).discard(hit)
        matched.append(w)
    for w in pending:  # synonym pass
        variants = w.split("/") if "/" in w else [w]
        hit = None
        for v in variants:
            for c in _candidates(v, syn):
                if c in remaining_gold or c in remaining_silver:
                    hit = c
                    break
            if hit:
                break
        if hit is None:
            unmatched.append(w)
        else:
            (remaining_gold if hit in remaining_gold else remaining_silver).discard(hit)
            matched.append(w)

    # Non-punish: subclasses of a matched parent concept are not false positives.
    matched_set = set(matched)
    pruned = []
    for w in unmatched:
        skip = False
        for parent, children in gold["NON_PUNISH_CLASS"].get(ds, {}).items():
            kids = {normalize_word(c) for c in children}
            if (normalize_word(parent) in matched_set or kids & matched_set) and w in kids:
                skip = True
                break
        if not skip:
            pruned.append(w)

    return {**metrics(len(matched), len(pruned), len(remaining_gold)),
            "false_positives": pruned, "missed": sorted(remaining_gold)}


def score_associations(predicted: list[tuple[str, str]], ds: str, gold: dict) -> dict:
    gold_set = {frozenset(map(normalize_word, p)) for p in gold["GOLD_STANDARD_ASSOCIATION"][ds]}
    silver = {frozenset(map(normalize_word, p))
              for p in gold["SILVER_STANDARD_ASSOCIATION"].get(ds, [])}
    syn = _synonyms(gold, ds)
    pairs = [tuple(sorted((normalize_word(x), normalize_word(y)))) for x, y in predicted]

    remaining_gold, remaining_silver = set(gold_set), set(silver)
    matched, unmatched = [], []
    for x, y in pairs:
        pair = frozenset({x, y})
        hit = pair if pair in remaining_gold or pair in remaining_silver else None
        if hit is None:
            cands = [frozenset({cx, cy}) for cx in _candidates(x, syn) for cy in _candidates(y, syn)]
            hit = next((c for c in cands if c in remaining_gold), None) \
                or next((c for c in cands if c in remaining_silver), None)
        if hit is None:
            unmatched.append(f"{x} - {y}")
        else:
            (remaining_gold if hit in remaining_gold else remaining_silver).discard(hit)
            matched.append(f"{x} - {y}")

    return {**metrics(len(matched), len(unmatched), len(remaining_gold)),
            "false_positives": unmatched,
            "missed": sorted(" - ".join(sorted(p)) for p in remaining_gold)}


def macro(rows: list[dict], keys=("precision", "recall", "f0.5", "f1", "f2")) -> dict:
    return {k: sum(r[k] for r in rows) / len(rows) for k in keys} if rows else {}


def gold_class_names(ds: str, gold: dict) -> list[str]:
    """Class list given to the association stage in the paper's protocol."""
    return list(gold["GOLD_STANDARD_CLASS"][ds])
