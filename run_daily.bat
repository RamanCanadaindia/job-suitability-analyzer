@echo off
cd /d "C:\Users\admin\.gemini\antigravity\scratch\job_suitability_analyzer"
python daily_job_scanner.py >> daily_scan.log 2>&1
