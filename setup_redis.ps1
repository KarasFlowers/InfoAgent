$ErrorActionPreference = "Stop"
$redisDir = "$PSScriptRoot\redis"
$zipFile = "$PSScriptRoot\redis.zip"

Write-Host "Checking for existing Redis instance..."
$process = Get-Process -Name "redis-server" -ErrorAction SilentlyContinue
if ($process) {
    Write-Host "✅ Redis server is already running in the background."
    exit
}

if (-not (Test-Path "$redisDir\redis-server.exe")) {
    Write-Host "🌐 Downloading Redis for Windows (v5.0.14.1)..."
    try {
        Invoke-WebRequest -Uri "https://github.com/tporadowski/redis/releases/download/v5.0.14.1/Redis-x64-5.0.14.1.zip" -OutFile $zipFile
    } catch {
        Write-Host "⚠️ Failed to download from GitHub directly. Trying proxy..."
        Invoke-WebRequest -Uri "https://ghproxy.net/https://github.com/tporadowski/redis/releases/download/v5.0.14.1/Redis-x64-5.0.14.1.zip" -OutFile $zipFile
    }
    
    Write-Host "📦 Extracting Redis..."
    Expand-Archive -Path $zipFile -DestinationPath $redisDir -Force
    Remove-Item $zipFile -Force
}

Write-Host "🚀 Starting Redis server on port 6379 in the background..."
Start-Process -FilePath "$redisDir\redis-server.exe" -WindowStyle Hidden
Write-Host "✅ Redis server successfully started!"
