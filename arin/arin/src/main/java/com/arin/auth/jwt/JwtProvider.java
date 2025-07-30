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

@Slf4j  // ✅ SLF4J 로그 어노테이션
@Component
public class JwtProvider {

    @Value("${jwt.secret}")
    private String secretRaw;

    @Value("${jwt.expiration}")
    private long expirationMs;

    private Key key;

    @PostConstruct
    public void init() {
        this.key = Keys.hmacShaKeyFor(secretRaw.getBytes(StandardCharsets.UTF_8));
        log.info("[JWT] 비밀키 초기화 완료");
    }

    public String generateToken(Long userId, String role) {
        String token = Jwts.builder()
                .claim("userId", userId)
                .claim("role", role)
                .setIssuedAt(new Date())
                .setExpiration(new Date(System.currentTimeMillis() + expirationMs))
                .signWith(key, SignatureAlgorithm.HS256)
                .compact();

        log.info("[JWT] 토큰 생성됨 | userId={}, role={}, expiresIn={}ms", userId, role, expirationMs);
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
        Long id = null;

        if (userId instanceof Integer) {
            id = ((Integer) userId).longValue();
        } else if (userId instanceof Long) {
            id = (Long) userId;
        } else if (userId instanceof String) {
            id = Long.parseLong((String) userId);
        } else {
            log.error("[JWT] userId 타입 비정상: {}", userId);
            throw new IllegalArgumentException("Invalid userId type in JWT");
        }

        log.debug("[JWT] userId 추출 성공: {}", id);
        return id;
    }

    public String getRole(String token) {
        String role = (String) getClaims(token).get("role");
        log.debug("[JWT] role 추출 성공: {}", role);
        return role;
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
}
