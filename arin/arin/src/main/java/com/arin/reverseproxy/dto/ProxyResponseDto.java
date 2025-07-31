package com.arin.reverseproxy.dto;

import lombok.*;

@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
public class ProxyResponseDto {
    private String question;
    private String answer;
}
