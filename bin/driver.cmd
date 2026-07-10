@echo off
REM driver.cmd - Windows shim for auto-research-driver
REM Usage:
REM   driver.cmd run --target-dir F:\Research\PAPER5_CONSOLIDATED --from-stage s5
REM   driver.cmd status --target-dir ...
REM   driver.cmd sign --target-dir ... --checkpoint s5_review
REM   driver.cmd alarms --target-dir ... [--show-rules]
REM   driver.cmd scan-alarms [--root F:\Research] [--stale-days 30] [--quiet]
REM   driver.cmd provider-check --ping
REM   driver.cmd reset --target-dir ...

chcp 65001 > nul
py -3 "C:\Users\Administrator\.mavis\skills\auto-research-driver\scripts\driver.py" %*
exit /b %ERRORLEVEL%