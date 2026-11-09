@echo off
rem Shows how far the simulation is.
wsl.exe -d Ubuntu-24.04 -u root -- bash -lc "cd /root/airway-aerosol-delivery && bash local/run.sh status"
pause
