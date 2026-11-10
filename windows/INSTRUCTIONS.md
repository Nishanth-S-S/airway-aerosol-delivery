# Running Nishanth's airway simulation on your PC

Thanks for helping! Your PC will run a large airflow simulation for about **half a day to a day and a half**.
You only have to double-click one file; it does everything else.

## What you need
- Windows 11 (Windows 10 version 2004 or newer also works)
- About **150 GB of free disk space** on drive C:
- An internet connection (the program downloads about 7 GB of simulation data by itself)

## Steps

### 1. Download the program
1. Go to **https://github.com/Nishanth-S-S/airway-aerosol-delivery**.
2. Click the green **Code** button, then **Download ZIP**.
3. Right-click the downloaded zip, choose **Extract All…**, and then **Extract**.

### 2. Double-click `START_HERE.bat`
It's in the extracted folder, inside the **`windows`** folder.
- If Windows says *"Windows protected your PC"*, click **More info**, then **Run anyway**.
- Click **Yes** when it asks for administrator permission.

A blue window opens and works through 7 steps by itself:

| Step | What happens | Time |
|---|---|---|
| 1 | Installs Linux (a free part of Windows called WSL) | 5–15 min |
| 2 | Sets memory and CPU limits | seconds |
| 3 | Downloads the program code | 1 min |
| 4 | Installs the simulation tools | 10–20 min |
| 5 | Downloads and checks the simulation data (about 7 GB) | 10–40 min |
| 6 | Checks the PC | 2 min |
| 7 | Starts the simulation | 9–19 hours |

**If it asks to restart the PC** (only the first time, to finish installing Linux): restart, then **double-click `START_HERE.bat` again**. It continues where it stopped.

At step 7 it asks whether to turn off sleep while plugged in. Type **Y** and press Enter.

### 3. While it runs
- **Leave the blue window open.** Minimizing it is fine. It shows progress every 5 minutes.
- **Pause Windows Update:** go to *Settings → Windows Update → Pause updates (1 week)*, so Windows doesn't restart by itself.
- You can still use the PC for light things like browsing and documents, but it will be slower. Avoid games or other heavy programs.
- To check progress at any time, double-click **`STATUS.bat`**.

### 4. When it's finished
The window says **FINISHED** and puts a file named `airway_results_….zip` on your **Desktop**.
Send that file to Nishanth by Google Drive, WeTransfer or email.

Later, Nishanth may ask you to run the next part. When he does, double-click `START_HERE.bat` again. It updates itself and starts the next part on its own.

## If something goes wrong
| Problem | What to do |
|---|---|
| You need to stop it or use the PC fully | Double-click **`STOP.bat`**, then wait 2 minutes. Later, double-click `START_HERE.bat` to continue from where it stopped. |
| The PC restarted, or the window was closed | Double-click `START_HERE.bat`. It continues from the last save. |
| A red error message | Take a screenshot of the window and send it to Nishanth. |
| "Virtualization" or "SVM" error at step 1 | Restart into the BIOS (press Del or F2 while the PC starts), turn on **SVM Mode** (often under Advanced → CPU Configuration), save and restart. Then run `START_HERE.bat` again. |
| The data download stops (internet dropped) | Double-click `START_HERE.bat` again. The download continues where it stopped. |
| Nishanth asks for the results early | Double-click **`SEND_RESULTS.bat`**. The zip appears on your Desktop. |

Nothing is installed outside the Linux part. To remove everything afterwards, open PowerShell and run `wsl --unregister Ubuntu-24.04`.
