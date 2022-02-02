FOR /F "tokens=* USEBACKQ" %%F IN (`type buildres\output\version.txt`) DO (
SET version=%%F
)
ECHO %version%

tool\nuget.exe install aclcache -Source Artifactory -Version %version% -OutputDirectory buildres

for /f "usebackq tokens=*" %%i in (`"c:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do (
  set MSVCDIR=%%i\VC\Auxiliary\Build
)
call %MSVCDIR%\vcvarsall.bat x86_amd64

set ACLCACHE_MODE=3
set ACLCACHE_PYTHON=c:\python37
set ACLCACHE_DIR=C:\aclcache
set ACLCACHE_SERVER=1
set ACLCACHE_LOG=%cd%\buildres\results\aclcache.log
call "buildres\aclcache.%version%\initialize.bat"
rmdir /s /q C:\aclcache
mkdir %cd%\buildres\results
%ACLCACHE_CMD%  -z || goto :error
%ACLCACHE_CMD%  -s || goto :error
call msbuild tests\winapp\winapp.vcxproj /p:configuration=release  /p:outdir=%cd%\buildres /p:intdir=%cd%\buildres\ /t:rebuild
ping 127.0.0.1 -n 5 > nul
%ACLCACHE_CMD% --json | tool\jq.exe -e .CacheEntries==12 || goto :error
%ACLCACHE_CMD% --json | tool\jq.exe -e .ManifestCount==11 || goto :error
%ACLCACHE_CMD% --json | tool\jq.exe -e .ManifestCountLink==1 || goto :error
%ACLCACHE_CMD% --json | tool\jq.exe -e .cache_miss==11 || goto :error
%ACLCACHE_CMD%  -z || goto :error
%ACLCACHE_CMD%  -s -E -S || goto :error
call msbuild tests\winapp\winapp.vcxproj /p:configuration=release  /p:outdir=%cd%\buildres /p:intdir=%cd%\buildres\ /t:rebuild
ping 127.0.0.1 -n 5 > nul
%ACLCACHE_CMD% --json | tool\jq.exe -e .cache_miss==0 || goto :error

goto :eof

:error

exit /b 1