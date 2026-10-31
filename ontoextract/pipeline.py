"""Default direct-TBox proposals; explicit legacy staged extraction and voting."""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass

from . import prompts as P
from .llm import LLM
from .normalize import Grounder, norm_name


@dataclass
class Config:
    kernel: str = "direct-tbox"
    samples: int = 1          # independent extraction runs per stage
    min_support: float = 0.5  # share of runs that must propose an element
    verify: bool = False       # run the verifier pass
    attributes: bool = True   # run the attribute stage
    workers: int = 4          # parallel requests per stage


def _dedupe(items):
    return list(dict.fromkeys(i.strip() for i in items if i.strip()))


class Pipeline:
    def __init__(self, document: str, llm: LLM, cfg: Config = Config()):
        self.doc = document
        self.llm = llm
        self.cfg = cfg
        self.grounder = Grounder(document)

    # -- helpers ---------------------------------------------------------------

    def _call(self, task: str, schema: dict) -> dict:
        return self.llm.json_call(P.SYSTEM, self.doc, task, schema)

    def _sample(self, task: str, schema: dict) -> list[dict]:
        # The first call writes the document to the prompt cache; the rest read it.
        first = self._call(task, schema)
        k = self.cfg.samples
        if k == 1:
            return [first]
        with ThreadPoolExecutor(min(self.cfg.workers, k - 1)) as pool:
            rest = list(pool.map(lambda _: self._call(task, schema), range(k - 1)))
        return [first, *rest]

    def _verify(self, candidates: list[dict], label, task: str,
                categories: list[str]) -> None:
        """Adds a 'verdict' to each candidate in place."""
        if not self.cfg.verify or not candidates:
            for c in candidates:
                c["verdict"] = {"decision": "keep", "category": "unreviewed", "reason": ""}
            return
        ids = [f"{i + 1}" for i in range(len(candidates))]
        listing = "\n".join(f"[{i}] {label(c)} (agreement {c['support']:.0%})"
                            for i, c in zip(ids, candidates))
        out = self._call(task.format(candidates=listing), P.verify_schema(ids, categories))
        verdicts = {v["id"]: v for v in out["verdicts"]}
        for i, c in zip(ids, candidates):
            v = verdicts.get(i, {"decision": "keep", "category": "unreviewed", "reason": ""})
            c["verdict"] = {k: v[k] for k in ("decision", "category", "reason")}

    def _accept(self, c: dict) -> bool:
        return (c["support"] >= self.cfg.min_support and c["grounded"]
                and c["verdict"]["decision"] == "keep")

    # -- stages ----------------------------------------------------------------

    def classes(self) -> tuple[list[dict], list[dict]]:
        k = self.cfg.samples
        runs = self._sample(P.CLASSES_TASK, P.CLASSES_SCHEMA)
        found: dict[str, dict] = {}
        for i, run in enumerate(runs):
            for c in run["classes"]:
                name = norm_name(c["name"])
                if not name:
                    continue
                entry = found.setdefault(name, {"runs": set(), "definitions": [], "evidence": []})
                entry["runs"].add(i)
                entry["definitions"].append(c["definition"])
                entry["evidence"] += c["evidence"]

        candidates = []
        for canonical, members in self._merge(found):
            runs_hit = set().union(*(found[m]["runs"] for m in members))
            evidence = _dedupe(e for m in members for e in found[m]["evidence"])
            definition = (found.get(canonical) or found[members[0]])["definitions"][0]
            candidates.append({
                "name": canonical,
                "aliases": [m for m in members if m != canonical],
                "definition": definition,
                "support": len(runs_hit) / k,
                "grounded": self.grounder.any_grounded(evidence),
                "evidence": evidence[:4],
            })
        candidates.sort(key=lambda c: (-c["support"], c["name"]))
        self._verify(candidates, lambda c: f"{c['name']}: {c['definition']}",
                     P.VERIFY_CLASSES_TASK, P.CLASS_CATEGORIES)
        return ([c for c in candidates if self._accept(c)],
                [c for c in candidates if not self._accept(c)])

    def _merge(self, found: dict) -> list[tuple[str, list[str]]]:
        """Clusters synonymous class names across runs; returns (canonical, members)."""
        names = list(found)
        if self.cfg.samples == 1 or len(names) < 2:
            return [(n, [n]) for n in names]
        listing = "\n".join(f"- {n} (used by {len(found[n]['runs'])}): {found[n]['definitions'][0]}"
                            for n in names)
        task = P.MERGE_TASK.format(k=self.cfg.samples, candidates=listing)
        out = self._call(task, P.MERGE_SCHEMA)

        groups, assigned = [], set()
        for g in out["groups"]:
            members = [m for m in _dedupe(norm_name(x) for x in g["members"])
                       if m in found and m not in assigned]
            if not members:
                continue
            assigned.update(members)
            canonical = norm_name(g["canonical"])
            groups.append((canonical if canonical in members else members[0], members))
        groups += [(n, [n]) for n in names if n not in assigned]
        return groups

    def attributes(self, class_names: list[str]) -> list[dict]:
        k = self.cfg.samples
        task = P.ATTRIBUTES_TASK.format(classes="\n".join(f"- {n}" for n in class_names))
        runs = self._sample(task, P.attributes_schema(class_names))
        found: dict[tuple, dict] = {}
        class_set = set(class_names)
        for i, run in enumerate(runs):
            for a in run["attributes"]:
                name = norm_name(a["name"])
                if not name or name in class_set:  # a class-valued "attribute" is a relation
                    continue
                entry = found.setdefault((a["class"], name),
                                         {"runs": set(), "types": Counter(), "evidence": []})
                entry["runs"].add(i)
                entry["types"][a["datatype"]] += 1
                entry["evidence"] += a["evidence"]

        out = []
        for (cls, name), e in found.items():
            evidence = _dedupe(e["evidence"])
            out.append({"class": cls, "name": name,
                        "datatype": e["types"].most_common(1)[0][0],
                        "support": len(e["runs"]) / k,
                        "grounded": self.grounder.any_grounded(evidence),
                        "evidence": evidence[:3]})
        accepted = [a for a in out if a["support"] >= self.cfg.min_support and a["grounded"]]
        return sorted(accepted, key=lambda a: (a["class"], -a["support"], a["name"]))

    def relations(self, class_names: list[str]) -> tuple[list[dict], list[dict]]:
        k = self.cfg.samples
        task = P.RELATIONS_TASK.format(classes="\n".join(f"- {n}" for n in class_names))
        runs = self._sample(task, P.relations_schema(class_names))
        found: dict[tuple, dict] = {}
        for i, run in enumerate(runs):
            for r in run["relations"]:
                s, t = r["source"], r["target"]
                ms, mt = r["source_multiplicity"], r["target_multiplicity"]
                if r["kind"] == "generalization":
                    key = ("generalization", s, t)
                else:
                    if s > t:  # orient undirected relations consistently
                        s, t, ms, mt = t, s, mt, ms
                    key = ("relation", s, t)
                entry = found.setdefault(key, {"runs": set(), "kinds": Counter(), "names": Counter(),
                                               "mult": Counter(), "evidence": []})
                entry["runs"].add(i)
                entry["kinds"][r["kind"]] += 1
                entry["names"][r["name"].strip()] += 1
                entry["mult"][(ms, mt)] += 1
                entry["evidence"] += r["evidence"]

        candidates = []
        for (_, s, t), e in found.items():
            evidence = _dedupe(e["evidence"])
            ms, mt = e["mult"].most_common(1)[0][0]
            candidates.append({
                "source": s, "target": t,
                "kind": e["kinds"].most_common(1)[0][0],
                "name": e["names"].most_common(1)[0][0],
                "source_multiplicity": ms, "target_multiplicity": mt,
                "support": len(e["runs"]) / k,
                "grounded": self.grounder.any_grounded(evidence),
                "evidence": evidence[:3],
            })
        candidates.sort(key=lambda c: (-c["support"], c["source"], c["target"]))
        self._verify(candidates,
                     lambda c: f"{c['source']} --{c['name']} ({c['kind']})--> {c['target']}",
                     P.VERIFY_RELATIONS_TASK, P.RELATION_CATEGORIES)
        return ([c for c in candidates if self._accept(c)],
                [c for c in candidates if not self._accept(c)])

    # -- entry point -------------------------------------------------------------

    def run(self, given_classes: list[str] | None = None) -> dict:
        if self.cfg.kernel == "direct-tbox":
            from .tbox import extract
            return extract(self.doc, self.llm, self.cfg, given_classes)
        if self.cfg.kernel != "legacy":
            raise ValueError(f"Unknown kernel: {self.cfg.kernel}")
        if given_classes is None:
            classes, rejected = self.classes()
            names = [c["name"] for c in classes]
        else:
            names = _dedupe(norm_name(n) for n in given_classes)
            classes, rejected = [{"name": n, "given": True} for n in names], []

        attributes = self.attributes(names) if self.cfg.attributes and names else []
        relations, rejected_rel = self.relations(names) if len(names) > 1 else ([], [])
        return {
            "classes": classes,
            "attributes": attributes,
            "relations": relations,
            "rejected": {"classes": rejected, "relations": rejected_rel},
            "meta": {"model": self.llm.model, "effort": self.llm.effort,
                     "config": asdict(self.cfg), "usage": dict(self.llm.usage),
                     "cost_usd_estimate": round(self.llm.cost_usd(), 4) if self.llm.cost_usd() is not None else None},
        }
