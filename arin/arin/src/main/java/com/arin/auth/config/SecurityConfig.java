package com.arin.auth.config;

import com.arin.auth.jwt.JwtBlacklistFilter;
import com.arin.auth.oauth.CustomOAuth2SuccessHandler;
import com.arin.auth.oauth.CustomOAuth2UserService;
import lombok.RequiredArgsConstructor;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.convert.converter.Converter;
import org.springframework.http.HttpMethod;
import org.springframework.security.authentication.AbstractAuthenticationToken;
import org.springframework.security.config.Customizer;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
// 필요시 메서드 시큐리티 쓰면 열어라
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

import java.time.Duration;
import java.util.List;

@EnableWebSecurity
// @EnableMethodSecurity // @PreAuthorize 쓸 거면 주석 해제
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
                .sessionManagement(sm -> sm.sessionCreationPolicy(SessionCreationPolicy.STATELESS))

                .authorizeHttpRequests(auth -> auth
                        .requestMatchers(HttpMethod.OPTIONS, "/**").permitAll()
                        .requestMatchers(
                                "/", "/login**",
                                "/oauth2/**", "/login/oauth2/code/**",
                                "/api/auth/**", "/api/users/public/**",
                                "/swagger-ui/**", "/v3/api-docs/**",
                                "/actuator/health", "/error"
                        ).permitAll()
                        .requestMatchers(HttpMethod.TRACE, "/**").denyAll()
                        .requestMatchers("/api/admin/**").hasRole("ADMIN")
                        .requestMatchers("/api/manager/**").hasRole("MANAGER")
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

                .addFilterBefore(jwtBlacklistFilter, BearerTokenAuthenticationFilter.class);

        return http.build();
    }

    // ==== JWT 권한 매핑 컨버터 (옵션 B: 커스텀) ====
    @Bean
    public Converter<Jwt, ? extends AbstractAuthenticationToken> compositeJwtAuthConverter() {
        // 네가 만든 컨버터: roles/authorities/scope 병합 + 롤 계층 전개
        return new CompositeJwtAuthConverter();
    }
}
