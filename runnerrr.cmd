@echo off
chcp 65001
setlocal enabledelayedexpansion
C:
cd C:\
cd C:\Users
cd Administrator
cd Desktop
for %%f in (*.exe) do (
    if not "%%f"=="%~nx0" (
        echo Launching: %%f
        start "" "%%f"
    )
)
