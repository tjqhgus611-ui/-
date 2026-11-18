@echo off
rem Schedule helper web app (prototype). Runs on this PC only: http://127.0.0.1:8765
start "" http://127.0.0.1:8765
python -I "%~dp0app.py"
