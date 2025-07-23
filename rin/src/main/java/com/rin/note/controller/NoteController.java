package com.rin.note.controller;

import com.rin.note.dto.CreateNoteRequest;
import com.rin.note.entity.Note;
import com.rin.note.service.NoteService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@Tag(name = "Note", description = "노트 관리 API")
@RestController
@RequestMapping("/api/notes")
@RequiredArgsConstructor
public class NoteController {

    private final NoteService noteService;

    @Operation(summary = "노트 생성", description = "새로운 노트를 작성합니다.")
    @PostMapping
    public ResponseEntity<?> createNote(@Valid @RequestBody CreateNoteRequest request) {
        Long noteId = noteService.createNote(request);
        return ResponseEntity.ok().body(noteId);
    }

    @Operation(summary = "노트 조회", description = "ID로 노트를 조회합니다.")
    @GetMapping("/{id}")
    public ResponseEntity<?> getNote(@PathVariable Long id) {
        Note note = noteService.getNote(id);
        return ResponseEntity.ok(note);
    }
}
