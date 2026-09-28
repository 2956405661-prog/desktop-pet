# Select a tab inside a VS Code window by (fuzzy) name, using Windows UI Automation.
#   exit 0 = selected (prints the selected tab name)
#   exit 2 = no VS Code window found
#   exit 3 = window found but no tab matched
# NOTE: keep this file ASCII-only (PowerShell 5.1 reads .ps1 as ANSI unless it has a BOM).
param(
    [string]$Hint = "",
    [string]$Title = ""
)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$AE = [System.Windows.Automation.AutomationElement]

function Norm([string]$s) {
    if (-not $s) { return "" }
    $s = $s -replace ([char]0x2026), ""     # drop the ellipsis
    $s = $s -replace "\s+", " "
    return $s.Trim().ToLowerInvariant()
}

function CommonPrefix([string]$a, [string]$b) {
    $n = [Math]::Min($a.Length, $b.Length)
    $i = 0
    while ($i -lt $n -and $a[$i] -eq $b[$i]) { $i++ }
    return $i
}

$wins = $AE::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children,
                                 [System.Windows.Automation.Condition]::TrueCondition)
$target = $null
foreach ($w in $wins) {
    $n = $w.Current.Name
    if ($n -notlike "*Visual Studio Code*") { continue }
    if ($Hint -and $n -notlike "*$Hint*") { continue }
    $target = $w
    break
}
if (-not $target) {
    foreach ($w in $wins) {
        if ($w.Current.Name -like "*Visual Studio Code*") { $target = $w; break }
    }
}
if (-not $target) { exit 2 }

$cond = New-Object System.Windows.Automation.PropertyCondition(
    $AE::ControlTypeProperty, [System.Windows.Automation.ControlType]::TabItem)
$tabs = $target.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond)

$want = Norm $Title
$best = $null
$bestScore = 0
$short = $want
if ($short.Length -gt 8) { $short = $short.Substring(0, 8) }
foreach ($t in $tabs) {
    $name = Norm $t.Current.Name
    if ($name.Length -lt 3) { continue }
    $score = CommonPrefix $name $want
    if ($short.Length -ge 4 -and $name.StartsWith($short)) { $score += 4 }
    if ($score -gt $bestScore) { $bestScore = $score; $best = $t }
}

if (-not $best -or $bestScore -lt 6) { exit 3 }

$pattern = $null
if ($best.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern,
                               [ref]$pattern)) {
    $pattern.Select()
} else {
    $best.SetFocus()
}
Write-Output ("selected: " + $best.Current.Name + "  score=" + $bestScore)
exit 0
