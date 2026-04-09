package com.arin.identity.config;

import lombok.Getter;
import lombok.Setter;
import org.springframework.boot.context.properties.ConfigurationProperties;

@Getter @Setter
@ConfigurationProperties(prefix = "app.security.refresh-cookie")
public class RefreshCookieProps {
    private String  name = "refresh_token";
    private String  path = "/api/auth/";
    private String  sameSite = "Lax";
    private boolean secure = false;
    private String  domain;
}
