// com.arin.auth.config.AppConfig
package com.arin.auth.config;

import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Configuration;

@Configuration
@EnableConfigurationProperties(AppOAuthProps.class)
public class AppConfig {}
