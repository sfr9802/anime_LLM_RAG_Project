package com.rin.note.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.NotBlank;
import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
@Schema(description = "노트 생성 요청 DTO")
public class CreateNoteRequest {

    @NotBlank
    @Schema(description = "노트 제목", example = "회의 내용 정리")
    private String title;

    @NotBlank
    @Schema(description = "노트 본문", example = "오늘 회의에서는 DB 구조 논의함")
    private String content;
}
