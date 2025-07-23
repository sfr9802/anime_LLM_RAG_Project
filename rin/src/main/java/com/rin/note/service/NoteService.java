package com.rin.note.service;

import com.rin.note.dto.CreateNoteRequest;
import com.rin.note.entity.Note;
import com.rin.note.repository.NoteRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.Optional;

@Service
@RequiredArgsConstructor
public class NoteService {

    private final NoteRepository noteRepository;

    public Long createNote(CreateNoteRequest request) {
        Note note = new Note(request.getTitle(), request.getContent());
        return noteRepository.save(note).getId();
    }

    public Note getNote(Long id) {
        return noteRepository.findById(id)
                .orElseThrow(() -> new IllegalArgumentException("해당 ID의 노트가 없습니다: " + id));
    }
}
