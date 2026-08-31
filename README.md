# Banyuwangi Information Assistant

Asisten informasi berbasis web untuk membantu pencarian FAQ, dokumen, direktori, dan data layanan publik Banyuwangi.

## Fitur

- Pencarian FAQ dan dokumen.
- Pencarian direktori serta dataset.
- Backend API menggunakan FastAPI.
- Frontend React/Vite.
- Integrasi LLM opsional untuk menyusun jawaban.
- Knowledge base lokal dari data Banyuwangi.

## Struktur Proyek

```text
chatbot/
├── kominfo-assistant/
│   ├── app/            # Backend FastAPI dan modul pencarian
│   ├── FE/             # Frontend React/Vite
│   ├── Tests/          # Pengujian
│   ├── Tools/          # Utilitas pengolahan data
│   └── data/           # Knowledge base aplikasi
├── ambil_data.py       # Pembersihan data mentah
└── requirements.txt
```

## Menjalankan Backend

```bash
git clone https://github.com/Rhefanza/chatbot.git
cd chatbot/kominfo-assistant
python -m venv .venv
```

Aktifkan virtual environment, lalu jalankan:

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Dokumentasi API tersedia di `http://127.0.0.1:8000/docs`.

## Menjalankan Frontend

```bash
cd kominfo-assistant/FE
npm install
npm run dev
```

## Catatan Konfigurasi

Jika fitur LLM digunakan, simpan API key melalui environment variable atau file konfigurasi lokal yang tidak di-commit. Jangan menaruh kredensial langsung di source code.

## Teknologi

Python, FastAPI, scikit-learn, React, Vite, dan JSON knowledge base.
