package com.arin.proxy.service;

import com.arin.identity.oauth.CustomOAuth2User;
import com.arin.proxy.dto.ProxyRequestDto;
import com.arin.proxy.dto.ProxyResponseDto;
import com.arin.proxy.dto.RagAskDto;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
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
import java.time.Instant;
import java.util.*;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
public class ProxyService {

    private static final String HDR_TRACE     = "X-Trace-Id";
    private static final String HDR_USER_ID   = "X-User-Id";
    private static final String HDR_USER_ROLE = "X-User-Role";
    private static final String HDR_USER_ROLES = "X-User-Roles";

    private final RestTemplate restTemplate;
    private final ObjectMapper om;

    @Value("${proxy.upstream:http://localhost:9000}")
    private String upstreamBase;

    @Value("${proxy.allowed-paths:/rag/ask}")
    private String allowedPaths;

    @Value("${proxy.forward-authorization:false}")
    private boolean forwardAuthorization;

    @Value("${proxy.hmac.secret:}")
    private String hmacSecret;

    public ResponseEntity<?> forward(ProxyRequestDto dto, Authentication auth) {
        String traceId = ensureOrAdoptTraceId(null);
        URI target = buildTargetUri(dto.getPath(), null);
        Map<String, Object> body = Map.of("question", dto.getQuestion());
        HttpHeaders headers = buildBaseHeaders(auth, traceId, target, body);
        return exchange(target, headers, body, dto.getQuestion(), traceId);
    }

    public ResponseEntity<?> forwardAskV2(RagAskDto dto, Authentication auth) {
        String traceId = ensureOrAdoptTraceId(dto.getTraceId());
        URI target = buildTargetUri(dto.getPath(), dto);
        Map<String, Object> body = Map.of("question", dto.getQuestion());
        HttpHeaders headers = buildBaseHeaders(auth, traceId, target, body);
        return exchange(target, headers, body, dto.getQuestion(), traceId);
    }

    private ResponseEntity<?> exchange(URI target, HttpHeaders headers, Map<String, Object> body, String originalQuestion, String traceId) {
        try {
            ResponseEntity<String> rs = restTemplate.exchange(target, HttpMethod.POST, new HttpEntity<>(body, headers), String.class);
            String raw = rs.getBody();
            try {
                JsonNode root = (raw != null && !raw.isBlank()) ? om.readTree(raw) : null;
                String question = (root != null && root.hasNonNull("question")) ? root.get("question").asText() : originalQuestion;
                String answer = (root != null && root.hasNonNull("answer")) ? root.get("answer").asText() : raw;
                return ResponseEntity.status(rs.getStatusCode()).header(HDR_TRACE, traceId).contentType(MediaType.APPLICATION_JSON).body(new ProxyResponseDto(question, answer));
            } catch (Exception ignore) {
                return ResponseEntity.status(rs.getStatusCode()).header(HDR_TRACE, traceId).contentType(MediaType.APPLICATION_JSON).body(new ProxyResponseDto(originalQuestion, raw));
            }
        } catch (RestClientResponseException e) {
            int sc = e.getStatusCode().value();
            HttpHeaders h = new HttpHeaders();
            h.setContentType(MediaType.APPLICATION_JSON);
            h.set(HDR_TRACE, traceId);
            if (sc == HttpStatus.UNAUTHORIZED.value()) h.set("X-Proxy-Upstream-Auth", "401");
            else if (sc == HttpStatus.FORBIDDEN.value()) h.set("X-Proxy-Upstream-Auth", "403");
            ProxyErrorBody err = ProxyErrorBody.fromUpstream(e, traceId);
            return ResponseEntity.status(e.getStatusCode()).headers(h).body(err);
        } catch (Exception e) {
            HttpHeaders h = new HttpHeaders();
            h.setContentType(MediaType.APPLICATION_JSON);
            h.set(HDR_TRACE, traceId);
            ProxyErrorBody err = ProxyErrorBody.gatewayError(traceId, e);
            return ResponseEntity.status(HttpStatus.BAD_GATEWAY).headers(h).body(err);
        }
    }

    private HttpHeaders buildBaseHeaders(Authentication auth, String traceId, URI target, Map<String, Object> body) {
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.setAccept(List.of(MediaType.APPLICATION_JSON));
        headers.set(HDR_TRACE, traceId);
        if (forwardAuthorization) {
            String bearer = extractBearer(auth);
            if (bearer != null) headers.set(HttpHeaders.AUTHORIZATION, "Bearer " + bearer);
        }
        resolveUserId(auth).ifPresent(v -> headers.set(HDR_USER_ID, String.valueOf(v)));
        List<String> roles = resolveRoles(auth);
        if (!roles.isEmpty()) {
            headers.set(HDR_USER_ROLE, roles.get(0));
            headers.set(HDR_USER_ROLES, String.join(",", roles));
        }
        if (hmacSecret != null && !hmacSecret.isBlank()) {
            try {
                String ts = String.valueOf(Instant.now().getEpochSecond());
                String canonicalBody = canonicalJson(body);
                String signingTarget = "POST\n" + target.getRawPath() + "\n" + nvl(target.getRawQuery()) + "\n" + ts + "\n" + canonicalBody;
                String sig = hmacSha256Hex(hmacSecret, signingTarget);
                headers.set("X-Ts", ts);
                headers.set("X-Sig", sig);
            } catch (Exception ignore) {}
        }
        return headers;
    }

    private OptionalLong resolveUserId(Authentication auth) {
        if (auth == null) return OptionalLong.empty();
        Object p = auth.getPrincipal();
        if (p instanceof CustomOAuth2User u) return OptionalLong.of(u.getId());
        if (auth instanceof JwtAuthenticationToken jwt) {
            var claims = jwt.getToken().getClaims();
            Object uid = claims.get("userId");
            if (uid != null) {
                try { return OptionalLong.of(Long.parseLong(uid.toString())); }
                catch (NumberFormatException ignored) {}
            }
        }
        return OptionalLong.empty();
    }

    private List<String> resolveRoles(Authentication auth) {
        if (auth == null) return List.of();
        List<String> fromAuthorities = auth.getAuthorities().stream()
                .map(GrantedAuthority::getAuthority).filter(Objects::nonNull).distinct().sorted().collect(Collectors.toList());
        if (!fromAuthorities.isEmpty()) return fromAuthorities;
        if (auth instanceof JwtAuthenticationToken jwt) {
            var claims = jwt.getToken().getClaims();
            Object roles = claims.get("roles");
            if (roles instanceof Collection<?> c) {
                return c.stream().filter(Objects::nonNull).map(Object::toString).map(this::normalizeRole).distinct().sorted().collect(Collectors.toList());
            }
            Object auths = claims.get("authorities");
            if (auths instanceof Collection<?> c2) {
                return c2.stream().filter(Objects::nonNull).map(Object::toString).map(this::normalizeRole).distinct().sorted().collect(Collectors.toList());
            }
        }
        return List.of();
    }

    private String normalizeRole(String r) {
        if (r == null) return "";
        if (r.startsWith("ROLE_")) return r;
        return "ROLE_" + r;
    }

    private URI buildTargetUri(String pathFromDto, RagAskDto v2) {
        String base = rstrip(upstreamBase);
        String path = (pathFromDto != null && !pathFromDto.isBlank()) ? pathFromDto.trim() : "/rag/ask";
        if (!path.startsWith("/")) path = "/" + path;
        if (!isAllowedPath(path)) throw new IllegalArgumentException("forbidden path: " + path);
        UriComponentsBuilder b = UriComponentsBuilder.fromUriString(base + path);
        if (v2 != null) {
            if (v2.getK() != null) b.queryParam("k", v2.getK());
            if (v2.getCandidateK() != null) b.queryParam("candidate_k", v2.getCandidateK());
            if (v2.getUseMmr() != null) b.queryParam("use_mmr", v2.getUseMmr());
            if (v2.getLam() != null) b.queryParam("lam", v2.getLam());
            if (v2.getMaxTokens() != null) b.queryParam("max_tokens", v2.getMaxTokens());
            if (v2.getTemperature() != null) b.queryParam("temperature", v2.getTemperature());
            if (v2.getPreviewChars() != null) b.queryParam("preview_chars", v2.getPreviewChars());
        }
        return b.build(true).toUri();
    }

    private boolean isAllowedPath(String path) {
        Set<String> allow = Arrays.stream(allowedPaths.split(",")).map(String::trim).filter(s -> !s.isEmpty()).collect(Collectors.toSet());
        return allow.contains(path);
    }

    private static String extractBearer(Authentication auth) {
        if (auth instanceof JwtAuthenticationToken jwt) return jwt.getToken().getTokenValue();
        return null;
    }

    private String canonicalJson(Object body) throws JsonProcessingException {
        ObjectMapper signer = om.copy();
        signer.configure(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS, true);
        return signer.writeValueAsString(body);
    }

    private static String ensureOrAdoptTraceId(String requested) {
        String existing = MDC.get(HDR_TRACE);
        if (isUuid(requested)) { MDC.put(HDR_TRACE, requested); return requested; }
        if (isUuid(existing)) return existing;
        String tid = UUID.randomUUID().toString();
        MDC.put(HDR_TRACE, tid);
        return tid;
    }

    private static boolean isUuid(String s) {
        if (s == null || s.isBlank()) return false;
        try { UUID.fromString(s.trim()); return true; } catch (Exception e) { return false; }
    }

    private static String hmacSha256Hex(String secret, String data) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
            byte[] sig = mac.doFinal(data.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(sig);
        } catch (Exception e) { return ""; }
    }

    private static String rstrip(String s) { return (s != null && s.endsWith("/")) ? s.substring(0, s.length() - 1) : s; }
    private static String nvl(String s) { return (s == null) ? "" : s; }

    public record ProxyErrorBody(String traceId, int status, String error, String message, String upstreamBody) {
        static ProxyErrorBody fromUpstream(RestClientResponseException e, String traceId) {
            String upstream = safeTrim(e.getResponseBodyAsString());
            String msg = safeTrim(e.getMessage());
            return new ProxyErrorBody(traceId, e.getStatusCode().value(), "UPSTREAM_ERROR", msg, upstream);
        }
        static ProxyErrorBody gatewayError(String traceId, Exception e) {
            return new ProxyErrorBody(traceId, 502, "BAD_GATEWAY", safeTrim(e.getMessage()), null);
        }
        private static String safeTrim(String s) {
            if (s == null) return null;
            String t = s.trim();
            return t.isEmpty() ? null : t;
        }
    }
}
