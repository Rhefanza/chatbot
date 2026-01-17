# tools/bootstrap_contacts_from_html.py
import json
from pathlib import Path
from bs4 import BeautifulSoup

def cf_decode(cfhex: str) -> str:
    data = bytes.fromhex(cfhex)
    key = data[0]
    decoded = bytes([b ^ key for b in data[1:]])
    return decoded.decode("utf-8", errors="replace")

html_path = Path("kominfo-assistant\Tools\Banyuwangi Satu Data _ Dataset.html")  # sesuaikan lokasi file
out_path = Path("data/official_contacts.json")

soup = BeautifulSoup(html_path.read_text(encoding="utf-8", errors="ignore"), "html.parser")

addr = soup.select_one("div.f-item.contact p")
address = addr.get_text(" ", strip=True) if addr else ""

phone = ""
for li in soup.select("div.f-item.contact li"):
    if "Kontak" in li.get_text():
        phone = li.get_text(" ", strip=True).replace("Kontak :", "").strip()

email = ""
cf = soup.select_one("a.__cf_email__")
if cf and cf.get("data-cfemail"):
    email = cf_decode(cf["data-cfemail"])

twitter = soup.select_one("ul.social li.twitter a")
instagram = soup.select_one("ul.social li.instagram a")

payload = {
  "meta": {"data_version": "0.1.0", "updated_by": "bootstrap", "updated_at": "2026-01-08"},
  "contacts": [
    {"id":"bsd_alamat","type":"alamat","label":"Alamat","value":address,"source_url":"(offline html export)","last_verified_date":"2026-01-08","notes":""},
    {"id":"bsd_tel","type":"tel","label":"Telepon","value":phone,"source_url":"(offline html export)","last_verified_date":"2026-01-08","notes":""},
    {"id":"bsd_email","type":"email","label":"Email","value":email,"source_url":"(offline html export)","last_verified_date":"2026-01-08","notes":""},
    {"id":"bsd_twitter","type":"website","label":"Twitter","value": (twitter["href"] if twitter else ""),"source_url":"(offline html export)","last_verified_date":"2026-01-08","notes":""},
    {"id":"bsd_instagram_link","type":"website","label":"Instagram (link)","value": (instagram["href"] if instagram else ""),"source_url":"(offline html export)","last_verified_date":"2026-01-08","notes":"Verifikasi handle IG sebelum ditulis sebagai @..."}
  ]
}

out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print("Wrote:", out_path)
