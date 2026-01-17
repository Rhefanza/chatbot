import json
from pathlib import Path
from datetime import date

INP = Path("kominfo-assistant\data\knowledge_base_final_fix.json")   # sesuaikan lokasi
OUT = Path("kominfo-assistant\data/dataset_catalog.json")

raw = json.loads(INP.read_text(encoding="utf-8"))

# raw bisa list atau dict
items = raw if isinstance(raw, list) else raw.get("datasets", raw.get("items", []))

datasets = []
for it in items:
    title = (it.get("title") or it.get("judul") or "").strip()
    if not title:
        continue
    datasets.append({
        "id": it.get("id"),
        "page": it.get("halaman"),
        "title": title,
        "detail_url": it.get("detail_url")  # kalau belum ada, biarkan null
    })

payload = {
    "meta": {
        "source": "banyuwangi satu data (judul saja)",
        "updated_at": str(date.today()),
        "count": len(datasets)
    },
    "datasets": datasets
}

OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print("Wrote:", OUT, "count:", len(datasets))
