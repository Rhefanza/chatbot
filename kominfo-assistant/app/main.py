import re
import os
import pymysql

from fastapi import FastAPI
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from app.schemas import DirectoryAnswer
from app.directory import (
    detect_intent,
    load_contacts,
    load_units,
    answer_contact,
    answer_org,
)
from app.dataset_search import build_index, stem_phrase, is_inflected_query
from app.faq_search import build_faq_index
from app.formatters import format_faq_answer, format_faq_doc_answer
from app.faq_docs_search import (
    build_faq_docs_index,
    answer_faq_doc_llm,
    answer_faq_doc_raw,
)
from app.llm import DummyLLM

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Kominfo Assistant Chatbot")

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=[
#         "http://127.0.0.1:5500",
#         "http://localhost:5500",
#         "http://127.0.0.1:8000",
#         "http://localhost:8000",
#     ],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# ✅ Kontak harus menang (agar email/ig/twitter/alamat tidak nyasar ke site_help/faq_doc/LLM)
CONTACT_OVERRIDE_RE = re.compile(
    r"\b("
    r"email|e-mail|surel|"
    r"instagram|ig|"
    r"twitter|x|"
    r"facebook|fb|"
    r"tiktok|youtube|linkedin|"
    r"telepon|telp|telfon|nomor|hp|wa|whatsapp|"
    r"alamat|lokasi|kantor|maps|"
    r"jam layanan|jam kerja|"
    r"kontak|hubungi"
    r")\b",
    re.I
)

# =========================
# DB (XAMPP MySQL)
# =========================
DB_CFG = {
    "host": "127.0.0.1",
    "user": "root",
    "password": "",          # XAMPP default biasanya kosong
    "database": "chatbot_bwsd",
    "port": 3306,
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
    "autocommit": True,
}

def db_conn():
    return pymysql.connect(**DB_CFG)

def cleanup_expired_sessions():
    # hapus session expired -> messages ikut kehapus karena ON DELETE CASCADE
    with db_conn() as con:
        with con.cursor() as cur:
            cur.execute("DELETE FROM chat_sessions WHERE expires_at < NOW()")

def get_or_create_session(session_id: str, name: str | None, phone: str | None) -> str:
    sid = (session_id or "").strip() or "anon"

    with db_conn() as con:
        with con.cursor() as cur:
            cur.execute("SELECT session_id FROM chat_sessions WHERE session_id=%s LIMIT 1", (sid,))
            row = cur.fetchone()

            if row:
                # refresh TTL 10 menit tiap ada aktivitas
                cur.execute(
                    "UPDATE chat_sessions "
                    "SET last_active=NOW(), expires_at=DATE_ADD(NOW(), INTERVAL 10 MINUTE) "
                    "WHERE session_id=%s",
                    (sid,)
                )
                # simpan formalitas (kalau diisi)
                if name or phone:
                    cur.execute(
                        "UPDATE chat_sessions "
                        "SET name=COALESCE(%s,name), phone=COALESCE(%s,phone) "
                        "WHERE session_id=%s",
                        (name, phone, sid)
                    )
                return sid

            # create new session
            cur.execute(
                "INSERT INTO chat_sessions (session_id, name, phone, last_active, expires_at) "
                "VALUES (%s,%s,%s,NOW(),DATE_ADD(NOW(), INTERVAL 10 MINUTE))",
                (sid, name, phone)
            )
            return sid

def save_message(session_id: str, role: str, content: str) -> None:
    sid = (session_id or "").strip() or "anon"
    txt = (content or "").strip()
    if not txt:
        return

    with db_conn() as con:
        with con.cursor() as cur:
            cur.execute(
                "INSERT INTO chat_messages (session_id, role, content) VALUES (%s,%s,%s)",
                (sid, role, txt)
            )

def load_last_messages(session_id: str, limit: int = 4) -> list[dict]:
    sid = (session_id or "").strip() or "anon"
    with db_conn() as con:
        with con.cursor() as cur:
            cur.execute(
                "SELECT role, content FROM chat_messages "
                "WHERE session_id=%s ORDER BY id DESC LIMIT %s",
                (sid, limit)
            )
            rows = cur.fetchall()
    return list(reversed(rows))

# =========================
# Memory helper (follow-up)
# =========================
def _looks_like_followup(msg: str) -> bool:
    m = (msg or "").lower()
    triggers = [
        "yang tadi", "tadi", "itu", "ini", "lanjut", "selanjutnya",
        "maksudnya", "detail", "bagian", "contoh", "yang tahun", "tahun berapa",
        "yang mana", "terus"
    ]
    return any(t in m for t in triggers)

def _build_effective_message(msg: str, mem: list[dict[str, str]]) -> str:
    if not _looks_like_followup(msg) or not mem:
        return msg

    ctx_lines = []
    for it in mem:
        r = it.get("role")
        t = (it.get("text") or "").strip()
        if not t:
            continue
        if r == "user":
            ctx_lines.append(f"User sebelumnya: {t}")
        else:
            ctx_lines.append(f"Jawaban sebelumnya: {t}")

    ctx = "\n".join(ctx_lines).strip()
    return f"{ctx}\n\nPertanyaan sekarang: {msg}" if ctx else msg

# =========================
# Request schema
# =========================
class ChatIn(BaseModel):
    message: str
    session_id: str | None = None
    name: str | None = None
    phone: str | None = None

def _has_pdf_lampiran(lampiran_list: list) -> bool:
    for f in lampiran_list or []:
        url = (f.get("url") or "").lower()
        nama = (f.get("nama_file") or "").lower()
        if url.endswith(".pdf") or nama.endswith(".pdf"):
            return True
    return False

@app.on_event("startup")
def startup():
    app.state.contacts_by_id = load_contacts()
    app.state.units_by_id = load_units()
    app.state.dataset_index = build_index()
    app.state.faq_index = build_faq_index()
    app.state.faq_docs_index = build_faq_docs_index()

    key = os.getenv("GEMINI_API_KEY")
    if key:
        from app.llm_gemini import GeminiLLM
        app.state.llm = GeminiLLM(api_key=key, model="gemini-3-flash-preview")
    else:
        app.state.llm = DummyLLM()

    print("[startup] contacts:", "OK" if app.state.contacts_by_id else "NONE")
    print("[startup] units:", "OK" if app.state.units_by_id else "NONE")
    print("[startup] dataset_index:", "OK" if app.state.dataset_index else "NONE")
    print("[startup] faq_index:", "OK" if app.state.faq_index else "NONE")
    print("[startup] faq_docs_index:", "OK" if app.state.faq_docs_index else "NONE")
    print("GEMINI_API_KEY loaded?", "YES" if key else "NO")

@app.get("/")
def root():
    return {"status": "ok"}

@app.post("/chat", response_model=DirectoryAnswer)
def chat(payload: ChatIn):
    msg = (payload.message or "").strip()
    if not msg:
        return DirectoryAnswer(
            mode="not_found",
            answer="Pesan kosong.",
            citations=[],
            followups=[],
        )

    sid = (payload.session_id or "anon").strip() or "anon"

    # ✅ override kontak (pakai msg asli, bukan effective_msg)
    intent_override_contact = bool(CONTACT_OVERRIDE_RE.search(msg))

    # DB session TTL + refresh
    cleanup_expired_sessions()
    sid = get_or_create_session(sid, payload.name, payload.phone)

    # ambil 2 percakapan terakhir (U1,A1,U2,A2) untuk follow-up
    mem_rows = load_last_messages(sid, limit=10)
    mem = [{"role": r.get("role", ""), "text": r.get("content", "")} for r in mem_rows]

    effective_msg = _build_effective_message(msg, mem)
    intent = detect_intent(effective_msg)
    if intent_override_contact:
        intent = "contact_lookup"

    def _return(res: DirectoryAnswer):
        save_message(sid, "user", msg)
        save_message(sid, "assistant", res.answer)
        return res

    from urllib.parse import urlparse, unquote
    from pathlib import PurePosixPath

    def _extract_pdf_filenames(lampiran_list: list) -> list[str]:
        out = []
        for f in lampiran_list or []:
            url = (f.get("url") or "").strip()
            nama = (f.get("nama_file") or "").strip()

            if url:
                path = unquote(urlparse(url).path)
                fn = PurePosixPath(path).name
                if fn.lower().endswith(".pdf"):
                    out.append(fn)

            if nama and nama.lower().endswith(".pdf"):
                out.append(nama)

        # dedup preserve order
        seen = set()
        uniq = []
        for x in out:
            xl = x.lower()
            if xl in seen:
                continue
            seen.add(xl)
            uniq.append(x)
        return uniq

    def _append_lampiran_to_answer(answer_text: str, lampiran_list: list) -> str:
        if not lampiran_list:
            return answer_text

        lines = [answer_text.rstrip(), "", "Lampiran dokumen:"]
        for f in lampiran_list or []:
            nama = (f.get("nama_file") or "Dokumen").strip()
            url = (f.get("url") or "").strip()
            if url:
                lines.append(f"- {nama}: {url}")
            else:
                lines.append(f"- {nama}")
        return "\n".join(lines).strip()

    # 1) CONTACT
    if intent == "contact_lookup":
        if not app.state.contacts_by_id:
            return _return(DirectoryAnswer(
                mode="not_found",
                answer="Data kontak belum tersedia (startup gagal).",
                citations=[],
                followups=[],
            ))
        ans, cites, followups = answer_contact(msg, app.state.contacts_by_id)
        return _return(DirectoryAnswer(mode="contact_lookup", answer=ans, citations=cites, followups=followups))

    # 2) ORG STRUCTURE
    if intent == "org_structure":
        if not app.state.units_by_id:
            return _return(DirectoryAnswer(
                mode="not_found",
                answer="Data struktur organisasi belum tersedia (startup gagal).",
                citations=[],
                followups=[],
            ))
        ans, cites, followups = answer_org(msg, app.state.units_by_id)
        return _return(DirectoryAnswer(mode="org_structure", answer=ans, citations=cites, followups=followups))

    # 2.5) SITE HELP (penjelasan fitur portal)
    if intent == "site_help":
        from app.site_help import answer_feature
        ans = answer_feature(msg)
        return _return(DirectoryAnswer(
            mode="faq",
            answer=ans,
            citations=["Sumber: penjelasan fitur portal"],
            followups=["Kamu mau saya arahkan ke menu Dataset, Geospasial, Publikasi, FAQ, atau Request Data?"],
        ))

    # 3) FAQ (KB ringkas -> bisa naik ke PDF)
    if intent == "faq":
        if not app.state.faq_index:
            return _return(DirectoryAnswer(
                mode="not_found",
                answer="FAQ lokal belum tersedia (startup gagal).",
                citations=[],
                followups=[],
            ))

        q_clean, ranked = app.state.faq_index.search(msg, top_k=1)
        if not ranked:
            return _return(DirectoryAnswer(
                mode="not_found",
                answer="Saya belum menemukan FAQ yang sesuai.",
                citations=["Sumber: FAQ lokal"],
                followups=["Coba gunakan kata kunci yang lebih spesifik."],
            ))

        item = ranked[0][1]
        answer = (item.get("jawaban") or "").strip()
        lampiran = item.get("lampiran_file") or []
        allowed_docs = _extract_pdf_filenames(lampiran)

        # ✅ hanya naik ke FAQ_DOC kalau ada lampiran PDF
        if allowed_docs and app.state.faq_docs_index:
            res = answer_faq_doc_llm(
                question=(item.get("pertanyaan") or msg),
                faq_docs_index=app.state.faq_docs_index,
                llm=app.state.llm,
                allowed_docs=allowed_docs,
            )
            if res.mode == "not_found":
                # ✅ kalau LLM bilang TIDAK RELEVAN, jangan jatuh ke RAW
                if (res.answer or "").strip().upper() == "TIDAK RELEVAN":
                    return _return(DirectoryAnswer(
                        mode="faq",
                        answer=_append_lampiran_to_answer(
                            answer or "Saya menemukan FAQ terkait, tetapi jawabannya kosong.",
                            lampiran
                        ),
                        citations=["Sumber: FAQ lokal"],
                        followups=["Kalau ingin detail dari dokumen, sebut bagian/istilah yang dicari (mis. pasal, definisi, tugas, alur)."],
                    ))

                # selain itu, kalau memang kamu tetap mau RAW untuk kasus “beneran gagal”
                raw = answer_faq_doc_raw(
                    question=(item.get("pertanyaan") or msg),
                    faq_docs_index=app.state.faq_docs_index,
                    allowed_docs=allowed_docs,
                )
                return _return(raw)

            return _return(res)

        # ✅ fallback FAQ biasa
        return _return(DirectoryAnswer(
            mode="faq",
            answer=_append_lampiran_to_answer(
                answer or "Saya menemukan FAQ terkait, tetapi jawabannya kosong.",
                lampiran
            ),
            citations=["Sumber: FAQ lokal"],
            followups=["Jika ada dokumen PDF terkait, tanyakan detail isi dokumen tersebut."],
        ))

    # 4) FAQ_DOC (langsung tanya isi dokumen)
    if intent == "faq_doc":
        if not app.state.faq_docs_index:
            return _return(DirectoryAnswer(
                mode="not_found",
                answer="Index dokumen belum tersedia (startup gagal).",
                citations=[],
                followups=[],
            ))

        res = answer_faq_doc_llm(
            question=msg,
            faq_docs_index=app.state.faq_docs_index,
            llm=app.state.llm,
        )
        if res.mode == "not_found":
            raw = answer_faq_doc_raw(
                question=msg,
                faq_docs_index=app.state.faq_docs_index,
            )
            return _return(raw)
        return _return(res)

    if intent == "general_info":
        if app.state.faq_index:
            q_clean, ranked = app.state.faq_index.search(msg, top_k=1)
            if ranked:
                item = ranked[0][1]
                answer = (item.get("jawaban") or "").strip()
                lampiran = item.get("lampiran_file") or []

                if _has_pdf_lampiran(lampiran) and app.state.faq_docs_index:
                    res = answer_faq_doc_llm(
                        question=(item.get("pertanyaan") or msg),
                        faq_docs_index=app.state.faq_docs_index,
                        llm=app.state.llm,
                    )
                    if res.mode == "not_found":
                        raw = answer_faq_doc_raw(
                            question=(item.get("pertanyaan") or msg),
                            faq_docs_index=app.state.faq_docs_index,
                        )
                        raw.answer = _append_lampiran_to_answer(raw.answer, lampiran)
                        return _return(raw)

                    res.answer = _append_lampiran_to_answer(res.answer, lampiran)
                    return _return(res)

                return _return(DirectoryAnswer(
                    mode="faq",
                    answer=_append_lampiran_to_answer(
                        answer or "Saya menemukan FAQ terkait, tetapi jawabannya kosong.",
                        lampiran
                    ),
                    citations=["Sumber: FAQ lokal"],
                    followups=["Jika ada dokumen PDF terkait, tanyakan detail isi dokumen tersebut."],
                ))

        return _return(DirectoryAnswer(
            mode="faq",
            answer=(
                "Banyuwangi Satu Data adalah portal untuk publikasi dan integrasi data resmi Pemkab Banyuwangi.\n"
                "Data disediakan oleh OPD (produsen data) dan dikelola melalui mekanisme Satu Data.\n\n"
                "Kalau kamu mencari dataset tertentu, sebut kata kunci temanya (mis. 'kematian', 'stunting', 'penduduk')."
            ),
            citations=["Sumber: penjelasan umum (aturan Satu Data/portal)"],
            followups=["Contoh: 'ada dataset kematian?', 'dataset stunting 2023', 'cara request data'."],
        ))

    # 5) DATASET
    if intent == "dataset_search":
        if not app.state.dataset_index:
            return _return(DirectoryAnswer(
                mode="not_found",
                answer="Katalog dataset belum tersedia (startup gagal).",
                citations=[],
                followups=[],
            ))

        q = re.sub(r"\b(dataset|data|tentang|mengenai|soal|terkait)\b", " ", msg, flags=re.I)
        q = re.sub(r"\s+", " ", q).strip()

        q_clean, results = app.state.dataset_index.search(q, top_k=5)
        if not results:
            return _return(DirectoryAnswer(
                mode="not_found",
                answer="Dataset tidak ditemukan.",
                citations=["Sumber: katalog dataset lokal"],
                followups=["Coba kata kunci lain (mis. tema, OPD, atau tahun)."],
            ))

        lines = ["Dataset yang relevan:"]
        for i, (_, it) in enumerate(results, start=1):
            title = (it.get("title") or it.get("judul") or "").strip()
            if title:
                lines.append(f"{i}) {title}")

        return _return(DirectoryAnswer(
            mode="dataset_search",
            answer="\n".join(lines),
            citations=["Sumber: katalog dataset lokal"],
            followups=["Balas dengan judul/nomor yang kamu maksud agar saya persempit."],
        ))

    # ✅ Jangan fallback ke dokumen kalau pertanyaan kontak
    if app.state.faq_docs_index and (not CONTACT_OVERRIDE_RE.search(msg)):
        q_clean, hits = app.state.faq_docs_index.search(msg, top_k=3)
        if hits and hits[0][0] >= 0.18:
            res = answer_faq_doc_llm(
                question=msg,
                faq_docs_index=app.state.faq_docs_index,
                llm=app.state.llm,
            )
            if res.mode != "not_found":
                return _return(res)
            raw = answer_faq_doc_raw(
                question=msg,
                faq_docs_index=app.state.faq_docs_index,
            )
            return _return(raw)

    return _return(DirectoryAnswer(
        mode="not_found",
        answer="Saya belum bisa menangani pertanyaan tersebut.",
        citations=[],
        followups=["Coba tanya tentang FAQ, isi dokumen, struktur, kontak, atau dataset."],
    ))

@app.get("/debug/find")
def debug_find(q: str):
    hits = []
    for ch in app.state.faq_docs_index.chunks[:]:
        text = (ch.get("text") or "").lower()
        if q.lower() in text:
            hits.append({
                "doc": ch.get("doc_id"),
                "page": ch.get("page"),
                "preview": (ch.get("text") or "")[:250]
            })
            if len(hits) >= 10:
                break
    return {"q": q, "hits": hits}
