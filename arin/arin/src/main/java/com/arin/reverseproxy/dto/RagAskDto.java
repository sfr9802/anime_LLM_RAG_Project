// src/main/java/com/arin/reverseproxy/dto/RagAskV2Dto.java
package com.arin.reverseproxy.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import jakarta.validation.constraints.*;
import lombok.*;

@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
@JsonInclude(JsonInclude.Include.NON_NULL)
public class RagAskDto {
    @NotBlank
    private String question;

    // 기본 경로. 필요 시 "/rag/ask" 이외도 허용
    @Builder.Default
    private String path = "/rag/ask";

    @Min(1) @Max(50)
    private Integer k;

    @Min(1) @Max(200)
    private Integer candidateK;

    private Boolean useMmr;

    @DecimalMin("0.0") @DecimalMax("1.0")
    private Double lam;

    @Min(1) @Max(4096)
    private Integer maxTokens;

    @DecimalMin("0.0") @DecimalMax("2.0")
    private Double temperature;

    @Min(0) @Max(8000)
    private Integer previewChars;

    private String traceId;
}
