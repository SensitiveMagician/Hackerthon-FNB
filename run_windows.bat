@echo off
python -m venv .venv
call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
if not exist .env copy .env.example .env
echo Starting MALI MODE at http://127.0.0.1:8000
echo For local testing, open .env and set SECRET_KEY to a long random value.
uvicorn app.main:app --reload
