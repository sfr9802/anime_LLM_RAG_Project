package com.arin.auth.controller;

import com.arin.auth.dto.TokenResponseDto;
import com.arin.auth.jwt.JwtProvider;
import com.arin.auth.service.TokenService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@Slf4j
@RestController
@RequestMapping("/api/auth")
@RequiredArgsConstructor
@Tag(name = "Auth", description = "인증 관련 API")
public class RefreshController {

    private final JwtProvider jwtProvider;
    private final TokenService tokenService;

    @Operation(summary = "Access Token 재발급", description = "유효한 Refresh Token을 기반으로 새로운 Access Token을 발급합니다.")
    @PostMapping("/refresh")
    public ResponseEntity<?> refreshAccessToken(HttpServletRequest request) {
        String refreshToken = extractToken(request);

        if (refreshToken == null || refreshToken.isBlank()) {
            log.warn("[REFRESH] 리프레시 토큰 누락");
            return ResponseEntity.badRequest().body("리프레시 토큰이 누락되었습니다.");
        }

        if (!jwtProvider.validateToken(refreshToken)) {
            log.warn("[REFRESH] 리프레시 토큰 유효성 실패");
            return ResponseEntity.status(401).body("리프레시 토큰이 유효하지 않습니다.");
        }

        Long userId = jwtProvider.getUserId(refreshToken);
        String storedToken = tokenService.getRefreshToken(userId);

        if (storedToken == null || !storedToken.equals(refreshToken)) {
            log.warn("[REFRESH] 저장된 토큰과 일치하지 않음 | userId={}", userId);
            return ResponseEntity.status(401).body("리프레시 토큰이 유효하지 않습니다.");
        }

        String role = jwtProvider.getRole(refreshToken);
        String newAccessToken = jwtProvider.generateAccessToken(userId, role);

        log.info("[REFRESH] 액세스 토큰 재발급 완료 | userId={}", userId);
        return ResponseEntity.ok(new TokenResponseDto(newAccessToken, refreshToken));
    }

    private String extractToken(HttpServletRequest request) {
        String bearer = request.getHeader("Authorization");
        if (bearer != null && bearer.startsWith("Bearer ")) {
            return bearer.substring(7).trim();
        }
        return null;
    }
}

