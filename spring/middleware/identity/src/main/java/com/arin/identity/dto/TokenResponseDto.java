package com.arin.identity.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Getter;
import lombok.NoArgsConstructor;

@Getter @NoArgsConstructor
@JsonInclude(JsonInclude.Include.NON_NULL)
public class TokenResponseDto {
    private String accessToken;
    private Long   expiresIn;
    private String tokenType = "Bearer";

    @Deprecated
    @JsonProperty(access = JsonProperty.Access.WRITE_ONLY)
    private String refreshToken;

    public TokenResponseDto(String accessToken, long expiresInSeconds) {
        this(accessToken, expiresInSeconds, "Bearer", null);
    }
    public TokenResponseDto(String accessToken, long expiresInSeconds, String tokenType, String refreshToken) {
        this.accessToken = accessToken;
        this.expiresIn   = expiresInSeconds;
        this.tokenType   = (tokenType == null || tokenType.isBlank()) ? "Bearer" : tokenType;
        this.refreshToken = refreshToken;
    }
}
