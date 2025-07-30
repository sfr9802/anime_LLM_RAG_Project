package com.arin.auth.oauth;

import com.arin.auth.jwt.JwtProvider;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.core.Authentication;
import org.springframework.security.oauth2.core.user.OAuth2User;
import org.springframework.security.web.authentication.AuthenticationSuccessHandler;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.util.HashMap;
import java.util.Map;

@Slf4j
@Component
@RequiredArgsConstructor
public class CustomAuthenticationSuccessHandler implements AuthenticationSuccessHandler {

    private final JwtProvider jwtProvider;

    @Override
    public void onAuthenticationSuccess(HttpServletRequest request,
                                        HttpServletResponse response,
                                        Authentication authentication) throws IOException {
        log.info("[OAuth2 Success] 인증 성공. 토큰 생성 시작");

        try {
            CustomOAuth2User oAuth2User = (CustomOAuth2User) authentication.getPrincipal();
            Long userId = oAuth2User.getId();
            String role = oAuth2User.getRole();

            log.debug("인증 사용자 ID: {}", userId);
            log.debug("인증 사용자 Role: {}", role);

            String token = jwtProvider.generateToken(userId, role);
            log.info("JWT 발급 완료");

            response.setContentType("application/json");
            response.setCharacterEncoding("UTF-8");
            response.getWriter().write("{\"token\":\"" + token + "\"}");
            response.getWriter().flush();

            log.info("JWT 응답 전송 완료");
        } catch (Exception e) {
            log.error("OAuth2 로그인 후 JWT 발급 또는 응답 중 오류 발생", e);
            response.sendError(HttpServletResponse.SC_INTERNAL_SERVER_ERROR, "JWT 발급 실패");
        }
    }
}

