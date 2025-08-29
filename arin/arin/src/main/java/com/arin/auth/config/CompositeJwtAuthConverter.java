package com.arin.auth.config;

import org.springframework.core.convert.converter.Converter;
import org.springframework.security.authentication.AbstractAuthenticationToken;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;

import java.util.*;
import java.util.stream.Collectors;

public class CompositeJwtAuthConverter implements Converter<Jwt, AbstractAuthenticationToken> {

    private static final String ROLE_PREFIX  = "ROLE_";
    private static final String SCOPE_PREFIX = "SCOPE_";

    @Override
    public AbstractAuthenticationToken convert(Jwt jwt) {
        Set<String> auths = new HashSet<>();

        // 1) roles: ["ADMIN","USER"] or "ADMIN USER"
        Object rolesObj = jwt.getClaims().get("roles");
        if (rolesObj instanceof Collection<?> c) {
            c.stream().map(String::valueOf).forEach(r -> addRole(auths, r));
        } else if (rolesObj instanceof String s && !s.isBlank()) {
            Arrays.stream(s.split("[,\\s]+")).forEach(r -> addRole(auths, r));
        }

        // 2) authorities: ["ROLE_ADMIN","READ"] or "ROLE_ADMIN READ"
        Object authObj = jwt.getClaims().get("authorities");
        if (authObj instanceof Collection<?> c) {
            c.forEach(a -> addRawAuthority(auths, String.valueOf(a)));
        } else if (authObj instanceof String s && !s.isBlank()) {
            Arrays.stream(s.split("[,\\s]+")).forEach(a -> addRawAuthority(auths, a));
        }

        // 3) scope/scp: "read write" or ["read","write"] → SCOPE_read / SCOPE_write
        Object scopeObj = Optional.ofNullable(jwt.getClaims().get("scope"))
                .orElse(jwt.getClaims().get("scp"));
        if (scopeObj instanceof Collection<?> c) {
            c.forEach(s -> auths.add(SCOPE_PREFIX + s));
        } else if (scopeObj instanceof String s && !s.isBlank()) {
            Arrays.stream(s.split("[,\\s]+")).forEach(x -> auths.add(SCOPE_PREFIX + x));
        }

        // 롤 계층(간이 전개): ADMIN > MANAGER > USER
        if (auths.contains(ROLE_PREFIX + "ADMIN")) {
            auths.add(ROLE_PREFIX + "MANAGER");
            auths.add(ROLE_PREFIX + "USER");
        } else if (auths.contains(ROLE_PREFIX + "MANAGER")) {
            auths.add(ROLE_PREFIX + "USER");
        }

        Set<GrantedAuthority> granted = auths.stream()
                .filter(a -> a != null && !a.isBlank())
                .map(SimpleGrantedAuthority::new)
                .collect(Collectors.toSet());

        // principal: sub > preferred_username > "user:{sub클레임없음}"
        String principal = Optional.ofNullable(jwt.getClaimAsString("sub"))
                .orElseGet(() -> Optional.ofNullable(jwt.getClaimAsString("preferred_username"))
                        .orElse("user:" + String.valueOf(jwt.getClaims().getOrDefault("userId", "unknown"))));

        return new JwtAuthenticationToken(jwt, granted, principal);
    }

    private static void addRole(Set<String> acc, String raw) {
        if (raw == null || raw.isBlank()) return;
        String normalized = raw.trim().toUpperCase(Locale.ROOT).replaceFirst("^ROLE_", "");
        acc.add(ROLE_PREFIX + normalized);
    }

    private static void addRawAuthority(Set<String> acc, String raw) {
        if (raw == null || raw.isBlank()) return;
        // ROLE_/SCOPE_는 그대로, 나머지는 접두사 없이 일반 authority로 추가
        acc.add(raw.trim());
    }
}
