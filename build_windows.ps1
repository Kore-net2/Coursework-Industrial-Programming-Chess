$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
python -m venv .build-venv
if ($LASTEXITCODE -ne 0) { throw 'Could not create the build environment.' }
& '.\.build-venv\Scripts\python.exe' -m pip install --no-cache-dir -r requirements.txt 'pyinstaller==6.16.0'
if ($LASTEXITCODE -ne 0) { throw 'Could not install dependencies.' }
& '.\.build-venv\Scripts\python.exe' -m PyInstaller --noconfirm ChessAnalytics.spec
if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }
Write-Output 'Ready: dist\ChessAnalytics\ChessAnalytics.exe (GUI) and cw2.exe (CLI). Keep the _internal directory beside both executables.'
