@echo off
setlocal
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ok=$false; try { $r=Invoke-WebRequest -UseBasicParsing http://127.0.0.1:9222/json/version -TimeoutSec 2; $ok=$r.StatusCode -eq 200 } catch {}; if (-not $ok) { Start-Process -FilePath '%~dp0abrir_chrome_cdp.bat'; Write-Host 'Abri o Chrome CDP. Faca login nos paineis e depois volte aqui.'; Start-Sleep -Seconds 5 }"

python bot.py --post
pause
