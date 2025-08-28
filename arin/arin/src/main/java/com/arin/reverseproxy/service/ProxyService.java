package com.arin.reverseproxy.service;

import com.arin.auth.oauth.CustomOAuth2User;
import com.arin.reverseproxy.dto.ProxyRequestDto;
import com.arin.reverseproxy.dto.ProxyResponseDto;
import com.arin.reverseproxy.dto.RagAskDto;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.*;
import org.springframework.security.core.Authentication;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClientResponseException;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.util.UriComponentsBuilder;

import java.net.URI;
import java.util.*;

@Service
@RequiredArgsConstructor
public class ProxyService {

    private final RestTemplate restTemplate;
    private final ObjectMapper om = new ObjectMapper();

    @Value("${proxy.upstream:http://fastapi:9000}")
    private String upstreamBase;

    @Value("${proxy.allowed-path-prefixes:/rag/}")
    private String allowedPathPrefixes;

    // ---------- v1: 기존 DTO 경로(하위호환) ----------
    public ResponseEntity<?> forward(ProxyRequestDto dto, Authentication auth) {
        // 인증 체크는 컨트롤러 @PreAuthorize("isAuthenticated()")에서 처리

        URI target = buildTargetUriV1(dto);
        if (isForbiddenHost(target) || isForbiddenPath(target.getPath())) {
            return ResponseEntity.badRequest().body("forbidden target: " + target);
        }

        HttpHeaders headers = buildBaseHeaders(auth, UUID.randomUUID().toString());
        Map<String, Object> body = Map.of("question", dto.getQuestion());

        return exchange(target, headers, body, dto.getQuestion());
    }

    // ---------- v2: RAG 파라미터 포함 ----------
    public ResponseEntity<?> forwardAskV2(RagAskDto dto, Authentication auth) {
        // 인증 체크는 컨트롤러 @PreAuthorize("isAuthenticated()")에서 처리

        URI target = buildTargetUriV2(dto);
        if (isForbiddenHost(target) || isForbiddenPath(target.getPath())) {
            return ResponseEntity.badRequest().body("forbidden target: " + target);
        }

        HttpHeaders headers = buildBaseHeaders(auth,
                dto.getTraceId() != null ? dto.getTraceId() : UUID.randomUUID().toString());
        Map<String, Object> body = Map.of("question", dto.getQuestion());

        return exchange(target, headers, body, dto.getQuestion());
    }

    // ---------- 공통 헬퍼 ----------
    private ResponseEntity<?> exchange(URI target, HttpHeaders headers, Map<String, Object> body, String originalQuestion) {
        HttpEntity<Map<String, Object>> entity = new HttpEntity<>(body, headers);
        try {
            ResponseEntity<String> rs = restTemplate.exchange(target, HttpMethod.POST, entity, String.class);
            // 가능하면 축약 DTO로, 아니면 raw
            try {
                JsonNode root = (rs.getBody() != null) ? om.readTree(rs.getBody()) : null;
                String question = (root != null && root.hasNonNull("question"))
                        ? root.get("question").asText()
                        : originalQuestion;
                String answer = (root != null && root.hasNonNull("answer"))
                        ? root.get("answer").asText()
                        : rs.getBody();
                return ResponseEntity.status(rs.getStatusCode())
                        .body(new ProxyResponseDto(question, answer));
            } catch (Exception ignore) {
                return ResponseEntity.status(rs.getStatusCode()).body(rs.getBody());
            }
        } catch (RestClientResponseException e) {
            return new ResponseEntity<>(
                    e.getResponseBodyAsString(),
                    e.getResponseHeaders() != null ? e.getResponseHeaders() : new HttpHeaders(),
                    e.getStatusCode()
            );
        } catch (Exception e) {
            return ResponseEntity.status(HttpStatus.BAD_GATEWAY).body("LLM Proxy Error: " + e.getMessage());
        }
    }

    private HttpHeaders buildBaseHeaders(Authentication auth, String traceId) {
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.setAccept(List.of(MediaType.APPLICATION_JSON));

        // auth가 null이어도 안전하게 (이상 상황 대비; 정상 경로는 @PreAuthorize가 보장)
        String bearer = extractBearer(auth);
        if (bearer != null) headers.set(HttpHeaders.AUTHORIZATION, "Bearer " + bearer);

        headers.addIfAbsent("X-Trace-Id", traceId);

        Object principal = (auth != null) ? auth.getPrincipal() : null;
        if (principal instanceof CustomOAuth2User u) {
            headers.set("X-User-Id", String.valueOf(u.getId()));
            if (u.getRole() != null) headers.set("X-User-Role", u.getRole());
        }
        return headers;
    }

    private URI buildTargetUriV1(ProxyRequestDto dto) {
        if (dto.getTargetUrl() != null && !dto.getTargetUrl().isBlank()) {
            return URI.create(dto.getTargetUrl());
        }
        String base = rstrip(upstreamBase);
        String path = (dto.getPath() != null && !dto.getPath().isBlank()) ? dto.getPath() : "/rag/ask";
        if (!path.startsWith("/")) path = "/" + path;
        return UriComponentsBuilder.fromUriString(base + path).build(true).toUri();
    }

    private URI buildTargetUriV2(RagAskDto dto) {
        String base = rstrip(upstreamBase);
        String path = (dto.getPath() != null && !dto.getPath().isBlank()) ? dto.getPath() : "/rag/ask";
        if (!path.startsWith("/")) path = "/" + path;

        UriComponentsBuilder b = UriComponentsBuilder.fromUriString(base + path);
        // FastAPI는 쿼리스트링으로 받는 파라미터들
        if (dto.getK() != null) b.queryParam("k", dto.getK());
        if (dto.getCandidateK() != null) b.queryParam("candidate_k", dto.getCandidateK());
        if (dto.getUseMmr() != null) b.queryParam("use_mmr", dto.getUseMmr());
        if (dto.getLam() != null) b.queryParam("lam", dto.getLam());
        if (dto.getMaxTokens() != null) b.queryParam("max_tokens", dto.getMaxTokens());
        if (dto.getTemperature() != null) b.queryParam("temperature", dto.getTemperature());
        if (dto.getPreviewChars() != null) b.queryParam("preview_chars", dto.getPreviewChars());
        return b.build(true).toUri();
    }

    private boolean isForbiddenHost(URI target) {
        try {
            URI base = URI.create(rstrip(upstreamBase));
            String ts = nvl(target.getScheme()), bs = nvl(base.getScheme());
            String th = nvl(target.getHost()),   bh = nvl(base.getHost());
            int tp = portOrDefault(target),      bp = portOrDefault(base);
            // 허용조건을 만족하지 않으면 금지
            return !(ts.equalsIgnoreCase(bs) && th.equalsIgnoreCase(bh) && tp == bp);
        } catch (Exception e) {
            return true; // 파싱 실패 == 금지
        }
    }

    private boolean isForbiddenPath(String path) {
        if (path == null) return true;
        for (String pref : allowedPathPrefixes.split(",")) {
            String p = pref.trim();
            if (!p.isEmpty() && path.startsWith(p)) return false; // 허용 prefix 발견 → 금지 아님
        }
        return true; // 어떤 허용 prefix에도 해당 안 되면 금지
    }

    private static String extractBearer(Authentication auth) {
        if (auth instanceof JwtAuthenticationToken jwt) {
            return jwt.getToken().getTokenValue();
        }
        return null;
    }

    private static String rstrip(String s) { return (s != null && s.endsWith("/")) ? s.substring(0, s.length()-1) : s; }
    private static String nvl(String s) { return (s == null) ? "" : s; }
    private static int portOrDefault(URI u) {
        int p = u.getPort();
        if (p != -1) return p;
        return "https".equals(nvl(u.getScheme()).toLowerCase(Locale.ROOT)) ? 443 : 80;
    }
}
