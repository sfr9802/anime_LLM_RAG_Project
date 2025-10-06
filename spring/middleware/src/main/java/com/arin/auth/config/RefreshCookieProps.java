package com.arin.auth.config;// com.arin.auth.config.RefreshCookieProps
import lombok.Getter; import lombok.Setter;
import org.springframework.boot.context.properties.ConfigurationProperties;

@Getter @Setter
@ConfigurationProperties(prefix = "app.security.refresh-cookie")
public class RefreshCookieProps {
    private String  name = "refresh_token";
    private String  path = "/api/auth/";
    private String  sameSite = "Lax"; // 크로스면 None(+HTTPS)
    private boolean secure = false;   // dev=false, prod=true
    private String  domain;           // 선택
}
