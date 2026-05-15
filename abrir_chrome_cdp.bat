@echo off
setlocal
cd /d "%~dp0"

set "CHROME_EXE=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME_EXE%" set "CHROME_EXE=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"

if not exist "%CHROME_EXE%" (
  echo Nao encontrei o Google Chrome instalado.
  pause
  exit /b 1
)

start "Chrome CDP Bot" "%CHROME_EXE%" ^
  --remote-debugging-address=127.0.0.1 ^
  --remote-debugging-port=9222 ^
  --user-data-dir="%~dp0browser_profile\chrome_cdp" ^
  https://www.mercadolivre.com.br/afiliados ^
  https://affiliate.shopee.com.br/offer/brand_offer?is_from_login=true

echo Chrome CDP aberto na porta 9222.
echo Faca login no Mercado Livre Afiliados e na Shopee Afiliados nesse Chrome.
pause
