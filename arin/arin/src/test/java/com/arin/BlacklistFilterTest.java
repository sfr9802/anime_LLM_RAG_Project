package com.arin;

import com.arin.auth.service.TokenService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.context.bean.override.mockito.MockitoBean; // ← 여기!

import static org.mockito.Mockito.when;
import static org.hamcrest.Matchers.containsString;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@SpringBootTest(
        properties = {
                "spring.datasource.url=jdbc:h2:mem:testdb;MODE=MySQL;DB_CLOSE_DELAY=-1",
                "spring.datasource.driverClassName=org.h2.Driver",
                "spring.jpa.hibernate.ddl-auto=none",
                "spring.redis.host=invalid",
                "spring.security.oauth2.client.registration.google.client-id=dummy",
                "spring.security.oauth2.client.registration.google.client-secret=dummy",
                "proxy.upstream=http://localhost:9999"
        }
)
@AutoConfigureMockMvc
@ActiveProfiles("test")
class BlacklistFilterTest {

    @Autowired MockMvc mvc;

    @MockitoBean           // ← @MockBean 대신
    TokenService tokenService;

    @Test
    void blacklistedToken_isBlockedWith401() throws Exception {
        String t = "BLACKLISTED_TOKEN";
        when(tokenService.isBlacklisted(t)).thenReturn(true);

        mvc.perform(get("/api/proxy/health")
                        .header("Authorization", "Bearer " + t))
                .andExpect(status().isUnauthorized())
                .andExpect(content().string(containsString("로그아웃된 토큰")));
    }
}
