# D:\port\rag_demo\app\app\scripts\smoke_rag.ps1
param(
  [string]$ApiBase = "http://localhost:9000",
  [string]$LLMBase = "http://localhost:8000",
  [string]$Query   = "기억 상실 주인공 서사",
  [int]$TopK       = 6,
  [float]$Temp     = 0.2,
  [int]$MaxTokens  = 512
)

$ProgressPreference = 'SilentlyContinue'

function W([string]$t, [string]$c="Cyan"){ Write-Host "`n== $t ==" -ForegroundColor $c }
function PJson($o, [int]$depth=10){ $o | ConvertTo-Json -Depth $depth }

function Try-GET($url){
  try {
    $r = Invoke-WebRequest -UseBasicParsing -Uri $url -Method GET -TimeoutSec 3
    return $true
  } catch { return $false }
}

function Try-POST($url, $obj){
  try {
    $json = $obj | ConvertTo-Json -Depth 20
    $r = Invoke-RestMethod -Method POST -Uri $url -ContentType "application/json" -Body $json -TimeoutSec 5
    return $true
  } catch { return $false }
}

function Wait-API([string]$base, [int]$timeoutSec=8){
  $deadline = (Get-Date).AddSeconds($timeoutSec)
  while ((Get-Date) -lt $deadline){
    if (Try-GET "$base/openapi.json") { return $true }
    if (Try-GET "$base/rag/healthz")   { return $true }  # 네 라우터에 있으면 여기서 끝
    if (Try-GET "$base/docs")          { return $true }
    if (Try-POST "$base/debug/retrieve" @{ q="ping"; k=1 }) { return $true }
    Start-Sleep -Milliseconds 400
  }
  return $false
}

function Get-Json($url){
  try { return Invoke-RestMethod -Method GET -Uri $url -TimeoutSec 8 }
  catch { Write-Host ("[GET ERROR] {0}" -f $_.Exception.Message) -ForegroundColor Yellow; return $null }
}
function Post-Json($url, $obj){
  $json = $obj | ConvertTo-Json -Depth 20
  try { return Invoke-RestMethod -Method POST -Uri $url -ContentType "application/json" -Body $json -TimeoutSec 20 }
  catch {
    Write-Host ("[POST ERROR] {0}" -f $_.Exception.Message) -ForegroundColor Yellow
    if ($_.Exception.Response -and $_.Exception.Response.GetResponseStream){
      $sr = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream()); $body = $sr.ReadToEnd()
      if ($body) { Write-Host ("[RESP] {0}" -f $body) -ForegroundColor DarkGray }
    }
    return $null
  }
}

# 0) API / LLM 체크
W "Check API alive: $ApiBase"
if (-not (Wait-API $ApiBase 8)) { Write-Host "API가 열려있지 않음. (/openapi.json, /rag/healthz, /docs, /debug/retrieve 모두 실패)" -ForegroundColor Red; exit 1 }
Write-Host "API OK" -ForegroundColor Green

W "Check LLM models: $LLMBase/models"
try { $models = Invoke-RestMethod -Method GET -Uri "$LLMBase/models" -TimeoutSec 5; PJson $models }
catch { Write-Host "LLM 모델 목록 조회 실패(로컬 LLM 미기동일 수 있음). 계속 진행." -ForegroundColor Yellow }

# 1) /debug/count
W "Chroma COUNT"
$c = Get-Json "$ApiBase/debug/count"; if ($c){ PJson $c }

# 2) /debug/retrieve
W "RETRIEVE"
$retr = Post-Json "$ApiBase/debug/retrieve" @{ q = $Query; k = $TopK; include_docs = $true }
if ($retr){ PJson $retr 8 }

# 3) /debug/rag-ask (가능하면)
W "RAG-ASK (debug)"
$rag = Post-Json "$ApiBase/debug/rag-ask" @{ q = $Query; k = $TopK; max_tokens = $MaxTokens; temperature = $Temp }
if ($rag){ PJson $rag 6 } else { Write-Host "rag-ask 호출 실패(엔드포인트 미존재/LLM 미기동일 수 있음). 스킵." -ForegroundColor Yellow }

# 4) /rag/query
W "/rag/query"
$qRes = Post-Json "$ApiBase/rag/query?top_k=$TopK" @{ question = $Query }
if ($qRes){ PJson $qRes 6 } else { Write-Host "rag/query 호출 실패. 스킵." -ForegroundColor Yellow }

# 5) /rag/query/debug
W "/rag/query/debug"
$qdRes = Post-Json "$ApiBase/rag/query/debug?top_k=$TopK" @{ question = $Query }
if ($qdRes){ PJson $qdRes 8 } else { Write-Host "rag/query/debug 호출 실패. 스킵." -ForegroundColor Yellow }

Write-Host "`nAll smoke steps attempted." -ForegroundColor Green
