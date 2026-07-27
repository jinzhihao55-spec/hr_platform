@echo off
REM Dev launcher for Windows
if "%APP_HOST%"=="" set APP_HOST=0.0.0.0
if "%APP_PORT%"=="" set APP_PORT=8000
uvicorn app.main:app --reload --host %APP_HOST% --port %APP_PORT%
