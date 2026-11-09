@echo off
rem Stops the simulation safely (it saves its state first). START_HERE.bat continues it later.
wsl.exe -d Ubuntu-24.04 -u root -- bash -lc "cd /root/airway-aerosol-delivery && bash local/run.sh stop"
echo.
echo Wait about 2 minutes before shutting down the PC.
pause
