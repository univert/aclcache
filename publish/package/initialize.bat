@echo off

@echo *** MSBUILD OVERRIDES to disable PDB / enable deterministic build / enable ccache

if "%_USENOPDB%"=="" if "%_USENOPCH%"=="" if "%_USEBREPRO%"=="" if "%_USECCACHE%"=="" (
    @echo *** OVERRIDES is NOT enbaled
    goto END
)

if "%CustomBeforeMicrosoftCommonTargets%" == "" (
    set CustomBeforeMicrosoftCommonTargets=%ASSEMBLYREF%\clcache\override.targets
)

if not "%CI_RES%"=="" if exist "%CI_RES%" set _statlog=%CI_RES%\msbuild_time.csv

:END
@echo CustomBeforeMicrosoftCommonTargets=%CustomBeforeMicrosoftCommonTargets%
@echo _STATLOG=%_statlog%
@echo _USENOPDB=%_USENOPDB%
@echo _USENOPCH=%_USENOPCH%
@echo _USECCACHE=%_USECCACHE%
@echo _USEBREPRO=%_USEBREPRO%
