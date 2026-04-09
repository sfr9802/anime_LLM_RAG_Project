package com.arin.identity.oauth;

import com.arin.identity.config.AppOAuthProps;
import com.arin.identity.jwt.JwtProvider;
import com.arin.identity.service.TokenService;
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
    public void onAuthenticationSuccess(HttpServletRequest req, HttpServletResponse res, Authentication authentication) throws IOException {
        var user = (CustomOAuth2User) authentication.getPrincipal();
        Long userId = user.getId();
        String role  = user.getRole();
        String access  = jwtProvider.generateAccessToken(userId, role);
        String refresh = jwtProvider.generateRefreshToken(userId, role);
        Claims refClaims = jwtProvider.getClaims(refresh);
        String jti = refClaims.getId();
        long ttlMillis = Math.max(0, refClaims.getExpiration().getTime() - System.currentTimeMillis());
        tokenService.saveRefreshSession(userId, jti, req, ttlMillis);
        String code = tokenService.issueOneTimeCode(userId, access, refresh, 60);
        String base = pickRedirectBase(req, props);
        String location = UriComponentsBuilder.fromUriString(base)
                .replaceQuery(null).queryParam("code", code).queryParam("state", UUID.randomUUID().toString())
                .build(true).toUriString();
        log.info("[OAuth2] Success → redirect {}", location);
        res.setHeader("Cache-Control", "no-store");
        res.setHeader("Pragma", "no-cache");
        res.sendRedirect(location);
    }

    private static String pickRedirectBase(HttpServletRequest req, AppOAuthProps props) {
        String configured = Optional.ofNullable(props.getRedirectUri()).filter(s -> !s.isBlank()).orElse("http://localhost/oauth/success-popup");
        String candidate = null;
        var session = req.getSession(false);
        if (session != null) {
            Object v = session.getAttribute("frontRedirect");
            if (v != null) { candidate = v.toString(); session.removeAttribute("frontRedirect"); }
        }
        if (candidate == null) candidate = req.getParameter("front");
        return (isAllowedFront(candidate, props.getAllowedOrigins())) ? candidate : configured;
    }

    private static boolean isAllowedFront(String url, List<String> allowedOrigins) {
        if (url == null || url.isBlank() || allowedOrigins == null || allowedOrigins.isEmpty()) return false;
        try {
            String origin = toNormalizedOrigin(url);
            return allowedOrigins.stream().filter(Objects::nonNull).map(CustomOAuth2SuccessHandler::toNormalizedOrigin).anyMatch(origin::equals);
        } catch (Exception ignored) { return false; }
    }

    private static String toNormalizedOrigin(String s) {
        URI u = URI.create(s);
        String scheme = u.getScheme(); String host = u.getHost(); int port = u.getPort();
        boolean isDefaultPort = (port == -1) || ("http".equalsIgnoreCase(scheme) && port == 80) || ("https".equalsIgnoreCase(scheme) && port == 443);
        String portPart = isDefaultPort ? "" : (":" + port);
        return scheme + "://" + host + portPart;
    }
}
