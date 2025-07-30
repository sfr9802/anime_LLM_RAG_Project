package com.arin.reverseproxy.service;

import com.arin.auth.oauth.CustomOAuth2User;
import com.arin.reverseproxy.dto.ProxyRequestDto;
import lombok.RequiredArgsConstructor;
import org.springframework.http.*;
import org.springframework.security.core.Authentication;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import java.util.Map;

@Service
@RequiredArgsConstructor
public class ProxyService {

    private final RestTemplate restTemplate;  // ← 필드 정의는 클래스 바깥에 있어야 함

    public ResponseEntity<?> forward(ProxyRequestDto dto, Authentication auth) {
        // JWT에서 유저 정보 꺼내기
        CustomOAuth2User user = (CustomOAuth2User) auth.getPrincipal();

        // 유저 정보 로그 or 인증 헤더에 삽입
        System.out.println("프록시 요청 유저: " + user.getId() + " / role: " + user.getRole());

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.set("X-User-Id", user.getId().toString());
        headers.set("X-User-Role", user.getRole());

        Map<String, String> bodyMap = Map.of("query", dto.getQuery());
        HttpEntity<Map<String, String>> entity = new HttpEntity<>(bodyMap, headers);

        try {
            return restTemplate.exchange(
                    dto.getTargetUrl(),
                    HttpMethod.POST,
                    entity,
                    String.class
            );
        } catch (Exception e) {
            return ResponseEntity.status(HttpStatus.BAD_GATEWAY)
                    .body("LLM Proxy Error: " + e.getMessage());
        }
    }
}
