# tools/gen_golden_faq.py
import json
from pathlib import Path

inp = Path("data/faq_kb.json")
out = Path("tests/golden_faq.json")

faqs = json.loads(inp.read_text(encoding="utf-8"))

tests = []
for it in faqs:
    q = (it.get("pertanyaan") or "").strip()
    a = (it.get("jawaban") or "").strip()
    files = [f.get("url") for f in (it.get("lampiran_file") or []) if f.get("url")]
    tc = {
        "q": q,
        "expect_mode": "faq",
        "must_contain": [],
        "must_mention_urls": files[:2]  # cukup cek 1-2 link biar nggak terlalu ketat
    }
    # ambil 1-2 kata kunci dari jawaban (heuristik simpel)
    for kw in ["request data", "SOP", "Peraturan", "JDIH", "email", "verifikasi", "validasi", "download", "unduh"]:
        if kw.lower() in a.lower():
            tc["must_contain"].append(kw)
            if len(tc["must_contain"]) >= 2:
                break

    tests.append(tc)

out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(tests, ensure_ascii=False, indent=2), encoding="utf-8")
print("Wrote", out, "count", len(tests))
