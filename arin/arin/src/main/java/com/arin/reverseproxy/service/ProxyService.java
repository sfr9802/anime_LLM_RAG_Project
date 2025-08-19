package com.arin.reverseproxy.service;

import com.arin.auth.oauth.CustomOAuth2User;
import com.arin.reverseproxy.dto.ProxyRequestDto;
import com.arin.reverseproxy.dto.ProxyResponseDto;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.*;
import org.springframework.security.core.Authentication;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClientResponseException;
import org.springframework.web.client.RestTemplate;

import java.net.URI;
import java.util.*;

@Service
@RequiredArgsConstructor
public class ProxyService {

    private final RestTemplate restTemplate;

    @Value("${proxy.upstream:http://fastapi:8000}") // 고정 업스트림(화이트리스트)
    private String upstreamBase;

    /** POST 프록시 (DTO 기반) */
    public ResponseEntity<?> forward(ProxyRequestDto dto, Authentication auth) {
        // 0) 대상 URL 생성 (path 우선, 없으면 targetUrl 호환)
        String target = buildTargetUrl(dto);
        if (!isAllowed(target)) {
            return ResponseEntity.status(HttpStatus.BAD_REQUEST)
                    .body("bad target: only " + upstreamBase + " is allowed");
        }

        // 1) 헤더 구성
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);

        // 1-1) Spring이 검증한 토큰을 FastAPI로 패스스루
        String bearer = extractBearer(auth);
        if (bearer != null) {
            headers.set(HttpHeaders.AUTHORIZATION, "Bearer " + bearer);
        }

        // 1-2) (선택) 내부 추적용 사용자 헤더 — 있으면 추가, 없으면 생략
        Object principal = (auth != null) ? auth.getPrincipal() : null;
        if (principal instanceof CustomOAuth2User u) {
            headers.set("X-User-Id", String.valueOf(u.getId()));
            if (u.getRole() != null) headers.set("X-User-Role", u.getRole());
        }

        // 2) 바디 구성 — 기존 호환: {"question": "..."}
        Map<String, Object> bodyMap = new HashMap<>();
        if (dto.getQuestion() != null) bodyMap.put("question", dto.getQuestion());
        // 필요하면 dto.getPayload() 같은 필드로 확장

        HttpEntity<Map<String, Object>> entity = new HttpEntity<>(bodyMap, headers);

        // 3) 업스트림 호출 및 결과 포워딩
        try {
            ResponseEntity<ProxyResponseDto> rs = restTemplate.exchange(
                    target, HttpMethod.POST, entity, ProxyResponseDto.class
            );
            // 응답 그대로 전달
            return ResponseEntity.status(rs.getStatusCode())
                    .headers(rs.getHeaders())
                    .body(rs.getBody());
        } catch (RestClientResponseException e) {
            // 업스트림 4xx/5xx는 상태/헤더/바디 그대로 넘김
            HttpHeaders eh = (e.getResponseHeaders() != null) ? e.getResponseHeaders() : new HttpHeaders();
            return new ResponseEntity<>(e.getResponseBodyAsByteArray(), eh, e.getStatusCode());
        } catch (Exception e) {
            return ResponseEntity.status(HttpStatus.BAD_GATEWAY)
                    .body(("LLM Proxy Error: " + e.getMessage()));
        }
    }

    /** dto.path가 있으면 base + path, 아니면 (레거시) dto.targetUrl 사용 */
    private String buildTargetUrl(ProxyRequestDto dto) {
        String base = normalizeBase(upstreamBase);
        String path = (dto.getPath() != null && !dto.getPath().isBlank())
                ? (dto.getPath().startsWith("/") ? dto.getPath() : "/" + dto.getPath())
                : null;

        if (path != null) return base + path;

        // 레거시 호환: targetUrl 허용하되 허용 도메인만
        return dto.getTargetUrl();
    }

    /** 업스트림 호스트/포트 화이트리스트 */
    private boolean isAllowed(String target) {
        try {
            URI t = URI.create(target);
            URI b = URI.create(normalizeBase(upstreamBase));
            String ts = safe(t.getScheme()), bs = safe(b.getScheme());
            String th = safe(t.getHost()),   bh = safe(b.getHost());
            int tp = portOrDefault(t),       bp = portOrDefault(b);
            return ts.equalsIgnoreCase(bs) && th.equalsIgnoreCase(bh) && tp == bp;
        } catch (Exception e) {
            return false;
        }
    }

    private String extractBearer(Authentication auth) {
        if (auth instanceof JwtAuthenticationToken jwt) {
            return jwt.getToken().getTokenValue(); // 원본 Access Token
        }
        return null;
    }

    private static String normalizeBase(String s) {
        if (s == null) return "";
        return s.endsWith("/") ? s.substring(0, s.length() - 1) : s;
    }

    private static String safe(String s) { return (s == null) ? "" : s; }

    private static int portOrDefault(URI u) {
        int p = u.getPort();
        if (p != -1) return p;
        String scheme = safe(u.getScheme()).toLowerCase(Locale.ROOT);
        return "https".equals(scheme) ? 443 : 80;
    }
}
