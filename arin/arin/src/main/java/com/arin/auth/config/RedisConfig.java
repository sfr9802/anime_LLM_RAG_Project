package com.arin.auth.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.data.redis.core.StringRedisTemplate;

@Configuration
public class RedisConfig {

    @Bean
    public LettuceConnectionFactory redisConnectionFactory() {
        return new LettuceConnectionFactory(); // localhost:6379 기본 사용
    }

    @Bean
    public StringRedisTemplate stringRedisTemplate() {
        return new StringRedisTemplate(redisConnectionFactory());
    }
}
