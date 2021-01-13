@echo off
powershell  -File install_dotnet.ps1
if defined CI_BRANCH (
  git branch -f %CI_BRANCH% %CUR_CL% && git checkout -f %CI_BRANCH% || goto :error
)
FOR /F "tokens=* USEBACKQ" %%F IN (`tool\gitversion /updateassemblyinfo /showvariable NuGetVersion`) DO (
SET version=%%F
)
mkdir acadbuildres\results
mkdir acadbuildres\output
ECHO %version% > acadbuildres\output\version.txt
for /f "usebackq tokens=*" %%i in (`"c:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do (
  set MSVCDIR=%%i\VC\Auxiliary\Build
)
call %MSVCDIR%\vcvarsall.bat x86_amd64
msbuild extension\aclcache.csproj /t:rebuild /p:Configuration=Release /p:Platform=AnyCPU
pushd publish
call publish.bat %version%
popd