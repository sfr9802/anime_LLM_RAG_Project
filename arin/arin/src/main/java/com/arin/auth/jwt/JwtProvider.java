package com.arin.auth.jwt;

import io.jsonwebtoken.*;
import io.jsonwebtoken.security.Keys;
import jakarta.annotation.PostConstruct;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.nio.charset.StandardCharsets;
import java.security.Key;
import java.util.*;

@Slf4j
@Component
public class JwtProvider {

    @Value("${jwt.secret}")                  private String secretRaw;            // Base64 권장
    @Value("${jwt.expiration}")              private long  expirationMs;          // access TTL(ms)
    @Value("${jwt.refresh-expiration}")      private long  refreshExpirationMs;   // refresh TTL(ms)

    // 추가: 엄격 검증용
    @Value("${jwt.issuer:arin}")             private String issuer;
    @Value("${jwt.audience:frontend}")       private String audience;
    @Value("${jwt.clock-skew-seconds:60}")   private long   clockSkewSeconds;
    @Value("${jwt.kid:hmac-1}")              private String kid;                  // 키 롤테이션 대비

    private Key key;
    private JwtParser parser;

    @PostConstruct
    public void init() {
        byte[] keyBytes = tryBase64(secretRaw);
        if (keyBytes == null) keyBytes = secretRaw.getBytes(StandardCharsets.UTF_8);
        if (keyBytes.length < 32) {
            throw new IllegalStateException("jwt.secret must be >= 256 bits (use a Base64-encoded 32B+ key)");
        }
        this.key = Keys.hmacShaKeyFor(keyBytes);

        this.parser = Jwts.parserBuilder()
                .setSigningKey(key)
                .requireIssuer(issuer)
                .requireAudience(audience)
                .setAllowedClockSkewSeconds(clockSkewSeconds)
                .build();

        log.info("[JWT] 키/파서 초기화 완료 (alg=HS256, kid={})", kid);
    }

    // ===== 발급 =====
    public String generateAccessToken(Long userId, String role) {
        return buildToken(userId, roleList(role), expirationMs, "acc", UUID.randomUUID().toString());
    }

    public String generateRefreshToken(Long userId, String role) {
        // refresh는 family 추적용 jti 필요. (TokenService에서 allow:{user}와 매칭)
        return buildToken(userId, roleList(role), refreshExpirationMs, "ref", UUID.randomUUID().toString());
    }

    public String buildToken(Long userId, Collection<String> roles, long ttlMillis, String typ, String jti) {
        List<String> normRoles = normalizeRoles(roles);
        List<String> authorities = toAuthorities(normRoles);

        long now = System.currentTimeMillis();
        Date iat = new Date(now), exp = new Date(now + ttlMillis);

        return Jwts.builder()
                .setHeaderParam("kid", kid)
                .setIssuer(issuer)
                .setAudience(audience)
                .setSubject(String.valueOf(userId))     // sub = userId
                .claim("userId", userId)
                .claim("roles", normRoles)              // 배열로 고정
                .claim("authorities", authorities)      // (스프링 ROLE_* 매핑용)
                .claim("typ", typ)                      // "acc"|"ref"
                .setId(jti)                             // 재사용 탐지/회전
                .setIssuedAt(iat)
                .setExpiration(exp)
                .signWith(key, SignatureAlgorithm.HS256)
                .compact();
    }

    // ===== 파싱/검증 =====
    public Claims getClaims(String token) {
        try {
            return parser.parseClaimsJws(token).getBody();
        } catch (JwtException e) {
            log.warn("[JWT] 파싱/검증 실패: {}", e.getMessage());
            throw e;
        }
    }

    public boolean validateToken(String token) {
        try {
            parser.parseClaimsJws(token);
            return true;
        } catch (JwtException | IllegalArgumentException e) {
            log.warn("[JWT] 유효하지 않은 토큰: {}", e.getMessage());
            return false;
        }
    }

    public long getRemainingValidity(String token) {
        try {
            Date exp = getClaims(token).getExpiration();
            return exp.getTime() - System.currentTimeMillis();
        } catch (Exception e) {
            log.error("[JWT] 남은 TTL 계산 실패: {}", e.getMessage());
            return -1;
        }
    }

    // ===== 편의 메서드 =====
    public Long getUserId(String token) {
        try {
            Claims c = getClaims(token);
            String sub = c.getSubject();
            if (sub != null) return Long.parseLong(sub);
            Object uid = c.get("userId");
            if (uid instanceof Integer i) return i.longValue();
            if (uid instanceof Long l)    return l;
            if (uid instanceof String s)  return Long.parseLong(s);
        } catch (Exception ignored) {}
        throw new IllegalArgumentException("Invalid userId in JWT");
    }

    /** 단일 role 대신 다중 roles를 사용하세요. */
    @Deprecated
    public String getRole(String token) {
        List<String> roles = getRoles(token);
        return roles.isEmpty() ? null : roles.get(0);
    }

    @SuppressWarnings("unchecked")
    public List<String> getRoles(String token) {
        Object v = getClaims(token).get("roles");
        if (v instanceof List<?> list) {
            List<String> out = new ArrayList<>(list.size());
            for (Object o : list) if (o != null) out.add(o.toString());
            return normalizeRoles(out);
        }
        return List.of();
    }

    public String getType(String token) {
        Object t = getClaims(token).get("typ");
        return (t == null) ? null : t.toString();
    }

    // ===== 내부 유틸 =====
    private static byte[] tryBase64(String s) {
        try { return Base64.getDecoder().decode(s); }
        catch (IllegalArgumentException e) { return null; }
    }

    private static List<String> roleList(String role) {
        return (role == null) ? List.of() : List.of(role);
    }

    private static List<String> normalizeRoles(Collection<String> roles) {
        List<String> out = new ArrayList<>();
        if (roles == null) return out;
        for (String r : roles) {
            if (r == null) continue;
            String v = r.trim();
            if (v.isEmpty()) continue;
            out.add(v.toUpperCase(Locale.ROOT));
        }
        return out;
    }

    private static List<String> toAuthorities(List<String> roles) {
        List<String> out = new ArrayList<>(roles.size());
        for (String r : roles) {
            out.add(r.startsWith("ROLE_") ? r : "ROLE_" + r);
        }
        return out;
    }
}
