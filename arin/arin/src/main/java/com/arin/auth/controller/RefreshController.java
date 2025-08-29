package com.arin.auth.controller;

import com.arin.auth.dto.TokenResponseDto;
import com.arin.auth.jwt.JwtProvider;
import com.arin.auth.service.TokenService;
import io.jsonwebtoken.Claims;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

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
    public ResponseEntity<?> refreshAccessToken(
            HttpServletRequest request,
            @CookieValue(value = "refresh_token", required = false) String rtFromCookie) {

        // 1) 토큰 추출: 쿠키 우선, 없으면 헤더(Bearer) 허용(이행기)
        String refreshToken = (rtFromCookie != null && !rtFromCookie.isBlank())
                ? rtFromCookie
                : extractToken(request); // Authorization: Bearer <refresh>

        if (refreshToken == null || refreshToken.isBlank()) {
            log.warn("[REFRESH] 리프레시 토큰 누락");
            return ResponseEntity.badRequest().body(Map.of("error","BAD_REQUEST","message","refresh token missing"));
        }

        // 2) 타입/만료/서명 검증
        Claims claims;
        try {
            claims = jwtProvider.getClaims(refreshToken);
        } catch (Exception e) {
            log.warn("[REFRESH] 리프레시 토큰 파싱 실패: {}", e.getMessage());
            return ResponseEntity.status(401).body(Map.of("error","UNAUTHORIZED","message","invalid refresh token"));
        }
        String typ = jwtProvider.getType(refreshToken);
        if (!"ref".equals(typ)) {
            return ResponseEntity.status(401).body(Map.of("error","UNAUTHORIZED","message","not a refresh token"));
        }

        // 3) jti/uid 추출 → 세션 consume
        Long userId = jwtProvider.getUserId(refreshToken);
        String jti = claims.getId();
        boolean ok = tokenService.consumeRefreshSession(userId, jti, request);
        if (!ok) {
            // 재사용 감지 또는 바인딩 불일치 → 전체 세션 폐기
            tokenService.revokeAllRefreshSessions(userId);
            log.warn("[REFRESH] 재사용/바인딩 불일치 감지 → 전체 세션 폐기 | uid={}, jti={}", userId, jti);
            return ResponseEntity.status(401).body(Map.of("error","UNAUTHORIZED","message","refresh reuse detected"));
        }

        // 4) 새 토큰 발급 (회전)
        //    role은 refresh의 roles에서 1개 뽑아 재사용(너의 JwtProvider에 getRoles 있음)
        var roles = jwtProvider.getRoles(refreshToken);
        String role = (roles != null && !roles.isEmpty()) ? roles.getFirst() : "USER";

        String newAccess = jwtProvider.generateAccessToken(userId, role);
        String newRefresh = jwtProvider.generateRefreshToken(userId, role);

        // 5) 새 refresh의 jti/TTL 계산 → 세션 저장 + 쿠키 세팅
        Claims newRefClaims = jwtProvider.getClaims(newRefresh);
        String newJti = newRefClaims.getId();
        long ttlMillis = newRefClaims.getExpiration().getTime() - System.currentTimeMillis();
        tokenService.saveRefreshSession(userId, newJti, request, ttlMillis);

        var cookie = tokenService.buildRefreshCookie(newRefresh, ttlMillis);

        log.info("[REFRESH] 회전 완료 | uid={}, oldJti={}, newJti={}", userId, jti, newJti);
        return ResponseEntity.ok()
                .header("Set-Cookie", cookie.toString())
                // 하위호환: 당분간 refresh도 바디에 실어줌. 곧 제거해라.
                .body(new TokenResponseDto(newAccess, newRefresh));
    }
    private String extractToken(HttpServletRequest request) {
        String bearer = request.getHeader("Authorization");
        if (bearer != null && bearer.startsWith("Bearer ")) {
            return bearer.substring(7).trim();
        }
        return null;
    }

}

