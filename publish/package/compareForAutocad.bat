copy /Y %PACK_PATH%\outputfiles1.hash.txt %CI_RES%\outputfiles1.hash.txt
copy /Y %PACK_PATH%\outputfiles2.hash.txt %CI_RES%\outputfiles2.hash.txt
copy /Y %PACK_PATH%\aclcache_output_binary_files.txt %CI_RES%\aclcache_output_binary_files.txt
for /f %%i in (%~dp0acadTools\aclcache_blacklist.txt) do (
    findstr /l /v "%%i" %PACK_PATH%\outputfiles1.hash.txt > %temp%\hash1.txt
    copy %temp%\hash1.txt %PACK_PATH%\outputfiles1.hash.txt
    findstr /l /v "%%i" %PACK_PATH%\outputfiles2.hash.txt > %temp%\hash2.txt
    copy %temp%\hash2.txt %PACK_PATH%\outputfiles2.hash.txt
)
copy /Y %temp%\hash1.txt %CI_RES%\outputfiles1.hash.filtered.txt
copy /Y %temp%\hash2.txt %CI_RES%\outputfiles2.hash.filtered.txt
call python3 %~dp0acadTools\compare2files.py -f1 %temp%\hash1.txt -f2 %temp%\hash2.txt > "%CI_RES%\compare.result.txt"
call %~dp0acadTools\aclcache_validate.bat
exit /b 0
