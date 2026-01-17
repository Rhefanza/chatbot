import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# Optional fuzzy (typo tolerant)
try:
    from rapidfuzz import fuzz
    RAPIDFUZZ_AVAILABLE = True
except Exception:
    RAPIDFUZZ_AVAILABLE = False

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
CATALOG_PATH = DATA_DIR / "dataset_catalog.json"

# Kata-kata umum yang sebaiknya dibuang dari query
STOPWORDS = {
    "dataset", "judul", "tema", "indikator", "katalog", "data",
    "tentang", "mengenai", "soal", "terkait", "seputar",
    "yang", "untuk", "dari", "di", "ke", "pada", "dengan", "dan", "atau",
    "tolong", "cari", "mencari", "ada", "info", "informasi",
    "apakah", "kah"
}

# Frasa pembuka pertanyaan yang sering bikin query "melebar"
QUESTION_PHRASES = [
    "bagaimana jika", "bagaimana cara", "bagaimana", "gimana", "cara",
    "apa itu", "apa saja", "apa", "apakah", "mohon", "tolong",
    "saya ingin", "saya mau", "kami ingin", "kami mau",
    "ingin mengetahui", "mau mengetahui", "ingin tahu", "mau tahu",
    "informasi", "info",
]

# Sinonim frasa (lebih prioritas daripada token)
# Pakai untuk padanan yang PASTI setara (mis. singkatan resmi)
PHRASE_SYNONYMS = {
    "akta lahir": "akta kelahiran",
    "surat lahir": "akta kelahiran",
    "bumil": "ibu hamil",

    # domain yang sering ditanya publik (aman karena padanan resmi)
    "anak tidak sekolah": "ats",
    "penyakit tidak menular": "ptm",
    "angka kematian ibu": "aki",
    "angka kematian bayi": "akb",
    "nomor induk kependudukan": "nik",
    "kartu keluarga": "kk",
}

# Token synonyms sengaja TIDAK dipakai (cukup stemming Sastrawi)
TOKEN_SYNONYMS: Dict[str, str] = {}


def norm(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s


# ==========================
# STEMMING HELPERS (dipakai dari main.py juga)
# ==========================
try:
    from Sastrawi.Stemmer.StemmerFactory import StemmerFactory
    _stemmer = StemmerFactory().create_stemmer()
    SASTRAWI_AVAILABLE = True
except Exception:
    _stemmer = None
    SASTRAWI_AVAILABLE = False


def stem_phrase(s: str) -> str:
    if not SASTRAWI_AVAILABLE:
        return (s or "").lower().strip()

    s = (s or "").lower().strip()
    s = re.sub(r"[^a-z0-9\s-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return _stemmer.stem(s)


def is_inflected_query(q: str) -> bool:
    qn = re.sub(r"\s+", " ", (q or "").lower().strip())
    qs = stem_phrase(qn)
    return bool(qn) and (qs != qn)


def apply_synonyms(text: str) -> str:
    t = norm(text)

    # frasa dulu (biar "anak tidak sekolah" tidak pecah)
    for k, v in PHRASE_SYNONYMS.items():
        t = re.sub(rf"\b{re.escape(k)}\b", v, t)

    # token synonyms tidak dipakai (biar tidak noise)
    return t


def clean_query(q: str) -> str:
    # 1) synonyms frasa
    q = apply_synonyms(q)
    q = norm(q)

    # 2) buang frasa pembuka pertanyaan (hanya di awal kalimat)
    for ph in QUESTION_PHRASES:
        q = re.sub(rf"^\s*{re.escape(ph)}\b\s*", "", q)

    # 3) rapikan karakter
    q = re.sub(r"[^a-z0-9\s-]", " ", q)
    q = re.sub(r"\s+", " ", q).strip()

    # 4) stemming (kalau tersedia)
    if SASTRAWI_AVAILABLE:
        q = stem_phrase(q)

    # 5) stopwords removal
    tokens = [t for t in q.split() if t and (t not in STOPWORDS)]
    return " ".join(tokens).strip()


class DatasetIndex:
    def __init__(self, items: List[Dict[str, Any]]):
        self.items = items
        self.titles = [self._get_title(x) for x in items]

        # ✅ pakai clean_query untuk corpus agar konsisten dengan query user
        corpus = [clean_query(t) for t in self.titles]

        # word n-gram (makna)
        self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=1)
        self.matrix = self.vectorizer.fit_transform(corpus)

        # char n-gram (tahan typo/variasi penulisan)
        self.char_vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1)
        self.char_matrix = self.char_vectorizer.fit_transform(corpus)

        # exact match setelah normalisasi
        self.exact: Dict[str, Dict[str, Any]] = {}
        for x in items:
            t = clean_query(self._get_title(x))
            if t:
                self.exact.setdefault(t, x)

    def _get_title(self, x: Dict[str, Any]) -> str:
        return (x.get("title") or x.get("judul") or "").strip()

    def contains_search(self, query: str, limit: int = 5) -> Tuple[str, List[Dict[str, Any]]]:
        """Return (cleaned_query, hits)."""
        q = clean_query(query)
        if not q:
            return q, []

        ql = q.lower()
        hits = []
        for it in self.items:
            title = (it.get("title") or it.get("judul") or "").lower()
            if ql in title:
                hits.append(it)
                if len(hits) >= limit:
                    break
        return q, hits

    def search(self, query: str, top_k: int = 10) -> Tuple[str, List[Tuple[float, Dict[str, Any]]]]:
        """Return (cleaned_query, combined TF-IDF results)."""
        q = clean_query(query)
        if not q:
            return q, []

        # exact match setelah normalisasi
        if q in self.exact:
            return q, [(1.0, self.exact[q])]

        # skor word
        qv = self.vectorizer.transform([q])
        sims_word = cosine_similarity(qv, self.matrix)[0]

        # skor char
        qvc = self.char_vectorizer.transform([q])
        sims_char = cosine_similarity(qvc, self.char_matrix)[0]

        # gabungkan (bobot bisa kamu tweak)
        sims = (0.70 * sims_word) + (0.30 * sims_char)

        idx = sims.argsort()[::-1][:top_k]
        results = [(float(sims[i]), self.items[i]) for i in idx]

        # fallback fuzzy kalau skor teratas rendah
        if results and results[0][0] < 0.18 and RAPIDFUZZ_AVAILABLE:
            _, fuzzy = self.fuzzy_suggest(query, top_k=top_k)

            # merge hasil: ambil skor tertinggi per item
            merged: Dict[int, Tuple[float, Dict[str, Any]]] = {id(it): (score, it) for score, it in results}
            for fs, it in fuzzy:
                # fs di [0..1], beri mapping supaya bisa bersaing dengan TF-IDF
                score = 0.12 + (0.88 * fs)
                prev = merged.get(id(it))
                if (prev is None) or (score > prev[0]):
                    merged[id(it)] = (score, it)

            results = sorted(merged.values(), key=lambda x: x[0], reverse=True)[:top_k]

        return q, results

    def fuzzy_suggest(self, query: str, top_k: int = 5) -> Tuple[str, List[Tuple[float, Dict[str, Any]]]]:
        """Optional: typo tolerant. Return (cleaned_query, results)."""
        q = clean_query(query)
        if not q or not RAPIDFUZZ_AVAILABLE:
            return q, []

        scored: List[Tuple[float, Dict[str, Any]]] = []
        for it in self.items:
            title = self._get_title(it)
            if not title:
                continue
            score = fuzz.partial_ratio(q, title.lower()) / 100.0
            scored.append((score, it))

        scored.sort(key=lambda x: x[0], reverse=True)
        return q, scored[:top_k]


def build_index() -> Optional[DatasetIndex]:
    if not CATALOG_PATH.exists():
        return None

    raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    items = raw if isinstance(raw, list) else raw.get("datasets", [])
    items = [x for x in items if (x.get("title") or x.get("judul") or "").strip()]

    return DatasetIndex(items) if items else None
