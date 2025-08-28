package com.arin.reverseproxy.service;

import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.*;
import org.springframework.security.core.Authentication;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.stereotype.Service;
import org.springframework.util.StreamUtils;
import org.springframework.web.client.RestClientResponseException;
import org.springframework.web.client.RestTemplate;

import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.*;

@Service
@RequiredArgsConstructor
public class ReverseProxyService {

    private final RestTemplate proxyRestTemplate;

    @Value("${proxy.upstream:http://fastapi:9000}")
    private String upstreamBase;

    // 전달 금지 헤더(소문자 비교)
    private static final Set<String> HOP = new HashSet<>(Arrays.asList(
            "connection","keep-alive","proxy-authenticate","proxy-authorization",
            "te","trailer","transfer-encoding","upgrade",
            "host","content-length","accept-encoding","content-encoding"
    ));

    /** 일반 프록시 엔드포인트 처리 */
    public ResponseEntity<byte[]> forward(HttpServletRequest req,
                                          Authentication auth,
                                          byte[] incomingBodyOrNull) {
        if (auth == null || auth.getPrincipal() == null) {
            return ResponseEntity.status(401).build();
        }

        final HttpMethod method;
        try {
            method = HttpMethod.valueOf(req.getMethod());
        } catch (IllegalArgumentException e) {
            return ResponseEntity.status(405)
                    .body(("Unsupported method: " + req.getMethod()).getBytes(StandardCharsets.UTF_8));
        }

        final String target = buildUpstreamUri(req);

        HttpHeaders headers = copyRequestHeaders(req);
        addForwardedHeaders(headers, req);

        // Spring이 검증한 JWT → FastAPI로 패스스루
        String token = extractBearer(auth);
        if (token != null) headers.set(HttpHeaders.AUTHORIZATION, "Bearer " + token);

        byte[] payload = supportsBody(method)
                ? ((incomingBodyOrNull != null) ? incomingBodyOrNull : readBody(req))
                : null;

        RequestEntity<byte[]> rq = new RequestEntity<>(
                (payload == null || payload.length == 0) ? null : payload,
                headers, method, URI.create(target)
        );

        try {
            ResponseEntity<byte[]> rs = proxyRestTemplate.exchange(rq, byte[].class);
            return copyResponse(rs);
        } catch (RestClientResponseException e) {
            HttpHeaders eh = new HttpHeaders();
            if (e.getResponseHeaders() != null) {
                e.getResponseHeaders().forEach((k, v) -> {
                    if (!HOP.contains(k.toLowerCase())) eh.put(k, v);
                });
            }
            HttpStatusCode sc = e.getStatusCode();
            return new ResponseEntity<>(e.getResponseBodyAsByteArray(), eh, sc);
        } catch (Exception e) {
            return ResponseEntity.status(502)
                    .body(("Proxy error: " + e.getMessage()).getBytes(StandardCharsets.UTF_8));
        }
    }

    // ===== helpers =====

    private String buildUpstreamUri(HttpServletRequest req) {
        String uri = req.getRequestURI();
        String prefix = getProxyPrefix(req);
        int idx = uri.indexOf(prefix);
        String after = (idx >= 0) ? uri.substring(idx + prefix.length()) : "";
        if (!after.startsWith("/")) after = "/" + after;

        String base = (upstreamBase != null && upstreamBase.endsWith("/"))
                ? upstreamBase.substring(0, upstreamBase.length() - 1)
                : upstreamBase;

        String q = req.getQueryString();
        return base + after + (q != null ? "?" + q : "");
    }

    private String getProxyPrefix(HttpServletRequest req) {
        String sp = req.getServletPath();
        return (sp == null || sp.isEmpty()) ? "/api/proxy" : sp;
    }

    private HttpHeaders copyRequestHeaders(HttpServletRequest req) {
        HttpHeaders h = new HttpHeaders();
        for (Enumeration<String> en = req.getHeaderNames(); en.hasMoreElements();) {
            String name = en.nextElement();
            if (name == null) continue;
            String low = name.toLowerCase();
            if (HOP.contains(low)) continue;
            List<String> values = Collections.list(req.getHeaders(name));
            if (!values.isEmpty()) h.put(name, values);
        }
        return h;
    }

    private void addForwardedHeaders(HttpHeaders h, HttpServletRequest req) {
        if (!h.containsKey("X-Forwarded-For") && req.getRemoteAddr() != null) {
            h.add("X-Forwarded-For", req.getRemoteAddr());
        }
        if (!h.containsKey("X-Forwarded-Proto") && req.getScheme() != null) {
            h.add("X-Forwarded-Proto", req.getScheme());
        }
        if (!h.containsKey("X-Forwarded-Host") && req.getServerName() != null) {
            String host = req.getServerName();
            if (req.getServerPort() > 0) host += ":" + req.getServerPort();
            h.add("X-Forwarded-Host", host);
        }
    }

    // enum 상수 대신 문자열 비교 → 심볼 오류 회피
    private static boolean supportsBody(HttpMethod m) {
        if (m == null) return false;
        String n = m.name();
        return !("GET".equals(n) || "HEAD".equals(n) || "OPTIONS".equals(n) || "TRACE".equals(n));
    }

    private static byte[] readBody(HttpServletRequest req) {
        try { return StreamUtils.copyToByteArray(req.getInputStream()); }
        catch (Exception e) { return null; }
    }

    private String extractBearer(Authentication a) {
        if (a instanceof JwtAuthenticationToken jwt) {
            return jwt.getToken().getTokenValue();
        }
        return null;
    }

    private ResponseEntity<byte[]> copyResponse(ResponseEntity<byte[]> rs) {
        HttpHeaders out = new HttpHeaders();
        rs.getHeaders().forEach((k, v) -> { if (!HOP.contains(k.toLowerCase())) out.put(k, v); });
        return new ResponseEntity<>(rs.getBody(), out, rs.getStatusCode());
    }
}
