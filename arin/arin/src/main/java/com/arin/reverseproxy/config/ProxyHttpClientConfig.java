package com.arin.reverseproxy.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestTemplate;

@Configuration
public class ProxyHttpClientConfig {

    @Bean
    public RestTemplate proxyRestTemplate(org.springframework.core.env.Environment env) {
        SimpleClientHttpRequestFactory f = new SimpleClientHttpRequestFactory();
        int ct = Integer.parseInt(env.getProperty("proxy.connect-timeout-ms","3000"));
        int rt = Integer.parseInt(env.getProperty("proxy.read-timeout-ms","5000"));
        f.setConnectTimeout(ct);
        f.setReadTimeout(rt);
        RestTemplate rtpl = new RestTemplate();
        rtpl.setRequestFactory(f);
        return rtpl;
    }
}
