package com.arin.reverseproxy.service;

import com.arin.auth.oauth.CustomOAuth2User;
import com.arin.reverseproxy.dto.ProxyRequestDto;
import com.arin.reverseproxy.dto.ProxyResponseDto;
import lombok.RequiredArgsConstructor;
import org.springframework.http.*;
import org.springframework.security.core.Authentication;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import java.util.Map;

@Service
@RequiredArgsConstructor
public class ProxyService {

    private final RestTemplate restTemplate;

    public ResponseEntity<?> forward(ProxyRequestDto dto, Authentication auth) {
        CustomOAuth2User user = (CustomOAuth2User) auth.getPrincipal();

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.set("X-User-Id", user.getId().toString());
        headers.set("X-User-Role", user.getRole());

        Map<String, String> bodyMap = Map.of("question", dto.getQuestion());  // ← 변경됨

        HttpEntity<Map<String, String>> entity = new HttpEntity<>(bodyMap, headers);

        try {
            return restTemplate.exchange(
                    dto.getTargetUrl(),
                    HttpMethod.POST,
                    entity,
                    ProxyResponseDto.class
            );
        } catch (Exception e) {
            return ResponseEntity.status(HttpStatus.BAD_GATEWAY)
                    .body("LLM Proxy Error: " + e.getMessage());
        }
    }
}
