package com.arin.service;

import com.arin.dto.UserReqDto;
import com.arin.dto.UserResDto;
import com.arin.entity.User;
import com.arin.repository.UserRepository;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class UserService {
    private final UserRepository userRepository;

    public UserService(UserRepository userRepository) {
        this.userRepository = userRepository;
    }

    public void register(UserReqDto dto) {
        if (userRepository.existsByUsername(dto.getUsername())) {
            throw new RuntimeException("Username already exists");
        }

        User user = User.builder()
                .username(dto.getUsername())
                .password(dto.getPassword()) // TODO: 해싱
                .role(User.Role.USER)
                .active(true)
                .build();

        userRepository.save(user);
    }

    public List<UserResDto> getAllUsers() {
        return userRepository.findAll().stream()
                .map(UserResDto::new)
                .toList();
    }

}

