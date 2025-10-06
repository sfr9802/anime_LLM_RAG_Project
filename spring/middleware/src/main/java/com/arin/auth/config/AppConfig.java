// com/arin/auth/config/AppConfig.java
package com.arin.auth.config;

import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Configuration;

@Configuration
@EnableConfigurationProperties({
        AppOAuthProps.class,
        RefreshCookieProps.class   // 이거도 쓰고 있으면 같이
})
public class AppConfig {}
