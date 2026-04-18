param(
    [string]$InputPath = "",
    [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$paperDir = Join-Path $projectRoot "docs\papers"

if ([string]::IsNullOrWhiteSpace($InputPath)) {
    $InputPath = Join-Path $paperDir "paper_source.md"
}

if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $paperDir "fengru_paper_draft.docx"
}

function Invoke-OfficeCli {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Args
    )

    & officecli @Args
    if ($LASTEXITCODE -ne 0) {
        throw "officecli command failed: officecli $($Args -join ' ')"
    }
}

if (-not (Test-Path $InputPath)) {
    throw "Input file not found: $InputPath"
}

$headerFile = Join-Path $paperDir "paper_header.txt"
if (-not (Test-Path $headerFile)) {
    throw "Header text file not found: $headerFile"
}

if (Test-Path $OutputPath) {
    Remove-Item $OutputPath -Force
}

$headerText = (Get-Content -Path $headerFile -Encoding UTF8 | Select-Object -First 1).Trim()

Invoke-OfficeCli @("create", $OutputPath)
Invoke-OfficeCli @("open", $OutputPath)

# Document/page setup (A4 + competition margins)
Invoke-OfficeCli @("set", $OutputPath, "/", "--prop", "defaultFont=SimSun")
Invoke-OfficeCli @("set", $OutputPath, "/section[1]", "--prop", "pageWidth=21cm", "--prop", "pageHeight=29.7cm")
Invoke-OfficeCli @("set", $OutputPath, "/section[1]", "--prop", "marginTop=1420", "--prop", "marginBottom=1420", "--prop", "marginLeft=1700", "--prop", "marginRight=1130")

# Style tuning
Invoke-OfficeCli @("set", $OutputPath, "/styles/Normal", "--prop", "font=SimSun", "--prop", "size=12", "--prop", "alignment=justify", "--prop", "lineSpacing=1.5x")
Invoke-OfficeCli @("set", $OutputPath, "/styles/Heading1", "--prop", "font=SimHei", "--prop", "size=16", "--prop", "bold=true", "--prop", "alignment=center", "--prop", "spaceBefore=240", "--prop", "spaceAfter=240", "--prop", "lineSpacing=1x")
Invoke-OfficeCli @("set", $OutputPath, "/styles/Heading2", "--prop", "font=SimHei", "--prop", "size=14", "--prop", "bold=true", "--prop", "alignment=left", "--prop", "spaceBefore=180", "--prop", "spaceAfter=120", "--prop", "lineSpacing=1x")
Invoke-OfficeCli @("set", $OutputPath, "/styles/Heading3", "--prop", "font=SimHei", "--prop", "size=12", "--prop", "bold=true", "--prop", "alignment=left", "--prop", "spaceBefore=120", "--prop", "spaceAfter=80", "--prop", "lineSpacing=1x")

# Header / footer (first page blank for cover)
Invoke-OfficeCli @("add", $OutputPath, "/", "--type", "header", "--prop", "type=first", "--prop", "text=")
Invoke-OfficeCli @("add", $OutputPath, "/", "--type", "header", "--prop", "type=default", "--prop", "text=$headerText", "--prop", "alignment=center", "--prop", "font=SimSun", "--prop", "size=9")
Invoke-OfficeCli @("add", $OutputPath, "/", "--type", "footer", "--prop", "type=first", "--prop", "text=")
Invoke-OfficeCli @("add", $OutputPath, "/", "--type", "footer", "--prop", "type=default", "--prop", "text=[PAGE]", "--prop", "alignment=center", "--prop", "font=Times New Roman", "--prop", "size=10")

$lines = Get-Content -Path $InputPath -Encoding UTF8

foreach ($raw in $lines) {
    $line = $raw.Trim()
    if ([string]::IsNullOrWhiteSpace($line)) {
        continue
    }

    if ($line -eq "[PAGEBREAK]") {
        Invoke-OfficeCli @("add", $OutputPath, "/body", "--type", "break", "--prop", "type=page")
        continue
    }

    if ($line -eq "[TOC]") {
        Invoke-OfficeCli @("add", $OutputPath, "/body", "--type", "toc", "--prop", "levels=1-3", "--prop", "hyperlinks=true", "--prop", "pageNumbers=true")
        continue
    }

    $style = "Normal"
    $alignment = "justify"
    $firstIndent = "480"
    $spaceAfter = "0"
    $text = $line

    if ($line.StartsWith("# ")) {
        $style = "Heading1"
        $alignment = "center"
        $firstIndent = "0"
        $spaceAfter = "120"
        $text = $line.Substring(2).Trim()
    }
    elseif ($line.StartsWith("## ")) {
        $style = "Heading2"
        $alignment = "left"
        $firstIndent = "0"
        $spaceAfter = "80"
        $text = $line.Substring(3).Trim()
    }
    elseif ($line.StartsWith("### ")) {
        $style = "Heading3"
        $alignment = "left"
        $firstIndent = "0"
        $spaceAfter = "60"
        $text = $line.Substring(4).Trim()
    }
    elseif ($line.StartsWith("[NOINDENT]")) {
        $style = "Normal"
        $alignment = "left"
        $firstIndent = "0"
        $spaceAfter = "0"
        $text = $line.Substring(10).Trim()
    }

    $safeText = $text.Replace('"', "'")
    Invoke-OfficeCli @(
        "add", $OutputPath, "/body", "--type", "paragraph",
        "--prop", "text=$safeText",
        "--prop", "style=$style",
        "--prop", "alignment=$alignment",
        "--prop", "firstLineIndent=$firstIndent",
        "--prop", "lineSpacing=1.5x",
        "--prop", "spaceAfter=$spaceAfter"
    )
}

Invoke-OfficeCli @("close", $OutputPath)

Write-Host "Done: $OutputPath"
