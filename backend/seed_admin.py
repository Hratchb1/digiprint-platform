"""
Run this ONCE after setting up the database to create your first admin user.

Usage:
    cd backend
    python seed_admin.py
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from passlib.context import CryptContext
from dotenv import load_dotenv
import uuid

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


async def seed():
    if not DATABASE_URL:
        print("❌ DATABASE_URL not set in .env")
        return

    print("🔧 Connecting to database...")
    engine = create_async_engine(DATABASE_URL, echo=False)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    print("\n📋 Creating master admin account")
    email = input("   Email: ").strip()
    password = input("   Password: ").strip()
    full_name = input("   Full name: ").strip()
    initials = input("   Initials (e.g. JD): ").strip().upper()

    async with SessionLocal() as session:
        from sqlalchemy import text

        # Check if user exists
        result = await session.execute(
            text("SELECT id FROM users WHERE email = :email"),
            {"email": email}
        )
        if result.scalar_one_or_none():
            print(f"⚠️  User {email} already exists")
            return

        user_id = str(uuid.uuid4())
        hashed = pwd_context.hash(password)

        await session.execute(
            text("""
                INSERT INTO users (id, email, password_hash, full_name, initials, role)
                VALUES (:id, :email, :password_hash, :full_name, :initials, 'master_admin')
            """),
            {
                "id": user_id,
                "email": email,
                "password_hash": hashed,
                "full_name": full_name,
                "initials": initials,
            }
        )
        await session.commit()

    print(f"\n✅ Master admin created: {email}")
    print("   You can now log in at http://localhost:5173")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
