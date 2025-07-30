package com.arin.reverseproxy.dto;

import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
public class ProxyRequestDto {
    private String targetUrl; // ex: http://localhost:8000/rag/query
    private String query;     // ex: 자연어 쿼리
}
