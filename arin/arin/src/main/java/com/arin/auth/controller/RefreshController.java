package com.arin.auth.controller;

import com.arin.auth.dto.TokenResponseDto;
import com.arin.auth.jwt.JwtProvider;
import com.arin.auth.service.TokenService;
import io.jsonwebtoken.Claims;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.CacheControl;
import org.springframework.http.HttpHeaders;
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

    @Operation(summary = "Access Token 재발급", description = "유효한 Refresh Token으로 Access를 회전 발급")
    // com.arin.auth.controller.RefreshController
    @PostMapping("/refresh")
    public ResponseEntity<?> refreshAccessToken(
            HttpServletRequest request,
            @CookieValue(value = "refresh_token", required = false) String rtFromCookie) {

        var noCache = new HttpHeaders();
        noCache.setCacheControl(CacheControl.noStore()); noCache.add("Pragma","no-cache");

        String refreshToken = (rtFromCookie != null && !rtFromCookie.isBlank())
                ? rtFromCookie : extractToken(request); // 이행기: 헤더도 허용
        if (refreshToken == null || refreshToken.isBlank()) {
            return ResponseEntity.badRequest().headers(noCache)
                    .body(Map.of("error","BAD_REQUEST","message","refresh token missing"));
        }

        Claims claims;
        try { claims = jwtProvider.getClaims(refreshToken); }
        catch (Exception e) {
            return ResponseEntity.status(401).headers(noCache)
                    .body(Map.of("error","UNAUTHORIZED","message","invalid refresh token"));
        }
        if (!"ref".equals(jwtProvider.getType(refreshToken))) {
            return ResponseEntity.status(401).headers(noCache)
                    .body(Map.of("error","UNAUTHORIZED","message","not a refresh token"));
        }

        Long userId = jwtProvider.getUserId(refreshToken);
        String jti  = claims.getId();
        boolean ok  = tokenService.consumeRefreshSession(userId, jti, request);
        if (!ok) {
            tokenService.revokeAllRefreshSessions(userId);
            return ResponseEntity.status(401).headers(noCache)
                    .body(Map.of("error","UNAUTHORIZED","message","refresh reuse detected"));
        }

        var roles = jwtProvider.getRoles(refreshToken);
        String role = (roles != null && !roles.isEmpty()) ? roles.get(0) : "USER";

        String newAccess  = jwtProvider.generateAccessToken(userId, role);
        String newRefresh = jwtProvider.generateRefreshToken(userId, role);

        Claims newRef = jwtProvider.getClaims(newRefresh);
        long   rtTtlMs = newRef.getExpiration().getTime() - System.currentTimeMillis();
        tokenService.saveRefreshSession(userId, newRef.getId(), request, rtTtlMs);

        var cookie   = tokenService.buildRefreshCookie(newRefresh, rtTtlMs);
        long atExpS  = (jwtProvider.getClaims(newAccess).getExpiration().getTime() - System.currentTimeMillis())/1000;

        return ResponseEntity.ok()
                .headers(noCache)
                .header(HttpHeaders.SET_COOKIE, cookie.toString())
                .body(new TokenResponseDto(newAccess, atExpS)); // access-only
    }

    private String extractToken(HttpServletRequest r){
        String b = r.getHeader("Authorization");
        return (b!=null && b.startsWith("Bearer ")) ? b.substring(7).trim() : null;
    }


}

