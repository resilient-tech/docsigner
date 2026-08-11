@echo off
rem Install the OpenSigner native messaging host for the current user (Windows).
rem
rem Usage:
rem     install.bat [CHROME_EXTENSION_ID] [FIREFOX_EXTENSION_ID]
rem
rem Registers the host through HKCU registry keys (the ".reg approach"), so no
rem admin rights are needed. Build the binary first:
rem     cargo build --release

setlocal

set "CHROME_EXT_ID=%~1"
if "%CHROME_EXT_ID%"=="" set "CHROME_EXT_ID=__EXTENSION_ID__"
set "FIREFOX_EXT_ID=%~2"
if "%FIREFOX_EXT_ID%"=="" set "FIREFOX_EXT_ID=__EXTENSION_ID__"

if "%CHROME_EXT_ID%"=="__EXTENSION_ID__" (
    echo warning: no extension ID given; manifests keep the __EXTENSION_ID__ placeholder.
    echo          Rerun with the real ID once the extension is installed.
)

set "HERE=%~dp0"
set "HOST_NAME=com.opensigner.host"
set "INSTALL_DIR=%LOCALAPPDATA%\opensigner"

rem Release first: a stale debug build must not be installed just because
rem someone ran `cargo build` once.
set "BINARY=%HERE%..\target\release\opensigner-host.exe"
if not exist "%BINARY%" set "BINARY=%HERE%..\target\debug\opensigner-host.exe"
if not exist "%BINARY%" set "BINARY=%HERE%opensigner-host.exe"
if not exist "%BINARY%" (
    echo error: opensigner-host.exe not found. Build it first:
    echo        cargo build --release
    exit /b 1
)

if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
copy /y "%BINARY%" "%INSTALL_DIR%\opensigner-host.exe" >nul
echo installed binary: %INSTALL_DIR%\opensigner-host.exe

rem JSON needs doubled backslashes in the binary path.
set "JSON_PATH=%INSTALL_DIR:\=\\%\\opensigner-host.exe"

> "%INSTALL_DIR%\%HOST_NAME%.chrome.json" (
    echo {
    echo   "name": "com.opensigner.host",
    echo   "description": "OpenSigner PKCS#11 signing host",
    echo   "path": "%JSON_PATH%",
    echo   "type": "stdio",
    echo   "allowed_origins": ["chrome-extension://%CHROME_EXT_ID%/"]
    echo }
)
echo wrote manifest:   %INSTALL_DIR%\%HOST_NAME%.chrome.json

> "%INSTALL_DIR%\%HOST_NAME%.firefox.json" (
    echo {
    echo   "name": "com.opensigner.host",
    echo   "description": "OpenSigner PKCS#11 signing host",
    echo   "path": "%JSON_PATH%",
    echo   "type": "stdio",
    echo   "allowed_extensions": ["%FIREFOX_EXT_ID%"]
    echo }
)
echo wrote manifest:   %INSTALL_DIR%\%HOST_NAME%.firefox.json

rem Chromium-family browsers. Brave and Opera read the Chrome key.
reg add "HKCU\Software\Google\Chrome\NativeMessagingHosts\%HOST_NAME%" /ve /t REG_SZ /d "%INSTALL_DIR%\%HOST_NAME%.chrome.json" /f >nul
reg add "HKCU\Software\Chromium\NativeMessagingHosts\%HOST_NAME%" /ve /t REG_SZ /d "%INSTALL_DIR%\%HOST_NAME%.chrome.json" /f >nul
reg add "HKCU\Software\Microsoft\Edge\NativeMessagingHosts\%HOST_NAME%" /ve /t REG_SZ /d "%INSTALL_DIR%\%HOST_NAME%.chrome.json" /f >nul

rem Firefox.
reg add "HKCU\Software\Mozilla\NativeMessagingHosts\%HOST_NAME%" /ve /t REG_SZ /d "%INSTALL_DIR%\%HOST_NAME%.firefox.json" /f >nul

echo registered registry keys under HKCU.
echo done.
endlocal
