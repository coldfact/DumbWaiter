Param(
  [string]$TaskName = "DumbWaiterTray"
)

try {
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
  Write-Host "Removed Scheduled Task '$TaskName'."
} catch {
  Write-Host "Failed to remove scheduled task '$TaskName': $($_.Exception.Message)"
  exit 1
}
