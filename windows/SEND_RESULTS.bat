@echo off
rem Puts a zip with the results on the Desktop, to send to Nishanth.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0START_HERE.ps1" -PackOnly
