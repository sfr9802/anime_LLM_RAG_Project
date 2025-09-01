// com/arin/auth/config/AppOAuthProps.java
package com.arin.auth.config;

import lombok.Getter;
import lombok.Setter;
import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.ArrayList;
import java.util.List;

@Getter
@Setter
@ConfigurationProperties(prefix = "app.oauth2")
public class AppOAuthProps {
    private String redirectUri;
    private List<String> allowedOrigins = new ArrayList<>();
}
