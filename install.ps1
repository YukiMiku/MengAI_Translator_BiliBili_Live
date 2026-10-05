<#
  MengAI Translator for BiliBili Live（萌AIちゃん）ポータブル版インストーラー

  やること:
    1. ポータブルパッケージをダウンロード（Python 同梱・別途インストール不要）
    2. 展開してインストール（アップグレード時は語彙/設定/ログイン情報を保持）
    3. デスクトップにショートカットを作成
    4. Pillow を入れるか確認（JPG/WEBP 背景 + 滑らかな拡縮）

  インストール先（既定）:
    install.bat を置いたフォルダの下に「萌AIちゃん」を作って、そこに入れます。
      D:\Tools\install.bat を実行  ->  D:\Tools\萌AIちゃん
    install.ps1 を単体で実行した場合は、install.ps1 のフォルダが基準になります。
    別の場所にしたいときは -Dest を使ってください。

  使い方:
    powershell -ExecutionPolicy Bypass -File install.ps1
    powershell -ExecutionPolicy Bypass -File install.ps1 -PackageUrl "http://127.0.0.1:8000/pkg.zip"
    powershell -ExecutionPolicy Bypass -File install.ps1 -Dest "D:\Tools"
    powershell -ExecutionPolicy Bypass -File install.ps1 -Pillow Yes

  ★ 命名について（実際に踏んだ罠）
    パスとショートカットのファイル名に、そのシステムの ANSI コードページで
    表現できない文字を入れてはいけません。日本語版 Windows（コードページ 932）では
    簡体字の「译」「酱」「启」「动」などが Shift-JIS に無いため、WScript.Shell が
    TargetPath を設定できず、.lnk の保存自体も失敗します。
    そのため本スクリプトは意図的に:
      · インストール先 萌AIちゃん（日本語版 Windows の Shift-JIS で表現できるため有効）
      · ショートカットの指す先 launch.bat（ASCII）
    日本語名はウィンドウタイトルと画面内（Unicode 経路）で使います。
#>
[CmdletBinding()]
param(
    [string]$PackageUrl = 'https://github.com/YukiMiku/MengAI_Translator_BiliBili_Live/releases/latest/download/MengAI_Translator_BiliBili_Live.zip',
    [string]$Dest = '',
    [string]$BaseDir = '',
    [ValidateSet('Ask', 'Yes', 'No')][string]$Pillow = 'Ask',
    [string]$ShortcutDir = ([Environment]::GetFolderPath('Desktop')),
    [string]$ShortcutName = '萌AIちゃん.lnk',
    [switch]$NoShortcut,
    [switch]$Unattended
)

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# インストール先の既定値:
#   install.bat が -BaseDir で自分のフォルダを渡してくるので、その下の「萌AIちゃん」。
#   install.ps1 を単体で実行した場合は install.ps1 のフォルダを基準にします。
#   （v1.2.0 以前は %USERPROFILE%\萌AIちゃん でした）
if (-not $Dest) {
    $base = $BaseDir
    if (-not $base) {
        $base = $PSScriptRoot
        # 安全弁: 古い install.bat は -BaseDir を渡してきません。その場合この
        # スクリプトは %TEMP% に落とした一時ファイルとして走っているので、
        # $PSScriptRoot は %TEMP% になります。そこへ入れると消えてしまうため、
        # 従来の既定位置（%USERPROFILE%\萌AIちゃん）にフォールバックします。
        if ($base -and $env:TEMP -and $base.StartsWith($env:TEMP, 'OrdinalIgnoreCase')) {
            Write-Host ''
            Write-Host '   [注意] install.bat が古いため、インストール先を従来の既定位置にします。' -ForegroundColor Yellow
            Write-Host '          最新の install.bat をダウンロードし直すことをおすすめします。' -ForegroundColor Yellow
            Write-Host ''
            $base = $env:USERPROFILE
        }
    }
    if (-not $base) { $base = (Get-Location).Path }
    $base = $base.TrimEnd('\')
    if ($base -match '^[A-Za-z]:$') { $base = $base + '\' }   # ドライブ直下（D:\）対策
    $Dest = Join-Path $base '萌AIちゃん'
}

$AppLabel = '萌AIちゃん'
$AppDir   = $Dest

function Write-Step($n, $text) { Write-Host "[$n] $text" -ForegroundColor Cyan }
function Write-Ok($text)       { Write-Host "    $text" -ForegroundColor Green }
function Write-Warn2($text)    { Write-Host "    $text" -ForegroundColor Yellow }
function Write-Err($text)      { Write-Host "    $text" -ForegroundColor Red }

Write-Host ('=' * 62)
Write-Host "   $AppLabel   ポータブル版インストーラー"
Write-Host ('=' * 62)
Write-Host ''
Write-Host "   パッケージ : $PackageUrl"
Write-Host "   インストール先 : $AppDir"
Write-Host ''

# 事前チェック: パスがシステム ANSI コードページで表現できるか
$ansi     = [System.Text.Encoding]::Default
$pathSafe = ($ansi.GetString($ansi.GetBytes($AppDir)) -eq $AppDir)

# ---------------------------------------------------------------- 1) ダウンロード
Write-Step '1/4' 'ポータブルパッケージをダウンロード中…'
$tmpZip = Join-Path $env:TEMP ("ai-mengyijiang-{0}.zip" -f (Get-Random))
try {
    $ProgressPreference = 'SilentlyContinue'
    Invoke-WebRequest -Uri $PackageUrl -OutFile $tmpZip -UseBasicParsing
} catch {
    Write-Err "ダウンロードに失敗しました: $($_.Exception.Message)"
    Write-Host ''
    Write-Host "   手動でダウンロードし、次のフォルダに展開してください: $AppDir"
    Write-Host "   $PackageUrl"
    exit 1
}
Write-Ok ("ダウンロード完了 {0:N1} MB" -f ((Get-Item $tmpZip).Length / 1MB))

# ---------------------------------------------------------------- 2) 展開
Write-Step '2/4' '展開中…'
$stage = Join-Path $env:TEMP ("ai-mengyijiang-stage-{0}" -f (Get-Random))
New-Item -ItemType Directory -Path $stage -Force | Out-Null
try {
    Expand-Archive -LiteralPath $tmpZip -DestinationPath $stage -Force
} catch {
    Write-Err "展開に失敗しました: $($_.Exception.Message)"
    exit 1
} finally {
    Remove-Item $tmpZip -Force -ErrorAction SilentlyContinue
}

# zip の中は 萌AIちゃん フォルダ 1 つ。launch.bat を含む階層を探す
$inner = Get-ChildItem -LiteralPath $stage -Directory | Select-Object -First 1
if ($inner -and (Test-Path (Join-Path $inner.FullName 'launch.bat'))) {
    $newRoot = $inner.FullName
} elseif (Test-Path (Join-Path $stage 'launch.bat')) {
    $newRoot = $stage
} else {
    Write-Err 'launch.bat が見つかりません。パッケージが壊れている可能性があります。'
    exit 1
}
Write-Ok "展開完了（$((Get-ChildItem $newRoot -Recurse -File).Count) ファイル）"

# ---------------------------------------------------------------- 3) インストール（data は保持）
Write-Step '3/4' 'インストール中…'
$keepData  = $null
$legacyDir = Join-Path $env:USERPROFILE '萌AIちゃん'
if (Test-Path $AppDir) {
    $oldData = Join-Path $AppDir 'data'
    if (Test-Path $oldData) {
        $keepData = Join-Path $env:TEMP ("ai-mengyijiang-data-{0}" -f (Get-Random))
        Copy-Item $oldData $keepData -Recurse -Force
        Write-Ok '既存のインストールを検出。アップグレードします（語彙・設定・ログイン情報は保持）'
    }
    Remove-Item $AppDir -Recurse -Force
} elseif ($AppDir -ne $legacyDir -and (Test-Path (Join-Path $legacyDir 'data'))) {
    # v1.2.0 以前の既定インストール先が残っていれば、その設定を引き継ぐ
    $keepData = Join-Path $env:TEMP ("ai-mengyijiang-data-{0}" -f (Get-Random))
    Copy-Item (Join-Path $legacyDir 'data') $keepData -Recurse -Force
    Write-Ok '以前のバージョンの設定（旧インストール先）を検出。引き継ぎます'
}
$parent = Split-Path $AppDir -Parent
if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
Move-Item -LiteralPath $newRoot -Destination $AppDir
Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue

if ($keepData) {
    $newData = Join-Path $AppDir 'data'
    if (-not (Test-Path $newData)) { New-Item -ItemType Directory -Path $newData -Force | Out-Null }
    Copy-Item (Join-Path $keepData '*') $newData -Recurse -Force
    Remove-Item $keepData -Recurse -Force -ErrorAction SilentlyContinue
    Write-Ok 'data フォルダを復元しました'
}

# 「インターネットから取得」マークを外す（bat/dll が実行を拒否されるのを防ぐ）
try {
    Get-ChildItem -LiteralPath $AppDir -Recurse -File -Include *.bat, *.exe, *.dll |
        Unblock-File -ErrorAction SilentlyContinue
} catch { }
Write-Ok "インストール完了: $AppDir"

# ---------------------------------------------------------------- 4) ショートカット
if (-not $NoShortcut) {
    Write-Host ''
    Write-Step '3.5' 'デスクトップにショートカットを作成中…'
    if (-not $pathSafe) {
        Write-Warn2 'インストール先に、このシステムのコードページで扱えない文字が含まれています。'
        Write-Warn2 'ショートカット作成に失敗する可能性があります。例: -Dest "D:\MengAI"'
    }
    try {
        if (-not (Test-Path $ShortcutDir)) { New-Item -ItemType Directory -Path $ShortcutDir -Force | Out-Null }
        $lnkPath = Join-Path $ShortcutDir $ShortcutName
        $ws  = New-Object -ComObject WScript.Shell
        $lnk = $ws.CreateShortcut($lnkPath)
        $lnk.TargetPath       = Join-Path $AppDir 'launch.bat'
        $lnk.WorkingDirectory = $AppDir
        $lnk.IconLocation     = (Join-Path $AppDir 'python\pythonw.exe') + ',0'
        $lnk.Description      = 'AI MengYiJiang - Bilibili danmaku translator'
        $lnk.Save()

        # 読み戻し検証: WScript.Shell は壊れたパスでも「成功」したように見えることがある
        $chk = (New-Object -ComObject WScript.Shell).CreateShortcut($lnkPath)
        if ($chk.TargetPath -and (Test-Path -LiteralPath $chk.TargetPath)) {
            Write-Ok "作成しました: $lnkPath"
        } else {
            Write-Warn2 'ショートカットは作られましたが、リンク先を解決できません（コードページ制限）'
            Write-Warn2 "手動作成: $AppDir\launch.bat を右クリック → 送る → デスクトップ（ショートカットを作成）"
        }
    } catch {
        Write-Warn2 "ショートカット作成に失敗しました: $($_.Exception.Message)"
        Write-Warn2 "直接 $AppDir\launch.bat をダブルクリックしても起動できます"
    }
}

# ---------------------------------------------------------------- 5) Pillow（任意）
Write-Host ''
Write-Step '4/4' 'オプション: Pillow'
Write-Host ''
Write-Host '    Pillow を入れると、弾幕エリアの背景に JPG / WEBP が使え、'
Write-Host '    拡大縮小も滑らかになります。無くても PNG / GIF は使えます。'
Write-Host '    約 7 MB、ネット接続が必要です。'
Write-Host ''

$doPillow = $false
if ($Pillow -eq 'Yes') {
    $doPillow = $true
} elseif ($Pillow -eq 'No') {
    $doPillow = $false
} else {
    $ans = Read-Host '    Pillow を今インストールしますか？ [Y/N]（Enter でスキップ）'
    $doPillow = ($ans -match '^[Yy]')
}

if ($doPillow) {
    $pyExe = Join-Path $AppDir 'python\python.exe'
    $sp    = Join-Path $AppDir 'python\Lib\site-packages'
    try {
        # ABI タグを正確に取る: 通常版は cp314、フリースレッド版は cp314t。
        # "cp314" だけで判定すると cp314t のホイールを選んでしまい、
        # 展開後に _imaging のインポートが失敗する（＝Pillow が壊れた状態）。
        $abi = (& $pyExe -c "import sysconfig,sys; print('cp%d%d'%(sys.version_info.major,sys.version_info.minor) + ('t' if sysconfig.get_config_var('Py_GIL_DISABLED') else ''))").Trim()
        Write-Host "    インタプリタ ABI: $abi"
        $json = Invoke-RestMethod -Uri 'https://pypi.org/pypi/pillow/json' -UseBasicParsing
        $file = $json.urls | Where-Object { $_.filename -like "*$abi-win_amd64.whl" } | Select-Object -First 1
        if (-not $file) { throw "PyPI に $abi win_amd64 の Pillow ホイールがありません" }
        Write-Host "    ダウンロード $($file.filename)（$([math]::Round($file.size/1MB,1)) MB）…"
        $whl = Join-Path $env:TEMP 'pillow.whl'
        Invoke-WebRequest -Uri $file.url -OutFile $whl -UseBasicParsing

        # 先に旧版を消す（pip --force-reinstall 相当）
        $oldPil = Join-Path $sp 'PIL'
        if (Test-Path $oldPil) { Remove-Item $oldPil -Recurse -Force }
        Get-ChildItem $sp -Directory -Filter 'pillow-*.dist-info' -ErrorAction SilentlyContinue |
            Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $zip = [System.IO.Compression.ZipFile]::OpenRead($whl)
        foreach ($e in $zip.Entries) {
            if ($e.Name -eq '' -or $e.FullName -like '*.dist-info/RECORD') { continue }
            $target = Join-Path $sp $e.FullName
            $tdir   = Split-Path $target -Parent
            if (-not (Test-Path $tdir)) { New-Item -ItemType Directory -Path $tdir -Force | Out-Null }
            [System.IO.Compression.ZipFileExtensions]::ExtractToFile($e, $target, $true)
        }
        $zip.Dispose()
        Remove-Item $whl -Force -ErrorAction SilentlyContinue

        if (Test-Path (Join-Path $sp 'PIL')) {
            Write-Ok 'Pillow をインストールしました'
        } else {
            throw '展開後に PIL フォルダが見つかりません'
        }
    } catch {
        Write-Warn2 "Pillow のインストールに失敗しました: $($_.Exception.Message)"
        Write-Warn2 'あとからアプリ内で入れられます: 外観 → Pillow をインストール / 修復'
    }
} else {
    Write-Ok 'スキップしました。あとからアプリ内で入れられます: 外観 → Pillow をインストール / 修復'
}

# ---------------------------------------------------------------- 完了
Write-Host ''
Write-Host ('=' * 62)
Write-Host '   インストール完了'
Write-Host ''
Write-Host "   フォルダ : $AppDir"
Write-Host "   起動     : デスクトップのショートカット、または $AppDir\launch.bat"
Write-Host "   診断     : $AppDir\check.bat"
Write-Host ''
Write-Host '   メモ : インストール先は install.bat と同じフォルダの下の「萌AIちゃん」です。'
Write-Host '          別の場所にしたいときは -Dest "D:\MengAI" のように指定してください。'
Write-Host '          （日本語以外の言語版 Windows では ASCII のパスを指定してください）'
Write-Host ''
Write-Host '   アプリの表示言語は既定で日本語です。起動後に中国語へ切り替えられます。'
Write-Host ('=' * 62)
Write-Host ''
if (-not $Unattended) { Read-Host 'Enter キーで閉じます' | Out-Null }