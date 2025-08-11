@echo off
REM Променя директория към папката на бат файла (и на скрипта)
cd /d %~dp0

REM Стартира Python скрипта
python r8c_programmer.py

REM Пауза да не се затвори конзолата след приключване
pause
