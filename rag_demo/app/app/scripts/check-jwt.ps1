param(
  [string]$Token  = $env:TOKEN,         # 액세스 토큰 (미지정 시 환경변수 TOKEN)
  [string]$Secret = $env:JWT_SECRET,    # 비밀키 문자열 (미지정 시 환경변수 JWT_SECRET)
  [bool]  $Base64 = $false,             # 비밀키가 Base64인지 여부 (JWT_SECRET_B64=true 와 동일)
  [string]$Aud    = $env:JWT_AUD,       # audience (예: frontend)
  [string]$Iss    = $env:JWT_ISS        # issuer   (예: arin)
)

if (-not $Token)  { Write-Error "Token not provided. -Token 또는 env:TOKEN 을 설정하세요."; exit 1 }
if (-not $Secret) { Write-Error "Secret not provided. -Secret 또는 env:JWT_SECRET 을 설정하세요."; exit 1 }

# 임시 파이썬 파일 생성
$py = @'
import os, sys, base64, hashlib, json, jwt

token = sys.argv[1]
secret_raw = sys.argv[2]
use_b64 = (sys.argv[3] == "1")
aud = sys.argv[4] or None
iss = sys.argv[5] or None

# .env에서 따옴표가 포함됐을 수 있어 제거
s = secret_raw.strip()
if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
    s = s[1:-1]

# 비밀키 바이트 만들기
if use_b64:
    try:
        key = base64.b64decode(s, validate=True)
    except Exception as e:
        print(f"[ERR] Base64 decode failed: {e}")
        sys.exit(2)
else:
    key = s.encode("utf-8")

print(f"key.len={len(key)} key.fp={hashlib.sha256(key).hexdigest()[:16]}")

# 헤더 확인(검증 없음)
try:
    hdr = jwt.get_unverified_header(token)
    print("header:", json.dumps(hdr, ensure_ascii=False))
except Exception as e:
    print(f"[ERR] invalid header: {e}")

# 본 검증
try:
    opts = {"require": ["exp"], "verify_exp": True, "verify_aud": bool(aud)}
    claims = jwt.decode(
        token, key,
        algorithms=["HS256"],
        audience=aud if aud else None,
        issuer=iss if iss else None,
        options=opts,
    )
    print("claims:", json.dumps(claims, ensure_ascii=False))
    sys.exit(0)
except Exception as e:
    print(f"[ERR] verify failed: {e}")
    sys.exit(1)
'@

$tmp = [System.IO.Path]::GetTempFileName().Replace(".tmp",".py")
[System.IO.File]::WriteAllText($tmp, $py, [System.Text.Encoding]::UTF8)
$argB64 = if ($Base64) { "1" } else { "0" }

# 파이썬 실행
& python $tmp $Token $Secret $argB64 $Aud $Iss
$code = $LASTEXITCODE
Remove-Item $tmp -Force
exit $code
