cmake_minimum_required(VERSION 3.18)

project(ball_detect_yolo_combind_ncnn LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

set(NCNN_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(NCNN_BUILD_BENCHMARK OFF CACHE BOOL "" FORCE)
set(NCNN_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(NCNN_BUILD_TOOLS OFF CACHE BOOL "" FORCE)
set(NCNN_VULKAN OFF CACHE BOOL "" FORCE)
if(NOT DEFINED NCNN_OPENMP)
    if(WIN32)
        set(NCNN_OPENMP OFF CACHE BOOL "Enable NCNN OpenMP support")
    else()
        set(NCNN_OPENMP ON CACHE BOOL "Enable NCNN OpenMP support")
    endif()
endif()

include(FetchContent)
set(NCNN_SOURCE_ARCHIVE "" CACHE FILEPATH "Optional local NCNN source archive for offline builds")
if(NCNN_SOURCE_ARCHIVE)
    set(NCNN_SOURCE_URL "${NCNN_SOURCE_ARCHIVE}")
else()
    set(NCNN_SOURCE_URL "https://codeload.github.com/Tencent/ncnn/tar.gz/a4d2ea1d4422c9e849f166fd7a4aefb52f942f6a")
endif()
FetchContent_Declare(
    ncnn
    URL "${NCNN_SOURCE_URL}"
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
)
FetchContent_MakeAvailable(ncnn)

find_package(Python COMPONENTS Interpreter Development.Module REQUIRED)
execute_process(
    COMMAND "${Python_EXECUTABLE}" -m pybind11 --cmakedir
    OUTPUT_VARIABLE pybind11_DIR
    OUTPUT_STRIP_TRAILING_WHITESPACE
    RESULT_VARIABLE pybind11_result
)
if(NOT pybind11_result EQUAL 0)
    message(FATAL_ERROR "pybind11 is not installed; run python -m pip install pybind11")
endif()
find_package(pybind11 CONFIG REQUIRED)

pybind11_add_module(_ncnn_cpp ncnn_backend.cpp)
target_link_libraries(_ncnn_cpp PRIVATE ncnn)

if(MINGW)
    target_link_options(_ncnn_cpp PRIVATE -static-libgcc -static-libstdc++ -Wl,-Bstatic -lwinpthread -Wl,-Bdynamic)
endif()

if(MSVC)
    target_compile_options(_ncnn_cpp PRIVATE /W4)
else()
    target_compile_options(_ncnn_cpp PRIVATE -Wall -Wextra -Wpedantic)
endif()
