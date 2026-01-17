# app/site_help.py
import re
from typing import Tuple, List

# Template jawaban per fitur (ringkas, publik-friendly)
FEATURE_ANSWERS = {
    "katalog": (
        "Katalog Dataset adalah tempat mencari dataset/indikator di portal.\n"
        "- Gunakan kotak pencarian untuk kata kunci (mis. 'stunting', 'ATS', 'kemiskinan').\n"
        "- Jika data tidak ditemukan, gunakan menu Request Data."
    ),
    "metadata": (
        "Metadata adalah informasi pendukung pada halaman dataset.\n"
        "- Biasanya mencakup definisi indikator, satuan, periode/tahun, dan pembaruan (jika tersedia).\n"
        "- Metadata membantu menghindari salah tafsir dan menunjukkan produsen data yang bisa dihubungi."
    ),
    "geospasial": (
        "Geospasial menampilkan data berbasis peta (lokasi/wilayah).\n"
        "- Cocok untuk melihat persebaran fasilitas atau indikator kewilayahan.\n"
        "- Gunakan saat membutuhkan konteks lokasi, bukan hanya angka tabel."
    ),
    "publikasi": (
        "Publikasi berisi ringkasan/visualisasi atau dokumen informasi yang disusun untuk dibaca cepat.\n"
        "- Cocok untuk mendapatkan gambaran tanpa mengolah data mentah.\n"
        "- Jika butuh angka detail, kembali ke Dataset/Katalog."
    ),
    "faq": (
        "FAQ berisi tanya-jawab yang membantu memahami portal dan prosedur umum.\n"
        "- Jika pertanyaan Anda bersifat prosedural (cara pakai, request data), cek FAQ terlebih dahulu."
    ),
    "request_data": (
        "Request Data digunakan jika data yang Anda butuhkan belum tersedia di katalog.\n"
        "- Jelaskan data yang dibutuhkan, periode/tahun, dan cakupan wilayah.\n"
        "- Jika ada kontak produsen data/OPD terkait, sebutkan agar proses lebih cepat."
    ),
    "login": (
        "Fitur Masuk/Login biasanya dipakai oleh admin/pengelola SKPD/Kecamatan/Desa.\n"
        "- Untuk masyarakat umum, umumnya cukup mengakses katalog dataset dan publikasi tanpa login.\n"
        "- Jika Anda pengelola, gunakan akun instansi sesuai ketentuan portal."
    ),
}

# Pola kata kunci -> fitur
FEATURE_PATTERNS = [
    ("geospasial", r"\b(geospasial|geoportal|peta|pemetaan|spasial)\b"),
    ("publikasi", r"\b(publikasi|infografis|laporan|artikel)\b"),
    ("request_data", r"\b(request\s*data|permintaan\s*data|minta\s*data|pengajuan\s*data)\b"),
    ("faq", r"\b(faq|tanya\s*jawab|pusat\s*bantuan|bantuan)\b"),
    ("metadata", r"\b(metadata|definisi|satuan|frekuensi|periode|tahun\s*rilis|pembaruan)\b"),
    ("katalog", r"\b(katalog|dataset|cari\s*data|pencarian|filter|indikator)\b"),
    ("login", r"\b(login|masuk|akun|skpd|kecamatan|desa)\b"),
]

def detect_feature_intent(msg: str) -> Tuple[bool, str]:
    """
    Return (is_feature_question, feature_key).

    Prinsip:
    - site_help hanya untuk pertanyaan tentang fitur/menu/cara pakai/di mana/apa itu.
    - Jika user bilang "cari dataset ..." tanpa kata tanya fitur -> JANGAN masuk site_help.
    """
    m = (msg or "").lower().strip()
    if not m:
        return False, ""

    # 1) Kalau user jelas-jelas ingin mencari data/dataset, biarkan masuk dataset_search
    # (kecuali kalau dia tanya cara pakainya)
    is_search_intent = bool(re.search(r"\b(cari|mencari|carikan|search|temukan)\b", m)) and bool(re.search(r"\b(dataset|data|indikator)\b", m))
    asks_how = bool(re.search(r"\b(fitur|menu|cara\s*pakai|cara\s*menggunakan|panduan|di\s*mana|bagaimana\s*pakai|apa\s*itu)\b", m))

    if is_search_intent and not asks_how:
        return False, ""

    # 2) Trigger pertanyaan fitur (HARUS ada)
    if not asks_how:
        # kalau tidak ada kata tanya fitur, hanya aktif bila menyebut fitur spesifik yang biasanya memang ditanya
        # (mis. geospasial, request data, login, publikasi, FAQ)
        for key, pat in FEATURE_PATTERNS:
            if key in ("geospasial", "publikasi", "request_data", "faq", "login") and re.search(pat, m):
                return True, key
        return False, ""

    # 3) Kalau ada kata tanya fitur, tentukan fitur yang dimaksud
    for key, pat in FEATURE_PATTERNS:
        if re.search(pat, m):
            return True, key

    # default kalau tanya fitur tapi tidak jelas: jelaskan katalog
    return True, "katalog"


def answer_feature(msg: str) -> str:
    is_q, key = detect_feature_intent(msg)
    if not is_q:
        return ""
    return FEATURE_ANSWERS.get(key, FEATURE_ANSWERS["katalog"])
