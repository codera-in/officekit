cmake_minimum_required(VERSION 3.18)
project(officekit_pii_gliner_runtime LANGUAGES CXX)

set(GLINER_ROOTDIR "" CACHE PATH "Checked-out Knowledgator GLiNER.cpp source")
set(GLINER_LIBRARY "" CACHE FILEPATH "Built GLiNER.cpp shared library")
set(ONNXRUNTIME_INCLUDE_DIR "" CACHE PATH "ONNX Runtime include directory")
set(ONNXRUNTIME_LIBRARY "" CACHE FILEPATH "ONNX Runtime shared library")
set(TOKENIZERS_CPP_INCLUDE_DIR "" CACHE PATH "tokenizers-cpp include directory")

foreach(required GLINER_ROOTDIR GLINER_LIBRARY ONNXRUNTIME_INCLUDE_DIR ONNXRUNTIME_LIBRARY TOKENIZERS_CPP_INCLUDE_DIR)
    if(NOT ${required})
        message(FATAL_ERROR "Set -D${required}=... to build the local GLiNER runtime")
    endif()
endforeach()

add_executable(officekit-pii-gliner ../pii_gliner_cpp_daemon.cpp)
target_compile_features(officekit-pii-gliner PRIVATE cxx_std_20)
target_include_directories(officekit-pii-gliner PRIVATE
    "${GLINER_ROOTDIR}/include"
    "${ONNXRUNTIME_INCLUDE_DIR}"
    "${TOKENIZERS_CPP_INCLUDE_DIR}"
)
target_link_libraries(officekit-pii-gliner PRIVATE "${GLINER_LIBRARY}" "${ONNXRUNTIME_LIBRARY}")
