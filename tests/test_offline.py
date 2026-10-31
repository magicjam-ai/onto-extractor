"""Offline tests: pipeline aggregation logic with a scripted fake LLM, plus the evaluator.

    .venv/bin/python -m pytest -q tests
"""

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bench"))

from evaluate import load_gold, score_associations, score_classes  # noqa: E402
from ontoextract import Config, Pipeline  # noqa: E402
from ontoextract.normalize import Grounder, norm_name  # noqa: E402

DOC = ("As a customer, I want to place an order for products so that I get groceries. "
       "As a customer, I want to add products to my wishlist. "
       "As a manager, I want to see each order's payment status.")


def cls(name, quote="place an order"):
    return {"name": name, "definition": f"a {name}", "evidence": [quote]}


class FakeLLM:
    """Returns scripted responses keyed on the stage, cycling through samples."""
    model, effort = "fake", "high"

    def __init__(self):
        self.usage = Counter()
        self.calls = Counter()
        self.tasks = []

    def cost_usd(self):
        return 0.0

    def json_call(self, system, document, task, schema):
        self.tasks.append(task)
        props = schema["properties"]
        if "classes" in props:
            i = self.calls["classes"]
            self.calls["classes"] += 1
            runs = [
                [cls("Customer", "As a customer"), cls("Orders"), cls("Product", "for products")],
                [cls("customer", "As a customer"), cls("order"), cls("product", "for products"),
                 cls("wish list", "my wishlist")],
                [cls("Client", "As a customer"), cls("order"), cls("products", "for products"),
                 cls("system", "invented quote that is nowhere in the text at all")],
            ]
            return {"classes": runs[i % 3]}
        if "groups" in props:
            return {"groups": [{"canonical": "customer", "members": ["customer", "client"]},
                               {"canonical": "order", "members": ["order"]}]}
        if "verdicts" in props:
            ids = props["verdicts"]["items"]["properties"]["id"]["enum"]
            first_is_system = "system" in task.split("[1]")[1].split("\n")[0]
            return {"verdicts": [{"id": i, "decision": "keep", "category": "valid", "reason": ""}
                                 for i in ids if not first_is_system]}
        if "relations" in props:
            i = self.calls["relations"]
            self.calls["relations"] += 1
            rel = lambda s, t, q="place an order": {  # noqa: E731
                "source": s, "target": t, "kind": "association", "name": "places",
                "source_multiplicity": "1", "target_multiplicity": "*", "evidence": [q]}
            runs = [[rel("customer", "order"), rel("order", "product")],
                    [rel("order", "customer"), rel("order", "product")],
                    [rel("customer", "order"), rel("customer", "product")]]
            return {"relations": runs[i % 3]}
        raise AssertionError(f"unexpected schema {list(props)}")


def test_norm_name():
    assert norm_name("ShoppingLists") == "shopping list"
    assert norm_name("delivery-person") == "delivery person"
    assert norm_name("Class") == "class"
    assert norm_name("购物车") == "购物车"


def test_grounder():
    g = Grounder(DOC)
    assert g.grounded("place an order for products")
    assert g.grounded("As a customer, I want to place")
    assert not g.grounded("the system sends an email reminder")
    assert Grounder("用户可以创建订单并支付").grounded("创建订单")


def test_pipeline_votes_merges_and_grounds():
    llm = FakeLLM()
    result = Pipeline(DOC, llm, Config(kernel="legacy", verify=True, samples=3, attributes=False, workers=2)).run()
    names = {c["name"]: c for c in result["classes"]}
    # "Client" merged into "customer"; plural/case variants collapse by normalization.
    assert set(names) == {"customer", "order", "product"}
    assert names["customer"]["aliases"] == ["client"] and names["customer"]["support"] == 1.0
    # "wish list" (1/3 support) and "system" (ungrounded quote) are rejected.
    rejected = {c["name"]: c for c in result["rejected"]["classes"]}
    assert rejected["wish list"]["support"] < 0.5
    assert not rejected["system"]["grounded"]
    # Undirected relations are oriented consistently before voting:
    # customer-order 3/3, order-product 2/3 accepted; customer-product 1/3 rejected.
    pairs = {(r["source"], r["target"]): r["support"] for r in result["relations"]}
    assert pairs == {("customer", "order"): 1.0, ("order", "product"): 2 / 3}
    assert [(r["source"], r["target"]) for r in result["rejected"]["relations"]] == \
        [("customer", "product")]


def test_given_classes_skip_class_stage():
    llm = FakeLLM()
    result = Pipeline(DOC, llm, Config(kernel="legacy", verify=True, samples=3, attributes=False, workers=2)).run(
        given_classes=["Customers", "order", "product"])
    assert llm.calls["classes"] == 0
    assert [c["name"] for c in result["classes"]] == ["customer", "order", "product"]
    assert len(result["relations"]) == 2


def test_evaluator_synonyms_silver_and_nonpunish():
    gold = load_gold()
    # camperplus: "staff" is a synonym of gold "camp worker"; "medical form" is a
    # non-punished subclass once "form" matched; "spaceship" is a false positive.
    s = score_classes(["Staff", "forms", "medical form", "spaceship"], "camperplus", gold)
    assert (s["tp"], s["fp"]) == (2, 1) and s["false_positives"] == ["spaceship"]
    # fish&chips: "cashier" is silver -> counted as hit, never as a miss.
    s = score_classes(["cashier"], "fish&chips", gold)
    assert s["tp"] == 1 and "cashier" not in s["missed"]
    # Associations are unordered and use class synonyms.
    a = score_associations([("order", "customers"), ("deliveryperson", "cash")], "fish&chips", gold)
    assert (a["tp"], a["fp"]) == (2, 0)
