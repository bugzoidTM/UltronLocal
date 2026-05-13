@echo off
setlocal

cd /d "%~dp0"
python "%~dp0run_ultron_ui.py" %*
exit /b %ERRORLEVEL%
