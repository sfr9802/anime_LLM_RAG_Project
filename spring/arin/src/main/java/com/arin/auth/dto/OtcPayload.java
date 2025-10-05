package com.arin.auth.dto;

/** 서버 내부에서만 쓰는 OTC 페이로드 (교환 시 refresh는 쿠키로만 쓴다) */
public record OtcPayload(String accessToken, String refreshToken) {}
