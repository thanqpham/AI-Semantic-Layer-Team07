param([switch]$Apply)

$ErrorActionPreference = 'Stop'
$targetOrders = if ($Apply) { '1000000' } else { '500010' }
$psqlArgs = @('exec', '-i', 'infra-postgres-1', 'psql', '-X', '-U', 'dev',
    '-d', 'ecommerce_dashboard_demo', '-v', 'ON_ERROR_STOP=1', '-v', "target_orders=$targetOrders")
if ($Apply) { $psqlArgs += @('-v', 'apply=true') }

Get-Content -Raw -Encoding utf8 (Join-Path $PSScriptRoot 'ecommerce_append_500k.sql') | & docker @psqlArgs
if ($LASTEXITCODE -ne 0) { throw "Data append failed with exit code $LASTEXITCODE; transaction was not committed." }
