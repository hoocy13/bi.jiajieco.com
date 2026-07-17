param(
    [string]$Server = "175.24.186.206",
    [string]$User = "root",
    [string]$AppDir = "/www/wwwroot/bi.jiajieco.com",
    [string]$ArchiveName = "bi-deploy.tar.gz"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ArchivePath = Join-Path $ProjectRoot $ArchiveName
$RemoteArchive = "/root/$ArchiveName"
$Target = "$User@$Server"

Write-Host "Project: $ProjectRoot"
Write-Host "Packing..."

if (Test-Path $ArchivePath) {
    Remove-Item $ArchivePath -Force
}

Push-Location $ProjectRoot
try {
    tar `
        --exclude=$ArchiveName `
        --exclude=frontend/node_modules `
        --exclude=frontend/dist `
        --exclude=backend/.venv `
        --exclude=backend/__pycache__ `
        --exclude=backend/*.db `
        --exclude=backend/.env `
        -czf $ArchiveName .
}
finally {
    Pop-Location
}

$SizeKb = [Math]::Round((Get-Item $ArchivePath).Length / 1KB, 1)
Write-Host "Archive created: $ArchivePath ($SizeKb KB)"

Write-Host "Uploading to $Target..."
scp $ArchivePath "${Target}:$RemoteArchive"

$RemoteScript = @"
set -e
APP_DIR="$AppDir"
ARCHIVE="$RemoteArchive"
TS=`$(date +%Y%m%d%H%M%S)
RELEASE="/www/wwwroot/bi.jiajieco.com.release.`$TS"
BACKUP="/www/wwwroot/bi.jiajieco.com.backup.`$TS"

mkdir -p "`$RELEASE"
tar -xzf "`$ARCHIVE" -C "`$RELEASE"

if [ -f "`$APP_DIR/backend/.env" ]; then
  mkdir -p "`$RELEASE/backend"
  cp "`$APP_DIR/backend/.env" "`$RELEASE/backend/.env"
fi

if [ -d "`$APP_DIR" ]; then
  mv "`$APP_DIR" "`$BACKUP"
fi

mv "`$RELEASE" "`$APP_DIR"
cd "`$APP_DIR"

docker compose up -d --build
docker compose ps

for i in `$(seq 1 15); do
  if curl -fsSI http://127.0.0.1:18080 >/dev/null; then
    echo "Frontend health check passed."
    break
  fi

  if [ "`$i" -eq 15 ]; then
    echo "Frontend health check failed after retries."
    docker compose logs --tail=80 frontend
    exit 1
  fi

  sleep 2
done

echo "Deploy finished."
echo "Backup: `$BACKUP"
"@

Write-Host "Deploying on server..."
$RemoteScript | ssh $Target "bash -s"
if ($LASTEXITCODE -ne 0) {
    throw "Remote deploy failed. SSH exit code: $LASTEXITCODE"
}

Write-Host "Done. Open your HTTPS site in the browser."
