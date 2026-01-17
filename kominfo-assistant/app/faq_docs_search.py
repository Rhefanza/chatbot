# app/faq_docs_search.py
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.schemas import DirectoryAnswer

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DOCS_PATH = DATA_DIR / "faq_docs.jsonl"
print("[LOAD] faq_docs_search from:", __file__)

# Stopword untuk query TF-IDF (retrieval)
STOPWORDS = {
    "dan", "atau", "yang", "di", "ke", "dari", "pada", "untuk", "dengan",
    "bagaimana", "gimana", "cara", "apa", "apakah", "mohon", "tolong", "info", "informasi",
    "tentang", "mengenai", "soal", "terkait", "seputar", "data", "dataset",
}

# Stopword untuk validator (lebih luas)
VALIDATOR_STOPWORDS = {
    "dan", "atau", "yang", "di", "ke", "dari", "pada", "untuk", "dengan", "agar", "sebagai",
    "ini", "itu", "tersebut", "adalah", "yaitu", "dapat", "bisa", "akan", "dalam", "oleh",
    "tidak", "bukan", "lebih", "kurang", "juga", "saja", "serta", "karena", "maka",
    "berikut", "ringkasan", "berdasarkan", "dokumen", "resmi", "bagian",
    "apa", "siapa", "kapan", "dimana", "mengapa", "kenapa", "bagaimana",
}

QUERY_GUARD_STOPWORDS = {
    "kabupaten", "banyuwangi", "tahun", "nomor", "no", "peraturan", "perbup",
    "tentang", "terkait", "mengenai", "seputar", "apakah",
    "telah", "sudah", "memiliki", "punya", "ada", "adakah", "apabila", "jika",
    "yang", "dan", "atau", "di", "ke", "dari", "pada", "untuk", "dengan",
    "ini", "itu", "tersebut",
}

# Kata kerja yang kita anggap "jawaban berisi" (anti jawaban judul saja)
VERB_WORDS = {
    "mengatur", "menjelaskan", "memuat", "berisi", "menetapkan", "mewajibkan",
    "dilakukan", "bertujuan", "meliputi", "mencakup", "memberikan", "menyediakan",
}

# ============================================================
# Normalization / cleaning
# ============================================================

def norm(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s

def clean_query(q: str) -> str:
    q = norm(q)
    toks = [t for t in q.split() if t not in STOPWORDS]
    return " ".join(toks).strip()

def _norm_text(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9\s-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _tokenize(s: str) -> List[str]:
    s = _norm_text(s)
    toks: List[str] = []
    for t in s.split():
        if t in VALIDATOR_STOPWORDS:
            continue
        if len(t) <= 2:
            continue
        toks.append(t)
    return toks

def clean_chunk_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    # dotted lines daftar isi
    text = re.sub(r"\.{8,}", " ", text)
    return text.strip()

def _doc_name(ch: Dict[str, Any]) -> str:
    return (ch.get("doc_id") or ch.get("source") or "").lower()

def _doc_id_exact(ch: Dict[str, Any]) -> str:
    # dipakai untuk allowlist yang butuh match persis
    return (ch.get("doc_id") or ch.get("source") or "").strip()

# ============================================================
# Index
# ============================================================

class FAQDocsIndex:
    def __init__(self, chunks: List[Dict[str, Any]]):
        self.chunks = chunks
        corpus = [norm(c.get("text", "")) for c in chunks]
        self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=1)
        self.matrix = self.vectorizer.fit_transform(corpus)

    def search(self, query: str, top_k: int = 5) -> Tuple[str, List[Tuple[float, Dict[str, Any]]]]:
        q = clean_query(query)
        if not q:
            return q, []
        qv = self.vectorizer.transform([q])
        sims = cosine_similarity(qv, self.matrix)[0]
        idx = sims.argsort()[::-1][:top_k]
        return q, [(float(sims[i]), self.chunks[i]) for i in idx]

def build_faq_docs_index() -> Optional[FAQDocsIndex]:
    if not DOCS_PATH.exists():
        return None
    chunks: List[Dict[str, Any]] = []
    with DOCS_PATH.open("r", encoding="utf-8") as r:
        for line in r:
            line = line.strip()
            if not line:
                continue
            chunks.append(json.loads(line))
    return FAQDocsIndex(chunks) if chunks else None

# ============================================================
# Chunk filtering
# ============================================================

def is_bad_chunk(text: str) -> bool:
    if not text or len(text) < 80:
        return True
    if re.search(r"\.{10,}", text):
        return True
    if text.strip().upper().startswith("BAB "):
        return True

    # Buang chunk yang tampak seperti daftar dokumen/lampiran:
    # contoh: "7. Pedoman ... 8. SOP ... 9. SOP ..."
    if len(re.findall(r"\b\d+\.\s", text)) >= 3:
        return True
    if len(re.findall(r"\bSOP\b", text, flags=re.I)) >= 3:
        return True
    if len(re.findall(r"\bPedoman\b", text, flags=re.I)) >= 3:
        return True

    return False

def filter_hits_allowed_docs(
    hits: List[Tuple[float, Dict[str, Any]]],
    allowed_docs: Optional[List[str]],
) -> List[Tuple[float, Dict[str, Any]]]:
    """
    Jika allowed_docs diberikan, batasi hasil hanya ke doc_id yang ada di list itu.
    IMPORTANT: match dilakukan persis (string equality), supaya tidak "nyasar" ke file lain.
    """
    if not allowed_docs:
        return hits
    allow = set([a.strip() for a in allowed_docs if a and a.strip()])
    if not allow:
        return hits

    filtered: List[Tuple[float, Dict[str, Any]]] = []
    for s, ch in hits:
        did = _doc_id_exact(ch)
        if did in allow:
            filtered.append((s, ch))
    return filtered

def rerank_hits_for_question(question: str, hits: List[Tuple[float, Dict[str, Any]]]):
    """
    Rerank sederhana:
    - kalau pertanyaan mengandung kata regulasi, dokumen regulasi di-boost
    - dokumen event (berita acara/notulen/forum) diturunkan
    """
    q = (question or "").lower()
    want_reg = bool(re.search(r"\b(peraturan|perbup|sop|pedoman|aturan)\b", q))

    out = []
    for score, ch in hits:
        doc = _doc_name(ch)
        bonus = 0.0

        if want_reg:
            if ("peraturan" in doc) or ("perbup" in doc) or ("sop" in doc) or ("pedoman" in doc):
                bonus += 0.20
            if ("berita_acara" in doc) or ("notulen" in doc) or ("forum" in doc) or ("undangan" in doc):
                bonus -= 0.30

        out.append((score + bonus, ch))

    out.sort(key=lambda x: x[0], reverse=True)
    return out

def filter_hits_for_question(question: str, hits: List[Tuple[float, Dict[str, Any]]]):
    """
    Filter ringan: buang dokumen event kalau user minta aturan/prosedur.
    """
    q = (question or "").lower()
    want_reg = bool(re.search(r"\b(peraturan|perbup|sop|pedoman|aturan)\b", q))
    if not want_reg:
        return hits

    filtered = []
    for s, ch in hits:
        doc = _doc_name(ch)
        if ("berita_acara" in doc) or ("notulen" in doc) or ("forum" in doc) or ("undangan" in doc):
            continue
        filtered.append((s, ch))

    return filtered or hits

def _query_keywords(question: str) -> List[str]:
    q = _norm_text(question)
    toks: List[str] = []
    for t in q.split():
        if t in QUERY_GUARD_STOPWORDS:
            continue
        if len(t) <= 2:
            continue
        toks.append(t)
    return toks

def filter_hits_by_query_overlap(
    question: str,
    hits: List[Tuple[float, Dict[str, Any]]],
    min_hits: int = 2,
) -> List[Tuple[float, Dict[str, Any]]]:
    keys = _query_keywords(question)
    if not keys:
        return hits

    uniq = list(dict.fromkeys(keys))  # dedup preserve order
    filtered = []
    for s, ch in hits:
        txt = _norm_text(ch.get("text", "") or "")
        hit_count = sum(1 for k in uniq if k and (k in txt))
        if hit_count >= min_hits:
            filtered.append((s, ch))

    return filtered or hits

def dedup_hits_by_text(
    hits: List[Tuple[float, Dict[str, Any]]],
    max_keep: int = 10,
) -> List[Tuple[float, Dict[str, Any]]]:
    """
    Dedup berbasis text awal (mengurangi kasus 3 cuplikan sama).
    """
    seen = set()
    out: List[Tuple[float, Dict[str, Any]]] = []
    for s, ch in hits:
        txt = clean_chunk_text(ch.get("text", "") or "")
        key = _norm_text(txt[:220])
        if not key:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append((s, ch))
        if len(out) >= max_keep:
            break
    return out

def boost_hits_by_heading(question: str, hits: List[Tuple[float, Dict[str, Any]]]):
    """
    Bonus kecil bila chunk memuat heading yang sering ditanya.
    (No-op aman; hanya menambah sedikit skor.)
    """
    q = (question or "").lower()
    want = []
    if "tujuan" in q:
        want.append("tujuan")
    if "maksud" in q:
        want.append("maksud")
    if "sasaran" in q:
        want.append("sasaran")
    if "ruang lingkup" in q or "lingkup" in q:
        want.append("ruang lingkup")
    if not want:
        return hits

    out = []
    for s, ch in hits:
        t = (ch.get("text") or "").lower()
        bonus = 0.0
        for w in want:
            if w in t:
                bonus += 0.05
        out.append((s + bonus, ch))
    out.sort(key=lambda x: x[0], reverse=True)
    return out

def expand_query_for_intent_words(q: str) -> str:
    """
    Tambah kata-kata bantu untuk intent tertentu (metadata, tujuan, dll).
    Ini hanya mempengaruhi retrieval, bukan jawaban.
    """
    tl = (q or "").lower()
    extra = []
    if "metadata" in tl:
        extra += ["variabel", "elemen", "atribut", "indikator", "kuesioner", "dashboard"]
    if "tujuan" in tl:
        extra += ["tujuan", "bertujuan"]
    if "sasaran" in tl:
        extra += ["sasaran"]
    if "maksud" in tl:
        extra += ["maksud"]
    if extra:
        return q + " " + " ".join(extra)
    return q

# ============================================================
# Prompt: SINGLE CALL multi-chunk
# ============================================================

SUMMARY_MULTI_PROMPT = """Anda adalah asisten layanan publik.

TUGAS:
Jawab pertanyaan hanya dengan mengutip/merangkum informasi dari TEKS [1], [2], [3].

ATURAN FORMAT (PALING PENTING):
1) Output HANYA berupa bullet list, maksimal 3 baris.
2) Format tiap baris HARUS persis: "- [1] ..." / "- [2] ..." / "- [3] ...".
3) Bahasa: HANYA Bahasa Indonesia. DILARANG Bahasa Inggris.
4) DILARANG bertanya balik atau memberi pertanyaan lanjutan.
5) Tiap bullet harus 1 kalimat utuh, minimal 8 kata.
6) DILARANG hanya judul dokumen ("SOP ...", "Pedoman ...") tanpa menjelaskan isi.
7) Tiap bullet wajib memuat minimal 1 kata kerja (mis. mengatur/menjelaskan/memuat/berisi/menetapkan/mewajibkan/dilakukan/bertujuan/meliputi).
8) Tiap bullet wajib memuat minimal 2 istilah yang benar-benar muncul pada TEKS sumber.
9) Jangan menambah fakta di luar TEKS.
10) Jika tidak ada jawaban eksplisit di TEKS, tulis persis: "TIDAK RELEVAN".

PERTANYAAN:
{question}

TEKS:
{context}

OUTPUT:
"""

SUMMARY_RETRY_PROMPT = """Perbaiki jawabanmu karena sebelumnya tidak sesuai format.

ATURAN WAJIB:
1) Output maksimal 3 bullet dengan label: "- [1]" / "- [2]" / "- [3]".
2) Bahasa Indonesia saja. Jangan bertanya balik.
3) Tiap bullet 1 kalimat utuh (minimal 8 kata).
4) DILARANG hanya judul ("SOP ...", "Pedoman ..."). Jika tidak bisa jelaskan isi dari TEKS: tulis "TIDAK RELEVAN".
5) Wajib minimal 1 kata kerja (mengatur/menjelaskan/memuat/berisi/menetapkan/mewajibkan/dilakukan/bertujuan/meliputi).
6) Wajib minimal 2 istilah yang benar-benar muncul pada TEKS sumber.
7) Tidak boleh menambah fakta di luar TEKS.

PERTANYAAN:
{question}

TEKS:
{context}

OUTPUT:
"""

# ============================================================
# Validator / output parsing
# ============================================================

def validate_summary_against_chunk(
    summary: str,
    chunk_text: str,
    min_overlap_ratio: float = 0.25,
    min_hits: int = 2,
) -> Tuple[bool, float, List[str]]:
    sum_tokens = _tokenize(summary)
    if not sum_tokens:
        return False, 0.0, []

    chunk_norm = _norm_text(chunk_text)
    hits = [t for t in sum_tokens if t in chunk_norm]
    ratio = len(hits) / max(1, len(sum_tokens))
    ok = (len(hits) >= min_hits) and (ratio >= min_overlap_ratio)
    return ok, ratio, hits

def is_too_short_summary(s: str) -> bool:
    s = (s or "").strip()
    s = s.lstrip("-").strip()
    if len(s) < 35:
        return True
    if len(s.split()) < 6:
        return True
    return False

def _has_verb(s: str) -> bool:
    tl = (s or "").lower()
    return any(v in tl.split() for v in VERB_WORDS)

def looks_like_title_only(s: str) -> bool:
    s = (s or "").strip().lower()

    # Pola judul yang sering keluar (dan tidak menjawab)
    if s.startswith("sop "):
        return True
    if s.startswith("pedoman "):
        return True
    if s.startswith("peraturan "):
        return True

    # Terlalu pendek atau tanpa kata kerja
    if len(s.split()) <= 4:
        return True
    if not _has_verb(s):
        return True

    return False

def _parse_labeled_bullets(output: str, max_bullets: int = 3) -> List[Tuple[int, str]]:
    rows: List[Tuple[int, str]] = []
    for ln in (output or "").splitlines():
        ln = ln.strip()
        if not ln.startswith("-"):
            continue
        m = re.match(r"^- \[(\d+)\]\s*(.+)$", ln)
        if not m:
            continue
        idx = int(m.group(1))
        txt = (m.group(2) or "").strip()
        if not txt:
            continue
        rows.append((idx, txt))
        if len(rows) >= max_bullets:
            break
    return rows

def dedup_list(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for x in items:
        if not x:
            continue
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out

def needs_retry(parsed: List[Tuple[int, str]]) -> bool:
    if not parsed:
        return True
    return all(is_too_short_summary(txt) or looks_like_title_only(txt) for _, txt in parsed)

def _normalize_llm_output(s: str) -> str:
    """
    Gemini kadang mengembalikan prefix seperti "JAWABAN:" atau kalimat tanpa bullet.
    Kita rapikan agar parser bullet punya peluang.
    """
    t = (s or "").strip()
    if not t:
        return ""

    # buang code fence
    t = re.sub(r"^```.*?\n", "", t, flags=re.S)
    t = re.sub(r"\n```$", "", t, flags=re.S).strip()

    # buang prefix "JAWABAN:"
    t = re.sub(r"^\s*jawaban\s*:\s*", "", t, flags=re.I).strip()

    return t

# ============================================================
# Build context for LLM
# ============================================================

def build_multi_chunk_context(
    hits: List[Tuple[float, Dict[str, Any]]],
    max_chunks: int = 3,
    max_chars: int = 1200,
) -> Tuple[str, List[str], List[str]]:
    blocks: List[str] = []
    cite_map: List[str] = []
    chunk_map: List[str] = []

    valid_idx = 0
    for _, ch in hits:
        if valid_idx >= max_chunks:
            break

        raw = ch.get("text", "") or ""
        if is_bad_chunk(raw):
            continue

        text = clean_chunk_text(raw)[:max_chars]
        if not text:
            continue

        valid_idx += 1
        blocks.append(f"[{valid_idx}] {text}")

        doc = ch.get("doc_id", "dokumen")
        page = ch.get("page")
        cite_map.append(f"{doc} (hal. {page})" if page else doc)
        chunk_map.append(text)

    return "\n\n".join(blocks), cite_map, chunk_map

# ============================================================
# Yes/No detection for raw mode
# ============================================================

def detect_yes_no_regulation(question: str, hits: List[Tuple[float, Dict[str, Any]]]) -> Optional[str]:
    q = (question or "").lower()
    if not re.search(r"\b(apakah|ada(kah)?|sudah|telah|memiliki)\b", q):
        return None
    if not re.search(r"\b(peraturan|perbup|pedoman|aturan)\b", q):
        return None

    for _, ch in hits[:8]:
        tl = (ch.get("text") or "").lower()
        if ("peraturan bupati" in tl and "pengelolaan data" in tl):
            return "Iya. Kabupaten Banyuwangi memiliki peraturan terkait pengelolaan data."
        if re.search(r"nomor\s+6\s+tahun\s+2021", tl) and "pengelolaan data" in tl:
            return "Iya. Kabupaten Banyuwangi memiliki peraturan terkait pengelolaan data."
    return None

def detect_yes_no_sop(question: str, hits: List[Tuple[float, Dict[str, Any]]]) -> Optional[str]:
    q = (question or "").lower()
    if not re.search(r"\b(apakah|ada(kah)?|sudah|telah|memiliki)\b", q):
        return None
    if not re.search(r"\b(sop)\b", q):
        return None

    for _, ch in hits[:8]:
        doc = _doc_name(ch)
        tl = (ch.get("text") or "").lower()
        if "sop" in doc or "sop" in tl:
            return "Iya. Dari cuplikan dokumen yang ditemukan, Kabupaten Banyuwangi memiliki SOP terkait data."
    return None

# ============================================================
# Answer: LLM (single-call) + validator
# ============================================================

def answer_faq_doc_llm(
    question: str,
    faq_docs_index: FAQDocsIndex,
    llm,
    top_k: int = 8,
    max_bullets: int = 3,
    allowed_docs: Optional[List[str]] = None,
) -> DirectoryAnswer:
    print(">>> ENTER answer_faq_doc_llm <<<")
    print(">>> LLM VERSION: 2026-01-16 C (scoped+dedup+retry) <<<")

    q_clean, hits = faq_docs_index.search(expand_query_for_intent_words(question), top_k=top_k)

    # ✅ scope by allowed docs (kalau dari FAQ item tertentu)
    hits = filter_hits_allowed_docs(hits, allowed_docs)

    hits = rerank_hits_for_question(question, hits)
    hits = filter_hits_for_question(question, hits)
    hits = boost_hits_by_heading(question, hits)
    hits = filter_hits_by_query_overlap(question, hits, min_hits=2)

    # ✅ dedup supaya [1][2][3] tidak sama
    hits = dedup_hits_by_text(hits, max_keep=max(8, top_k))

    if not hits:
        return DirectoryAnswer(mode="not_found", answer="Tidak ada cuplikan relevan.", citations=[], followups=[])

    context, cite_map, chunk_map = build_multi_chunk_context(hits, max_chunks=3, max_chars=1200)
    if not context or not chunk_map:
        return DirectoryAnswer(mode="not_found", answer="Cuplikan dokumen tidak cukup untuk diringkas.", citations=[], followups=[])

    prompt = SUMMARY_MULTI_PROMPT.format(question=question, context=context)
    print("[llm] prompt_head:", repr(prompt[:220]))

    out = _normalize_llm_output((llm.generate(prompt) or ""))
    print("[llm] raw_out:", repr(out[:600]))

    parsed = _parse_labeled_bullets(out, max_bullets=max_bullets)
    print("[llm] parsed:", parsed)

    if needs_retry(parsed):
        prompt2 = SUMMARY_RETRY_PROMPT.format(question=question, context=context)
        out2 = _normalize_llm_output((llm.generate(prompt2) or ""))
        print("[llm] retry_out:", repr(out2[:600]))

        parsed2 = _parse_labeled_bullets(out2, max_bullets=max_bullets)
        print("[llm] retry_parsed:", parsed2)
        if parsed2:
            parsed = parsed2

    if not parsed:
        return DirectoryAnswer(mode="not_found", answer="LLM tidak memberi jawaban eksplisit.", citations=[], followups=[])

    bullets: List[str] = []
    citations: List[str] = []

    for idx, txt in parsed:
        if idx < 1 or idx > len(chunk_map):
            continue

        if is_too_short_summary(txt):
            continue
        if looks_like_title_only(txt):
            continue

        ok, ratio, hit_tokens = validate_summary_against_chunk(txt, chunk_map[idx - 1])
        if not ok:
            continue

        bullets.append(f"- {txt}")
        citations.append(cite_map[idx - 1])

        if len(bullets) >= max_bullets:
            break
        
    if not bullets and parsed:
        # fallback lembut: pakai bullet terpanjang yang idx-nya valid
        cand = [(idx, txt) for idx, txt in parsed if 1 <= idx <= len(chunk_map)]
        if cand:
            idx, txt = max(cand, key=lambda x: len((x[1] or "").split()))
            return DirectoryAnswer(
                mode="faq_doc",
                answer="Berikut ringkasan berdasarkan dokumen resmi:\n\n- " + txt,
                citations=[cite_map[idx - 1]] if cite_map and idx - 1 < len(cite_map) else [],
                followups=["Mau saya ambil rincian langkah berikutnya atau peran aktor terkait?"],
            )

    if not bullets:
        return DirectoryAnswer(
            mode="not_found",
            answer="Ringkasan ada, tetapi tidak lolos verifikasi/format (lihat log raw_out/retry_out).",
            citations=[],
            followups=[],
        )

    citations = dedup_list(citations)
    return DirectoryAnswer(
        mode="faq_doc",
        answer="Berikut ringkasan berdasarkan dokumen resmi:\n\n" + "\n".join(bullets),
        citations=citations,
        followups=["Jika perlu, sebut bagian yang dicari (mis. 'tujuan', 'definisi', 'alur', 'syarat')."],
    )

# ============================================================
# Answer: RAW fallback
# ============================================================

def _format_doc_hits(
    hits: List[Tuple[float, Dict[str, Any]]],
    max_items: int = 3,
    max_chars: int = 400,
) -> Tuple[str, List[str]]:
    lines = ["Berikut jawaban berdasarkan isi dokumen (cuplikan):"]
    cites: List[str] = []

    for i, (score, ch) in enumerate(hits[:max_items], start=1):
        text = (ch.get("text") or "").strip()
        text = re.sub(r"\s+", " ", text)[:max_chars]
        lines.append(f"\n{i}) {text}...")

        doc_id = ch.get("doc_id", "dokumen")
        page = ch.get("page")
        cites.append(f"{doc_id} (hal. {page})" if page else doc_id)

    return "\n".join(lines), cites

def answer_faq_doc_raw(
    question: str,
    faq_docs_index: FAQDocsIndex,
    top_k: int = 6,
    allowed_docs: Optional[List[str]] = None,
) -> DirectoryAnswer:
    print(">>> ENTER answer_faq_doc_raw <<<")

    q_clean, hits = faq_docs_index.search(expand_query_for_intent_words(question), top_k=top_k)

    # ✅ scope by allowed docs
    hits = filter_hits_allowed_docs(hits, allowed_docs)

    hits = rerank_hits_for_question(question, hits)
    hits = filter_hits_for_question(question, hits)
    hits = boost_hits_by_heading(question, hits)
    hits = filter_hits_by_query_overlap(question, hits, min_hits=2)

    # ✅ dedup cuplikan agar tidak 3x sama
    hits = dedup_hits_by_text(hits, max_keep=max(8, top_k))

    # yes/no SOP dulu (kalau relevan)
    yn_sop = detect_yes_no_sop(question, hits)
    if yn_sop:
        answer_text, cites = _format_doc_hits(hits, max_items=1, max_chars=450)
        cites = dedup_list(cites)
        return DirectoryAnswer(
            mode="faq_doc",
            answer=yn_sop + "\n\nBukti (cuplikan):\n" + answer_text,
            citations=cites,
            followups=["Mau saya ambil bagian tujuan SOP, alur/prosedur, atau peran Walidata/Produsen Data?"],
        )

    yn_reg = detect_yes_no_regulation(question, hits)
    if yn_reg:
        answer_text, cites = _format_doc_hits(hits, max_items=1, max_chars=450)
        cites = dedup_list(cites)
        return DirectoryAnswer(
            mode="faq_doc",
            answer=yn_reg + "\n\nBukti (cuplikan):\n" + answer_text,
            citations=cites,
            followups=["Mau saya ambil Pasal tentang ruang lingkup, peran Walidata, atau standar data?"],
        )

    if not hits:
        return DirectoryAnswer(
            mode="not_found",
            answer="Saya tidak menemukan bagian dokumen yang relevan.",
            citations=[],
            followups=[],
        )

    answer_text, cites = _format_doc_hits(hits)
    cites = dedup_list(cites)
    return DirectoryAnswer(
        mode="faq_doc",
        answer=answer_text,
        citations=cites,
        followups=["Sebut kata kunci spesifik untuk mempersempit."],
    )
