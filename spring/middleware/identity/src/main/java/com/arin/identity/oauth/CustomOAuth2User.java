package com.arin.identity.oauth;

import com.arin.identity.entity.AppUser;
import lombok.Getter;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.oauth2.core.user.OAuth2User;

import java.util.Collection;
import java.util.List;
import java.util.Map;

@Getter
public class CustomOAuth2User implements OAuth2User {
    private final AppUser appUser;
    private final Map<String, Object> attributes;

    public CustomOAuth2User(AppUser appUser, Map<String, Object> attributes) {
        this.appUser = appUser;
        this.attributes = attributes;
    }

    @Override public Map<String, Object> getAttributes() { return attributes; }

    @Override
    public Collection<? extends GrantedAuthority> getAuthorities() {
        String role = (appUser.getRole() != null) ? appUser.getRole().name() : "USER";
        return List.of(new SimpleGrantedAuthority("ROLE_" + role));
    }

    @Override public String getName() { return String.valueOf(appUser.getId()); }

    public Long   getId()   { return appUser.getId(); }
    public String getRole() { return appUser.getRole().name(); }
    public String getEmail(){ return appUser.getEmail(); }
}
