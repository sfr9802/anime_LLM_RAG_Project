package com.arin.controller;


import com.arin.common.ApiResponse;
import com.arin.dto.UserReqDto;
import com.arin.dto.UserResDto;
import com.arin.entity.User;
import com.arin.repository.UserRepository;
import com.arin.service.UserService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import jakarta.validation.Valid;

import java.util.List;

@RestController
@RequestMapping("/api/users")
public class UserController {
    private final UserRepository userRepository;
    private final UserService userService;
    public UserController(
            UserRepository userRepository,
            UserService userService
    ) {
        this.userRepository = userRepository;
        this.userService = userService;
    }

    @PostMapping("/register")
    public ResponseEntity<?> register(@RequestBody @Valid UserReqDto dto) {
        userService.register(dto);
        return ResponseEntity.ok(new ApiResponse<>(true, "User registered"));
    }


    @GetMapping("/browse")
    public ResponseEntity<?> getAllUsers() {
        List<UserResDto> users = userService.getAllUsers();
        return ResponseEntity.ok(new ApiResponse<>(true, users));
    }



}
