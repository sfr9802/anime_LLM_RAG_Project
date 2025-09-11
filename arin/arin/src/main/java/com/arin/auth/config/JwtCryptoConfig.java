package com.arin.auth.config;// com.arin.auth.config.JwtCryptoConfig
import io.jsonwebtoken.security.Keys;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.*;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.security.oauth2.jwt.*;
import javax.crypto.SecretKey;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Base64;

// com.arin.auth.config.JwtCryptoConfig
@Configuration
@Slf4j
public class JwtCryptoConfig {

    @Bean
    public SecretKey jwtHmacKey(
            @Value("${jwt.secret}") String secret,
            @Value("${jwt.is-base64:false}") boolean isBase64
    ) {
        String s = (secret == null) ? "" : secret.trim();
        if (s.startsWith("\"") && s.endsWith("\"") && s.length() >= 2) {
            s = s.substring(1, s.length()-1);
        }
        byte[] keyBytes = isBase64 ? Base64.getDecoder().decode(s) : s.getBytes(StandardCharsets.UTF_8);
        if (keyBytes.length < 32) throw new IllegalStateException("jwt.secret must be >= 256 bits");

        MessageDigest md = null;
        try {
            md = MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException e) {
            throw new RuntimeException(e);
        }
        var fp = bytesToHex(md.digest(keyBytes)).substring(0,16);
        log.info("[JWT] key.len={} key.fp={}", keyBytes.length, fp);

        return Keys.hmacShaKeyFor(keyBytes);
    }

    @Bean
    public JwtDecoder jwtDecoder(SecretKey jwtHmacKey) {
        return NimbusJwtDecoder.withSecretKey(jwtHmacKey)
                .macAlgorithm(MacAlgorithm.HS256)
                .build();
    }

    private static String bytesToHex(byte[] a) {
        var sb = new StringBuilder(a.length*2);
        for (byte b: a) sb.append(String.format("%02x", b));
        return sb.toString();
    }
}

