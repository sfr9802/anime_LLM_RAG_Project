package com.arin.api;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication(scanBasePackages = "com.arin")
public class ArinApplication {

    public static void main(String[] args) {
        SpringApplication.run(ArinApplication.class, args);
    }
}
