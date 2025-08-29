package com.arin.auth.oauth;

import com.arin.auth.config.AppOAuthProps;
import com.arin.auth.jwt.JwtProvider;
import com.arin.auth.service.TokenService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseCookie;
import org.springframework.security.core.Authentication;
import org.springframework.security.web.authentication.AuthenticationSuccessHandler;
import org.springframework.stereotype.Component;
import org.springframework.web.util.UriComponentsBuilder;

import java.io.IOException;
import java.net.URI;
import java.util.List;
import java.util.Objects;
import java.util.Optional;

@Slf4j
@Component
@RequiredArgsConstructor
public class CustomOAuth2SuccessHandler implements AuthenticationSuccessHandler {

    private final JwtProvider jwtProvider;
    private final TokenService tokenService;
    private final AppOAuthProps props; // redirect-uri, allowed-origins 등

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

        // 2) Refresh 회전/허용 등록 (TTL = refresh 만료까지)
        tokenService.storeRefreshToken(userId, refresh, jwtProvider.getRemainingValidity(refresh));

        // 3) Refresh를 HttpOnly 쿠키로 심기 (경로는 재발급/로그아웃 엔드포인트로 좁힘 권장: "/auth/")
        var maxAgeSec = Math.max(0, (int) (jwtProvider.getRemainingValidity(refresh) / 1000));
        ResponseCookie refreshCookie = ResponseCookie.from("REFRESH_TOKEN", refresh)
                .httpOnly(true)
                .secure(true)                // 배포는 반드시 HTTPS
                .sameSite("Lax")             // 크로스오리진이면 "None" + CORS credentials=true 로 전환
                .path("/auth/")              // 재발급/로그아웃에만 전송
                .maxAge(maxAgeSec)
                .build();
        res.addHeader(HttpHeaders.SET_COOKIE, refreshCookie.toString());

        // 4) 프론트 리다이렉트 (토큰/코드 절대 싣지 않음)
        String base = pickRedirectBase(req, props);
        String location = UriComponentsBuilder.fromUriString(base)
                .replaceQuery(null)      // 기존 쿼리 제거(혹시 모를 노출 방지)
                .build()
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
        } catch (Exception ignored) {
            return false;
        }
    }

    private static String normalizeOrigin(String s) {
        try {
            URI u = URI.create(s);
            return u.getScheme() + "://" + u.getHost() + ((u.getPort() > 0) ? (":" + u.getPort()) : "");
        } catch (Exception e) {
            return s;
        }
    }
}

