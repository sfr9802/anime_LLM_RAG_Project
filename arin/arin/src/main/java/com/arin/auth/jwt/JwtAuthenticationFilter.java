package com.arin.auth.jwt;

import com.arin.auth.service.AppUserDetailsService;
import com.arin.auth.service.TokenService;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;

@Slf4j
@Component
public class JwtAuthenticationFilter extends OncePerRequestFilter {

    private final JwtProvider jwtProvider;
    private final UserDetailsService userDetailsService;
    private final AppUserDetailsService appUserDetailsService;
    private final TokenService tokenService;

    public JwtAuthenticationFilter(JwtProvider jwtProvider,
                                   UserDetailsService userDetailsService,
                                   AppUserDetailsService appUserDetailsService,
                                   TokenService tokenService) {
        this.jwtProvider = jwtProvider;
        this.userDetailsService = userDetailsService;
        this.appUserDetailsService = appUserDetailsService;
        this.tokenService = tokenService;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain filterChain) throws ServletException, IOException {

        String token = null;

        try {
            token = resolveToken(request);
            log.debug("요청 URI: {}", request.getRequestURI());

            if (token != null && !token.isBlank()) {
                log.debug("JWT 추출 성공: {}", token);

                // 🔥 블랙리스트 체크
                if (tokenService.isBlacklisted(token)) {
                    log.warn("[JWT] 블랙리스트 토큰 접근 시도: {}", token);

                    // 보안상 컨텍스트 초기화
                    SecurityContextHolder.clearContext();

                    // 명시적인 JSON 응답
                    response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
                    response.setContentType("application/json");
                    response.getWriter().write("{\"error\": \"로그아웃된 토큰입니다.\"}");
                    return;
                }

                // ✅ 유효한 토큰이라면 인증 처리
                if (jwtProvider.validateToken(token)) {
                    log.debug("JWT 유효성 검사 통과");

                    Long userId = jwtProvider.getUserId(token);
                    log.debug("JWT에서 userId 추출: {}", userId);

                    UserDetails userDetails = appUserDetailsService.loadUserById(userId);
                    log.debug("UserDetails 로드 완료: {}", userDetails.getUsername());

                    if (SecurityContextHolder.getContext().getAuthentication() == null) {
                        UsernamePasswordAuthenticationToken auth =
                                new UsernamePasswordAuthenticationToken(
                                        userDetails, null, userDetails.getAuthorities()
                                );
                        SecurityContextHolder.getContext().setAuthentication(auth);
                        log.debug("SecurityContext에 인증 객체 설정 완료");
                    } else {
                        log.debug("SecurityContext에 이미 인증 정보가 존재함");
                    }
                } else {
                    log.warn("JWT 유효성 검사 실패: {}", token);
                }
            } else {
                log.debug("Authorization 헤더에 JWT가 없거나 빈 문자열");
            }

        } catch (Exception e) {
            log.warn("JWT 인증 처리 중 예외 발생 (token: {}): {}", token, e.getMessage(), e);
            SecurityContextHolder.clearContext();  // 예외 발생 시도 보안상 초기화
        }

        filterChain.doFilter(request, response);
    }


    private String resolveToken(HttpServletRequest request) {
        String bearerToken = request.getHeader("Authorization");
        log.debug("Authorization 헤더: {}", bearerToken);
        if (bearerToken != null && bearerToken.startsWith("Bearer ")) {
            String token = bearerToken.substring(7).trim();
            if (!token.isEmpty()) {
                return token;
            }
        }
        return null;
    }
}
