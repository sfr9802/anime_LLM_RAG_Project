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
    private String path;        // 권장: "/llm/ask"처럼 상대경로
    private String targetUrl;   // 레거시 호환: 풀 URL (화이트리스트 검사함)
    private String question;    // ex: 자연어 질의
}
