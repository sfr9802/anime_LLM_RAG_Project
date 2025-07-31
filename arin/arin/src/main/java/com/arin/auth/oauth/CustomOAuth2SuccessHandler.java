package com.arin.auth.oauth;

import com.arin.auth.jwt.JwtProvider;
import com.arin.auth.service.TokenService;
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
    private final TokenService tokenService;

    @Override
    public void onAuthenticationSuccess(HttpServletRequest request,
                                        HttpServletResponse response,
                                        Authentication authentication) throws IOException {
        log.info("[OAuth2 Success] 인증 성공. 팝업창 postMessage로 토큰 전달");

        try {
            CustomOAuth2User oAuth2User = (CustomOAuth2User) authentication.getPrincipal();
            Long userId = oAuth2User.getId();
            String role = oAuth2User.getRole();

            // JWT 발급
            String accessToken = jwtProvider.generateAccessToken(userId, role);
            String refreshToken = jwtProvider.generateRefreshToken(userId, role);

            // Redis 저장
            long refreshTtl = jwtProvider.getRemainingValidity(refreshToken);
            tokenService.storeRefreshToken(userId, refreshToken, refreshTtl);

            // HTML + JS로 token 전달
            response.setContentType("text/html;charset=UTF-8");
            response.getWriter().write("""
            <html><body>
            <script>
              window.opener.postMessage({
                accessToken: '%s',
                refreshToken: '%s'
              }, '*');
              window.close();
            </script>
            </body></html>
        """.formatted(accessToken, refreshToken));

        } catch (Exception e) {
            log.error("OAuth2 로그인 후 토큰 발급 중 오류", e);
            response.sendError(HttpServletResponse.SC_INTERNAL_SERVER_ERROR, "OAuth2 처리 실패");
        }
    }


}
