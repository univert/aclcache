@echo off
powershell  -File install_dotnet.ps1

FOR /F "tokens=* USEBACKQ" %%F IN (`tool\gitversion.exe /updateassemblyinfo /showvariable NuGetVersion`) DO (
SET version=%%F
)
mkdir buildres\results
mkdir buildres\output
ECHO %version% > buildres\output\version.txt
for /f "usebackq tokens=*" %%i in (`"c:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do (
  set MSVCDIR=%%i\VC\Auxiliary\Build
)
call %MSVCDIR%\vcvarsall.bat x86_amd64
msbuild extension\aclcache.csproj /t:rebuild /p:Configuration=Release /p:Platform=AnyCPU
pushd publish
call publish.bat %version%
popd