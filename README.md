# digiPrint Operations Platform

National film processing + B2B order management system for digiDirect.

## Stack
- **Backend**: FastAPI (Python)
- **Database**: PostgreSQL via Supabase (managed, free tier)
- **Frontend**: React + Vite
- **Hosting**: Railway (when ready to deploy)

## Quick Start

### 1. Prerequisites
- Python 3.11+
- Node.js 18+
- A free Supabase account (supabase.com)

### 2. Backend Setup
```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Fill in your Supabase credentials in .env
uvicorn app.main:app --reload --port 8000
```

### 3. Frontend Setup
```bash
cd frontend
npm install
cp .env.example .env
# Set VITE_API_URL=http://localhost:8000
npm run dev
```

### 4. Supabase Setup
1. Go to supabase.com, create a free project
2. Go to SQL Editor, paste and run the contents of `backend/migrations/001_initial.sql`
3. Copy your project URL and anon key into backend `.env`

## Stores
Each store has its own config. Add stores via the Admin panel.
Current stores: Bondi, Miranda, Parramatta, Brisbane, Cannington

## Project Structure
```
digiprint/
├── backend/
│   ├── app/
│   │   ├── api/          # Route handlers
│   │   ├── models/       # Pydantic schemas
│   │   ├── services/     # Business logic
│   │   └── core/         # Config, DB, auth
│   └── migrations/       # SQL migrations
└── frontend/
    └── src/
        ├── components/   # Reusable UI
        ├── pages/        # Route pages
        ├── hooks/        # Custom React hooks
        └── lib/          # API client, utils
```
