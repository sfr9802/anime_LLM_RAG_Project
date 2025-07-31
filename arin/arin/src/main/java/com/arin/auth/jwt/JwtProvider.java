package com.arin.auth.jwt;

import io.jsonwebtoken.*;
import io.jsonwebtoken.security.Keys;
import jakarta.annotation.PostConstruct;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.nio.charset.StandardCharsets;
import java.security.Key;
import java.util.Date;

@Slf4j
@Component
public class JwtProvider {

    @Value("${jwt.secret}")
    private String secretRaw;

    @Value("${jwt.expiration}") // Access Token 유효기간 (ms)
    private long expirationMs;

    @Value("${jwt.refresh-expiration}") // Refresh Token 유효기간 (ms)
    private long refreshExpirationMs;

    private Key key;

    @PostConstruct
    public void init() {
        this.key = Keys.hmacShaKeyFor(secretRaw.getBytes(StandardCharsets.UTF_8));
        log.info("[JWT] 비밀키 초기화 완료");
    }

    // ✅ Access 토큰 전용
    public String generateAccessToken(Long userId, String role) {
        return generateToken(userId, role, expirationMs);
    }

    // ✅ Refresh 토큰 전용
    public String generateRefreshToken(Long userId, String role) {
        return generateToken(userId, role, refreshExpirationMs);
    }

    // ✅ 공통 토큰 생성 로직
    public String generateToken(Long userId, String role, long ttlMillis) {
        String token = Jwts.builder()
                .claim("userId", userId)
                .claim("role", role)
                .setIssuedAt(new Date())
                .setExpiration(new Date(System.currentTimeMillis() + ttlMillis))
                .signWith(key, SignatureAlgorithm.HS256)
                .compact();

        log.info("[JWT] 토큰 생성됨 | userId={}, role={}, TTL={}ms", userId, role, ttlMillis);
        return token;
    }

    public Claims getClaims(String token) {
        try {
            Claims claims = Jwts.parserBuilder()
                    .setSigningKey(key)
                    .build()
                    .parseClaimsJws(token)
                    .getBody();
            log.info("[JWT] 클레임 파싱 성공 | userId={}, role={}", claims.get("userId"), claims.get("role"));
            return claims;
        } catch (JwtException e) {
            log.warn("[JWT] 클레임 파싱 실패 | reason={}", e.getMessage());
            throw e;
        }
    }

    public Long getUserId(String token) {
        Object userId = getClaims(token).get("userId");

        if (userId instanceof Integer) return ((Integer) userId).longValue();
        if (userId instanceof Long) return (Long) userId;
        if (userId instanceof String) return Long.parseLong((String) userId);

        log.error("[JWT] userId 타입 비정상: {}", userId);
        throw new IllegalArgumentException("Invalid userId type in JWT");
    }

    public String getRole(String token) {
        return (String) getClaims(token).get("role");
    }

    public boolean validateToken(String token) {
        try {
            getClaims(token);
            return true;
        } catch (SecurityException e) {
            log.warn("JWT 서명 오류: {}", e.getMessage());
        } catch (MalformedJwtException e) {
            log.warn("잘못된 JWT 형식: {}", e.getMessage());
        } catch (ExpiredJwtException e) {
            log.warn("JWT 만료됨: {}", e.getMessage());
        } catch (UnsupportedJwtException e) {
            log.warn("지원하지 않는 JWT: {}", e.getMessage());
        } catch (IllegalArgumentException e) {
            log.warn("JWT 문자열이 비어 있음: {}", e.getMessage());
        }
        return false;
    }

    public long getRemainingValidity(String token) {
        try {
            Claims claims = Jwts.parserBuilder()
                    .setSigningKey(key)
                    .build()
                    .parseClaimsJws(token)
                    .getBody();

            return claims.getExpiration().getTime() - System.currentTimeMillis();
        } catch (Exception e) {
            log.error("토큰 만료 시간 계산 실패: {}", e.getMessage());
            return -1;
        }
    }
}
