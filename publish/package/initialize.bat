@echo off

if "%_USENOPDB%"=="" if "%_USENOPCH%"=="" if "%_USEBREPRO%"=="" if "%_USECCACHE%"=="" if "%_USEZ7%"== "" (
    goto :eof
)

@echo *** MSBUILD OVERRIDES to disable PDB / enable deterministic build / enable ccache[clcache]

if "%CustomBeforeMicrosoftCommonTargets%" == "" (
    set CustomBeforeMicrosoftCommonTargets=%~dp0override.targets
)

if "%_statlog%" == "" (
   if not "%CI_RES%"=="" if exist "%CI_RES%" set _statlog=%CI_RES%\msbuild_time.csv
)

if "%_USECCACHE%"=="" goto END

@ECHO *** clcache is enabled


if "%CLCACHE_LOCATION%" == "" (
    set CLCACHE_LOCATION=%~dp0bin
)

if "%CLCACHE_PYTHON%" == "" (
    set CLCACHE_PYTHON=%ACPACKAGEDIR%\python37
)

if not exist "%CLCACHE_PYTHON%\pythonw.exe" (
    echo "***CLCACHE_PYTHON does not have python installed"
    goto END
)

doskey clcache="%CLCACHE_PYTHON%\python.exe" "%CLCACHE_LOCATION%\clcache.py" $*

if "%CLCACHE_DIR%" == "" (
    set CLCACHE_DIR=%ACTOP_BIN%\cache
)
if "%CLCACHE_HARDLINK%" == "" (
    set CLCACHE_HARDLINK=1
)
if not "%CLCACHE_SIZE%" == "" (
   "%CLCACHE_PYTHON%\python.exe" "%CLCACHE_LOCATION%\clcache.py" -M %CLCACHE_SIZE%
)

if "%CLCACHE_LOG%" == "" (
    if not "%CI_RES%"=="" if exist "%CI_RES%" (
      set CLCACHE_LOG=%CI_RES%\clcache.log
      del %CLCACHE_LOG% >nul 2>nul
    )
)

if "%CLCACHE_SERVER%" == "3" (
 @echo Start clcache server
 start "clcache server" /min "%CLCACHE_PYTHON%\python.exe" "%CLCACHE_LOCATION%\clcachesrv.py"
)
if "%CLCACHE_SERVER%" == "2" (
 @echo Start clcache server without watching change
 start "clcache server" /min "%CLCACHE_PYTHON%\python.exe" "%CLCACHE_LOCATION%\clcachesrv.py" --disable_watching
)
if not "%CLCACHE_RESET%" == "" (
   "%CLCACHE_PYTHON%\python.exe" "%CLCACHE_LOCATION%\clcache.py" --reset
)
if not "%CLCACHE_CLEAR%" == "" (
   "%CLCACHE_PYTHON%\python.exe" "%CLCACHE_LOCATION%\clcache.py" -C
)

:END
@echo CustomBeforeMicrosoftCommonTargets=%CustomBeforeMicrosoftCommonTargets%
@echo _STATLOG=%_statlog%
@echo _USENOPDB=%_USENOPDB%
@echo _USENOPCH=%_USENOPCH%
@echo _USECCACHE=%_USECCACHE%
@echo _USEBREPRO=%_USEBREPRO%
@echo _USEZ7=%_USEZ7%
@echo CLCACHE_LOCATION=%CLCACHE_LOCATION%
@echo CLCACHE_HARDLINK=%CLCACHE_HARDLINK%
@echo CLCACHE_DIR=%CLCACHE_DIR%
@echo CLCACHE_PYTHON=%CLCACHE_PYTHON%
@echo CLCACHE_SERVER=%CLCACHE_SERVER%
@echo CLCACHE_SIZE=%CLCACHE_SIZE%
@echo CLCACHE_RESET=%CLCACHE_RESET%
