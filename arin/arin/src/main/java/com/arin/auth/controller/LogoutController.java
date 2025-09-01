package com.arin.auth.controller;

import com.arin.auth.jwt.JwtProvider;
import com.arin.auth.service.TokenService;
import io.jsonwebtoken.Claims;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.CacheControl;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseCookie;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import jakarta.servlet.http.HttpServletRequest;
import java.util.Map;

@Slf4j
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/auth")
public class LogoutController {

    private final JwtProvider jwtProvider;   // DI
    private final TokenService tokenService; // DI

    /**
     * 로그아웃:
     * - Access 블랙리스트(남은 TTL만큼)
     * - Refresh 세션 철회(단말 1개 or 전기기 all=true)
     * - Refresh 쿠키 즉시 만료
     */
    @PostMapping("/logout")
    public ResponseEntity<?> logout(HttpServletRequest request,
                                    @CookieValue(value = "refresh_token", required = false) String refreshCookie,
                                    @RequestParam(value = "all", defaultValue = "false") boolean all) {

        HttpHeaders noCache = new HttpHeaders();
        noCache.setCacheControl(CacheControl.noStore());
        noCache.add("Pragma", "no-cache");

        // 1) Access 블랙리스트(있으면)
        String access = extractBearer(request);
        if (access != null && !access.isBlank()) {
            try {
                tokenService.blacklistToken(access);
            } catch (Exception ignored) { /* 만료/무효면 그냥 무시 */ }
        }

        // 2) Refresh 세션 철회(쿠키 기준)
        if (refreshCookie != null && !refreshCookie.isBlank()) {
            try {
                Claims rc = jwtProvider.getClaims(refreshCookie);
                Long uid = jwtProvider.getUserId(refreshCookie);
                String jti = rc.getId();
                if (all) tokenService.revokeAllRefreshSessions(uid);
                else     tokenService.revokeRefreshSession(uid, jti);
            } catch (Exception e) {
                // 파싱 실패여도 쿠키는 지울 거라서 진행
                log.debug("[LOGOUT] refresh parse failed: {}", e.toString());
            }
        }

        // 3) Refresh 쿠키 즉시 만료
        ResponseCookie del = tokenService.buildDeleteRefreshCookie();

        return ResponseEntity.ok()
                .headers(noCache)
                .header(HttpHeaders.SET_COOKIE, del.toString())
                .body(Map.of("status", "OK"));
    }

    private static String extractBearer(HttpServletRequest request) {
        String bearer = request.getHeader("Authorization");
        if (bearer != null && bearer.startsWith("Bearer ")) {
            return bearer.substring(7).trim();
        }
        return null;
    }
}
