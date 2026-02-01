@echo off
title OPCore-Ready
setlocal enabledelayedexpansion

echo Welcome to the OPCore-Ready Tool.
echo This tool combines all the Tools you need for your OpenCore Configuration: 
echo OpCore-Simplify, OpenCorePkg, Rufus, USBToolBox, OCAuxiliaryTools.
echo It also removes the step of editing the EFI after mapping USB Ports using the inbuild USB2EFI Script by TheCCraft
echo.
echo Press Enter to continue.
pause >nul
echo ===========================================================================
echo DISCLAIMER:
echo This tool is provided "as is", without warranty of any kind. 
echo Use it at your own risk. The author is not responsible for any 
echo hardware damage, data loss, or issues caused by the use of this script.
echo ===========================================================================
echo.
echo Press Enter to continue.
pause >nul

echo Let's start by downloading all the tools.

curl -L --progress-bar https://github.com/pbatard/rufus/releases/download/v4.12/rufus-4.12.exe --output rufus-4.12.exe
curl -L --progress-bar https://github.com/lzhoang2801/OpCore-Simplify/archive/refs/heads/main.zip --output OpCore-Simplify-main.zip
curl -L --progress-bar https://github.com/acidanthera/OpenCorePkg/releases/download/1.0.6/OpenCore-1.0.6-RELEASE.zip --output OpenCore-1.0.6-RELEASE.zip
curl -L --progress-bar https://github.com/ic005k/OCAuxiliaryTools/releases/download/20250001/OCAT_Mac.dmg --output OCAT_Mac.dmg
curl -L --progress-bar https://github.com/USBToolBox/tool/releases/download/0.2/Windows.exe --output USBToolBox.exe

echo.
echo Extracting files...
tar -xf OpCore-Simplify-main.zip
mkdir "OpenCore-1.0.6-RELEASE"
tar -xf OpenCore-1.0.6-RELEASE.zip -C OpenCore-1.0.6-RELEASE
echo Done.
timeout /t 1 >nul

cls
echo ===========================================================================
echo SETUP:
echo ===========================================================================
echo - First we will run OpCore-Simplify to download the dependencies.
echo - After you see OpCore Simplify, close CMD and run OpCore-Ready.bat again
echo - Press 2 If you have already completed this step.
echo - Press 1 If you have not completed this step.

set /p setup=
if /i "%setup%" == "2" goto :1
if /i "%setup%" == "1" goto :2

:1
cls
echo ===========================================================================
echo RUFUS GUIDE:
echo ===========================================================================
echo 1. Select your USB Drive and be sure it's the correct one.
echo 2. On boot selection select "Non bootable".
echo 3. For the Partition scheme select "GPT".
echo 4. Select FAT32 under "File System" and a name "e.g. INSTALLER".
echo 5. Press "START".
echo 5. After it is complete press "CLOSE".
echo 6. EVERYTHING WILL BE REMOVED
echo.
echo Press Enter to open Rufus...
pause >nul

if exist "rufus-4.12.exe" (
    call rufus-4.12.exe
) else (
    echo [ERROR] Rufus not found.
)

cls
echo Completed Part 1/5, now your USB is formatted
echo If you couldn't format your Drive, type "b" to go back. Press enter to proceed.
set /p rufus=
if /i "%rufus%" == "b" goto :1

:2
cls
echo ===========================================================================
echo OPCORE-SIMPLIFY GUIDE:
echo ===========================================================================
echo - Type "1" and on the next menu type "e".
echo - Then you will see all your PC Components, just press enter.
echo - Select macOS Version "e.g. 25 for macOS Tahoe 26".
echo - You might need to select Kexts. I recommend going with the standard.
echo - Type "6" to Build OpenCore EFI.
echo - Type "AGGRE" to open the EFI Folder, then copy it using "CTRL + C".
echo - Type "q" and then press enter to return here.
echo.
echo Press Enter to open OpCore-Simplify...
pause >nul

if exist "OpCore-Simplify-main\OpCore-Simplify.bat" (
    call "OpCore-Simplify-main\OpCore-Simplify.bat"
) else (
    echo [ERROR] OpCore-Simplify.bat not found in OpCore-Simplify-main folder.
)



echo .
cls
echo Completed Part 2/5, now your EFI Folder should be generated.
echo Now paste your EFI into here using "CTRL + V" and then press enter.
echo If you are on Windows 10 or older, you might need to drag and drop the folder instead.
echo If you didn't get an EFI Folder and want to repeat this step, type "b".
set /p efi=
if /i "%efi%" == "b" goto :2

:3
cls
echo ===========================================================================
echo USB MAPPING GUIDE "USING USBTOOLBOX":
echo ===========================================================================
echo - Type "d" and wait until you are on the next menu.
echo - Then Plug a USB 2 Device into all of the Ports on your PC.
echo - Then Plug a USB 3 Device into all of the USB 3 Ports on your PC.
echo - Then Plug a USB-C 2 Device into all of the USB-C Ports on your PC.
echo - Then Plug a USB-C 3 Device into all of the USB-C 3 Ports on your PC.
echo - Now the program will show all your ports in green.
echo - Type "b" to return to the menu.
echo - Here, type "s".
echo - Check if all ports are set corectly. If not make changes.
echo - Once you are done, type "k"
echo - Once this is done, type "b", "b" and "q" to return here.
echo.
echo Press Enter to open USBToolBox...
pause >nul

if exist "USBToolBox.exe" (
    call USBToolBox.exe
) else (
    echo [ERROR] USBToolBox not found.
)

echo .
cls
echo Completed Part 3/5, now your UTBMap.kext should be generated.
echo If you want to repeat, type "b". To proceed, type "p"
set /p usb=
if /i "%usb%" == "b" goto :3

:: USB2EFI by @theccraft-git
:4
cls
echo ===========================================================================
echo OPCore-Ready will now complete your EFI Folder
echo ===========================================================================
echo.
echo Press enter to start.
pause >nul
:: Clean the path
set "efi=%efi:"=%"

if not exist "%efi%\OC\config.plist" (
    echo [ERROR] Could not find config.plist at: "%efi%\OC\config.plist"
    pause
    goto :2
)

echo Initializing configuration patch...
echo.

set "bar=##################################################"
set "fill=                                                  "
for /L %%i in (1,4,100) do (
    set /a "display=%%i"
    set /a "graph=%%i/2"
    for /f "delims=" %%g in ("!graph!") do set "filled=!bar:~0,%%g!"
    for /f "delims=" %%g in ("!graph!") do set "empty=!fill:~%%g!"
    
    cls
    echo ===========================================================================
    echo OPCore-Ready: Finalizing EFI...
    echo ===========================================================================
    echo.
    echo Status: [!filled!!empty!] !display!%%
    echo.
    if %%i LSS 25 echo [LOG] Scanning Plist structure...
    if %%i GEQ 25 if %%i LSS 50 echo [LOG] Fixing config.plist...
    if %%i GEQ 50 if %%i LSS 75 echo [LOG] Deleting UTBDefault.kext...
    if %%i GEQ 75 echo [LOG] Importing UTBMap.kext...
    
    timeout /t 0 /nobreak >nul
)

::: --- 1. CONFIG FIX ---
powershell -Command "(Get-Content '%efi%\OC\config.plist') -replace 'UTBDefault.kext', 'UTBMap.kext' -replace '<string>x86_64</string>', '<string>Any</string>' | Set-Content '%efi%\OC\config.plist' -Encoding UTF8"

:: --- 2. DELETE OLD KEXT ---
if exist "%efi%\OC\Kexts\UTBDefault.kext" (
    rd /s /q "%efi%\OC\Kexts\UTBDefault.kext"
)

:: --- 3. COPY NEW KEXT ---
if exist "UTBMap.kext" (
    :: Robocopying the folder structure properly
    robocopy "UTBMap.kext" "%efi%\OC\Kexts\UTBMap.kext" /e /is /it /njs /njh /ndl /nc /ns >nul
) else (
    echo [WARNING] UTBMap.kext not found in script directory!
)

cls
echo ===========================================================================
echo EFI COMPLETE
echo ===========================================================================
echo [OK] Config.plist updated (UTBMap + Architecture)
echo [OK] UTBDefault.kext removed from EFI.
echo [OK] UTBMap.kext installed to EFI.
echo.
echo Press enter to continue.
pause >nul
goto :5

:5
cls
echo ===========================================================================
echo FINAL STEP: DOWNLOAD MACOS RECOVERY
echo ===========================================================================
echo Select the macOS Version you selected before:
echo [20] macOS Big Sur (11)
echo [21] macOS Monterey (12)
echo [22] macOS Ventura (13)
echo [23] macOS Sonoma (14)
echo [24] macOS Sequoia (15)
echo [25] macOS Tahoe (26)
echo.
set /p v=Version: 

:: Assign IDs
set "bid="
set "os_flag="
if "%v%"=="20" set "bid=Mac-2BD1B31983FE1663"
if "%v%"=="21" set "bid=Mac-E43C1C25D4880AD6"
if "%v%"=="22" set "bid=Mac-B4831CEBD52A0C4C"
if "%v%"=="23" set "bid=Mac-827FAC58A8FDFA22"
if "%v%"=="24" set "bid=Mac-7BA5B2D9E42DDD94"
if "%v%"=="25" set "bid=Mac-CFF7D910A743CAAF" & set "os_flag=-os latest"

if "%bid%"=="" goto :5

echo.
echo Downloading...
pushd "OpenCore-1.0.6-RELEASE\Utilities\macrecovery"
python macrecovery.py -b %bid% -m 00000000000000000 %os_flag% download

:: --- ORGANIZE FINAL FOLDER ---
set "final_dir=%userprofile%\Desktop\OPCore-Ready_Final_Output"
mkdir "%final_dir%" 2>nul

:: Move Recovery Folder
if exist "com.apple.recovery.boot" (
    robocopy "com.apple.recovery.boot" "%final_dir%\com.apple.recovery.boot" /e /move >nul
)
popd

:: Move EFI Folder
if exist "%efi%" (
    robocopy "%efi%" "%final_dir%\EFI" /e /move >nul
)

:: Move OCAT DMG
if exist "OCAT_Mac.dmg" (
    move /y "OCAT_Mac.dmg" "%final_dir%\" >nul
)


:: --- SPECIFIC CLEANUP SECTION ---
cls
echo ===========================================================================
echo CLEANUP
echo ===========================================================================
set /p cleanup=Would you like to delete the source files and tools? (y/n): 

if /i "%cleanup%"=="y" (
    echo.
    echo Cleaning up...
    
    del /q "rufus-4.12.exe" 2>nul
    del /q "OpCore-Simplify-main.zip" 2>nul
    del /q "OpenCore-1.0.6-RELEASE.zip" 2>nul
    del /q "OCAT_Mac.dmg" 2>nul
    del /q "USBToolBox.exe" 2>nul
    del /q "usb.json" 2>nul
    del /q "acpidump.exe" 2>nul
    
    rd /s /q "OpenCore-1.0.6-RELEASE" 2>nul
    rd /s /q "OpCore-Simplify-main" 2>nul
    rd /s /q "UTBMap.kext" 2>nul
    
    echo [OK] Cleanup complete.
)
echo Press ENTER to get your EFI and macOS Installation.
pause >nul

echo.
echo ===========================================================================
echo PROCESS COMPLETE
echo ===========================================================================
echo Your EFI and macOS Recovery have been moved to:
echo %final_dir%
echo.
echo Just copy everything in this Folder onto your USB

:: Open the directory
start "" "%final_dir%"

cls
echo ===========================================================================
echo Thank you for using OPCore-Ready.
echo ===========================================================================
echo by @theccraft-git
pause

exit
