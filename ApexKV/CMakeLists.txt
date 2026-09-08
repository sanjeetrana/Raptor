cmake_minimum_required(VERSION 3.16)

project(ApexKV LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_executable(apexkv
    main.cpp
    src/hash_table.cpp
)

target_include_directories(apexkv PRIVATE include)

add_executable(test_apexkv
    tests/test_apexkv.cpp
    src/hash_table.cpp
)

target_include_directories(test_apexkv PRIVATE include)