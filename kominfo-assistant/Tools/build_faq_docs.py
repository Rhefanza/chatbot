import json
from pathlib import Path
import fitz  # pymupdf

FILES_DIR = Path("data/faq_files")
OUT = Path("data/faq_docs.jsonl")

CHUNK_SIZE = 900      # karakter
CHUNK_OVERLAP = 150   # karakter

def chunk_text(text: str):
    text = " ".join(text.split())
    if not text:
        return []
    chunks = []
    i = 0
    while i < len(text):
        j = min(len(text), i + CHUNK_SIZE)
        chunks.append(text[i:j])
        i = max(j - CHUNK_OVERLAP, j)
    return chunks

def extract_pdf(pdf_path: Path):
    doc = fitz.open(pdf_path)
    rows = []
    for page_idx in range(len(doc)):
        page = doc[page_idx]
        t = page.get_text("text") or ""
        t = t.strip()
        # Kalau PDF scan dan text kosong, ini akan kecil — nanti butuh OCR 
        if not t:
            continue
        for ci, ch in enumerate(chunk_text(t)):
            rows.append({
                "doc_id": pdf_path.name,
                "page": page_idx + 1,  # 1-index biar mudah buat manusia
                "chunk_id": ci,
                "text": ch
            })
    return rows

OUT.parent.mkdir(parents=True, exist_ok=True)
count = 0
with OUT.open("w", encoding="utf-8") as w:
    for pdf in sorted(FILES_DIR.glob("*.pdf")):
        rows = extract_pdf(pdf)
        for r in rows:
            w.write(json.dumps(r, ensure_ascii=False) + "\n")
            count += 1
        print(f"[OK] {pdf.name} -> chunks {len(rows)}")

print("Wrote:", OUT, "total_chunks:", count)
