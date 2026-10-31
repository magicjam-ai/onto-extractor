"""Name normalization and evidence grounding."""

import re

import inflect

_inflect = inflect.engine()
# Words inflect would wrongly singularize ("class" -> "clas").
_NO_SINGULAR_SUFFIXES = ("ss", "us", "is", "ics")
_CJK = re.compile(r"[㐀-鿿豈-﫿]")


def singular(word: str) -> str:
    if not word.isascii() or word.endswith(_NO_SINGULAR_SUFFIXES):
        return word
    return _inflect.singular_noun(word) or word


def norm_name(name: str) -> str:
    """'ShoppingLists' / 'shopping_list' / 'Shopping lists' -> 'shopping list'."""
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name.strip())
    s = re.sub(r"[_\-/]+", " ", s)
    s = re.sub(r"[^\w\s]", "", s)
    words = s.lower().split()
    if not words:
        return ""
    words[-1] = singular(words[-1])
    return " ".join(words)


def _flatten(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split())


class Grounder:
    """Checks that an evidence quote actually occurs in the source document."""

    def __init__(self, document: str):
        self.flat = _flatten(document)
        self.words = set(self.flat.split())
        self.bigrams = {self.flat[i:i + 2] for i in range(len(self.flat) - 1)}

    def grounded(self, quote: str) -> bool:
        q = _flatten(quote)
        if len(q) < 2:
            return False
        if q in self.flat:
            return True
        if _CJK.search(q):
            grams = [q[i:i + 2] for i in range(len(q) - 1)]
            return sum(g in self.bigrams for g in grams) / len(grams) >= 0.8
        tokens = q.split()
        if len(tokens) < 3:
            return False
        return sum(t in self.words for t in tokens) / len(tokens) >= 0.85

    def any_grounded(self, quotes: list[str]) -> bool:
        return any(self.grounded(q) for q in quotes)
