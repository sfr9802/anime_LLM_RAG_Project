package com.arin.reverseproxy.service;

import com.arin.auth.oauth.CustomOAuth2User;
import com.arin.reverseproxy.dto.ProxyRequestDto;
import com.arin.reverseproxy.dto.ProxyResponseDto;
import com.arin.reverseproxy.dto.RagAskDto;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import org.slf4j.MDC;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.*;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClientResponseException;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.util.UriComponentsBuilder;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.*;

@Service
@RequiredArgsConstructor
public class ProxyService {

    private static final String HDR_TRACE     = "X-Trace-Id";
    private static final String HDR_USER_ID   = "X-User-Id";
    private static final String HDR_USER_ROLE = "X-User-Role";

    private final RestTemplate restTemplate;
    private final ObjectMapper om = new ObjectMapper();

    @Value("${proxy.upstream:http://localhost:9000}")
    private String upstreamBase;

    @Value("${proxy.allowed-path-prefixes:/rag/}")
    private String allowedPathPrefixes;

    // Authorization 헤더 전달 여부 (FastAPI가 스프링 JWT를 검증할 때만 true)
    @Value("${proxy.forward-authorization:false}")
    private boolean forwardAuthorization;

    // 바디 서명용 (선택)
    @Value("${proxy.hmac.secret:}")
    private String hmacSecret;

    // ---------- v1 (하위호환) ----------
    public ResponseEntity<?> forward(ProxyRequestDto dto, Authentication auth) {
        URI target = buildTargetUriV1(dto);
        if (isForbiddenHost(target) || isForbiddenPath(target.getPath())) {
            return withTrace(ResponseEntity.badRequest(), "forbidden target: " + target);
        }
        String traceId = ensureTraceId();
        Map<String, Object> body = Map.of("question", dto.getQuestion());
        HttpHeaders headers = buildBaseHeaders(auth, traceId, body);
        return exchange(target, headers, body, dto.getQuestion(), traceId);
    }

    // ---------- v2 (RAG 파라미터) ----------
    public ResponseEntity<?> forwardAskV2(RagAskDto dto, Authentication auth) {
        URI target = buildTargetUriV2(dto);
        if (isForbiddenHost(target) || isForbiddenPath(target.getPath())) {
            return withTrace(ResponseEntity.badRequest(), "forbidden target: " + target);
        }
        String traceId = (dto.getTraceId() != null && !dto.getTraceId().isBlank())
                ? dto.getTraceId() : ensureTraceId();

        Map<String, Object> body = Map.of("question", dto.getQuestion());
        HttpHeaders headers = buildBaseHeaders(auth, traceId, body);
        return exchange(target, headers, body, dto.getQuestion(), traceId);
    }

    // ---------- 공통 ----------
    private ResponseEntity<?> exchange(URI target, HttpHeaders headers, Map<String, Object> body,
                                       String originalQuestion, String traceId) {
        try {
            ResponseEntity<String> rs = restTemplate.exchange(target, HttpMethod.POST, new HttpEntity<>(body, headers), String.class);

            try {
                JsonNode root = (rs.getBody() != null) ? om.readTree(rs.getBody()) : null;
                String question = (root != null && root.hasNonNull("question")) ? root.get("question").asText() : originalQuestion;
                String answer   = (root != null && root.hasNonNull("answer"))   ? root.get("answer").asText()   : rs.getBody();
                return ResponseEntity.status(rs.getStatusCode())
                        .header(HDR_TRACE, traceId)
                        .body(new ProxyResponseDto(question, answer));
            } catch (Exception ignore) {
                return ResponseEntity.status(rs.getStatusCode())
                        .header(HDR_TRACE, traceId)
                        .body(rs.getBody());
            }

        } catch (RestClientResponseException e) {
            // 읽기 전용 헤더 복사 (전송/인코딩 관련 헤더는 제거)
            HttpHeaders h = new HttpHeaders();
            if (e.getResponseHeaders() != null) {
                e.getResponseHeaders().forEach((k, v) -> {
                    if (k == null) return;
                    if (!HttpHeaders.CONTENT_LENGTH.equalsIgnoreCase(k)
                            && !HttpHeaders.TRANSFER_ENCODING.equalsIgnoreCase(k)
                            && !HttpHeaders.CONTENT_ENCODING.equalsIgnoreCase(k)
                            && !HttpHeaders.CONNECTION.equalsIgnoreCase(k)) {
                        if (v != null && !v.isEmpty()) {
                            h.put(k, new java.util.ArrayList<>(v));
                        }
                    }
                });
            }

            // 상태코드 (getRawStatusCode() 대체)
            var status = e.getStatusCode(); // HttpStatusCode
            int sc = status.value();

            // 업스트림 인증 실패 마커(프론트 인터셉터에서 리다이렉트 방지용)
            if (sc == org.springframework.http.HttpStatus.UNAUTHORIZED.value()) {       // 401
                h.set("X-Proxy-Upstream-Auth", "401");
            } else if (sc == org.springframework.http.HttpStatus.FORBIDDEN.value()) {   // 403 (옵션)
                h.set("X-Proxy-Upstream-Auth", "403");
            }

            // 안전하게 JSON으로 고정 (본문은 String으로 내려가므로 길이 헤더는 세팅하지 않음)
            h.setContentType(org.springframework.http.MediaType.APPLICATION_JSON);

            return org.springframework.http.ResponseEntity
                    .status(status)                // HttpStatusCode 그대로 사용
                    .headers(h)
                    .header(HDR_TRACE, traceId)
                    .body(e.getResponseBodyAsString());


    } catch (Exception e) {
            return ResponseEntity.status(HttpStatus.BAD_GATEWAY)
                    .header(HDR_TRACE, traceId)
                    .body("LLM Proxy Error: " + e.getMessage());
        }
    }

    private HttpHeaders buildBaseHeaders(Authentication auth, String traceId, Map<String, Object> body) {
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.setAccept(List.of(MediaType.APPLICATION_JSON));
        headers.set(HDR_TRACE, traceId);

        // 1) Authorization 전달(토글)
        if (forwardAuthorization) {
            String bearer = extractBearer(auth);
            if (bearer != null) headers.set(HttpHeaders.AUTHORIZATION, "Bearer " + bearer);
        }

        // 2) 사용자 컨텍스트 (게이트웨이 신뢰)
        resolveUserId(auth).ifPresent(v -> headers.set(HDR_USER_ID, String.valueOf(v)));
        String role = resolveRole(auth);
        if (role != null && !role.isBlank()) headers.set(HDR_USER_ROLE, role);

        // 3) (옵션) 요청 바디 HMAC 서명
        if (hmacSecret != null && !hmacSecret.isBlank()) {
            try {
                String payload = om.writeValueAsString(body);
                String ts = String.valueOf(System.currentTimeMillis() / 1000);
                String sig = hmacSha256Hex(hmacSecret, ts + "." + payload);
                headers.set("X-Ts", ts);
                headers.set("X-Sig", sig);
            } catch (Exception ignore) { /* 실패 시 생략 */ }
        }
        return headers;
    }

    private OptionalLong resolveUserId(Authentication auth) {
        if (auth == null) return OptionalLong.empty();
        Object p = auth.getPrincipal();
        if (p instanceof CustomOAuth2User u) return OptionalLong.of(u.getId());

        if (auth instanceof JwtAuthenticationToken jwt) {
            var claims = jwt.getToken().getClaims();
            Object sub = claims.get("sub");
            if (sub != null) {
                try { return OptionalLong.of(Long.parseLong(sub.toString())); } catch (NumberFormatException ignored) {}
            }
            Object uid = claims.get("userId");
            if (uid != null) {
                try { return OptionalLong.of(Long.parseLong(uid.toString())); } catch (NumberFormatException ignored) {}
            }
        }
        return OptionalLong.empty();
    }

    private String resolveRole(Authentication auth) {
        if (auth == null) return null;

        // 1) Spring Security 권한 사용 (ROLE_* 형태)
        Optional<String> firstAuth = auth.getAuthorities().stream()
                .map(GrantedAuthority::getAuthority)
                .filter(Objects::nonNull)
                .findFirst();
        if (firstAuth.isPresent()) return firstAuth.get();

        // 2) JWT claims에서 roles/authorities
        if (auth instanceof JwtAuthenticationToken jwt) {
            var claims = jwt.getToken().getClaims();
            Object roles = claims.get("roles");
            if (roles instanceof Collection<?> c && !c.isEmpty()) return "ROLE_" + c.iterator().next().toString();
            Object auths = claims.get("authorities");
            if (auths instanceof Collection<?> c2 && !c2.isEmpty()) return c2.iterator().next().toString();
        }
        return null;
    }

    private URI buildTargetUriV1(ProxyRequestDto dto) {
        if (dto.getTargetUrl() != null && !dto.getTargetUrl().isBlank()) return URI.create(dto.getTargetUrl());
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
        if (dto.getK() != null)             b.queryParam("k", dto.getK());
        if (dto.getCandidateK() != null)    b.queryParam("candidate_k", dto.getCandidateK());
        if (dto.getUseMmr() != null)        b.queryParam("use_mmr", dto.getUseMmr());
        if (dto.getLam() != null)           b.queryParam("lam", dto.getLam());
        if (dto.getMaxTokens() != null)     b.queryParam("max_tokens", dto.getMaxTokens());
        if (dto.getTemperature() != null)   b.queryParam("temperature", dto.getTemperature());
        if (dto.getPreviewChars() != null)  b.queryParam("preview_chars", dto.getPreviewChars());
        return b.build(true).toUri();
    }

    private boolean isForbiddenHost(URI target) {
        try {
            URI base = URI.create(rstrip(upstreamBase));
            String ts = nvl(target.getScheme()), bs = nvl(base.getScheme());
            String th = nvl(target.getHost()),   bh = nvl(base.getHost());
            int tp = portOrDefault(target),      bp = portOrDefault(base);
            return !(ts.equalsIgnoreCase(bs) && th.equalsIgnoreCase(bh) && tp == bp);
        } catch (Exception e) { return true; }
    }

    private boolean isForbiddenPath(String path) {
        if (path == null) return true;
        for (String pref : allowedPathPrefixes.split(",")) {
            String p = pref.trim();
            if (!p.isEmpty() && path.startsWith(p)) return false;
        }
        return true;
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

    private static String ensureTraceId() {
        String tid = MDC.get(HDR_TRACE);
        if (tid == null || tid.isBlank()) {
            tid = UUID.randomUUID().toString();
            MDC.put(HDR_TRACE, tid);
        }
        return tid;
    }

    private static String hmacSha256Hex(String secret, String data) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
            byte[] sig = mac.doFinal(data.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(sig);
        } catch (Exception e) { return ""; }
    }

    private static <T> ResponseEntity<T> withTrace(ResponseEntity.BodyBuilder b, T body) {
        String tid = Optional.ofNullable(MDC.get(HDR_TRACE)).orElse(UUID.randomUUID().toString());
        return b.header(HDR_TRACE, tid).body(body);
    }
}
