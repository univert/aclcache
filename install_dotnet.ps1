function devpack-installed ($version) {
  if (Get-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*", "HKLM:\SOFTWARE\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*" | Where {$_.DisplayName -eq "Microsoft .NET Framework $($version) Developer Pack"}) {
    return $true
  }
}

#needed for 4.5.2 which has different naming convention
function multitargetingpack-installed ($version) {
  if (Get-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*", "HKLM:\SOFTWARE\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*" | Where {$_.DisplayName -eq "Microsoft .NET Framework $($version) Multi-Targeting Pack"}) {
    return $true
  }
}

function install-devpack ($version, $location) {
  if (devpack-installed -version $version) {
    Write-Host ".NET Framework $($version) Developer Pack already installed." -ForegroundColor Cyan
  }
  elseif (multitargetingpack-installed -version $version) {
    Write-Host ".NET Framework $($version) Multi-Targeting Pack already installed." -ForegroundColor Cyan
  }
  else {
    Write-Host ".NET Framework $($version) Developer Pack..." -ForegroundColor Cyan
    Write-Host "Downloading..."
    $exePath = "$env:TEMP\$($version)-devpack.exe"
    (New-Object Net.WebClient).DownloadFile($location, $exePath)
    Write-Host "Installing..."
    cmd /c start /wait "$exePath" /quiet /norestart
    Remove-Item $exePath -Force -ErrorAction Ignore
    Write-Host "Installed" -ForegroundColor Green
  }
}

install-devpack -version "4.7.2" -location "https://download.microsoft.com/download/3/B/F/3BFB9C35-405D-45DF-BDAF-0EB57D047888/NDP472-DevPack-ENU.exe"
