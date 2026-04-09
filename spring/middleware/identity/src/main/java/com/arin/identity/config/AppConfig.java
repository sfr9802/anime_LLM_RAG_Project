package com.arin.identity.config;

import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Configuration;

@Configuration
@EnableConfigurationProperties({
        AppOAuthProps.class,
        RefreshCookieProps.class
})
public class AppConfig {}
