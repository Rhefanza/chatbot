# app/faq_search.py
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
FAQ_PATH = DATA_DIR / "faq_kb.json"

STOPWORDS = {
    "faq", "tanya", "tanya jawab", "bagaimana", "gimana", "cara",
    "apa", "apakah", "jika", "kalau", "bila",
    "yang", "untuk", "dari", "di", "ke", "pada", "dengan", "dan", "atau",
    "tolong", "mohon", "info", "informasi"
}

def norm(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s

def clean_query(q: str) -> str:
    q = norm(q)
    toks = [t for t in q.split() if t not in STOPWORDS]
    return " ".join(toks).strip()

class FAQIndex:
    def __init__(self, items: List[Dict[str, Any]]):
        self.items = items
        self.questions = [self._q(it) for it in items]

        corpus = [norm(x) for x in self.questions]
        self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=1)
        self.matrix = self.vectorizer.fit_transform(corpus)

    def _q(self, it: Dict[str, Any]) -> str:
        return (it.get("pertanyaan") or "").strip()

    def _a(self, it: Dict[str, Any]) -> str:
        return (it.get("jawaban") or "").strip()

    def contains(self, query: str, limit: int = 3) -> Tuple[str, List[Dict[str, Any]]]:
        q = clean_query(query)
        if not q:
            return q, []
        hits = []
        for it in self.items:
            if q in norm(self._q(it)):
                hits.append(it)
                if len(hits) >= limit:
                    break
        return q, hits

    def search(self, query: str, top_k: int = 5) -> Tuple[str, List[Tuple[float, Dict[str, Any]]]]:
        q = clean_query(query)
        if not q:
            return q, []
        qv = self.vectorizer.transform([q])
        sims = cosine_similarity(qv, self.matrix)[0]
        idx = sims.argsort()[::-1][:top_k]
        return q, [(float(sims[i]), self.items[i]) for i in idx]

def build_faq_index() -> Optional[FAQIndex]:
    if not FAQ_PATH.exists():
        return None
    raw = json.loads(FAQ_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        return None
    raw = [x for x in raw if (x.get("pertanyaan") or "").strip() and (x.get("jawaban") or "").strip()]
    return FAQIndex(raw) if raw else None
