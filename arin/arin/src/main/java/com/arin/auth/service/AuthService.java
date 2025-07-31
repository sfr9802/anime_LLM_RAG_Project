package com.arin.auth.service;

import com.arin.auth.dto.TokenResponseDto;
import com.arin.auth.jwt.JwtProvider;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

@Slf4j
@Service
@RequiredArgsConstructor
public class AuthService {

    private final JwtProvider jwtProvider;
    private final TokenService tokenService;

    public TokenResponseDto issueTokens(Long userId, String role) {
        String accessToken = jwtProvider.generateAccessToken(userId, role);
        String refreshToken = jwtProvider.generateRefreshToken(userId, role);
        long ttl = jwtProvider.getRemainingValidity(refreshToken);

        tokenService.storeRefreshToken(userId, refreshToken, ttl);
        return new TokenResponseDto(accessToken, refreshToken);
    }

    public void logout(String accessToken) {
        tokenService.blacklistToken(accessToken);

        Long userId = jwtProvider.getUserId(accessToken);
        tokenService.deleteRefreshToken(userId);

        String role = jwtProvider.getRole(accessToken);
        log.info("[LOGOUT] 사용자 로그아웃 처리됨 | userId={}, role={}", userId, role);
    }
}
