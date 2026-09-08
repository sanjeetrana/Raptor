"""
bm25.py — Pure-stdlib BM25 full-text ranking engine.

BM25 (Best Match 25) is the industry standard for text relevance ranking,
used by Elasticsearch, Solr, and Lucene under the hood.

Zero third-party dependencies. Python 3.9+.
"""
from __future__ import annotations
import json, math, re, dataclasses
from collections import Counter
from pathlib import Path
from typing import Optional


# ── Tokenizer ────────────────────────────────────────────────────────────────

_STOP = frozenset({
    "a","an","the","is","are","was","were","be","been","being",
    "have","has","had","do","does","did","will","would","shall",
    "should","may","might","must","can","could","to","of","in",
    "for","on","with","at","by","from","as","into","through",
    "and","but","or","not","if","then","that","this","it","its","self",
})

def tokenize(text: str) -> list[str]:
    """CamelCase-aware, snake_case-aware tokenizer. Removes stop words."""
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)  # CamelCase split
    text = text.replace("_", " ")
    tokens = re.split(r"[^a-zA-Z0-9]+", text.lower())
    return [t for t in tokens if len(t) >= 2 and t not in _STOP]


# ── Document ─────────────────────────────────────────────────────────────────

@dataclasses.dataclass
class Document:
    doc_id: str      # unique key — e.g. "auth.validate_token"
    body: str        # text to index (name + signature + docstring)
    metadata: dict   # stored and returned with search results

    @property
    def tokens(self) -> list[str]:
        return tokenize(self.body)


# ── BM25Index ─────────────────────────────────────────────────────────────────

class BM25Index:
    """
    Inverted index with BM25 scoring.

    k1 = 1.5  (term-frequency saturation)
    b  = 0.75 (document-length normalisation)

    Usage:
        idx = BM25Index()
        idx.add_document(Document("auth.validate_token", "validate token jwt", {}))
        idx.build()
        results = idx.search("token validation", top_k=10)
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._docs: dict[str, Document] = {}
        self._tf: dict[str, Counter] = {}      # doc_id → Counter(term → freq)
        self._df: Counter = Counter()           # term → # docs containing it
        self._avg_dl: float = 0.0
        self._built: bool = False

    def add_document(self, doc: Document) -> None:
        tokens = doc.tokens
        self._docs[doc.doc_id] = doc
        self._tf[doc.doc_id] = Counter(tokens)
        for term in set(tokens):
            self._df[term] += 1
        self._built = False

    def build(self) -> None:
        n = len(self._docs)
        self._avg_dl = (sum(sum(c.values()) for c in self._tf.values()) / n) if n else 0.0
        self._built = True

    def _idf(self, term: str) -> float:
        n = len(self._docs)
        df = self._df.get(term, 0)
        return math.log((n - df + 0.5) / (df + 0.5) + 1.0)

    def _score(self, doc_id: str, terms: list[str]) -> float:
        tf = self._tf.get(doc_id, Counter())
        dl = sum(tf.values())
        s = 0.0
        for t in terms:
            f = tf.get(t, 0)
            if not f:
                continue
            idf = self._idf(t)
            num = idf * f * (self.k1 + 1)
            den = f + self.k1 * (1 - self.b + self.b * (dl / max(self._avg_dl, 1)))
            s += num / den
        return s

    def search(self, query: str, top_k: int = 20) -> list[tuple[str, float]]:
        """Returns [(doc_id, bm25_score)] sorted descending. Score > 0 only."""
        if not self._built:
            self.build()
        terms = tokenize(query)
        if not terms:
            return []
        results = [(did, self._score(did, terms)) for did in self._docs]
        results = [(did, s) for did, s in results if s > 0]
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def get(self, doc_id: str) -> Optional[Document]:
        return self._docs.get(doc_id)

    def __len__(self) -> int:
        return len(self._docs)

    # ── Persistence ────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "k1": self.k1, "b": self.b, "avg_dl": self._avg_dl,
            "docs": {did: {"body": d.body, "metadata": d.metadata}
                     for did, d in self._docs.items()},
            "tf":   {did: dict(c) for did, c in self._tf.items()},
            "df":   dict(self._df),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BM25Index":
        idx = cls(k1=data["k1"], b=data["b"])
        idx._avg_dl = data["avg_dl"]
        for did, info in data["docs"].items():
            idx._docs[did] = Document(did, info["body"], info["metadata"])
        for did, tf_map in data["tf"].items():
            idx._tf[did] = Counter(tf_map)
        idx._df = Counter(data["df"])
        idx._built = True
        return idx

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "BM25Index":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
