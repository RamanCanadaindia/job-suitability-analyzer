$action = New-ScheduledTaskAction -Execute "C:\Users\admin\.gemini\antigravity\scratch\job_suitability_analyzer\run_daily.bat"
$trigger = New-ScheduledTaskTrigger -Daily -At 7:00PM
Register-ScheduledTask -Action $action -Trigger $trigger -TaskName "JobSuitabilityAnalyzerDailyScan" -Description "Scans Indeed job alert emails and posts suitability analyses to Google Sheets daily." -Force
Write-Host "Task registered successfully!"
