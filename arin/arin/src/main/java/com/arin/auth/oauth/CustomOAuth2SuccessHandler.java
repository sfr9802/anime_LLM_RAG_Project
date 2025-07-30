package com.arin.auth.oauth;

import com.arin.auth.jwt.JwtProvider;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.core.Authentication;
import org.springframework.security.web.authentication.AuthenticationSuccessHandler;
import org.springframework.stereotype.Component;

import java.io.IOException;

@Slf4j
@Component
@RequiredArgsConstructor
public class CustomOAuth2SuccessHandler implements AuthenticationSuccessHandler {

    private final JwtProvider jwtProvider;

    @Override
    public void onAuthenticationSuccess(HttpServletRequest request,
                                        HttpServletResponse response,
                                        Authentication authentication) throws IOException {
        log.info("[OAuth2 Success] 인증 성공. 리다이렉트 준비");

        try {
            CustomOAuth2User oAuth2User = (CustomOAuth2User) authentication.getPrincipal();
            Long userId = oAuth2User.getId();
            String role = oAuth2User.getRole();

            log.debug("인증된 사용자 ID: {}", userId);
            log.debug("사용자 권한: {}", role);

            String token = jwtProvider.generateToken(userId, role);
            log.info("JWT 발급 완료");

            String redirectUrl = "http://localhost:3000/oauth/success?token=" + token;
            log.info("리다이렉트 URL: {}", redirectUrl);

            response.sendRedirect(redirectUrl);
        } catch (Exception e) {
            log.error("OAuth2 로그인 후 리다이렉트 중 오류 발생", e);
            response.sendError(HttpServletResponse.SC_INTERNAL_SERVER_ERROR, "OAuth2 리다이렉트 실패");
        }
    }
}
