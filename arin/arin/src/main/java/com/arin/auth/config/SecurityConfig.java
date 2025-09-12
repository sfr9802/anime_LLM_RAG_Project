package com.arin.auth.config;

import com.arin.auth.jwt.JwtBlacklistFilter;
import com.arin.auth.oauth.CustomOAuth2SuccessHandler;
import com.arin.auth.oauth.CustomOAuth2UserService;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.convert.converter.Converter;
import org.springframework.http.HttpMethod;
import org.springframework.security.authentication.AbstractAuthenticationToken;
import org.springframework.security.config.Customizer;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
// import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.config.annotation.web.configurers.RequestCacheConfigurer;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.server.resource.web.authentication.BearerTokenAuthenticationFilter;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.CorsConfigurationSource;
import org.springframework.web.cors.UrlBasedCorsConfigurationSource;

import java.util.List;

@EnableWebSecurity
// @EnableMethodSecurity
@Configuration
@RequiredArgsConstructor
public class SecurityConfig {

    private final CustomOAuth2UserService customOAuth2UserService;
    private final CustomOAuth2SuccessHandler customOAuth2SuccessHandler;
    private final JwtBlacklistFilter jwtBlacklistFilter;

    @Bean
    public SecurityFilterChain securityFilterChain(HttpSecurity http) throws Exception {
        http
                .csrf(AbstractHttpConfigurer::disable)
                .httpBasic(AbstractHttpConfigurer::disable)
                .cors(Customizer.withDefaults())
//                .sessionManagement(sm -> sm.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .sessionManagement(sm -> sm.sessionCreationPolicy(SessionCreationPolicy.IF_REQUIRED))

                .authorizeHttpRequests(auth -> auth
                        .requestMatchers(HttpMethod.OPTIONS, "/**").permitAll()

                        // ✅ 인증 플로우에 필요한 공개 엔드포인트만 열기
                        .requestMatchers(
                                "/oauth2/**", "/login/oauth2/code/**",
                                "/api/auth/exchange", "/api/auth/refresh", "/api/auth/logout"
                        ).permitAll()

                        // 공개 유저 리소스가 따로 있으면 유지
                        .requestMatchers("/api/users/public/**").permitAll()

                        // 문서/헬스 (dev/prod 프로필에 맞게 유지)
                        .requestMatchers("/swagger-ui/**", "/v3/api-docs/**").permitAll()
                        .requestMatchers("/actuator/health", "/error").permitAll()

                        // 관리자/매니저 보호
                        .requestMatchers("/api/admin/**").hasRole("ADMIN")
                        .requestMatchers("/api/manager/**").hasRole("MANAGER")

                        // 프록시는 인증 필요
                        .requestMatchers("/api/proxy/**").authenticated()

                        .anyRequest().authenticated()
                )

                .oauth2Login(oauth -> oauth
                        .userInfoEndpoint(u -> u.userService(customOAuth2UserService))
                        .successHandler(customOAuth2SuccessHandler)
                )

                .oauth2ResourceServer(oauth2 -> oauth2
                        .jwt(jwt -> jwt.jwtAuthenticationConverter(compositeJwtAuthConverter()))
                )

                .requestCache(RequestCacheConfigurer::disable)

                .exceptionHandling(ex -> ex
                        .authenticationEntryPoint((req, res, e) -> {
                            res.setStatus(401);
                            res.setContentType("application/json;charset=UTF-8");
                            res.getWriter().write("{\"error\":\"unauthorized\"}");
                        })
                        .accessDeniedHandler((req, res, e) -> {
                            res.setStatus(403);
                            res.setContentType("application/json;charset=UTF-8");
                            res.getWriter().write("{\"error\":\"forbidden\"}");
                        })
                )

                // ✅ Bearer 토큰이 파싱된 뒤 블랙리스트 여부를 확인
                .addFilterAfter(jwtBlacklistFilter, BearerTokenAuthenticationFilter.class);

        return http.build();
    }

    @Bean
    public Converter<Jwt, ? extends AbstractAuthenticationToken> compositeJwtAuthConverter() {
        // 네가 만든 컨버터: roles/authorities/scope 병합 + 롤 계층 전개
        return new CompositeJwtAuthConverter();
    }

    /**
     * CORS 설정 (이미 WebCorsConfig가 있으면 이 Bean은 생략해도 됨)
     * - 프론트에서 credentials: 'include' 로 쿠키 전송하기 위해 allowCredentials=true 필요
     * - allowedOrigins는 정확히 한정 (와일드카드 금지)
     */
    // SecurityConfig.java
    // SecurityConfig.java
    @Bean
    public CorsConfigurationSource corsConfigurationSource(
            @Value("${app.front.origin:http://localhost}") String frontOrigin) {
        CorsConfiguration cfg = new CorsConfiguration();
        cfg.setAllowCredentials(true);

        // nginx 80 기준 오리진 허용
        cfg.setAllowedOriginPatterns(List.of(
                frontOrigin,
                "http://127.0.0.1"
        ));

        cfg.setAllowedMethods(List.of("GET","POST","PUT","PATCH","DELETE","OPTIONS"));
        cfg.setAllowedHeaders(List.of("*"));
        cfg.setExposedHeaders(List.of("Set-Cookie","X-Trace-Id"));

        UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource();
        source.registerCorsConfiguration("/**", cfg);
        return source;
    }


}
