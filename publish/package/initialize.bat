@echo

if "%ACLCACHE_MODE%"=="" if "%_USENOPCH%"=="" if "%_USEBREPRO%"=="" if "%ACLCACHE_STATLOG%"=="" if "%ACLCACHE_USEZ7%"== "" if "%_USENOPDB%"== "" if "%_REMOVEPCH%" == "" (
    goto :eof
)

@echo *** MSBUILD OVERRIDES to disable PDB / enable deterministic build / enable aclcache

if "%CustomBeforeMicrosoftCommonTargets%" == "" (
    set CustomBeforeMicrosoftCommonTargets=%~dp0override.targets
)

if "%ACLCACHE_MODE%"=="" if "%_USEBREPRO%"== "" goto END

@ECHO *** aclcache is enabled

if "%ACLCACHE_LOCATION%" == "" (
    set ACLCACHE_LOCATION=%~dp0bin
)

if not exist "%ACLCACHE_LOCATION%\aclcache.py" (
    echo "***ACLCACHE_LOCATION does not have aclcache.py installed"
    goto END
)

if not exist "%ACLCACHE_PYTHON%\pythonw.exe" (
    echo "***ACLCACHE_PYTHON does not have python installed"
    goto END
)

if "%ACLCACHE_MODE%"=="" goto END


doskey aclcache="%ACLCACHE_PYTHON%\python.exe" -E "%ACLCACHE_LOCATION%\aclcache.py" $*
doskey clcache="%ACLCACHE_PYTHON%\python.exe" -E "%ACLCACHE_LOCATION%\aclcache.py" $*

set ACLCACHE_CMD="%ACLCACHE_PYTHON%\python.exe" -E "%ACLCACHE_LOCATION%\aclcache.py"

if not "%ACLCACHE_SIZE%" == "" (
   "%ACLCACHE_PYTHON%\python.exe" "%ACLCACHE_LOCATION%\aclcache.py" -M %ACLCACHE_SIZE%
)


if "%ACLCACHE_SERVER%" == "3" (
 @echo Start clcache server
 start "clcache server" /min "%ACLCACHE_PYTHON%\python.exe" "%ACLCACHE_LOCATION%\aclcachesrv.py"
)
if "%ACLCACHE_SERVER%" == "2" (
 @echo Start clcache server without watching change
 start "clcache server" /min "%ACLCACHE_PYTHON%\python.exe" "%ACLCACHE_LOCATION%\aclcachesrv.py" --disable_watching
)
if not "%ACLCACHE_CLEAR%" == "" (
   "%ACLCACHE_PYTHON%\python.exe" "%ACLCACHE_LOCATION%\aclcache.py" -C
)
if defined ACLCACHE_MEMCACHED_SERVER (
   @echo Use memcached server "%ACLCACHE_MEMCACHED_SERVER%"
   "%ACLCACHE_PYTHON%\python.exe" "%ACLCACHE_LOCATION%\aclcache.py" -B "%ACLCACHE_MEMCACHED_SERVER%"
)

:END
@echo CustomBeforeMicrosoftCommonTargets=%CustomBeforeMicrosoftCommonTargets%
@echo _USENOPDB=%_USENOPDB%
@echo _REMOVEPCH=%_REMOVEPCH%
@echo ACLCACHE_STATLOG=%ACLCACHE_STATLOG%
@echo ACLCACHE_OUTPUT_BINARY_FILES=%ACLCACHE_OUTPUT_BINARY_FILES%
@echo ACLCACHE_MODE=%ACLCACHE_MODE%
@echo ACLCACHE_USEZ7=%ACLCACHE_USEZ7%
@echo ACLCACHE_LOCATION=%ACLCACHE_LOCATION%
@echo ACLCACHE_HARDLINK=%ACLCACHE_HARDLINK%
@echo ACLCACHE_DIR=%ACLCACHE_DIR%
@echo ACLCACHE_PYTHON=%ACLCACHE_PYTHON%
@echo ACLCACHE_SERVER=%ACLCACHE_SERVER%
@echo ACLCACHE_SIZE=%ACLCACHE_SIZE%
@echo ACLCACHE_RESET=%ACLCACHE_RESET%
@echo ACLCACHE_MEMCACHED_SERVER=%ACLCACHE_MEMCACHED_SERVER%
@echo ACLCACHE_COMPRESS=%ACLCACHE_COMPRESS%

