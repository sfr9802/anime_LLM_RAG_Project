package com.arin.auth.oauth;

import com.arin.auth.config.AppOAuthProps;
import com.arin.auth.jwt.JwtProvider;
import com.arin.auth.service.TokenService;
import io.jsonwebtoken.Claims;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpHeaders;
import org.springframework.security.core.Authentication;
import org.springframework.security.web.authentication.AuthenticationSuccessHandler;
import org.springframework.stereotype.Component;
import org.springframework.web.util.UriComponentsBuilder;

import java.io.IOException;
import java.net.URI;
import java.util.List;
import java.util.Objects;
import java.util.Optional;
import java.util.UUID;

@Slf4j
@Component
@RequiredArgsConstructor
public class CustomOAuth2SuccessHandler implements AuthenticationSuccessHandler {

    private final JwtProvider jwtProvider;
    private final TokenService tokenService;
    private final AppOAuthProps props;

    @Override
    public void onAuthenticationSuccess(HttpServletRequest req,
                                        HttpServletResponse res,
                                        Authentication authentication) throws IOException {
        var user = (CustomOAuth2User) authentication.getPrincipal();
        Long userId = user.getId();
        String role  = user.getRole();

        // 1) 토큰 발급 (여기서 refresh 세션도 저장해 바인딩)
        String access  = jwtProvider.generateAccessToken(userId, role);
        String refresh = jwtProvider.generateRefreshToken(userId, role);

        Claims refClaims = jwtProvider.getClaims(refresh);
        String jti = refClaims.getId();
        long ttlMillis = Math.max(0, refClaims.getExpiration().getTime() - System.currentTimeMillis());
        tokenService.saveRefreshSession(userId, jti, req, ttlMillis); // UA/IP 바인딩

        // 2) 1회용 코드(OTC) 발급 — 60초 권장 (refresh TTL보다 길어지지 않음)
        String code = tokenService.issueOneTimeCode(userId, access, refresh, 60);

        // 3) 프론트 리다이렉트 (code만 전달; 토큰/쿠키 없음)
        String base = pickRedirectBase(req, props);
        String location = UriComponentsBuilder.fromUriString(base)
                .replaceQuery(null)
                .queryParam("code", code)
                .queryParam("state", UUID.randomUUID().toString()) // 선택: 추적용
                .build(true)
                .toUriString();

        log.info("[OAuth2] Success → redirect {}", location);

        res.setHeader("Cache-Control", "no-store");
        res.setHeader("Pragma", "no-cache");
        res.sendRedirect(location);
    }

    /** 세션(frontRedirect) > 요청 ?front= > 설정값 순서 + origin 화이트리스트 */
    private static String pickRedirectBase(HttpServletRequest req, AppOAuthProps props) {
        String configured = Optional.ofNullable(props.getRedirectUri())
                .filter(s -> !s.isBlank())
                .orElse("http://localhost:5173/oauth/success-popup");

        String candidate = null;
        var session = req.getSession(false);
        if (session != null) {
            Object v = session.getAttribute("frontRedirect");
            if (v != null) {
                candidate = v.toString();
                session.removeAttribute("frontRedirect");
            }
        }
        if (candidate == null) candidate = req.getParameter("front");

        return (isAllowedFront(candidate, props.getAllowedOrigins())) ? candidate : configured;
    }

    private static boolean isAllowedFront(String url, List<String> allowedOrigins) {
        if (url == null || url.isBlank() || allowedOrigins == null || allowedOrigins.isEmpty()) return false;
        try {
            URI u = URI.create(url);
            String origin = u.getScheme() + "://" + u.getHost() + ((u.getPort() > 0) ? (":" + u.getPort()) : "");
            return allowedOrigins.stream()
                    .filter(Objects::nonNull)
                    .map(CustomOAuth2SuccessHandler::normalizeOrigin)
                    .anyMatch(origin::equals);
        } catch (Exception ignored) { return false; }
    }

    private static String normalizeOrigin(String s) {
        try {
            URI u = URI.create(s);
            return u.getScheme() + "://" + u.getHost() + ((u.getPort() > 0) ? (":" + u.getPort()) : "");
        } catch (Exception e) { return s; }
    }
}
