param(
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$CliArgs
)

$ErrorActionPreference = 'Stop'
$KenseiRoot = if ($env:KENSEI_ROOT) { $env:KENSEI_ROOT } else { (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path }

function Show-KenseiBanner {
  param([switch]$Animate)
  if ($env:KENSEI_NO_ANIM -eq '1') {
    Write-Host $script:KenseiLogo
    return
  }
  $tte = Get-Command tte.exe -ErrorAction SilentlyContinue
  if ($Animate -and $tte) {
    $oldEncoding = [Console]::OutputEncoding
    try {
      [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
      $env:PYTHONIOENCODING = 'utf-8'
      $script:KenseiLogo | & $tte.Source print --print-speed 12 --final-gradient-stops eda000 --final-gradient-steps 1
    } catch {
      Write-Host $script:KenseiLogo -ForegroundColor Green
    } finally {
      [Console]::OutputEncoding = $oldEncoding
    }
  } else {
    Write-Host $script:KenseiLogo -ForegroundColor Green
  }
  Write-Host 'model kensei · terminal-native security operator' -ForegroundColor DarkGray
}

$script:KenseiLogo = @'
  K   K EEEEE N   N SSSSS EEEEE III
  K  K  E     NN  N S     E      I
  KKK   EEE   N N N SSSSS EEE    I
  K  K  E     N  NN     S E      I
  K   K EEEEE N   N SSSSS EEEEE III
                 RONIN // 07
'@

function Invoke-Kensei {
  param([string[]]$Arguments)
  Push-Location $KenseiRoot
  try {
    & uv run kensei @Arguments
    exit $LASTEXITCODE
  } finally {
    Pop-Location
  }
}

if (-not $CliArgs -or $CliArgs.Count -eq 0) {
  Show-KenseiBanner -Animate
  Invoke-Kensei @('chat', '--model', 'kensei', '--execute', '--allow-code-blocks')
}

switch ($CliArgs[0]) {
  '--help' { Invoke-Kensei @('--help') }
  '-h' { Invoke-Kensei @('--help') }
  '--version' { Invoke-Kensei @('--version') }
  '--no-anim' {
    $env:KENSEI_NO_ANIM = '1'
    Show-KenseiBanner
    Invoke-Kensei @('chat', '--model', 'kensei', '--execute', '--allow-code-blocks')
  }
  '--auto' {
    Show-KenseiBanner -Animate
    $prompt = if ($CliArgs.Count -gt 1) { $CliArgs[1..($CliArgs.Count - 1)] -join ' ' } else { Read-Host 'kensei(auto)' }
    if (-not $prompt) { Write-Error 'Prompt vacío.'; exit 2 }
    Invoke-Kensei @('auto', $prompt, '--model', 'kensei', '--allow-code-blocks')
  }
  '--root' {
    Write-Host 'La shell root de Kensei es Linux (Ronin/workOS). En Windows usá PowerShell como administrador.' -ForegroundColor Yellow
    exit 2
  }
  default {
    $prompt = $CliArgs -join ' '
    Invoke-Kensei @('ask', $prompt, '--model', 'kensei', '--allow-code-blocks')
  }
}
