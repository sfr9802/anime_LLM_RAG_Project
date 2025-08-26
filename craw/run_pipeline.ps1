<#  
  One-shot 파이프라인 실행 스크립트 (Windows PowerShell)

  기능:
    1) (옵션) Mongo pages -> JSONL export
    2) pipeline_chroma_hf.py 실행
       - 스키마 정리 / '요약' 선별 재생성 / 본문 청킹
       - Chroma 업서트 (옵션)
    3) (옵션) 청크를 Mongo chunks 컬렉션에 upsert

  필요 패키지:
    pip install chromadb sentence-transformers pymongo requests python-dotenv

  참고:
    - pipeline_chroma_hf.py 파일이 현재 디렉토리에 있다고 가정함.
      (없으면 이 스크립트 하단의 "파일 체크" 섹션을 수정해 자동 생성하도록 해도 됨)
#>

param(
  # 입력 소스 (둘 중 하나)
  [string] $InputJsonl = ".\out_with_chars.jsonl",     # JSONL이 이미 있으면 이걸 사용
  [switch] $FromMongo,                                  # JSONL 대신 Mongo에서 export할지

  # Mongo 설정 (env 우선, 없으면 기본값)
  [string] $MongoUri       = $(if ($env:MONGO_URI)       { $env:MONGO_URI }       else { "mongodb://raguser:ragpass@localhost:27017/clean_namu_crawl?authSource=clean_namu_crawl" }),
  [string] $MongoDb        = $(if ($env:MONGO_DB)        { $env:MONGO_DB }        else { "clean_namu_crawl" }),
  [string] $MongoRawCol    = $(if ($env:MONGO_RAW_COL)   { $env:MONGO_RAW_COL }   else { "pages" }),
  [string] $MongoChunkCol  = $(if ($env:MONGO_CHUNK_COL) { $env:MONGO_CHUNK_COL } else { "chunks" }),

  # LLM (로컬 OpenAI 호환)
  [string] $LlmBase   = $(if ($env:LLM_BASE_URL) { $env:LLM_BASE_URL } else { "http://localhost:8000/v1" }),
  [string] $LlmModel  = $(if ($env:LLM_MODEL)    { $env:LLM_MODEL }    else { "gemma-2-9b-it" }),

  # Chroma / 임베딩
  [switch] $DoChroma,
  [string] $ChromaPath       = $(if ($env:CHROMA_PATH)       { $env:CHROMA_PATH }       else { "./data/chroma" }),
  [string] $ChromaCollection = $(if ($env:CHROMA_COLLECTION) { $env:CHROMA_COLLECTION } else { "namu-anime" }),
  [string] $EmbedModel       = $(if ($env:EMBED_MODEL)       { $env:EMBED_MODEL }       else { "BAAI/bge-m3" }),
  [int]    $EmbedBatch       = $(if ($env:EMBED_BATCH)       { [int]$env:EMBED_BATCH }  else { 32 }),

  # 파이프라인 동작 옵션
  [string] $OutDir        = ".\out_v2",
  [switch] $SkipResum,                                  # 요약 재생성 스킵
  [int]    $ChunkMin      = 750,
  [int]    $ChunkMax      = 900,
  [int]    $ChunkOverlap  = 120,

  # 결과 청크 Mongo upsert 여부
  [switch] $WriteMongoChunks
)

# ---------- 유틸 ----------
function Write-Info($msg)  { Write-Host "[INFO]  $msg" -ForegroundColor Cyan }
function Write-Warn($msg)  { Write-Host "[WARN]  $msg" -ForegroundColor Yellow }
function Write-Err($msg)   { Write-Host "[ERROR] $msg" -ForegroundColor Red }

# ---------- 파일 체크 ----------
$PipelinePy = Join-Path (Get-Location) "pipeline_chroma_hf.py"
if (-not (Test-Path $PipelinePy)) {
  Write-Err "pipeline_chroma_hf.py 파일이 현재 폴더에 없음. (이전에 제공한 파이썬 스크립트를 저장해두세요)"
  exit 1
}

# ---------- 출력 디렉토리 준비 ----------
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

# ---------- (옵션) Mongo -> JSONL export ----------
if ($FromMongo) {
  $ExportPath = Join-Path $OutDir "mongo_pages_export.jsonl"
  Write-Info "Mongo pages를 JSONL로 export: $ExportPath"

  $exportPy = @"
import os, json, sys
from pymongo import MongoClient

MONGO_URI = os.environ.get("MONGO_URI")
MONGO_DB  = os.environ.get("MONGO_DB")
MONGO_COL = os.environ.get("MONGO_RAW_COL")
OUT       = os.environ.get("EXPORT_PATH")

cli = MongoClient(MONGO_URI)
cur = cli[MONGO_DB][MONGO_COL].find({})
with open(OUT, "w", encoding="utf-8") as f:
    for doc in cur:
        doc.pop("_id", None)
        f.write(json.dumps(doc, ensure_ascii=False) + "\n")
"@

  $env:MONGO_URI     = $MongoUri
  $env:MONGO_DB      = $MongoDb
  $env:MONGO_RAW_COL = $MongoRawCol
  $env:EXPORT_PATH   = $ExportPath

  $tmpExport = Join-Path $OutDir "__export_mongo_tmp.py"
  $exportPy | Out-File -FilePath $tmpExport -Encoding utf8 -Force
  python $tmpExport
  if ($LASTEXITCODE -ne 0) { Write-Err "Mongo export 실패"; exit 1 }

  $InputJsonl = $ExportPath
}

if (-not (Test-Path $InputJsonl)) {
  Write-Err "입력 JSONL이 존재하지 않음: $InputJsonl"
  exit 1
}

# ---------- 파이프라인 실행 ----------
Write-Info "pipeline 실행 시작"
$argsList = @(
  "-i", $InputJsonl,
  "-o", $OutDir,
  "--chunk-min", $ChunkMin, "--chunk-max", $ChunkMax, "--chunk-overlap", $ChunkOverlap,
  "--llm-base", $LlmBase, "--llm-model", $LlmModel,
  "--chroma-dir", $ChromaPath, "--chroma-collection", $ChromaCollection,
  "--embed-model", $EmbedModel
)

if ($DoChroma)   { $argsList += "--do-chroma" }
if ($SkipResum)  { $argsList += "--skip-resum" }

python $PipelinePy @argsList
if ($LASTEXITCODE -ne 0) { Write-Err "pipeline 실행 실패"; exit 1 }

$SectionsFinal = Join-Path $OutDir "hf_sections_final.jsonl"
$ChunksJsonl   = Join-Path $OutDir "hf_chunks.jsonl"

Write-Info "산출물:
  sections: $SectionsFinal
  chunks  : $ChunksJsonl
"

# ---------- (옵션) 청크 Mongo upsert ----------
if ($WriteMongoChunks) {
  if (-not (Test-Path $ChunksJsonl)) {
    Write-Warn "청크 파일이 없음: $ChunksJsonl"
  } else {
    Write-Info "Mongo [$MongoDb.$MongoChunkCol] 에 청크 upsert"

    $upsertPy = @"
import os, json
from pymongo import MongoClient, UpdateOne

MONGO_URI  = os.environ.get("MONGO_URI")
MONGO_DB   = os.environ.get("MONGO_DB")
MONGO_COL  = os.environ.get("MONGO_CHUNK_COL")
CHUNKS     = os.environ.get("CHUNKS_PATH")

cli = MongoClient(MONGO_URI)
col = cli[MONGO_DB][MONGO_COL]

ops = []
with open(CHUNKS, "r", encoding="utf-8") as f:
    for line in f:
        if not line.strip(): continue
        o = json.loads(line)
        uid = o.get("uid") or f"{o['doc_id']}#b{o.get('chunk_index',0):04d}"
        o["_id"] = uid
        ops.append(UpdateOne({"_id": uid}, {"$set": o}, upsert=True))
        if len(ops) >= 1000:
            col.bulk_write(ops, ordered=False); ops.clear()
if ops:
    col.bulk_write(ops, ordered=False)
print("mongo upsert done")
"@

    $env:MONGO_URI        = $MongoUri
    $env:MONGO_DB         = $MongoDb
    $env:MONGO_CHUNK_COL  = $MongoChunkCol
    $env:CHUNKS_PATH      = $ChunksJsonl

    $tmpUpsert = Join-Path $OutDir "__upsert_chunks_tmp.py"
    $upsertPy | Out-File -FilePath $tmpUpsert -Encoding utf8 -Force
    python $tmpUpsert
    if ($LASTEXITCODE -ne 0) { Write-Err "Mongo chunks upsert 실패"; exit 1 }
  }
}

Write-Info "모든 작업 완료."
