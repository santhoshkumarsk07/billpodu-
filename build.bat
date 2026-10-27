@echo off
REM Build 83 MEN'S WEAR POS on Windows: tests, the .exe folder, and (if Inno Setup is installed) the installer.
REM Requires Python 3.11+ from python.org (tick "Add python.exe to PATH" when installing).
setlocal
cd /d "%~dp0"

if not exist .venv (
    py -3 -m venv .venv || goto :error
)
call .venv\Scripts\activate.bat || goto :error
python -m pip install --upgrade pip || goto :error
pip install -r requirements-dev.txt || goto :error

echo.
echo === Running automated tests ===
python -m pytest -q || goto :error

echo.
echo === Building the program folder ===
pyinstaller packaging\83mw.spec --noconfirm --clean || goto :error

set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist %ISCC% (
    echo.
    echo === Building the installer ===
    %ISCC% packaging\installer.iss || goto :error
    echo Installer created in the dist folder.
) else (
    echo Inno Setup 6 not found - skipped the installer. The program is in dist\83MensWear\83MensWear.exe
)
echo.
echo Build finished.
exit /b 0

:error
echo.
echo BUILD FAILED. See the messages above.
exit /b 1
