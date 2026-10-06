@echo off
REM Builds dist\TaskFlow.exe (single file). Run on a Windows PC with Python 3.10+.
cd /d "%~dp0"
python -m pip install -r requirements.txt pyinstaller || goto :err
python -m PyInstaller --noconfirm taskflow.spec || goto :err
echo.
echo Built: %~dp0dist\TaskFlow.exe
echo Copy that ONE file to the server folder. Data (tracker.db, .env) is created next to it.
pause
exit /b 0
:err
echo BUILD FAILED
pause
exit /b 1
