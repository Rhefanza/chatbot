import json
from pathlib import Path
from urllib.parse import urlparse

FAQ = Path("data/faq_kb.json")  # atau data/faq_banyuwangi.json kalau belum rename
FILES_DIR = Path("data/faq_files")

def basename_from_url(url: str) -> str:
    # url biasanya .../file.pdf -> ambil file.pdf
    p = urlparse(url)
    return Path(p.path).name

raw = json.loads(FAQ.read_text(encoding="utf-8"))
missing = []
present = 0

for it in raw:
    for f in (it.get("lampiran_file") or []):
        url = (f.get("url") or "").strip()
        if not url:
            continue
        fn = basename_from_url(url)
        if (FILES_DIR / fn).exists():
            present += 1
        else:
            missing.append(fn)

print("Lampiran ditemukan:", present)
print("Lampiran hilang:", len(missing))
if missing:
    print("Contoh missing (maks 20):")
    for x in missing[:20]:
        print("-", x)
