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
/*
왜 이렇게 고쳤는지 — 핵심만

회전/재사용 감지는 “jti 단위로 1회용 세션을 저장했다가, /api/auth/refresh에서 consume하며 폐기”가 본질이다.
→ 로그인 성공 시점에 세션 저장을 해둬야, 첫 리프레시부터 회전이 성립한다.

쿠키 path가 /auth/면 /api/auth/refresh로는 안 붙는다. 이거 하나로 “왜 리프레시가 안 돼?”가 1시간 증발한다.

URL에 토큰 금지를 유지하려면, 팝업에서 프론트가 /api/auth/refresh 한 번 쏴서 Access만 받으면 된다(쿠키 전달). 그 후 메인창에 postMessage("LOGIN_OK")만 던지고 팝업 닫아라.
 */
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

        var user   = (CustomOAuth2User) authentication.getPrincipal();
        Long userId = user.getId();
        String role = user.getRole();

        // 1) 토큰 발급 (Access는 프론트에 직접 안 보냄: silent exchange)
        String access  = jwtProvider.generateAccessToken(userId, role);
        String refresh = jwtProvider.generateRefreshToken(userId, role);

        // 2) jti/TTL 계산 후, "세션형 refresh" 등록 (재사용 감지용)
        Claims refClaims = jwtProvider.getClaims(refresh);
        String jti = refClaims.getId();
        long ttlMillis = Math.max(0, refClaims.getExpiration().getTime() - System.currentTimeMillis());
        tokenService.saveRefreshSession(userId, jti, req, ttlMillis);

        // 3) Refresh를 HttpOnly 쿠키로 심기
        //    ⚠ 쿠키 path는 /api/auth/ 로 맞춘다(네 리프레시 엔드포인트 경로 프리픽스와 일치해야 브라우저가 전송).
        ResponseCookie refreshCookie = ResponseCookie.from("refresh_token", refresh)
                .httpOnly(true)
                .secure(true)
                .sameSite(isCrossSite(req, props) ? "None" : "Lax") // 크로스도메인이면 None + HTTPS + CORS(credentials=true)
                .path("/api/auth/")  // <<==== 기존 "/auth/"는 오동작. 반드시 "/api/auth/" 또는 "/" 로.
                .maxAge(ttlMillis / 1000)
                .build();
        res.addHeader(HttpHeaders.SET_COOKIE, refreshCookie.toString());

        // (선택) 서버 로그 상관관계용: Access는 바로 쓰지 않으니 굳이 전송하지 않음
        log.info("[OAuth2] login success | uid={} role={} -> refresh jti={} ttl={}s",
                userId, role, jti, ttlMillis / 1000);

        // 4) 프론트로 리다이렉트(토큰/코드 절대 싣지 않음)
        String base = pickRedirectBase(req, props);
        String location = UriComponentsBuilder.fromUriString(base)
                .replaceQuery(null)
                .build()
                .toUriString();

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

    /** 현재 요청이 cross-site인지 라이트하게 판별(도메인/포트/스킴 비교) */
    private static boolean isCrossSite(HttpServletRequest req, AppOAuthProps props) {
        try {
            String referer = req.getHeader("Origin");
            if (referer == null) referer = req.getHeader("Referer");
            if (referer == null) return false;
            URI o = URI.create(referer);
            // 백엔드 자신의 오리진(대략)과 비교
            String host = Optional.ofNullable(req.getHeader("Host")).orElse("");
            String backendOrigin = (req.isSecure() ? "https://" : "http://") + host;
            URI b = URI.create(backendOrigin);
            return !(Objects.equals(o.getScheme(), b.getScheme()) &&
                    Objects.equals(o.getHost(),   b.getHost())   &&
                    ((o.getPort() == -1 ? o.toURL().getDefaultPort() : o.getPort())
                            == (b.getPort() == -1 ? b.toURL().getDefaultPort() : b.getPort())));
        } catch (Exception e) {
            return false;
        }
    }
}
