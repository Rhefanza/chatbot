import re
from fastapi import FastAPI
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

import os

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

app = FastAPI(title="Kominfo Assistant Chatbot")


class ChatIn(BaseModel):
    message: str


def _has_pdf_lampiran(lampiran_list: list) -> bool:
    """Deteksi cepat apakah lampiran mengandung file PDF."""
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

    intent = detect_intent(msg)
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
        """
        Tambahkan daftar lampiran di bawah jawaban (kalau ada).
        Ini hanya formatting, tidak mengubah logika retrieval.
        """
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
            return DirectoryAnswer(
                mode="not_found",
                answer="Data kontak belum tersedia (startup gagal).",
                citations=[],
                followups=[],
            )
        ans, cites, followups = answer_contact(msg, app.state.contacts_by_id)
        return DirectoryAnswer(mode="contact_lookup", answer=ans, citations=cites, followups=followups)

    # 2) ORG STRUCTURE
    if intent == "org_structure":
        if not app.state.units_by_id:
            return DirectoryAnswer(
                mode="not_found",
                answer="Data struktur organisasi belum tersedia (startup gagal).",
                citations=[],
                followups=[],
            )
        ans, cites, followups = answer_org(msg, app.state.units_by_id)
        return DirectoryAnswer(mode="org_structure", answer=ans, citations=cites, followups=followups)
    # 2.5) SITE HELP (penjelasan fitur portal)
    if intent == "site_help":
        from app.site_help import answer_feature
        ans = answer_feature(msg)
        return DirectoryAnswer(
            mode="faq",
            answer=ans,
            citations=["Sumber: penjelasan fitur portal"],
            followups=[
                "Kamu mau saya arahkan ke menu Dataset, Geospasial, Publikasi, FAQ, atau Request Data?"
            ],
        )

    # 3) FAQ (KB ringkas -> bisa naik ke PDF)
    if intent == "faq":
        if not app.state.faq_index:
            return DirectoryAnswer(
                mode="not_found",
                answer="FAQ lokal belum tersedia (startup gagal).",
                citations=[],
                followups=[],
            )

        q_clean, ranked = app.state.faq_index.search(msg, top_k=1)
        if not ranked:
            return DirectoryAnswer(
                mode="not_found",
                answer="Saya belum menemukan FAQ yang sesuai.",
                citations=["Sumber: FAQ lokal"],
                followups=["Coba gunakan kata kunci yang lebih spesifik."],
            )

        item = ranked[0][1]
        answer = (item.get("jawaban") or "").strip()
        lampiran = item.get("lampiran_file") or []

        allowed_docs = _extract_pdf_filenames(lampiran)

        res = answer_faq_doc_llm(
            question=(item.get("pertanyaan") or msg),
            faq_docs_index=app.state.faq_docs_index,
            llm=app.state.llm,
            allowed_docs=allowed_docs,   # ✅ tambah ini
        )

        if res.mode == "not_found":
            return answer_faq_doc_raw(
                question=(item.get("pertanyaan") or msg),
                faq_docs_index=app.state.faq_docs_index,
                allowed_docs=allowed_docs,  # ✅ tambah ini juga
            )
        return res


        # fallback FAQ biasa (tambahkan lampiran bila ada)
        return DirectoryAnswer(
            mode="faq",
            answer=_append_lampiran_to_answer(
                answer or "Saya menemukan FAQ terkait, tetapi jawabannya kosong.",
                lampiran
            ),
            citations=["Sumber: FAQ lokal"],
            followups=["Jika ada dokumen PDF terkait, tanyakan detail isi dokumen tersebut."],
        )

    # 4) FAQ_DOC (langsung tanya isi dokumen)
    if intent == "faq_doc":
        if not app.state.faq_docs_index:
            return DirectoryAnswer(
                mode="not_found",
                answer="Index dokumen belum tersedia (startup gagal).",
                citations=[],
                followups=[],
            )

        res = answer_faq_doc_llm(
            question=msg,
            faq_docs_index=app.state.faq_docs_index,
            llm=app.state.llm,
        )

        if res.mode == "not_found":
            return answer_faq_doc_raw(
                question=msg,
                faq_docs_index=app.state.faq_docs_index,
            )
        return res

    # ✅ FIX BUG: general_info tidak boleh menimpa FAQ yang sebenarnya ada di KB
    if intent == "general_info":
        # Coba cek dulu FAQ KB. Kalau ketemu, jalankan alur FAQ normal.
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
                        return raw

                    res.answer = _append_lampiran_to_answer(res.answer, lampiran)
                    return res

                return DirectoryAnswer(
                    mode="faq",
                    answer=_append_lampiran_to_answer(
                        answer or "Saya menemukan FAQ terkait, tetapi jawabannya kosong.",
                        lampiran
                    ),
                    citations=["Sumber: FAQ lokal"],
                    followups=["Jika ada dokumen PDF terkait, tanyakan detail isi dokumen tersebut."],
                )

        # Kalau benar-benar tidak ada FAQ yang match, baru jawab penjelasan umum
        return DirectoryAnswer(
            mode="faq",
            answer=(
                "Banyuwangi Satu Data adalah portal untuk publikasi dan integrasi data resmi Pemkab Banyuwangi.\n"
                "Data disediakan oleh OPD (produsen data) dan dikelola melalui mekanisme Satu Data.\n\n"
                "Kalau kamu mencari dataset tertentu, sebut kata kunci temanya (mis. 'kematian', 'stunting', 'penduduk')."
            ),
            citations=["Sumber: penjelasan umum (aturan Satu Data/portal)"],
            followups=["Contoh: 'ada dataset kematian?', 'dataset stunting 2023', 'cara request data'."],
        )

    # 5) DATASET
    if intent == "dataset_search":
        if not app.state.dataset_index:
            return DirectoryAnswer(
                mode="not_found",
                answer="Katalog dataset belum tersedia (startup gagal).",
                citations=[],
                followups=[],
            )

        q = re.sub(r"\b(dataset|data|tentang|mengenai|soal|terkait)\b", " ", msg, flags=re.I)
        q = re.sub(r"\s+", " ", q).strip()

        q_clean, results = app.state.dataset_index.search(q, top_k=5)
        if not results:
            return DirectoryAnswer(
                mode="not_found",
                answer="Dataset tidak ditemukan.",
                citations=["Sumber: katalog dataset lokal"],
                followups=["Coba kata kunci lain (mis. tema, OPD, atau tahun)."],
            )

        lines = ["Dataset yang relevan:"]
        for i, (_, it) in enumerate(results, start=1):
            title = (it.get("title") or it.get("judul") or "").strip()
            if title:
                lines.append(f"{i}) {title}")

        return DirectoryAnswer(
            mode="dataset_search",
            answer="\n".join(lines),
            citations=["Sumber: katalog dataset lokal"],
            followups=["Balas dengan judul/nomor yang kamu maksud agar saya persempit."],
        )

    if app.state.faq_docs_index:
        q_clean, hits = app.state.faq_docs_index.search(msg, top_k=3)
        if hits and hits[0][0] >= 0.18:
            res = answer_faq_doc_llm(
                question=msg,
                faq_docs_index=app.state.faq_docs_index,
                llm=app.state.llm,
            )
            if res.mode != "not_found":
                return res
            return answer_faq_doc_raw(
                question=msg,
                faq_docs_index=app.state.faq_docs_index,
            )

    return DirectoryAnswer(
        mode="not_found",
        answer="Saya belum bisa menangani pertanyaan tersebut.",
        citations=[],
        followups=["Coba tanya tentang FAQ, isi dokumen, struktur, kontak, atau dataset."],
    )
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
