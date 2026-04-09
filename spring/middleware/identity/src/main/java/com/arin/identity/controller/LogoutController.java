package com.arin.identity.controller;

import com.arin.identity.jwt.JwtProvider;
import com.arin.identity.service.TokenService;
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

    private final JwtProvider jwtProvider;
    private final TokenService tokenService;

    @PostMapping("/logout")
    public ResponseEntity<?> logout(HttpServletRequest request,
                                    @CookieValue(value = "refresh_token", required = false) String refreshCookie,
                                    @RequestParam(value = "all", defaultValue = "false") boolean all) {
        HttpHeaders noCache = new HttpHeaders();
        noCache.setCacheControl(CacheControl.noStore());
        noCache.add("Pragma", "no-cache");
        String access = extractBearer(request);
        if (access != null && !access.isBlank()) {
            try { tokenService.blacklistToken(access); } catch (Exception ignored) {}
        }
        if (refreshCookie != null && !refreshCookie.isBlank()) {
            try {
                Claims rc = jwtProvider.getClaims(refreshCookie);
                Long uid = jwtProvider.getUserId(refreshCookie);
                String jti = rc.getId();
                if (all) tokenService.revokeAllRefreshSessions(uid);
                else     tokenService.revokeRefreshSession(uid, jti);
            } catch (Exception e) { log.debug("[LOGOUT] refresh parse failed: {}", e.toString()); }
        }
        ResponseCookie del = tokenService.buildDeleteRefreshCookie();
        return ResponseEntity.ok().headers(noCache).header(HttpHeaders.SET_COOKIE, del.toString()).body(Map.of("status", "OK"));
    }

    private static String extractBearer(HttpServletRequest request) {
        String bearer = request.getHeader("Authorization");
        if (bearer != null && bearer.startsWith("Bearer ")) return bearer.substring(7).trim();
        return null;
    }
}
