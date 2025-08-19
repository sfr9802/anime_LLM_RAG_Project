package com.arin.auth.config;

// package com.arin.auth.config;

import org.springframework.core.convert.converter.Converter;
import org.springframework.security.authentication.AbstractAuthenticationToken;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;

import java.util.*;
import java.util.stream.Collectors;

public class CompositeJwtAuthConverter implements Converter<Jwt, AbstractAuthenticationToken> {

    private static final String ROLE_PREFIX = "ROLE_";
    private static final String SCOPE_PREFIX = "SCOPE_";

    @Override
    public AbstractAuthenticationToken convert(Jwt jwt) {
        Set<String> authorities = new HashSet<>();

        // 1) roles: ["ADMIN","USER"] or "ADMIN"
        Object rolesObj = jwt.getClaims().get("roles");
        if (rolesObj instanceof Collection<?> c) {
            c.stream().map(Object::toString).forEach(r -> addRole(authorities, r));
        } else if (rolesObj instanceof String s && !s.isBlank()) {
            Arrays.stream(s.split("[,\\s]")).forEach(r -> addRole(authorities, r));
        }

        // 2) authorities: ["ROLE_ADMIN","READ"]
        Object authObj = jwt.getClaims().get("authorities");
        if (authObj instanceof Collection<?> c) {
            c.forEach(a -> addRawAuthority(authorities, a.toString()));
        } else if (authObj instanceof String s && !s.isBlank()) {
            Arrays.stream(s.split("[,\\s]")).forEach(a -> addRawAuthority(authorities, a));
        }

        // 3) scope: "read write" or ["read","write"]
        Object scopeObj = jwt.getClaims().getOrDefault("scope", jwt.getClaims().get("scp"));
        if (scopeObj instanceof Collection<?> c) {
            c.forEach(s -> authorities.add(SCOPE_PREFIX + s.toString()));
        } else if (scopeObj instanceof String s && !s.isBlank()) {
            Arrays.stream(s.split("[,\\s]")).forEach(x -> authorities.add(SCOPE_PREFIX + x));
        }

        // (선택) Role Hierarchy 간이 적용: ADMIN > MANAGER > USER
        if (authorities.contains(ROLE_PREFIX + "ADMIN")) {
            authorities.add(ROLE_PREFIX + "MANAGER");
            authorities.add(ROLE_PREFIX + "USER");
        } else if (authorities.contains(ROLE_PREFIX + "MANAGER")) {
            authorities.add(ROLE_PREFIX + "USER");
        }

        var granted = authorities.stream()
                .filter(a -> !a.isBlank())
                .map(SimpleGrantedAuthority::new)
                .collect(Collectors.toSet());

        // principal claim: sub 또는 preferred_username
        String principal = Optional.ofNullable(jwt.getClaimAsString("sub"))
                .orElseGet(() -> jwt.getClaimAsString("preferred_username"));

        return new JwtAuthenticationToken(jwt, granted, principal);
    }

    private static void addRole(Set<String> acc, String raw) {
        if (raw == null || raw.isBlank()) return;
        String normalized = raw.toUpperCase(Locale.ROOT).replaceFirst("^ROLE_", "");
        acc.add(ROLE_PREFIX + normalized);
    }

    private static void addRawAuthority(Set<String> acc, String raw) {
        if (raw == null || raw.isBlank()) return;
        if (raw.startsWith("ROLE_") || raw.startsWith("SCOPE_")) {
            acc.add(raw);
        } else {
            // 일반 authority는 prefix 없이 그대로
            acc.add(raw);
        }
    }
}

