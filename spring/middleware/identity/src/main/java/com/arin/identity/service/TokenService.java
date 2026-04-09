package com.arin.identity.service;

import com.arin.identity.config.RefreshCookieProps;
import com.arin.identity.dto.OtcPayload;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.Jwts;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.http.ResponseCookie;
import org.springframework.stereotype.Service;

import javax.crypto.SecretKey;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.TimeUnit;

@Slf4j
@Service
@RequiredArgsConstructor
public class TokenService {

    private final StringRedisTemplate redisTemplate;
    private final ObjectMapper objectMapper;
    private final RefreshCookieProps refreshCookieProps;
    private final SecretKey jwtHmacKey;

    private static final String BLACKLIST_PREFIX     = "blacklist:";
    private static final String REFRESH_PREFIX       = "refresh:";
    private static final String OTC_PREFIX           = "otc:";
    private static final String REFRESH_SESS_PREFIX  = "refreshsess:";
    private static final java.security.SecureRandom RNG = new java.security.SecureRandom();

    private static final DefaultRedisScript<String> GETDEL_SCRIPT =
            new DefaultRedisScript<>("local v=redis.call('GET', KEYS[1]); if v then redis.call('DEL', KEYS[1]); end; return v", String.class);

    public void blacklistToken(String token) {
        long ttl = getRemainingTime(token);
        if (ttl <= 0) { log.warn("[JWT-BLACKLIST] 만료/무효 토큰은 등록 생략"); return; }
        String key = BLACKLIST_PREFIX + sha256(token);
        redisTemplate.opsForValue().set(key, "1", ttl, TimeUnit.MILLISECONDS);
        log.info("[JWT-BLACKLIST] 블랙리스트 등록 (TTL={}ms)", ttl);
    }

    public boolean isBlacklisted(String token) {
        return redisTemplate.hasKey(BLACKLIST_PREFIX + sha256(token));
    }

    private long getRemainingTime(String token) {
        try {
            Claims claims = Jwts.parserBuilder().setSigningKey(jwtHmacKey).build().parseClaimsJws(token).getBody();
            return claims.getExpiration().getTime() - System.currentTimeMillis();
        } catch (Exception e) { log.error("[JWT-BLACKLIST] 토큰 만료 시간 추출 실패: {}", e.getMessage()); return -1; }
    }

    public String getRefreshToken(Long userId) { return redisTemplate.opsForValue().get(REFRESH_PREFIX + userId); }
    public void deleteRefreshToken(Long userId) { redisTemplate.delete(REFRESH_PREFIX + userId); log.info("[JWT-REFRESH] 삭제 | key={}", REFRESH_PREFIX + userId); }

    public String issueOneTimeCode(Long userId, String accessToken, String refreshToken, int ttlSeconds) {
        int ttl = (ttlSeconds > 0) ? ttlSeconds : 60;
        try {
            Claims c = Jwts.parserBuilder().setSigningKey(jwtHmacKey).build().parseClaimsJws(refreshToken).getBody();
            long refreshTtlMs = c.getExpiration().getTime() - System.currentTimeMillis();
            if (refreshTtlMs > 0) ttl = (int) Math.min(ttl, Math.max(1, refreshTtlMs / 1000));
        } catch (Exception e) { log.warn("[OTC] refresh TTL 파싱 실패: {}", e.getMessage()); ttl = Math.min(ttl, 60); }
        String json;
        try { json = objectMapper.writeValueAsString(new OtcPayload(accessToken, refreshToken)); }
        catch (JsonProcessingException e) { throw new IllegalStateException("OTC 직렬화 실패", e); }
        for (int i = 0; i < 5; i++) {
            String code = generateCode();
            String k = OTC_PREFIX + code;
            Boolean ok = redisTemplate.opsForValue().setIfAbsent(k, json, ttl, TimeUnit.SECONDS);
            if (Boolean.TRUE.equals(ok)) { log.info("[OTC] 코드 발급 uid={}, TTL={}s", userId, ttl); return code; }
        }
        throw new IllegalStateException("1회용 코드 발급 실패(충돌 과다)");
    }

    public Optional<OtcPayload> consumeOneTimeCode(String code) {
        if (code == null || code.isBlank()) return Optional.empty();
        String k = OTC_PREFIX + code.trim();
        String json = redisTemplate.execute(GETDEL_SCRIPT, Collections.singletonList(k));
        if (json == null || json.isBlank()) { log.warn("[OTC] code not found or already consumed: {}", k); return Optional.empty(); }
        try { return Optional.of(objectMapper.readValue(json, OtcPayload.class)); }
        catch (Exception e) { log.error("[OTC] deserialize failed for key={} payload='{}'", k, json, e); return Optional.empty(); }
    }

    public void saveRefreshSession(Long userId, String jti, HttpServletRequest req, long ttlMillis) {
        String ua = Optional.ofNullable(req.getHeader("User-Agent")).orElse("-");
        String uaHash = sha256(ua);
        String ip = Optional.ofNullable(req.getRemoteAddr()).orElse("0.0.0.0");
        String ipPrefix = ip.substring(0, Math.min(7, ip.length()));
        String key = REFRESH_SESS_PREFIX + userId + ":" + jti;
        String val = uaHash + "|" + ipPrefix;
        redisTemplate.opsForValue().set(key, val, ttlMillis, TimeUnit.MILLISECONDS);
    }

    public boolean consumeRefreshSession(Long userId, String jti, HttpServletRequest req) {
        String key = REFRESH_SESS_PREFIX + userId + ":" + jti;
        String val = redisTemplate.opsForValue().get(key);
        if (val == null) return false;
        String uaHashNow = sha256(Optional.ofNullable(req.getHeader("User-Agent")).orElse("-"));
        String[] parts = val.split("\\|", 2);
        boolean uaOk = parts.length > 0 && parts[0].equals(uaHashNow);
        redisTemplate.delete(key);
        return uaOk;
    }

    public void revokeRefreshSession(Long userId, String jti) { redisTemplate.delete(REFRESH_SESS_PREFIX + userId + ":" + jti); }

    public void revokeAllRefreshSessions(Long userId) {
        Set<String> keys = redisTemplate.keys(REFRESH_SESS_PREFIX + userId + ":*");
        if (keys != null && !keys.isEmpty()) redisTemplate.delete(keys);
    }

    public ResponseCookie buildRefreshCookie(String refreshToken, long ttlMillis) {
        ResponseCookie.ResponseCookieBuilder b = ResponseCookie.from(refreshCookieProps.getName(), refreshToken)
                .httpOnly(true).secure(refreshCookieProps.isSecure()).sameSite(refreshCookieProps.getSameSite())
                .path(refreshCookieProps.getPath()).maxAge(Duration.ofMillis(Math.max(0, ttlMillis)));
        if (refreshCookieProps.getDomain() != null && !refreshCookieProps.getDomain().isBlank()) b.domain(refreshCookieProps.getDomain());
        return b.build();
    }

    public ResponseCookie buildDeleteRefreshCookie() {
        ResponseCookie.ResponseCookieBuilder b = ResponseCookie.from(refreshCookieProps.getName(), "")
                .httpOnly(true).secure(refreshCookieProps.isSecure()).sameSite(refreshCookieProps.getSameSite())
                .path(refreshCookieProps.getPath()).maxAge(Duration.ZERO);
        if (refreshCookieProps.getDomain() != null && !refreshCookieProps.getDomain().isBlank()) b.domain(refreshCookieProps.getDomain());
        return b.build();
    }

    public boolean isRefreshCookieSecure() { return refreshCookieProps.isSecure(); }
    public String getRefreshCookieSameSite() { return refreshCookieProps.getSameSite(); }
    public String getRefreshCookiePath() { return refreshCookieProps.getPath(); }
    public String getRefreshCookieName() { return refreshCookieProps.getName(); }

    private static String generateCode() {
        byte[] buf = new byte[32]; RNG.nextBytes(buf);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(buf);
    }

    private static String sha256(String s) {
        try {
            var md = java.security.MessageDigest.getInstance("SHA-256");
            byte[] dig = md.digest(s.getBytes(java.nio.charset.StandardCharsets.UTF_8));
            StringBuilder hex = new StringBuilder(dig.length * 2);
            for (byte b : dig) hex.append(String.format("%02x", b));
            return hex.toString();
        } catch (Exception e) { throw new RuntimeException(e); }
    }
}
