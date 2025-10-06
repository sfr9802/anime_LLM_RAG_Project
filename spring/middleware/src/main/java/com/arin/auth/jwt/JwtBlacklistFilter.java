package com.arin.auth.jwt;

import com.arin.auth.service.TokenService;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.Set;

@Slf4j
@Component
@RequiredArgsConstructor
public class JwtBlacklistFilter extends OncePerRequestFilter {

    private final TokenService tokenService;

    // 무조건 통과할 prefix
    private static final Set<String> PUBLIC_PREFIXES = Set.of(
            "/api/auth/",           // 네 로그인/리프레시/로그아웃 라인
            "/oauth2/",             // OAuth2 엔드포인트
            "/login/oauth2/code/",  // OAuth2 콜백
            "/swagger-ui",
            "/v3/api-docs",
            "/actuator/health",
            "/error"
    );

    @Override
    protected boolean shouldNotFilter(HttpServletRequest req) {
        String path = req.getRequestURI();
        if (HttpMethod.OPTIONS.matches(req.getMethod())) return true;
        for (String p : PUBLIC_PREFIXES) {
            if (path.startsWith(p)) return true;
        }
        return false;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest req, HttpServletResponse res, FilterChain chain)
            throws IOException, ServletException {

        // 토큰 없으면 통과 (뒤 단계에서 인증 실패 처리)
        String auth = req.getHeader(HttpHeaders.AUTHORIZATION);
        if (auth == null || !startsWithBearer(auth)) {
            chain.doFilter(req, res);
            return;
        }

        String token = auth.substring(7).trim();
        if (!token.isEmpty() && tokenService.isBlacklisted(token)) {
            // 로깅: 프록시 환경이면 X-Forwarded-For 우선
            String ip = headerOr(req, "X-Forwarded-For", req.getRemoteAddr());
            log.warn("[BLACKLIST] blocked path={} ip={} ua={}", req.getRequestURI(), ip, headerOr(req, "User-Agent", "-"));

            res.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
            res.setContentType(MediaType.APPLICATION_JSON_VALUE);
            res.setCharacterEncoding("UTF-8");
            res.setHeader("Cache-Control", "no-store");
            res.setHeader("Pragma", "no-cache");
            res.getWriter().write("{\"error\":\"로그아웃된 토큰입니다.\"}");
            res.getWriter().flush();
            return;
        }

        chain.doFilter(req, res);
    }

    private static boolean startsWithBearer(String v) {
        // "Bearer " 대/소문자 관대 처리
        return v.regionMatches(true, 0, "Bearer ", 0, 7);
    }

    private static String headerOr(HttpServletRequest req, String name, String def) {
        String v = req.getHeader(name);
        return (v == null || v.isBlank()) ? def : v;
    }
}
