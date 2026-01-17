# app/formatters.py
import re
from typing import Any, Dict, List, Tuple

def _clean_text(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s

def format_faq_answer(jawaban: str, lampiran: List[Dict[str, Any]]) -> str:
    """
    Output FAQ yang rapi dan konsisten:
    - jawaban (kalau ada)
    - lampiran (kalau ada) => list jelas
    """
    lines: List[str] = []
    jawaban = _clean_text(jawaban)

    if jawaban:
        lines.append(jawaban)
    else:
        lines.append("Saya menemukan FAQ terkait, tetapi teks jawabannya tidak tersedia.")

    if lampiran:
        lines.append("")
        lines.append("Lampiran dokumen:")
        for f in lampiran:
            nama = _clean_text(f.get("nama_file") or "Dokumen")
            url = _clean_text(f.get("url") or "")
            if url:
                lines.append(f"- {nama}: {url}")
            else:
                lines.append(f"- {nama}")

    return "\n".join(lines).strip()

def format_faq_doc_answer(bullets: List[str], citations: List[str], lampiran: List[Dict[str, Any]] = None) -> str:
    """
    Output FAQ_DOC:
    - 2–3 bullet ringkasan
    - lampiran (opsional) selalu ditaruh bawah biar user bisa download
    """
    lampiran = lampiran or []
    lines: List[str] = []

    lines.append("Ringkasan dari dokumen resmi:")
    for b in bullets[:3]:
        b = b.strip()
        if not b.startswith("-"):
            b = "- " + b
        lines.append(b)

    if lampiran:
        lines.append("")
        lines.append("Lampiran dokumen (PDF):")
        for f in lampiran:
            nama = _clean_text(f.get("nama_file") or "PDF")
            url = _clean_text(f.get("url") or "")
            if url:
                lines.append(f"- {nama}: {url}")
            else:
                lines.append(f"- {nama}")

    return "\n".join(lines).strip()
