<#
.SYNOPSIS
  caffeinate Windows x64 빌드: 패치한 libcurl-impersonate + caffeinate 플랫폼 휠 (내장 _curl_cffi).

.DESCRIPTION
  1. curl-impersonate (CurlImpersonateTag, curl_cffi 0.16.3 은 v2.2.2) 를 얕게 받는다.
  2. native/patches/ 의 패치를 적용한다.
       superbuild-msvc.patch  - 상위 CMakeLists: clang-cl 대신 MSVC cl.exe 로 빌드되게,
                                아래 패치들을 ExternalProject 패치 단계에 연결
       curl-caffeinate.patch  - curl: CURLOPT_HTTP2_INITIAL_STREAM_ID(1900),
                                CURLOPT_HTTP2_STREAM_WINDOW_UPDATE(1901)
       curl-msvc.patch        - curl: MSVC C 컴파일 수정 (VLA)
       boringssl-msvc.patch   - BoringSSL: MSVC C++ 컴파일 수정
  3. MSVC + CMake + Ninja (+ NASM) 로 의존성(BoringSSL, nghttp2, ngtcp2, nghttp3, brotli,
     zstd, zlib)과 libcurl-impersonate.dll 을 빌드한다 (upstream win/build.bat 과 같은 옵션).
  4. 그 DLL 로 caffeinate 휠(caffeinate._curl_cffi._wrapper 확장 포함)을 빌드하고 delvewheel 로 DLL 을
     휠에 넣는다. (setup.py 는 CAFFEINATE_LIBCURL_DIR 이 있을 때만 확장을 빌드한다)

  필요: Visual Studio 2022+ (C++ 데스크톱), cmake>=3.20, ninja, git (Git for Windows 의 patch.exe 사용),
        Python 3.10+ (pip). NASM 이 PATH 에 없으면 nasm.us 에서 포터블 zip 을 받는다 (SHA256 확인).
  디스크: 작업 폴더에 약 3 GB.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File native\build_windows.ps1 -WorkDir D:\cafbuild
  pip install --force-reinstall D:\cafbuild\dist\caffeinate-*.whl
#>
[CmdletBinding()]
param(
    [string]$WorkDir = (Join-Path (Split-Path -Parent $PSScriptRoot) "build-win"),
    [string]$CurlImpersonateTag = "v2.2.2",
    [string]$VcVars = "",
    [switch]$SkipLib,
    [switch]$CleanIntermediates
)
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$PatchDir = Join-Path $RepoRoot "native\patches"
New-Item -ItemType Directory -Force $WorkDir | Out-Null
$WorkDir = (Resolve-Path $WorkDir).Path
$Src = Join-Path $WorkDir "curl-impersonate"
$Pkg = Join-Path $Src "packages"
$Stage = Join-Path $WorkDir "stage"
$Dist = Join-Path $WorkDir "dist"
$Tools = Join-Path $WorkDir "tools"

function Find-VcVars {
    if ($VcVars) { return $VcVars }
    $vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    if (Test-Path $vswhere) {
        # VS 2022 (Python 3.x 공식 빌드와 같은 툴셋) 우선, 없으면 최신
        foreach ($range in @("[17.0,18.0)", "")) {
            $a = @("-products", "*", "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                   "-find", "VC\Auxiliary\Build\vcvars64.bat")
            if ($range) { $a = @("-version", $range) + $a } else { $a = @("-latest") + $a }
            $found = & $vswhere @a | Select-Object -First 1
            if ($found) { return $found }
        }
    }
    throw "vcvars64.bat 을 찾지 못했습니다. -VcVars 로 경로를 지정하세요."
}

function Invoke-InVcEnv([string[]]$Commands) {
    $bat = Join-Path $WorkDir "_step.bat"
    $lines = @("@echo off", "call `"$script:VcVarsBat`" >NUL || exit /b 1",
               "set `"PATH=$Tools\nasm;%PATH%`"") + ($Commands | ForEach-Object { "$_ || exit /b 1" })
    Set-Content -Path $bat -Value $lines -Encoding ascii
    & cmd.exe /c $bat
    if ($LASTEXITCODE -ne 0) { throw "명령 실패 (exit $LASTEXITCODE): $($Commands -join ' ; ')" }
}

$script:VcVarsBat = Find-VcVars
Write-Host "vcvars: $script:VcVarsBat"
foreach ($t in @("cmake", "ninja", "git", "python")) {
    if (-not (Get-Command $t -ErrorAction SilentlyContinue)) { throw "$t 가 PATH 에 없습니다." }
}
$GitPatch = Join-Path (Split-Path -Parent (Split-Path -Parent (Get-Command git).Source)) "usr\bin\patch.exe"
if (-not (Test-Path $GitPatch)) { $GitPatch = "C:\Program Files\Git\usr\bin\patch.exe" }
if (-not (Test-Path $GitPatch)) { throw "patch.exe (Git for Windows) 를 찾지 못했습니다." }

# NASM: BoringSSL 어셈블리 (없으면 OPENSSL_NO_ASM 이 필요하지만 upstream 과 맞추려고 NASM 사용)
if (-not (Get-Command nasm -ErrorAction SilentlyContinue) -and -not (Test-Path "$Tools\nasm\nasm.exe")) {
    New-Item -ItemType Directory -Force $Tools | Out-Null
    $zip = Join-Path $Tools "nasm.zip"
    Invoke-WebRequest "https://www.nasm.us/pub/nasm/releasebuilds/2.16.03/win64/nasm-2.16.03-win64.zip" -OutFile $zip
    $h = (Get-FileHash $zip -Algorithm SHA256).Hash
    if ($h -ne "3EE4782247BCB874378D02F7EAB4E294A84D3D15F3F6EE2DE2F47A46AA7226E6") { throw "nasm zip SHA256 불일치: $h" }
    Expand-Archive $zip -DestinationPath $Tools -Force
    Move-Item (Join-Path $Tools "nasm-2.16.03") (Join-Path $Tools "nasm")
    Remove-Item $zip
}

if (-not $SkipLib) {
    if (-not (Test-Path $Src)) {
        git -c core.autocrlf=false clone --depth 1 --branch $CurlImpersonateTag `
            https://github.com/lexiforest/curl-impersonate.git $Src
        if ($LASTEXITCODE -ne 0) { throw "curl-impersonate clone 실패" }
        git -c core.autocrlf=false -c safe.directory=* -C $Src apply --whitespace=nowarn `
            (Join-Path $PatchDir "superbuild-msvc.patch")
        if ($LASTEXITCODE -ne 0) { throw "superbuild-msvc.patch 적용 실패" }
    }
    foreach ($p in @("curl-caffeinate.patch", "curl-msvc.patch", "boringssl-msvc.patch")) {
        Copy-Item (Join-Path $PatchDir $p) (Join-Path $Src "patches\$p") -Force
    }
    $t0 = Get-Date
    # upstream win/build.bat 과 같은 옵션, 컴파일러만 clang-cl -> cl
    Invoke-InVcEnv @(
        "cd /d `"$Src`"",
        "cmake -S . -B build -GNinja -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=`"$Pkg`" -DUSE_LIBIDN2=OFF -DCMAKE_POLICY_DEFAULT_CMP0091=NEW -DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded -DCMAKE_C_COMPILER=cl.exe -DCMAKE_CXX_COMPILER=cl.exe -DCMAKE_LINKER=link.exe -DPATCH_EXE=`"$GitPatch`"",
        "cmake --build build --config Release --target install-all"
    )
    Write-Host ("libcurl-impersonate 빌드 시간: {0:hh\:mm\:ss}" -f ((Get-Date) - $t0))
}

# 확장 빌드 입력 (native/build_ffi.py): <stage>\libcurl-impersonate.dll, *_imp.lib, include\curl
if (Test-Path $Stage) { Remove-Item -Recurse -Force $Stage }
New-Item -ItemType Directory -Force (Join-Path $Stage "include") | Out-Null
Copy-Item (Join-Path $Pkg "lib\libcurl-impersonate.dll") $Stage
Copy-Item (Join-Path $Pkg "lib\libcurl-impersonate_imp.lib") $Stage
Copy-Item -Recurse (Join-Path $Pkg "include\curl") (Join-Path $Stage "include\curl")

$Raw = Join-Path $WorkDir "rawwheel"
if (Test-Path $Raw) { Remove-Item -Recurse -Force $Raw }
New-Item -ItemType Directory -Force $Dist | Out-Null
Get-ChildItem $Dist -Filter "caffeinate-*.whl" -ErrorAction SilentlyContinue | Remove-Item -Force
python -m pip install --quiet --upgrade delvewheel
if ($LASTEXITCODE -ne 0) { throw "delvewheel 설치 실패" }
$env:CAFFEINATE_LIBCURL_DIR = $Stage
try {
    Invoke-InVcEnv @(
        "cd /d `"$RepoRoot`"",
        "python -m pip wheel . --no-deps -w `"$Raw`"",
        "python -m delvewheel repair --add-path `"$Stage`" -w `"$Dist`" `"$Raw\*.whl`""
    )
} finally {
    Remove-Item Env:\CAFFEINATE_LIBCURL_DIR -ErrorAction SilentlyContinue
}
Get-ChildItem $Dist -Filter *.whl | ForEach-Object { Write-Host ("휠: {0} ({1:N0} bytes)" -f $_.FullName, $_.Length) }

if ($CleanIntermediates) {
    # 의존성 소스/오브젝트 (약 2 GB) 삭제. packages\ 와 dist\ 는 남긴다.
    Remove-Item -Recurse -Force (Join-Path $Src "build"), $Raw -ErrorAction SilentlyContinue
}
