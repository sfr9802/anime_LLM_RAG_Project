package com.arin.auth.service;

import com.arin.auth.dto.TokenResponseDto;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import io.jsonwebtoken.security.WeakKeyException;
import jakarta.annotation.PostConstruct;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Service;

import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.util.Base64;
import java.util.Collections;
import java.util.Date;
import java.util.Optional;
import java.util.concurrent.TimeUnit;
import org.springframework.http.ResponseCookie;
import java.time.Duration;
import java.util.Optional;
import java.util.Set;
import java.util.concurrent.TimeUnit;

@Slf4j
@Service
@RequiredArgsConstructor
public class TokenService {

    private final StringRedisTemplate redisTemplate;
    private final ObjectMapper objectMapper; // ✅ JSON 직렬화

    private static final String BLACKLIST_PREFIX = "blacklist:";
    private static final String REFRESH_PREFIX   = "refresh:";
    private static final String OTC_PREFIX       = "otc:";      // ✅ 1회용 코드
    private static final SecureRandom RNG        = new SecureRandom();
    private static final String REFRESH_SESS_PREFIX = "refreshsess:"; // refreshsess:{uid}:{jti}

    // Lua 스크립트로 GET+DEL 원자 실행 (버전 의존성 회피)
    private static final DefaultRedisScript<String> GETDEL_SCRIPT =
            new DefaultRedisScript<>("local v=redis.call('GET', KEYS[1]); if v then redis.call('DEL', KEYS[1]); end; return v", String.class);

    @Value("${jwt.secret}")
    private String jwtSecret;

    private SecretKey key;

    @PostConstruct
    public void init() {
        byte[] keyBytes = jwtSecret.getBytes(StandardCharsets.UTF_8);
        if (keyBytes.length < 32) {
            throw new WeakKeyException("JWT secret key must be at least 256 bits (32 bytes). 현재 길이: " + keyBytes.length);
        }
        this.key = Keys.hmacShaKeyFor(keyBytes);
        log.info("[JWT-TOKEN] SecretKey 초기화 완료");
    }

    // ===== 블랙리스트 =====

    public void blacklistToken(String token) {
        long ttl = getRemainingTime(token);
        if (ttl <= 0) {
            log.warn("[JWT-BLACKLIST] 만료/무효 토큰은 등록 생략");
            return;
        }
        String key = BLACKLIST_PREFIX + sha256(token);
        redisTemplate.opsForValue().set(key, "1", ttl, TimeUnit.MILLISECONDS);
        log.info("[JWT-BLACKLIST] 블랙리스트 등록 (TTL={}ms)", ttl);
    }

    public boolean isBlacklisted(String token) {
        return Boolean.TRUE.equals(redisTemplate.hasKey(BLACKLIST_PREFIX + sha256(token)));
    }

    private long getRemainingTime(String token) {
        try {
            Claims claims = Jwts.parserBuilder()
                    .setSigningKey(key)
                    .build()
                    .parseClaimsJws(token)
                    .getBody();
            return claims.getExpiration().getTime() - System.currentTimeMillis();
        } catch (Exception e) {
            log.error("[JWT-BLACKLIST] 토큰 만료 시간 추출 실패: {}", e.getMessage());
            return -1;
        }
    }

    // ===== Refresh =====

//    public void storeRefreshToken(Long userId, String refreshToken, long ttlMillis) {
//        String key = REFRESH_PREFIX + userId;
//        redisTemplate.opsForValue().set(key, refreshToken, ttlMillis, TimeUnit.MILLISECONDS);
//        log.info("[JWT-REFRESH] 저장 | key={}, TTL={}ms", key, ttlMillis);
//    }

    public String getRefreshToken(Long userId) {
        return redisTemplate.opsForValue().get(REFRESH_PREFIX + userId);
    }

    public void deleteRefreshToken(Long userId) {
        redisTemplate.delete(REFRESH_PREFIX + userId);
        log.info("[JWT-REFRESH] 삭제 | key={}", REFRESH_PREFIX + userId);
    }

    // ===== One-Time Code (교환 플로우) =====

    /** 1회용 코드 발급 (기본 60초) */
    public String issueOneTimeCode(Long userId, String accessToken, String refreshToken, int ttlSeconds) {
        if (ttlSeconds <= 0) ttlSeconds = 60;

        TokenResponseDto dto = new TokenResponseDto(accessToken, refreshToken);
        String json;
        try {
            json = objectMapper.writeValueAsString(dto);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("토큰 직렬화 실패", e);
        }

        // 충돌 방지를 위해 SETNX로 할당. 드물게 충돌나면 재시도.
        for (int i = 0; i < 5; i++) {
            String code = generateCode();
            String key = OTC_PREFIX + code;
            Boolean ok = redisTemplate.opsForValue().setIfAbsent(key, json, ttlSeconds, TimeUnit.SECONDS);
            if (Boolean.TRUE.equals(ok)) {
                log.info("[OTC] 코드 발급 userId={}, TTL={}s", userId, ttlSeconds);
                return code;
            }
        }
        throw new IllegalStateException("1회용 코드 발급 실패(충돌 과다)");
    }

    /** 1회용 코드 소비(원자적 get+del). 성공 시 즉시 삭제됨. */
    public Optional<TokenResponseDto> consumeOneTimeCode(String code) {
        if (code == null || code.isBlank()) return Optional.empty();
        String key = OTC_PREFIX + code;

        String json = redisTemplate.execute(GETDEL_SCRIPT, Collections.singletonList(key));
        if (json == null) {
            return Optional.empty(); // 만료/이미 사용됨
        }
        try {
            return Optional.of(objectMapper.readValue(json, TokenResponseDto.class));
        } catch (Exception e) {
            log.error("[OTC] 역직렬화 실패", e);
            return Optional.empty();
        }
    }

    // ===== helpers =====

    private static String generateCode() {
        // URL-safe, padding 없는 32바이트 랜덤 → 약 43자
        byte[] buf = new byte[32];
        RNG.nextBytes(buf);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(buf);
    }

    private static String sha256(String s) {
        try {
            var md = java.security.MessageDigest.getInstance("SHA-256");
            byte[] dig = md.digest(s.getBytes(StandardCharsets.UTF_8));
            StringBuilder hex = new StringBuilder(dig.length * 2);
            for (byte b : dig) hex.append(String.format("%02x", b));
            return hex.toString();
        } catch (Exception e) { throw new RuntimeException(e); }
    }
    // 쿠키 빌더
    public ResponseCookie buildRefreshCookie(String refreshToken, long ttlMillis) {
        return ResponseCookie.from("refresh_token", refreshToken)
                .httpOnly(true)
                .secure(true)
                .sameSite("Lax")
                .path("/")
                .maxAge(Duration.ofMillis(ttlMillis))
                .build();
    }
    // 세션 저장
    public void saveRefreshSession(Long userId, String jti, HttpServletRequest req, long ttlMillis) {
        String ua = Optional.ofNullable(req.getHeader("User-Agent")).orElse("-");
        String uaHash = sha256(ua);
        String ip = Optional.ofNullable(req.getRemoteAddr()).orElse("0.0.0.0");
        String ipPrefix = ip.substring(0, Math.min(7, ip.length())); // 대충 /24 비슷

        String key = REFRESH_SESS_PREFIX + userId + ":" + jti;
        String val = uaHash + "|" + ipPrefix;
        redisTemplate.opsForValue().set(key, val, ttlMillis, TimeUnit.MILLISECONDS);
    }
    // 세션 소모
    public boolean consumeRefreshSession(Long userId, String jti, HttpServletRequest req) {
        String key = REFRESH_SESS_PREFIX + userId + ":" + jti;
        String val = redisTemplate.opsForValue().get(key);
        if (val == null) return false; // 재사용 감지(이미 쓰였거나 존재X)

        String uaHashNow = sha256(Optional.ofNullable(req.getHeader("User-Agent")).orElse("-"));
        String[] parts = val.split("\\|", 2);
        boolean uaOk = parts.length > 0 && parts[0].equals(uaHashNow);

        redisTemplate.delete(key); // 사용 즉시 폐기(회전)
        return uaOk; // UA mismatch면 사실상 탈취 의심
    }
    // 사용자 전체 세션 폐기 (재사용 감지 시 호출)
    public void revokeAllRefreshSessions(Long userId) {
        Set<String> keys = redisTemplate.keys(REFRESH_SESS_PREFIX + userId + ":*");
        if (!keys.isEmpty()) {
            redisTemplate.delete(keys);
        }
    }



}
