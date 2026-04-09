package com.arin.identity.config;

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

        Object rolesObj = jwt.getClaims().get("roles");
        if (rolesObj instanceof Collection<?> c) {
            c.stream().map(String::valueOf).forEach(r -> addRole(auths, r));
        } else if (rolesObj instanceof String s && !s.isBlank()) {
            Arrays.stream(s.split("[,\\s]+")).forEach(r -> addRole(auths, r));
        }

        Object authObj = jwt.getClaims().get("authorities");
        if (authObj instanceof Collection<?> c) {
            c.forEach(a -> addRawAuthority(auths, String.valueOf(a)));
        } else if (authObj instanceof String s && !s.isBlank()) {
            Arrays.stream(s.split("[,\\s]+")).forEach(a -> addRawAuthority(auths, a));
        }

        Object scopeObj = Optional.ofNullable(jwt.getClaims().get("scope"))
                .orElse(jwt.getClaims().get("scp"));
        if (scopeObj instanceof Collection<?> c) {
            c.forEach(s -> auths.add(SCOPE_PREFIX + s));
        } else if (scopeObj instanceof String s && !s.isBlank()) {
            Arrays.stream(s.split("[,\\s]+")).forEach(x -> auths.add(SCOPE_PREFIX + x));
        }

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
        acc.add(raw.trim());
    }
}
