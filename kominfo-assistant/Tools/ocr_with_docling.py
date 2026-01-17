import json
import os
from pathlib import Path

from huggingface_hub import snapshot_download

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, TableStructureOptions, RapidOcrOptions
from docling.document_converter import DocumentConverter, PdfFormatOption

PROJECT_DIR = Path(__file__).resolve().parents[1]
FILES_DIR = PROJECT_DIR / "data" / "faq_files"
DOCS_PATH = PROJECT_DIR / "data" / "faq_docs.jsonl"

MAX_CHARS = 900
OVERLAP = 150


def split_text(text: str):
    text = " ".join((text or "").split())
    if not text:
        return []
    if len(text) <= MAX_CHARS:
        return [text]
    out = []
    i = 0
    while i < len(text):
        j = min(len(text), i + MAX_CHARS)
        out.append(text[i:j])
        i = max(j - OVERLAP, j)
    return out


def existing_doc_ids() -> set[str]:
    if not DOCS_PATH.exists():
        return set()
    ids = set()
    with DOCS_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if obj.get("doc_id"):
                    ids.add(obj["doc_id"])
            except Exception:
                pass
    return ids


def build_converter():
    # 1) download RapidOCR models (sekali, lalu cache)
    print("Downloading RapidOCR models (HuggingFace cache)…")
    download_path = snapshot_download(repo_id="SWHL/RapidOCR")

    det_model_path = os.path.join(download_path, "PP-OCRv4", "en_PP-OCRv3_det_infer.onnx")
    rec_model_path = os.path.join(download_path, "PP-OCRv4", "ch_PP-OCRv4_rec_server_infer.onnx")
    cls_model_path = os.path.join(download_path, "PP-OCRv3", "ch_ppocr_mobile_v2.0_cls_train.onnx")

    ocr_options = RapidOcrOptions(
        det_model_path=det_model_path,
        rec_model_path=rec_model_path,
        cls_model_path=cls_model_path,
    )

    pdf_options = PdfPipelineOptions()
    pdf_options.do_ocr = True
    pdf_options.do_table_structure = True
    pdf_options.table_structure_options = TableStructureOptions(do_cell_matching=True)
    pdf_options.ocr_options = ocr_options

    # 2) force full-page OCR (jika field ini ada di versi docling kamu)
    try:
        pdf_options.ocr_options.force_full_page_ocr = True
    except Exception:
        pass

    fmt_opt = PdfFormatOption(pipeline_options=pdf_options)

    # 3) coba pakai backend pdfium jika tersedia (lebih kompatibel untuk PDF sulit)
    try:
        from docling.backends.pdf_backend import PyPdfiumDocumentBackend
        fmt_opt = PdfFormatOption(pipeline_options=pdf_options, backend=PyPdfiumDocumentBackend)
    except Exception:
        pass

    return DocumentConverter(
        format_options={InputFormat.PDF: fmt_opt}
    )


def main():
    if not FILES_DIR.exists():
        raise FileNotFoundError(f"Folder tidak ada: {FILES_DIR}")

    already = existing_doc_ids()
    pdfs = sorted(FILES_DIR.glob("*.pdf"))
    todo = [p for p in pdfs if p.name not in already]

    print("Total PDF:", len(pdfs))
    print("Sudah ada chunks:", len(already))
    print("Perlu OCR (missing in jsonl):", len(todo))
    if not todo:
        print("Tidak ada yang perlu di-OCR.")
        return

    converter = build_converter()

    DOCS_PATH.parent.mkdir(parents=True, exist_ok=True)
    added = 0

    with DOCS_PATH.open("a", encoding="utf-8") as out:
        for pdf in todo:
            print(f"\n[OCR] {pdf.name}")
            try:
                result = converter.convert(str(pdf))
                doc = result.document
                md = (doc.export_to_markdown() or "").strip()
            except Exception as e:
                print(f"  [FAIL] convert/export: {e}")
                continue

            if not md:
                print("  [WARN] Markdown kosong setelah OCR. (Coba cek PDF benar-benar scan / backend)")
                continue

            chunk_id = 0
            n_before = added

            for piece in split_text(md):
                row = {
                    "doc_id": pdf.name,
                    "page": None,          # markdown export tidak selalu bawa info halaman secara stabil
                    "chunk_id": chunk_id,
                    "text": piece,
                }
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                chunk_id += 1
                added += 1

            print(f"  [OK] added_chunks: {added - n_before}")

    print("\nDone. Total chunks appended:", added)
    print("Output:", DOCS_PATH)


if __name__ == "__main__":
    main()
