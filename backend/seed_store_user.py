"""
Create a store-scoped login (role: staff or store_admin).

Run this yourself, interactively, in your own terminal — never paste the
password into chat. The password is bcrypt-hashed locally before it ever
touches the database; only the hash is stored.

Usage:
    cd backend
    python seed_store_user.py

No store name or ID is hardcoded here — the store list is read live from
the `stores` table and you pick one, so this script works for any store,
not just Bondi.
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import text
from passlib.context import CryptContext
from dotenv import load_dotenv
import uuid

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

VALID_ROLES = ("staff", "store_admin")  # master_admin has no store_id — use seed_admin.py for that


async def seed():
    if not DATABASE_URL:
        print("❌ DATABASE_URL not set in .env")
        return

    print("🔧 Connecting to database...")
    engine = create_async_engine(DATABASE_URL, echo=False)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with SessionLocal() as session:
        stores = (await session.execute(
            text("SELECT id, name, label FROM stores WHERE is_active = true ORDER BY name")
        )).all()

        if not stores:
            print("❌ No active stores found — seed stores first.")
            await engine.dispose()
            return

        print("\n📍 Active stores:")
        for i, s in enumerate(stores, start=1):
            print(f"   {i}. {s.name} ({s.label})")

        choice = input(f"\n   Pick a store [1-{len(stores)}]: ").strip()
        try:
            store = stores[int(choice) - 1]
        except (ValueError, IndexError):
            print("❌ Invalid selection")
            await engine.dispose()
            return

        print(f"\n📋 Creating login for {store.name}")
        email = input("   Email: ").strip()

        role = input(f"   Role {VALID_ROLES} [store_admin]: ").strip() or "store_admin"
        if role not in VALID_ROLES:
            print(f"❌ Invalid role — must be one of {VALID_ROLES}")
            await engine.dispose()
            return

        password = input("   Password: ").strip()
        if not password:
            print("❌ Password cannot be empty")
            await engine.dispose()
            return
        full_name = input("   Full name: ").strip()
        initials = input("   Initials (e.g. JD): ").strip().upper()

        existing = (await session.execute(
            text("SELECT id FROM users WHERE email = :email"),
            {"email": email}
        )).scalar_one_or_none()
        if existing:
            print(f"⚠️  User {email} already exists — not overwriting.")
            await engine.dispose()
            return

        user_id = str(uuid.uuid4())
        hashed = pwd_context.hash(password)

        await session.execute(
            text("""
                INSERT INTO users (id, email, password_hash, full_name, initials, role, store_id)
                VALUES (:id, :email, :password_hash, :full_name, :initials, :role, :store_id)
            """),
            {
                "id": user_id,
                "email": email,
                "password_hash": hashed,
                "full_name": full_name,
                "initials": initials,
                "role": role,
                "store_id": str(store.id),
            }
        )
        await session.commit()

    print(f"\n✅ {role} created: {email} → {store.name}")
    print("   You can now log in at http://localhost:5173")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
