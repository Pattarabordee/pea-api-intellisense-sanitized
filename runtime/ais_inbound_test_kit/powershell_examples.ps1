# PEA AIS pilot API test script for Windows PowerShell.
# Fill in the private pilot key before running.

$ApiKey = "<private pilot key provided by PEA>"
$HealthUrl = "https://<REDACTED_TUNNEL>/health"
$PostUrl = "https://<REDACTED_TUNNEL>/api/v1/ais/outage-verifications"
$StatusUrl = "https://<REDACTED_TUNNEL>/api/v1/ais/outage-verifications/AIS-TEST-0001"

$Headers = @{
    "X-API-Key" = $ApiKey
    "bypass-tunnel-reminder" = "true"
}

Write-Host "Health check"
Invoke-RestMethod -Method Get -Uri $HealthUrl -Headers @{ "bypass-tunnel-reminder" = "true" }

$Body = @'
{
  "request_id": "AIS-TEST-0001",
  "meter_no": "REDACTED-METER-0000",
  "timestamp": "2026-06-20T00:35:00+07:00",
  "province": "Sakon Nakhon",
  "district": "<district>",
  "subdistrict": "<subdistrict>"
}
'@

Write-Host "Send one pilot request"
Invoke-RestMethod -Method Post -Uri $PostUrl -Headers $Headers -ContentType "application/json" -Body $Body

Write-Host "Read stored result"
Invoke-RestMethod -Method Get -Uri $StatusUrl -Headers $Headers
