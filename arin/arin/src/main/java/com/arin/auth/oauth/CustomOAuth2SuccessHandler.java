package com.arin.auth.oauth;

import com.arin.auth.config.AppOAuthProps;
import com.arin.auth.jwt.JwtProvider;
import com.arin.auth.service.TokenService;
import io.jsonwebtoken.Claims;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
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

        // 1) 토큰 발급
        String access  = jwtProvider.generateAccessToken(userId, role);
        String refresh = jwtProvider.generateRefreshToken(userId, role);

        // 2) refresh 세션 바인딩 (UA/IP 등)
        Claims refClaims = jwtProvider.getClaims(refresh);
        String jti = refClaims.getId();
        long ttlMillis = Math.max(0, refClaims.getExpiration().getTime() - System.currentTimeMillis());
        tokenService.saveRefreshSession(userId, jti, req, ttlMillis);

        // 3) 1회용 코드 발급
        String code = tokenService.issueOneTimeCode(userId, access, refresh, 60);

        // 4) 프론트 리다이렉트 (code만 전달)
        String base = pickRedirectBase(req, props);
        String location = UriComponentsBuilder.fromUriString(base)
                .replaceQuery(null)
                .queryParam("code", code)
                .queryParam("state", UUID.randomUUID().toString())
                .build(true)
                .toUriString();

        log.info("[OAuth2] Success → redirect {}", location);

        res.setHeader("Cache-Control", "no-store");
        res.setHeader("Pragma", "no-cache");
        res.sendRedirect(location);
    }

    /**
     * 세션(frontRedirect) > 요청 ?front= > 설정값(app.oauth2.redirect-uri) 순서 + origin 화이트리스트
     */
    private static String pickRedirectBase(HttpServletRequest req, AppOAuthProps props) {
        // 기본값: nginx:80 기준
        String configured = Optional.ofNullable(props.getRedirectUri())
                .filter(s -> !s.isBlank())
                .orElse("http://localhost/oauth/success-popup");

        String candidate = null;

        var session = req.getSession(false);
        if (session != null) {
            Object v = session.getAttribute("frontRedirect");
            if (v != null) {
                candidate = v.toString();
                session.removeAttribute("frontRedirect");
            }
        }
        if (candidate == null) {
            candidate = req.getParameter("front");
        }

        return (isAllowedFront(candidate, props.getAllowedOrigins())) ? candidate : configured;
    }

    private static boolean isAllowedFront(String url, List<String> allowedOrigins) {
        if (url == null || url.isBlank() || allowedOrigins == null || allowedOrigins.isEmpty()) return false;
        try {
            String origin = toNormalizedOrigin(url);
            return allowedOrigins.stream()
                    .filter(Objects::nonNull)
                    .map(CustomOAuth2SuccessHandler::toNormalizedOrigin)
                    .anyMatch(origin::equals);
        } catch (Exception ignored) {
            return false;
        }
    }

    /** 기본 포트(http:80 / https:443)는 제거해서 비교 일관성 확보 */
    private static String toNormalizedOrigin(String s) {
        URI u = URI.create(s);
        String scheme = u.getScheme();
        String host = u.getHost();
        int port = u.getPort();

        boolean isDefaultPort =
                (port == -1) ||
                        ("http".equalsIgnoreCase(scheme) && port == 80) ||
                        ("https".equalsIgnoreCase(scheme) && port == 443);

        String portPart = isDefaultPort ? "" : (":" + port);
        return scheme + "://" + host + portPart;
    }
}
