import pandas as pd
import json

# Load data
with open('full_dataset_banyuwangi_3738_items.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

df = pd.DataFrame(data)

# 1. Buang UI Junk standar
trash = ['Preview', 'Selengkapnya', 'Halaman', '»', '«']
df_clean = df[~df['judul'].str.contains('|'.join(trash), case=False, na=False)]

# 2. Aturan Emas: Buang yang kurang dari 3 kata
df_clean = df_clean[df_clean['judul'].str.split().str.len() >= 2]

# 3. Hapus Duplikat
df_clean = df_clean.drop_duplicates(subset=['judul'])

print(f"Data Bersih: {len(df_clean)} item")

# Simpan untuk Chatbot
df_clean.to_json('knowledge_base_final_fix.json', orient='records', indent=4)