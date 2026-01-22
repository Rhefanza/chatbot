import json
import re
from pathlib import Path
from typing import Dict, List, Tuple

from .schemas import Contact, OrgUnit
from app.site_help import detect_feature_intent

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def load_contacts() -> Dict[str, Contact]:
    p = DATA_DIR / "official_contacts.json"
    raw = json.loads(p.read_text(encoding="utf-8"))
    contacts = [Contact(**c) for c in raw.get("contacts", [])]
    return {c.id: c for c in contacts}


def load_units() -> Dict[str, OrgUnit]:
    p = DATA_DIR / "org_structure.json"
    if not p.exists():
        return {}  # belum ada data
    raw = json.loads(p.read_text(encoding="utf-8"))
    units = [OrgUnit(**u) for u in raw.get("units", [])]
    return {u.id: u for u in units}

CONTACT_KEYWORDS = {
    "ig": ["ig", "instagram"],
    "twitter": ["twitter", "x"],
    "wa": ["wa", "whatsapp", "whatssapp", "w.a"],
    "email": ["email", "e-mail", "surel"],
    "tel": ["telp", "telepon", "phone", "kontak", "nomor"],
    "website": ["website", "web", "situs", "url"],
    "ppid": ["ppid", "informasi publik"],
    "pengaduan": ["pengaduan", "aduan", "lapor", "keluhan"],
    "alamat": ["alamat", "lokasi", "kantor"],
}


# Kontak harus eksplisit (jangan pernah pakai kata umum seperti "data", "apakah", "bisa", dll)
CONTACT_RE = re.compile(
    r"\b("
    r"kontak|contact|hubungi|"
    r"email|e-mail|mail|surel|"
    r"telepon|telp|telfon|no\.?\s*hp|nomor|hp|"
    r"wa|whatsapp|"
    r"ig|instagram|"
    r"twitter|x|"
    r"facebook|fb|"
    r"alamat|lokasi|maps|"
    r"jam layanan|jam kerja"
    r")\b",
    re.I
)

ORG_RE = re.compile(
    r"\b(struktur|organisasi|tupoksi|tugas|fungsi|bidang|seksi|unit|pegawai|jabatan)\b",
    re.I
)

# FAQ: layanan, prosedur, trustworthiness, pertanyaan umum portal
FAQ_RE = re.compile(
    r"\b("
    r"faq|"
    r"apakah|bagaimana|gimana|mengapa|kenapa|"
    r"dipercaya|dapat dipercaya|akurat|valid|validasi|verifikasi|"
    r"sumber data|metodologi|"
    r"permintaan data|minta data|request data|pengajuan data|"
    r"prosedur|syarat|"
    r"form|formulir|unduh|download|lampiran|"
    r"sop|panduan|manual"
    r")\b",
    re.I
)

FAQ_DOC_RE = re.compile(
    r"\b(perbup|peraturan bupati|peraturan|agenda|berita acara|buku panduan|sop statistik)\b",
    re.I
)

DATASET_RE = re.compile(
    r"\b(dataset|data|katalog dataset|judul dataset|tema dataset|indikator)\b",
    re.I
)


def detect_intent(text: str) -> str:
    t = (text or "").strip()
    tl = t.lower()

    # 1) CONTACT harus menang dulu (biar email/ig/twitter/alamat tidak nyasar ke site_help atau doc)
    if CONTACT_RE.search(t):
        return "contact_lookup"

    # 2) ORG
    if ORG_RE.search(t):
        return "org_structure"

    # 3) DATASET (naikkan prioritas sebelum site_help/FAQ)
    if DATASET_RE.search(t) or tl.startswith("dataset ") or ("dataset" in tl):
        return "dataset_search"

    # 4) SITE HELP: hanya setelah kontak/dataset/org lolos dulu
    is_feat, _ = detect_feature_intent(text)
    if is_feat:
        return "site_help"

    # 5) GENERAL INFO (pertanyaan awam)
    if ("apa itu" in tl) or ("itu apa" in tl) or ("data bwi" in tl) or ("banyuwangi satu data" in tl):
        return "general_info"

    # 6) FAQ_DOC (kalau query jelas minta dokumen regulasi)
    if FAQ_DOC_RE.search(t):
        return "faq_doc"

    # 7) FAQ (pertanyaan layanan / trust / prosedur portal)
    if FAQ_RE.search(t):
        return "faq"

    return "not_found"


def pick_contact_types(text: str) -> List[str]:
    """
    Perbaikan penting:
    - Jangan pakai `if k in t` karena 'ig' bisa nyangkut di kata lain (mis. "tinggi").
    - Pakai regex word-boundary agar hanya match token yang benar.
    """
    t = (text or "").lower()
    types: List[str] = []

    for ctype, kws in CONTACT_KEYWORDS.items():
        for k in kws:
            # boundary aman untuk token pendek seperti "ig", "wa"
            if re.search(rf"(?<!\w){re.escape(k)}(?!\w)", t):
                types.append(ctype)
                break

    return types


def format_contacts(contacts: List[Contact]) -> Tuple[str, List[str]]:
    lines = []
    citations = []
    for c in contacts:
        pretty = f"{c.label}: {c.value}"
        lines.append(pretty)
        citations.append(f"Sumber: {c.source_url} | Terakhir diverifikasi: {c.last_verified_date}")
    return "\n".join(lines), citations


def answer_contact(text: str, contacts_by_id: Dict[str, Contact]) -> Tuple[str, List[str], List[str]]:
    requested_types = set(pick_contact_types(text))
    all_contacts = list(contacts_by_id.values())

    # If user is vague ("kontak kominfo"), return all contacts
    if not requested_types:
        selected = all_contacts
    else:
        req = {x.lower().strip() for x in requested_types}
        selected = []

        for c in all_contacts:
            ctype = (c.type or "").lower().strip()
            clabel = (c.label or "").lower().strip()

            # match normal berdasarkan type
            if ctype in req:
                selected.append(c)
                continue

            # fallback: data IG/Twitter kamu saat ini bertipe "website"
            if ctype == "website":
                if ("ig" in req) and ("instagram" in clabel):
                    selected.append(c)
                    continue
                if ("twitter" in req) and ("twitter" in clabel):
                    selected.append(c)
                    continue


    if not selected:
        return (
            "Saya belum menemukan kontak tersebut di data yang saya pegang. "
            "Kalau kamu punya sumber resmi/tautan resminya, aku bisa bantu tambahkan ke daftar kontak.",
            [],
            ["Kamu butuh kontak untuk layanan apa (PPID/pengaduan/umum)?"]
        )

    ans, citations = format_contacts(selected)
    return ans, citations, []


def answer_org(text: str, units_by_id: Dict[str, OrgUnit]) -> Tuple[str, List[str], List[str]]:
    t = text.lower()

    # naive match by unit name token overlap
    scored = []
    for u in units_by_id.values():
        name = u.name.lower()
        score = 0
        for tok in set(t.split()):
            if len(tok) >= 4 and tok in name:
                score += 1
        scored.append((score, u))

    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best = scored[0] if scored else (0, None)

    if not best or best_score == 0:
        # fallback: show top-level units as overview
        top = [u for u in units_by_id.values() if u.parent_id is None]
        if top:
            overview = "\n".join([f"- {u.name}" for u in top])
            return (
                "Saya belum bisa mencocokkan unit spesifik dari pertanyaanmu. Berikut gambaran unit tingkat atas yang tersedia:\n"
                f"{overview}",
                [],
                ["Sebutkan nama bidang/unit yang kamu maksud (mis. Aptika/Humas/Persandian)."]
            )

        return (
            "Data struktur organisasi belum tersedia di repositori lokal.",
            [],
            ["Tambahkan unit di org_structure.json dulu ya."]
        )

    lines = [f"**{best.name}**"]
    if best.tasks:
        lines.append("Tugas ringkas:")
        lines.extend([f"- {x}" for x in best.tasks])

    # simple breadcrumb
    if best.parent_id and best.parent_id in units_by_id:
        lines.append(f"Di bawah: {units_by_id[best.parent_id].name}")

    return "\n".join(lines), [], []
