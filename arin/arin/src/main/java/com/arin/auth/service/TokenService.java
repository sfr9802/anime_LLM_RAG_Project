package com.arin.auth.service;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import io.jsonwebtoken.security.WeakKeyException;
import jakarta.annotation.PostConstruct;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import javax.crypto.SecretKey;
import java.util.Date;
import java.util.concurrent.TimeUnit;

@Slf4j
@Service
@RequiredArgsConstructor
public class TokenService {

    private final StringRedisTemplate redisTemplate;

    private static final String BLACKLIST_PREFIX = "blacklist:";
    private static final String REFRESH_PREFIX = "refresh:";

    @Value("${jwt.secret}")
    private String jwtSecret;

    private SecretKey key;

    @PostConstruct
    public void init() {
        byte[] keyBytes = jwtSecret.getBytes();

        if (keyBytes.length < 32) {
            throw new WeakKeyException("JWT secret key must be at least 256 bits (32 bytes). 현재 길이: " + keyBytes.length);
        }

        this.key = Keys.hmacShaKeyFor(keyBytes);
        log.info("[JWT-TOKEN] SecretKey 초기화 완료");
    }

    /**
     * 토큰을 블랙리스트에 등록하고 TTL 지정
     */
    public void blacklistToken(String token) {
        long expirationMillis = getRemainingTime(token);
        if (expirationMillis <= 0) {
            log.warn("[JWT-BLACKLIST] 만료된 토큰은 블랙리스트에 등록하지 않음");
            return;
        }

        redisTemplate.opsForValue().set(BLACKLIST_PREFIX + token, "blacklisted", expirationMillis, TimeUnit.MILLISECONDS);
        log.info("[JWT-BLACKLIST] 토큰 블랙리스트 등록 완료 (TTL={}ms)", expirationMillis);
    }

    /**
     * 토큰이 블랙리스트에 등록되어 있는지 확인
     */
    public boolean isBlacklisted(String token) {
        return redisTemplate.hasKey(BLACKLIST_PREFIX + token);
    }

    /**
     * 토큰의 남은 만료 시간(ms)을 반환
     */
    private long getRemainingTime(String token) {
        try {
            Claims claims = Jwts.parserBuilder()
                    .setSigningKey(key)
                    .build()
                    .parseClaimsJws(token)
                    .getBody();

            Date expiration = claims.getExpiration();
            long now = System.currentTimeMillis();
            return expiration.getTime() - now;

        } catch (Exception e) {
            log.error("[JWT-BLACKLIST] 토큰 만료 시간 추출 실패: {}", e.getMessage());
            return -1;
        }
    }

    /**
     * 리프레시 토큰 저장
     */
    public void storeRefreshToken(Long userId, String refreshToken, long ttlMillis) {
        String key = REFRESH_PREFIX + userId;
        redisTemplate.opsForValue().set(key, refreshToken, ttlMillis, TimeUnit.MILLISECONDS);
        log.info("[JWT-REFRESH] 리프레시 토큰 저장 완료 | key={}, TTL={}ms", key, ttlMillis);
    }

    /**
     * 리프레시 토큰 조회
     */
    public String getRefreshToken(Long userId) {
        String key = REFRESH_PREFIX + userId;
        return redisTemplate.opsForValue().get(key);
    }

    /**
     * 리프레시 토큰 삭제
     */
    public void deleteRefreshToken(Long userId) {
        String key = REFRESH_PREFIX + userId;
        redisTemplate.delete(key);
        log.info("[JWT-REFRESH] 리프레시 토큰 삭제 완료 | key={}", key);
    }
}
