@echo off
REM Run from anywhere:  scripts\use_project_env.cmd
pushd "%~dp0.."
set "ROOT=%CD%"
popd
set "PATH=%ROOT%\venv\Scripts;%ROOT%\tools\render-cli;%PATH%"
echo OK: PATH includes project venv and tools\render-cli
