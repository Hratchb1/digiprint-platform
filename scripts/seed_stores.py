"""
scripts/seed_stores.py — Create the initial stores in the DB
Run once after first setup: python -m scripts.seed_stores
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.db.database import SessionLocal
from backend.models import Store, Base
from backend.db.database import engine

Base.metadata.create_all(bind=engine)

STORES = [
    {
        "name": "Bondi",
        "label": "digiDirect Bondi",
        "reply_to": "lab.bondi@digidirect.com.au",
        "drive_root_id": "1XKV9aV9AQy1wXYGwkEZDfZfogi3Y1hv2",   # ← update to real ID
        "drive_inbox_id": "1XKV9aV9AQy1wXYGwkEZDfZfogi3Y1hv2",  # ← update to real ID
    },
    {
        "name": "Miranda",
        "label": "digiDirect Miranda",
        "reply_to": "lab.miranda@digidirect.com.au",
    },
    {
        "name": "Parramatta",
        "label": "digiDirect Parramatta",
        "reply_to": "lab.parramatta@digidirect.com.au",
    },
    {
        "name": "Brisbane",
        "label": "digiDirect Brisbane",
        "reply_to": "lab.brisbane@digidirect.com.au",
    },
    {
        "name": "Cannington",
        "label": "digiDirect Cannington",
        "reply_to": "lab.cannington@digidirect.com.au",
    },
]

db = SessionLocal()
for s in STORES:
    existing = db.query(Store).filter(Store.name == s["name"]).first()
    if existing:
        print(f"  Skip (exists): {s['name']}")
        continue
    store = Store(**s)
    db.add(store)
    print(f"  Created: {s['name']}")

db.commit()
db.close()
print("\nDone. All stores seeded.")
