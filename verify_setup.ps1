# Verification script for NW Digital Operations Hub V3

Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "NW Digital Operations Hub V3 - Developer Setup Verification" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan

# 1. Check Python Environment
Write-Host ""
Write-Host "1. Checking Python Environment..." -ForegroundColor Yellow
if (Test-Path ".venv") {
    Write-Host "Virtual environment (.venv) exists." -ForegroundColor Green
    
    # Try importing key libraries using a single-line expression
    $importCheck = & .venv\Scripts\python.exe -c "import fastapi, sqlalchemy, alembic, redis; print('OK')"
    if ($importCheck.Trim() -eq "OK") {
        Write-Host "Core Python libraries imported successfully." -ForegroundColor Green
    } else {
        Write-Host "Error importing Python libraries." -ForegroundColor Red
    }
} else {
    Write-Host "Virtual environment (.venv) not found. Run: python -m venv .venv" -ForegroundColor Red
}

# 2. Check Next.js Frontend
Write-Host ""
Write-Host "2. Checking Next.js Workspace..." -ForegroundColor Yellow
if (Test-Path "apps/web/package.json") {
    Write-Host "Next.js workspace structure exists." -ForegroundColor Green
} else {
    Write-Host "Next.js workspace package.json not found." -ForegroundColor Red
}

# 3. Check Migrations
Write-Host ""
Write-Host "3. Checking Database Migrations..." -ForegroundColor Yellow
$migrationFiles = Get-ChildItem "packages/database/alembic/versions/*.py" -ErrorAction SilentlyContinue
if ($migrationFiles) {
    Write-Host "Database migration script generated:" -ForegroundColor Green
    foreach ($file in $migrationFiles) {
        Write-Host "  - $($file.Name)" -ForegroundColor Gray
    }
} else {
    Write-Host "No database migration files found." -ForegroundColor Red
}

# 4. Check Environment Configuration
Write-Host ""
Write-Host "4. Checking Environment Configurations..." -ForegroundColor Yellow
if (Test-Path ".env") {
    Write-Host ".env file exists." -ForegroundColor Green
} else {
    Write-Host ".env file not found. Copy .env.example to .env to configure local environment variables." -ForegroundColor Red
}

Write-Host ""
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "Verification Complete" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
