@echo off
setlocal
pushd "%~dp0..\.."

envsubtrans\Scripts\python.exe scripts\gui-subtrans.py --profile-startup %*
set "EXIT_CODE=%ERRORLEVEL%"

echo.
echo Startup profile report is saved in the application config directory as profile_guisubtrans_startup.txt.
if not "%EXIT_CODE%"=="0" echo Profiling command exited with code %EXIT_CODE%.
pause

popd
endlocal & exit /b %EXIT_CODE%
