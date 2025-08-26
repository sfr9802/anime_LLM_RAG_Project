param(
  [string]$Script    = "D:\port\craw\build_from_character_pages_refactored_clean.py",
  [string]$InPath    = "D:\port\craw\crawled.jsonl",          # ← 기존 -Input 금지
  [string]$OutPath   = "D:\port\craw\out_with_chars.jsonl",   # ← 기존 -Output도 무난히 유지 가능하지만 통일
  [int]$SumBullets   = 5,
  [int]$SumMaxChars  = 6000,
  [switch]$TopSummary = $true,
  [switch]$Debug      = $true
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# LLM 환경
$env:LOCAL_LLM_BASE_URL = "http://127.0.0.1:8000/v1"
$env:LOCAL_LLM_API_KEY  = "sk-local"
$env:LOCAL_LLM_MODEL    = "gemma-2-9b-it"
$env:LOCAL_LLM_TIMEOUT  = "60"

# 경로 검사
if (-not (Test-Path $Script)) { throw "스크립트 없음: $Script" }
if (-not (Test-Path $InPath)) { throw "입력 JSONL 없음: $InPath" }
$null = New-Item -ItemType Directory -Force -Path (Split-Path $OutPath) 2>$null

# 인자 구성
$argsList = @(
  "-i", $InPath,
  "-o", $OutPath,
  "--summarize",
  "--sum-bullets", $SumBullets,
  "--sum-max-chars", $SumMaxChars
)
if ($TopSummary) { $argsList += "--top-summary" }
if ($Debug)      { $argsList += "--debug" }

Write-Host "python $Script $($argsList -join ' ')" -ForegroundColor Cyan
python $Script @argsList
