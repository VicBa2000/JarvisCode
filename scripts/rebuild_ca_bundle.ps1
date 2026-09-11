# Reconstruye el bundle de CA que usa pip en este proyecto.
#
# Contexto: Avast Antivirus inspecciona HTTPS sustituyendo el certificado
# del servidor por uno firmado con su propia CA raiz. Windows confia en
# esa CA, pero Python no lee el almacen de Windows: usa certifi. Sin este
# bundle, `pip install` falla con CERTIFICATE_VERIFY_FAILED.
#
# Esto no relaja la seguridad: anade una CA ya presente y confiada en el
# almacen del sistema, en lugar de usar --trusted-host, que desactivaria
# la verificacion por completo.
#
# Ejecutar de nuevo si se reinstala Avast (regenera su CA) o se actualiza
# certifi.

$ErrorActionPreference = "Stop"

$root      = Split-Path -Parent $PSScriptRoot
$certDir   = Join-Path $root ".certs"
$python    = Join-Path $root ".venv\Scripts\python.exe"
$bundle    = Join-Path $certDir "bundle.pem"

if (-not (Test-Path $python)) {
    throw "No se encontro el venv en $python. Crea el entorno primero."
}
New-Item -ItemType Directory -Force -Path $certDir | Out-Null

Write-Host "Buscando CAs de inspeccion TLS en el almacen de Windows..."
$interceptors = Get-ChildItem Cert:\LocalMachine\Root, Cert:\CurrentUser\Root |
    Where-Object { $_.Subject -match 'Avast|AVG|Kaspersky|ESET|Bitdefender|Fiddler|Charles' } |
    Sort-Object Thumbprint -Unique

if (-not $interceptors) {
    Write-Host "No se detectaron CAs de inspeccion. El bundle sera certifi puro."
}

Write-Host "Copiando el bundle base de certifi..."
& $python -c "import certifi, shutil, sys; shutil.copy(certifi.where(), sys.argv[1])" $bundle

foreach ($cert in $interceptors) {
    Write-Host ("  + " + $cert.Subject.Split(',')[0])
    $pem = "-----BEGIN CERTIFICATE-----`n" +
           [Convert]::ToBase64String($cert.RawData, 'InsertLineBreaks') +
           "`n-----END CERTIFICATE-----"
    Add-Content -Path $bundle -Value $pem -Encoding ascii
}

$lines = (Get-Content $bundle | Measure-Object -Line).Lines
Write-Host "Bundle reconstruido en $bundle ($lines lineas)."
Write-Host "pip lo usa via .venv\pip.ini."
