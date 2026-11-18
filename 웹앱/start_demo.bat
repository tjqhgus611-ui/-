@echo off
rem Presentation mode: executive schedule is fictional demo data. http://127.0.0.1:8766
set SCHEDULE_DEMO=1
start "" http://127.0.0.1:8766
python -I "%~dp0app.py"
