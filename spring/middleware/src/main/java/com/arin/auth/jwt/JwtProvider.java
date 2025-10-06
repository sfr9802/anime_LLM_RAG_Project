package com.arin.auth.jwt;

import io.jsonwebtoken.*;
import jakarta.annotation.PostConstruct;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import javax.crypto.SecretKey;
import java.util.*;
import java.util.Date;

@Slf4j
@Component
@RequiredArgsConstructor
public class JwtProvider {

    private final SecretKey jwtHmacKey; // ✅ Bean 주입 (JwtCryptoConfig)

    @Value("${jwt.expiration}")         private long  expirationMs;
    @Value("${jwt.refresh-expiration}") private long  refreshExpirationMs;
    @Value("${jwt.issuer:arin}")        private String issuer;
    @Value("${jwt.audience:frontend}")  private String audience;
    @Value("${jwt.clock-skew-seconds:60}") private long clockSkewSeconds;
    @Value("${jwt.kid:hmac-1}")         private String kid;

    private JwtParser parser;

    @PostConstruct
    public void init() {
        this.parser = Jwts.parserBuilder()
                .setSigningKey(jwtHmacKey) // ★ 공용키
                .requireIssuer(issuer)
                .requireAudience(audience)
                .setAllowedClockSkewSeconds(clockSkewSeconds)
                .build();
    }

    public String generateAccessToken(Long userId, String role) {
        return buildToken(userId, List.of(role), expirationMs, "acc", UUID.randomUUID().toString());
    }
    public String generateRefreshToken(Long userId, String role) {
        return buildToken(userId, List.of(role), refreshExpirationMs, "ref", UUID.randomUUID().toString());
    }

    private String buildToken(Long userId, Collection<String> roles, long ttl, String typ, String jti) {
        long now = System.currentTimeMillis();
        Date iat = new Date(now), exp = new Date(now + ttl);

        return Jwts.builder()
                .setHeaderParam("kid", kid)
                .setIssuer(issuer)
                .setAudience(audience)
                .setSubject(String.valueOf(userId))
                .claim("userId", userId)
                .claim("roles", roles)
                .claim("authorities", roles.stream().map(r -> r.startsWith("ROLE_")? r: "ROLE_" + r).toList())
                .claim("typ", typ)
                .setId(jti)
                .setIssuedAt(iat)
                .setExpiration(exp)
                .signWith(jwtHmacKey, SignatureAlgorithm.HS256) // ★ 공용키
                .compact();
    }

    public io.jsonwebtoken.Claims getClaims(String token) { return parser.parseClaimsJws(token).getBody(); }
    public boolean validateToken(String token) { try { parser.parseClaimsJws(token); return true; } catch (JwtException e) { return false; } }



    public long getRemainingValidity(String token) {
        try { return getClaims(token).getExpiration().getTime() - System.currentTimeMillis(); }
        catch (Exception e) { log.error("[JWT] TTL calc failed: {}", e.getMessage()); return -1; }
    }

    // ===== 편의 =====
    public Long getUserId(String token) {
        Claims c = getClaims(token);
        String sub = c.getSubject();
        if (sub != null) return Long.parseLong(sub);
        Object uid = c.get("userId");
        if (uid instanceof Integer i) return i.longValue();
        if (uid instanceof Long l)    return l;
        if (uid instanceof String s)  return Long.parseLong(s);
        throw new IllegalArgumentException("Invalid userId in JWT");
    }

    @Deprecated
    public String getRole(String token) {
        List<String> roles = getRoles(token);
        return roles.isEmpty() ? null : roles.get(0);
    }

    @SuppressWarnings("unchecked")
    public List<String> getRoles(String token) {
        Object v = getClaims(token).get("roles");
        if (v instanceof List<?> list) {
            List<String> out = new ArrayList<>(list.size());
            for (Object o : list) if (o != null) out.add(o.toString());
            return normalizeRoles(out);
        }
        return List.of();
    }

    public String getType(String token) {
        Object t = getClaims(token).get("typ");
        return (t == null) ? null : t.toString();
    }

    private static List<String> roleList(String role) {
        return (role == null) ? List.of() : List.of(role);
    }
    private static List<String> normalizeRoles(Collection<String> roles) {
        List<String> out = new ArrayList<>();
        if (roles == null) return out;
        for (String r : roles) {
            if (r == null) continue;
            String v = r.trim();
            if (!v.isEmpty()) out.add(v.toUpperCase(Locale.ROOT));
        }
        return out;
    }
    private static List<String> toAuthorities(List<String> roles) {
        List<String> out = new ArrayList<>(roles.size());
        for (String r : roles) out.add(r.startsWith("ROLE_") ? r : "ROLE_" + r);
        return out;
    }
}
