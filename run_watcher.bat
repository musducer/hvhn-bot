@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "D:\Bothvhn"
title HVHN watcher
:loop
echo [%date% %time%] Khoi dong HVHN watcher...
python watcher.py
echo [%date% %time%] Watcher da dung (loi hoac tat). Tu chay lai sau 10 giay...
timeout /t 10 /nobreak >nul
goto loop
