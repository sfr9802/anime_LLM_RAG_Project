package com.arin.auth.controller;

import com.arin.auth.jwt.JwtProvider;
import com.arin.auth.service.TokenService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.security.SecurityRequirement;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@Slf4j
@SecurityRequirement(name = "bearerAuth")
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/auth")
public class LogoutController {

    private final JwtProvider jwtProvider;
    private final TokenService tokenService;

    @Operation(summary = "로그아웃", description = "JWT를 블랙리스트에 등록하여 로그아웃 처리합니다.")
    @PostMapping("/logout")
    public ResponseEntity<?> logout(HttpServletRequest request) {
        String token = extractToken(request);

        if (token == null || token.isBlank()) {
            return ResponseEntity.badRequest().body("토큰이 존재하지 않습니다.");
        }

        if (!jwtProvider.validateToken(token)) {
            return ResponseEntity.badRequest().body("유효하지 않은 토큰입니다.");
        }

        tokenService.blacklistToken(token);

        try {
            Long userId = jwtProvider.getUserId(token);
            String role = jwtProvider.getRole(token);
            log.info("[LOGOUT] 사용자 로그아웃 처리됨 | userId={}, role={}", userId, role);
        } catch (Exception e) {
            log.warn("[LOGOUT] 토큰 파싱 중 오류: {}", e.getMessage());
        }

        return ResponseEntity.ok().body("로그아웃 성공");
    }

    private String extractToken(HttpServletRequest request) {
        String bearer = request.getHeader("Authorization");
        if (bearer != null && bearer.startsWith("Bearer ")) {
            return bearer.substring(7).trim();
        }
        return null;
    }
}


