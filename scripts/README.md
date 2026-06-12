Build and Package

- Build the app (downloads MODFLOW 6 and bundles binaries):
  powershell -ExecutionPolicy Bypass -File .\build.ps1 -Clean -DownloadMf6

- Optional: quick smoke test after build:
  powershell -ExecutionPolicy Bypass -File .\build.ps1 -Test

- Create installer (requires Inno Setup installed and iscc on PATH):
  iscc .\scripts\installer\BasinSIM.iss

Artifacts:
- dist\BasinSIM.exe (portable app)
- installer_output\BasinSIM_Setup_1.0.0.exe (installer)
