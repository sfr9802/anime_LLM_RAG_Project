package com.arin.auth.jwt;

import com.arin.auth.service.TokenService;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.Set;

@Slf4j
@Component
@RequiredArgsConstructor
public class JwtBlacklistFilter extends OncePerRequestFilter {

    private final TokenService tokenService;

    // 공개 패스(무조건 통과)
    private static final Set<String> PUBLIC_PREFIXES = Set.of(
            "/api/auth/", "/swagger-ui", "/v3/api-docs"
    );

    @Override
    protected void doFilterInternal(HttpServletRequest req, HttpServletResponse res, FilterChain chain)
            throws IOException, ServletException {

        final String path = req.getRequestURI();

        // 1) 프리플라이트/공개 경로는 무조건 통과
        if ("OPTIONS".equalsIgnoreCase(req.getMethod()) || isPublic(path)) {
            chain.doFilter(req, res);
            return;
        }

        // 2) 토큰 없으면 통과(인증 필요한 엔드포인트는 뒤에서 401 처리)
        String auth = req.getHeader("Authorization");
        if (auth == null || !auth.startsWith("Bearer ")) {
            chain.doFilter(req, res);
            return;
        }

        String token = auth.substring(7).trim();
        if (!token.isEmpty() && tokenService.isBlacklisted(token)) {
            log.warn("[BLACKLIST] blocked path={} ip={} ua={}",
                    path, req.getRemoteAddr(), req.getHeader("User-Agent"));

            res.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
            res.setContentType("application/json; charset=UTF-8");
            res.setHeader("Cache-Control", "no-store");
            res.setHeader("Pragma", "no-cache");
            res.getWriter().write("{\"error\":\"로그아웃된 토큰입니다.\"}");
            return;
        }

        chain.doFilter(req, res);
    }

    private boolean isPublic(String path) {
        for (String p : PUBLIC_PREFIXES) {
            if (path.startsWith(p)) return true;
        }
        return false;
    }
}
