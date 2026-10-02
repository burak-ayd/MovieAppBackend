#requires -Version 5.1
<#
.SYNOPSIS
    MovieApp imaj derleme ve Docker Hub'a gönderme (Windows / PowerShell)

.DESCRIPTION
    scripts/build-push.sh dosyasının Windows karşılığıdır. Aynı akışı yürütür:
    ön kontrol → test kapısı → Docker Hub girişi → derleme → boyut raporu →
    etiketleme → gönderim.

    PowerShell, bash sürümündeki HER ŞEYİ yapabilir; tek fark mimari tespiti ve
    boyut hesabı için Windows araçları kullanılmasıdır (uname/numfmt yok).

.PARAMETER ImageTag
    Etiket. Varsayılan: latest. Örnek: 1.1.0

.PARAMETER RunTests
    Derleme öncesi pytest çalıştır. Başarısızsa imaj ÜRETİLMEZ.

.PARAMETER Platform
    Hedef mimari. Varsayılan: bu makinenin mimarisi (linux/amd64).
    Çoklu mimari örnek: linux/amd64,linux/arm64

.PARAMETER NoCache
    Docker önbelleğini kullanma (temiz derleme). Yavaştır.

.PARAMETER AlsoLatest
    Sürümlü etiketten sonra :latest etiketini de gönder. Varsayılan: açık.

.EXAMPLE
    .\scripts\build-push.ps1

.EXAMPLE
    .\scripts\build-push.ps1 -ImageTag 1.1.0 -RunTests

.EXAMPLE
    $env:DOCKERHUB_USER = "burakaydogan"
    $env:DOCKERHUB_TOKEN = "dckr_pat_..."
    .\scripts\build-push.ps1 -ImageTag 1.1.0

.NOTES
    ── Gereksinimler ──────────────────────────────────────────────────────────
      Docker Desktop:  https://www.docker.com/products/docker-desktop/
      WSL2 önce:       wsl --install     (sonra bilgisayarı yeniden başlat)
      Doğrulama:       docker version ; docker compose version

    ── Sır YÖNETİMİ ─────────────────────────────────────────────────────────
      Parola komut satırına ASLA yazılmaz (ps ve PSReadLine history'de görünür).
      Betik token'ı --password-stdin ile geçirir.

      En temiz yöntem — token'ı ortam değişkeni olarak dışarıdan ver:
          $env:DOCKERHUB_TOKEN = "dckr_pat_..."
      Kalıcı istemiyorsanız sorulacak (ekranda gizlenerek).

    ── PowerShell yürütme politikası ──────────────────────────────────────────
      İlk çalıştırmada "running scripts is disabled" hatası alırsanız:
          Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
      Ya da tek seferlik:
          powershell -ExecutionPolicy Bypass -File .\scripts\build-push.ps1
#>

[CmdletBinding()]
param(
    [string] $ImageTag    = $(if ($env:IMAGE_TAG)    { $env:IMAGE_TAG }    else { "latest" }),
    [string] $DockerHubUser = $(if ($env:DOCKERHUB_USER) { $env:DOCKERHUB_USER } else { "" }),
    [string] $DockerHubToken = $(if ($env:DOCKERHUB_TOKEN) { $env:DOCKERHUB_TOKEN } else { "" }),
    [string] $Platform    = $(if ($env:PLATFORM)    { $env:PLATFORM }    else { "" }),
    [switch] $RunTests,
    [switch] $NoCache,
    [switch] $ForceLogin,
    [bool]   $AlsoLatest  = $(if ($null -ne $env:ALSO_LATEST) { $env:ALSO_LATEST -eq "1" } else { $true })
)

# ── Ayarlar ──────────────────────────────────────────────────────────────────
# Betiğin GERÇEK konumunu çöz: nokta ile çağrıldığında $PSScriptRoot doğrudur,
# ancak script yolu ile çağrılabilir ya da kopyalanabilir.
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path
Set-Location $projectRoot

$ErrorActionPreference = "Stop"

# Türkçe karakterler (▸ ✓ ! ✗) Windows konsolunda bozuk görünmesin diye
# çıktı kodlamasını UTF-8'e sabitliyoruz. PowerShell 5.1 varsayılan olarak
# konsol kod sayfasını yerel ayara göre ayarlar ve "Ön kontrol" → "n kontrol"
# gibi görünür.
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch {
    # Eski/kısıtlı hostlarda yoksayılabilir — çıktı yine de üretilir.
}

$ImageName = $(if ($env:IMAGE_NAME) { $env:IMAGE_NAME } else { "movieapp-api" })

# ── Renkli çıktı ─────────────────────────────────────────────────────────────
function Write-Step { param([string]$m) Write-Host "▸ $m" -ForegroundColor Cyan }
function Write-Ok   { param([string]$m) Write-Host "✓ $m" -ForegroundColor Green }
function Write-Warn { param([string]$m) Write-Host "! $m" -ForegroundColor Yellow }
function Write-Die  { param([string]$m) Write-Host "✗ $m" -ForegroundColor Red; exit 1 }

# Native komut hata kodu kontrolü
function Invoke-Native {
    param([string]$Exe, [string[]]$NativeArgs, [string]$FailMessage)
    & $Exe @NativeArgs
    if ($LASTEXITCODE -ne 0) { Write-Die $FailMessage }
}

Write-Host ""
Write-Host "╭──────────────────────────────────────────────╮" -ForegroundColor DarkGray
Write-Host "│  MovieApp imaj derleme ve yükleme (Windows)   │" -ForegroundColor DarkGray
Write-Host "╰──────────────────────────────────────────────╯" -ForegroundColor DarkGray
Write-Host ""

# ── 1) Ön kontrol ────────────────────────────────────────────────────────────
Write-Step "Ön kontrol"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Die @"
docker bulunamadı.

Kurulum:
  1. wsl --install            (PowerShell admin, sonra bilgisayarı yeniden başlat)
  2. Docker Desktop kur: https://www.docker.com/products/docker-desktop/
  3. Docker Desktop'u başlat ve "Use WSL 2 based engine" seçili kalsın
"@
}

# Docker çalışıyor mu (servis açık mı)?
& docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Die @"
docker çalışmıyor veya bu kullanıcı docker grubunda değil.

Deneyin:
  Docker Desktop'u açın (saat simgesinden durumunu kontrol edin), sonra:
  docker version
"@
}

# compose V2 eklentisi gerekli. "docker-compose" (V1, ayrı program) DEĞİL.
& docker compose version *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Die @"
'docker compose' (V2 eklentisi) bulunamadı.

Docker Desktop güncel olmalı. Alternatif:
  winget install Docker.DockerDesktop
"@
}

# ── Mimari tespiti (bash'taki `uname -m` karşılığı) ──────────────────────────
$rawArch = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString().ToLower()
switch ($rawArch) {
    "x64"   { $hostArch = "amd64" }
    "arm64" { $hostArch = "arm64" }
    default { $hostArch = $rawArch }
}
if (-not $Platform) { $Platform = "linux/$hostArch" }

Write-Warn "derleme mimarisi: $Platform (bu makine: $rawArch)"

if (-not $DockerHubUser) {
    $DockerHubUser = $env:USERNAME
    Write-Warn "DOCKERHUB_USER tanımsız, Windows kullanıcı adına düşülüyor: $DockerHubUser"
}

$fullImage = "$DockerHubUser/$ImageName"

$dockerVersion = (& docker version --format "{{.Server.Version}}" 2>$null)
$composeVersion = (& docker compose version --short 2>$null)
Write-Ok "docker $dockerVersion · compose $composeVersion"
Write-Ok "hedef imaj: ${fullImage}:$ImageTag"

# Docker Hub etiket kuralı: büyük harf ve boşluk kabul edilmez.
if ($ImageTag -notmatch '^[a-zA-Z0-9_][a-zA-Z0-9._-]{0,127}$') {
    Write-Die "geçersiz ImageTag: '$ImageTag' (yalnızca harf, rakam, . _ - kullanın)"
}

# Mimari uyarısı: build makinesi ile hedef makine aynı olmalı.
$isMulti = $Platform.Contains(",")
if (-not $isMulti -and $Platform -ne "linux/$hostArch") {
    Write-Warn "DİKKAT: bu makine $hostArch ama '$Platform' üretiliyor — çapraz mimari emülasyonu YAVAŞ olabilir"
}
if ($isMulti) { Write-Warn "çoklu mimari — buildx + emülatör kullanılacak (yavaş)" }

# ── 2) Derleme bağlamı ───────────────────────────────────────────────────────
Write-Step "Derleme bağlamı"

if (-not (Test-Path "Dockerfile"))              { Write-Die "Dockerfile bulunamadı: $projectRoot" }
if (-not (Test-Path "requirements.txt"))        { Write-Die "requirements.txt bulunamadı" }
if (-not (Test-Path "docker-compose.build.yml")){ Write-Die "docker-compose.build.yml bulunamadı" }

$contextBytes = (Get-ChildItem -Recurse -File -Force -ErrorAction SilentlyContinue |
                 Where-Object { $_.FullName -notmatch '\\\.git\\' } |
                 Measure-Object -Property Length -Sum).Sum
Write-Ok ("kaynak ağacı {0} MB ({1})" -f [math]::Round($contextBytes / 1MB, 0), $projectRoot)

if (Test-Path ".dockerignore") {
    Write-Ok ".dockerignore mevcut — .git, .env ve cache bağlam dışında"
} else {
    Write-Warn ".dockerignore yok — .git ve .env derleme bağlamına girebilir (gereksiz yer kaplar)"
}

# ── 3) Testler (isteğe bağlı kapı) ───────────────────────────────────────────
Write-Step "Testler"
if ($RunTests) {
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        Write-Warn "python yok, testler atlandı"
    } elseif (-not (Test-Path ".venv\Scripts\python.exe")) {
        Write-Warn "proje venv'i yok (.venv\Scripts\python.exe) — testler atlandı"
        Write-Warn "oluşturmak için: python -m venv .venv; .\.venv\Scripts\Activate.ps1"
        Write-Warn "pip install -r requirements-dev.txt"
    } else {
        Write-Host "  çalıştırılıyor: .\.venv\Scripts\python.exe -m pytest tests -q --no-header"
        & .\.venv\Scripts\python.exe -m pytest tests -q --no-header
        if ($LASTEXITCODE -ne 0) { Write-Die "TESTLER BAŞARISIZ — imaj üretilmedi" }
        Write-Ok "testler geçti"
    }
} else {
    Write-Warn "RunTests verilmedi — testler çalıştırılmadı (production öncesi önerilir)"
}

# ── 4) Docker Hub oturumu ─────────────────────────────────────────────────────
Write-Step "Docker Hub oturumu"

# Önce MEVCUT oturumu kontrol et. `docker login` bilgileri
# %DOCKER_CONFIG%\config.json içine yazılır; betik bunu okumadan her seferinde
# token istemek hataydı. Sıra:
#   1) -ForceLogin (veya FORCE_LOGIN=1) → atla, yeniden giriş yap
#   2) config.json'de oturum var         → devam et, token SORMA
#   3) DOCKERHUB_TOKEN                    → kullan
#   4) İnteraktif soru (gizli)            → ekranda al
$dockerConfigDir = $(if ($env:DOCKER_CONFIG) { $env:DOCKER_CONFIG } else { Join-Path $env:USERPROFILE ".docker" })
$dockerCfg = Join-Path $dockerConfigDir "config.json"
$forceLogin = [bool]$ForceLogin -or ($env:FORCE_LOGIN -eq "1")

$sessionVar = $false
if ((-not $forceLogin) -and (Test-Path $dockerCfg)) {
    $raw = Get-Content $dockerCfg -Raw -ErrorAction SilentlyContinue
    if ($raw) {
        # auths altında Docker Hub kaydı var mı?
        if (($raw -match '"auths"') -and ($raw -match 'index\.docker\.io|registry-1\.docker\.io|docker\.io')) {
            $sessionVar = $true
        }
        # veya kimlik bir yardımcıda saklanıyor (Docker Desktop / GCM)
        elseif ($raw -match '"credsStore"|"credHelpers"') {
            $sessionVar = $true
        }
    }
}

if ($sessionVar) {
    Write-Ok "mevcut Docker Hub oturumu bulundu ($dockerCfg)"
    Write-Warn "sudo docker login yaptıysanız kimlik /root/.docker'da olabilir, burada görünmez."
    Write-Warn "Bu durumda token sorulmadan push başarısız olur; -ForceLogin ile zorla giriş yapın."
} else {
    if ($forceLogin) { Write-Warn "ForceLogin - mevcut oturum yok sayıldı, yeniden giriş yapılıyor" }

    if (-not $DockerHubToken -and $env:DOCKERHUB_TOKEN) {
        $DockerHubToken = $env:DOCKERHUB_TOKEN
    }
    if (-not $DockerHubToken) {
        # Token'ı ekranda gizli al. PS 7'de -MaskInput, 5.1'de -AsSecureString.
        Write-Host "  Docker Hub Personal Access Token (görünmez): " -NoNewline
        try   { $DockerHubToken = Read-Host -MaskInput }
        catch { $DockerHubToken = Read-Host -AsSecureString | ForEach-Object {
                    [System.Net.NetworkCredential]::new("", $_).Password } }
        Write-Host ""
    }
    if (-not $DockerHubToken) { Write-Die "token boş — oturum açılamadı" }

    # --password-stdin: parola komut satırına ve PSReadLine history'ye GİRMEZ
    $DockerHubToken | & docker login --username $DockerHubUser --password-stdin *> $null
    if ($LASTEXITCODE -ne 0) { Write-Die "docker login başarısız — kullanıcı adı veya token hatalı" }
    $DockerHubToken = $null
    Write-Ok "oturum açıldı: $DockerHubUser"
}

# ── 5) Derleme ───────────────────────────────────────────────────────────────
# --pull: taban imajını günceller → güvenlik yamaları imaja girer.
$buildFlags = @("--pull")
if ($NoCache) { $buildFlags += "--no-cache" }

$nativePlatform = "linux/$hostArch"
$useBuildx = ($Platform -ne $nativePlatform) -or $isMulti
$pushedByBuildx = $false

if (-not $useBuildx) {
    Write-Step "derleniyor ($Platform)"
    $buildCmd = @("compose", "-f", "docker-compose.build.yml", "build") + $buildFlags
    Write-Host "  komut: docker $($buildCmd -join ' ')" -ForegroundColor DarkGray
    Write-Host ""

    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    & docker @buildCmd
    if ($LASTEXITCODE -ne 0) { Write-Die "derleme başarısız" }
    $sw.Stop()
    $buildSec = [int]$sw.Elapsed.TotalSeconds
    Write-Ok "derleme tamamlandı ($buildSec sn)"
} else {
    Write-Step "derleniyor (buildx, $Platform) — yerelde aracı görüntü oluşmaz, doğrudan push edilir"
    Write-Warn "çapraz/çoklu mimari emülasyon kullanır; saatler sürebilir"

    & docker buildx version *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Die @"
çoklu mimari için buildx gerekli ama bulunamadı.

Buildx Docker Desktop ile birlikte gelir; güncel sürümü kurun.
Alternatif (daha basit): build makinesinin mimarisini Coolify sunucusuyla
AYNI yapın — bu durumda Platform parametresini hiç vermeyin.
"@
    }

    if ($isMulti) {
        & docker buildx inspect movieapp-builder *> $null
        if ($LASTEXITCODE -ne 0) {
            Write-Step "buildx hazırlanıyor (container sürücü + emülatör)"
            Invoke-Native docker @("buildx", "create", "--name", "movieapp-builder",
                                   "--driver", "docker-container", "--use") "buildx oluşturulamadı"
        } else {
            Invoke-Native docker @("buildx", "use", "movieapp-builder") "buildx seçilemedi"
        }
    }

    $buildCmd = @("buildx", "build", "--platform", $Platform, "--push")
    $buildCmd += @("--tag", "${fullImage}:$ImageTag")
    if ($AlsoLatest -and $ImageTag -ne "latest") { $buildCmd += @("--tag", "${fullImage}:latest") }
    $buildCmd += $buildFlags
    $buildCmd += "."

    Write-Host "  komut: docker $($buildCmd -join ' ')" -ForegroundColor DarkGray
    Write-Host ""

    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    & docker @buildCmd
    if ($LASTEXITCODE -ne 0) { Write-Die "derleme başarısız" }
    $sw.Stop()
    $buildSec = [int]$sw.Elapsed.TotalSeconds
    $pushedByBuildx = $true
    Write-Ok "derleme tamamlandı ($buildSec sn)"
}

# ── 6) Boyut raporu ──────────────────────────────────────────────────────────
# buildx --push yerelde görüntü bırakmadığı için raporlanamaz.
if (-not $pushedByBuildx) {
    Write-Step "Boyut"
    $sizeRaw = (& docker image inspect "${fullImage}:$ImageTag" --format "{{.Size}}" 2>$null)
    if ($sizeRaw -and [int64]$sizeRaw -gt 0) {
        $mb = [math]::Round([int64]$sizeRaw / 1MB, 0)
        Write-Ok "sıkıştırılmamış: ${mb} MB  (Docker Hub sıkıştırılmış hâlini gösterir, ~%60-65 küçük)"
    } else {
        Write-Warn "boyut okunamadı"
    }
}

# ── 7) Etiketleme ve gönderme ────────────────────────────────────────────────
if (-not $pushedByBuildx) {
    if ($AlsoLatest -and $ImageTag -ne "latest") {
        Write-Step "Etiketleme"
        Invoke-Native docker @("tag", "${fullImage}:$ImageTag", "${fullImage}:latest") "etiketleme başarısız"
        Write-Ok "$ImageTag → latest"
    }

    Write-Step "Docker Hub'a gönderiliyor"
    Invoke-Native docker @("push", "${fullImage}:$ImageTag") "push başarısız ($ImageTag)"
    Write-Ok "gönderildi: ${fullImage}:$ImageTag"

    if ($AlsoLatest -and $ImageTag -ne "latest") {
        Invoke-Native docker @("push", "${fullImage}:latest") "push başarısız (latest)"
        Write-Ok "gönderildi: ${fullImage}:latest"
    }
} else {
    Write-Ok "gönderim buildx --push ile tamamlandı"
}

# ── 8) Özet ──────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "──────────────────────────────────────────────" -ForegroundColor DarkGray
Write-Host " TAMAMLANDI" -ForegroundColor Green
Write-Host "──────────────────────────────────────────────" -ForegroundColor DarkGray
Write-Host "  imaj      : ${fullImage}:$ImageTag"
Write-Host "  mimari    : $Platform"
Write-Host "  süre      : $buildSec sn"
Write-Host ""
Write-Host "  Sunucuda doğrulamak için:" -ForegroundColor DarkGray
Write-Host "    docker pull ${fullImage}:$ImageTag"
Write-Host "    docker run --rm -p 8000:8000 ${fullImage}:$ImageTag"
Write-Host "    curl http://localhost:8000/"
Write-Host ""
Write-Host "  Coolify tarafında:" -ForegroundColor DarkGray
Write-Host "    IMAGE_TAG=$ImageTag olarak ayarla ve redeploy yap"
Write-Host ""
Write-Host "  Disk alanı kazanmak için:" -ForegroundColor DarkGray
Write-Host "    docker builder prune --filter until=168h   # önbellek"
Write-Host "    docker image prune -a --filter until=720h  # eski imajlar"
Write-Host ""
