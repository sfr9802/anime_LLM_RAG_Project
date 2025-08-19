package com.arin.auth.oauth;

import com.arin.auth.config.AppOAuthProps;
import com.arin.auth.jwt.JwtProvider;
import com.arin.auth.service.TokenService;
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

@Slf4j
@Component
@RequiredArgsConstructor
public class CustomOAuth2SuccessHandler implements AuthenticationSuccessHandler {

    private final JwtProvider jwtProvider;
    private final TokenService tokenService;
    private final AppOAuthProps props; // app.oauth2.redirect-uri, allowed-origins

    @Override
    public void onAuthenticationSuccess(HttpServletRequest req,
                                        HttpServletResponse res,
                                        Authentication authentication) throws IOException {
        var user = (CustomOAuth2User) authentication.getPrincipal();
        Long userId = user.getId();
        String role  = user.getRole();

        // 1) 토큰 발급 & refresh 저장
        String access  = jwtProvider.generateAccessToken(userId, role);
        String refresh = jwtProvider.generateRefreshToken(userId, role);
        tokenService.storeRefreshToken(userId, refresh, jwtProvider.getRemainingValidity(refresh));

        // 2) 1회용 코드(OTC) 발급 (60s 예시)
        String code = tokenService.issueOneTimeCode(userId, access, refresh, 60);

        // 3) 프론트에서 보냈던 state 에코백(있으면)
        String state = req.getParameter("state");
        Optional<String> stateOpt = Optional.ofNullable(state).filter(s -> !s.isBlank());

        // 4) 리다이렉트 base 결정(세션/쿼리 ?front=…/설정값)
        String base = pickRedirectBase(req, props);

        // 5) 안전하게 URL 빌드 (★ 인코딩을 Builder에 맡긴다: build() / build(false))
        String location = UriComponentsBuilder.fromHttpUrl(base)
                .replaceQueryParam("code")                  // 혹시 기존 code 제거
                .queryParam("code", code)                   // =, + 등 안전하게 인코딩됨
                .queryParamIfPresent("state", stateOpt)
                .build()                                    // ← build(true) 쓰지 마세요!
                .toUriString();

        log.info("[OAuth2] Success → redirect {}", location);

        // 캐시 방지 + 302
        res.setHeader("Cache-Control", "no-store");
        res.setHeader("Pragma", "no-cache");
        res.sendRedirect(location);
    }

    /** 세션(frontRedirect) > 요청 ?front= > 설정값 순서로 선택, origin 화이트리스트 체크 */
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
                session.removeAttribute("frontRedirect"); // 1회성
            }
        }
        if (candidate == null) {
            candidate = req.getParameter("front");
        }

        return (candidate != null && isAllowedFront(candidate, props.getAllowedOrigins()))
                ? candidate
                : configured;
    }

    /** origin(스킴+호스트[:포트])만 비교해 화이트리스트 검사 */
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
