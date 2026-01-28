#include <iostream>
#include <string>
#include <vector>
#include <fstream>
#include <sstream>
#include <algorithm> // for std::min
#include <limits>    // for UINT32_MAX if needed by older compilers
#include "lib/include/tree_sitter/api.h"

// ==========================================================
// [플랫폼 호환성 추상화] Windows vs Linux
// ==========================================================
#ifdef _WIN32
    // [Windows 환경]
    #include <windows.h>
    typedef HMODULE LibraryHandle;

    // 매크로 정의: Windows API 매핑
    #define LOAD_LIBRARY(path) LoadLibraryA(path)
    #define GET_PROC_ADDRESS(handle, name) GetProcAddress(handle, name)
    #define CLOSE_LIBRARY(handle) FreeLibrary(handle)
    #define GET_ERROR_MSG() ("GetLastError code: " + std::to_string(GetLastError()))

#else
    // [Linux/Unix 환경]
    #include <dlfcn.h>
    typedef void* LibraryHandle;

    // 매크로 정의: POSIX API 매핑
    #define LOAD_LIBRARY(path) dlopen(path, RTLD_LAZY)
    #define GET_PROC_ADDRESS(handle, name) dlsym(handle, name)
    #define CLOSE_LIBRARY(handle) dlclose(handle)
    // dlerror()는 null을 반환할 수 있으므로 안전하게 처리
    #define GET_ERROR_MSG() (dlerror() ? std::string(dlerror()) : std::string("Unknown error"))
#endif
// ==========================================================

// TSLanguage*를 반환하는 함수 포인터 타입을 정의 (동적 로딩용)
typedef TSLanguage *(*LanguageFunction)();


// ==================[ 헬퍼 함수: 위치 -> 바이트 오프셋 ]=================
size_t FindByteOffsetForPosition(const std::string& text, uint32_t target_row, uint32_t target_col) {
    size_t current_offset = 0;
    uint32_t current_row = 0; 
    uint32_t current_col = 0; 
    const uint32_t tab_width = 4; 

    while (current_offset < text.length()) {
        if (current_row > target_row || (current_row == target_row && current_col >= target_col)) {
             return current_offset;
        }

        unsigned char current_char = static_cast<unsigned char>(text[current_offset]);

        if (current_char == '\n') {
            current_row++;
            current_col = 0;
            current_offset++;
        } else if (current_char == '\r' && (current_offset + 1 < text.length() && text[current_offset + 1] == '\n')) {
            current_row++;
            current_col = 0;
            current_offset += 2;
        }
        else if (current_char == '\t') {
            current_col = ((current_col / tab_width) + 1) * tab_width;
            current_offset++;
        }
        else {
             current_col++;
             current_offset++;
             if (current_char >= 0xC0) { 
                 while (current_offset < text.length() && (static_cast<unsigned char>(text[current_offset]) & 0xC0) == 0x80) {
                     current_offset++; 
                 }
             }
        }
    }
    return text.length();
}
// ====================================================================


int main(int argc, char* argv[]) {
    std::cout << "DEBUG: Program started." << std::endl;

    // 1. 인자 파싱
    if (argc < 4) {
        std::cerr << "Usage: " << argv[0] << " <lang> <lib_path> <file_path> [<stop_row> <stop_col> <flag>]" << std::endl;
        std::cerr << "\n  <flag>: 1 = Collection Mode, 0 = Parse State ID Mode" << std::endl;
        std::cerr << "\n  Examples:" << std::endl;
        std::cerr << "    " << argv[0] << " smallbasic ./tree-sitter-smallbasic.dll ./test.sb" << std::endl;
        std::cerr << "    " << argv[0] << " smallbasic ./tree-sitter-smallbasic.dll ./test.sb 5 10 1" << std::endl;
        std::cerr << "    " << argv[0] << " python ./python.dll ./test.py 20 5 0" << std::endl;
        return 1;
    }

    // 인자 할당
    std::string language_name = argv[1];
    const char* library_path = argv[2]; // 2번째 인자는 무조건 DLL/SO 경로
    const char* file_path = argv[3];    // 3번째 인자는 무조건 파일 경로

    TSLanguage *language = nullptr;
    LibraryHandle library_handle = nullptr; // 통합된 타입 사용

    bool stop_position_provided = false;
    uint32_t stop_row = 0; 
    uint32_t stop_col = 0; 
    bool bIsCollectionMode = false; // 플래그 값 저장

    // 옵션 인자 처리 (7개일 때)
    // 순서: exe(0) lang(1) dll(2) file(3) row(4) col(5) flag(6)
    if (argc == 7) {
        stop_position_provided = true;
        stop_row = std::stoul(argv[4]);
        stop_col = std::stoul(argv[5]);

        std::string flag_str = argv[6];
        // 1이면 true (Collection), 0이면 false (Parse State ID)
        bIsCollectionMode = (flag_str == "1");
        std::cout << "DEBUG: Flag set to: " 
                  << (bIsCollectionMode ? "Collection Mode (1)" : "Parse State ID Mode (0)") 
                  << std::endl;

    } else if (argc != 4) {
        // 인자가 4개(기본)도 아니고 7개(옵션포함)도 아니면 에러
        std::cerr << "Error: Incorrect number of arguments. Expected 4 or 7." << std::endl;
        return 1;
    }

    // --- 언어 로딩 (동적 로딩으로 통일) ---
    try {
        // 1. DLL 파일 열기
        std::cout << "DEBUG: Loading dynamic library: " << library_path << std::endl;

        library_handle = LOAD_LIBRARY(library_path);

        if (!library_handle) {
            throw std::runtime_error("Could not load library: " + GET_ERROR_MSG());
        }
        std::cout << "DEBUG: Library loaded successfully." << std::endl;

        // 2. 함수 심볼 찾기 (tree_sitter_언어이름)
        std::string language_func_name = "tree_sitter_" + language_name;
        std::cout << "DEBUG: Searching for function: '" << language_func_name << "'..." << std::endl;
        
        LanguageFunction language_function = (LanguageFunction)GET_PROC_ADDRESS(library_handle, language_func_name.c_str());

        if (!language_function) {
            throw std::runtime_error("Could not find function '" + language_func_name + "' in library.");
        }
        std::cout << "DEBUG: Function found." << std::endl;
        
        // 3. 언어 포인터 획득
        language = language_function();
        if (!language) {
            throw std::runtime_error("Failed to get language pointer from function.");
        }

        // --- 파싱 준비 ---
        TSParser *parser = ts_parser_new();
        ts_parser_set_language(parser, language);
        std::cout << "DEBUG: Parser created and language set." << std::endl;

        // 플래그 및 중단 위치 설정
        ts_parser_set_stop_position(parser, {stop_row, stop_col});
        ts_parser_set_find_state_mode(parser, bIsCollectionMode); 
        
        // --- 파일 읽기 ---
        std::cout << "DEBUG: Reading source file: " << file_path << std::endl;
        std::ifstream file(file_path);
        if (!file) {
            throw std::runtime_error("Could not open source file " + std::string(file_path));
        }
        std::stringstream buffer;
        buffer << file.rdbuf();
        std::string source_code = buffer.str();

        size_t effective_length = source_code.length();

        // 중단 위치 계산
        if (stop_position_provided) {
            std::cout << "--- Stop position requested at row " << stop_row << ", col " << stop_col << " ---" << std::endl;
            size_t stop_offset = FindByteOffsetForPosition(source_code, stop_row > 0 ? stop_row - 1 : 0, stop_col > 0 ? stop_col - 1 : 0);
            effective_length = source_code.length() < stop_offset ? source_code.length() : stop_offset;
            std::cout << "DEBUG: Effective parsing length set to " << effective_length << " bytes." << std::endl;
        }

        // --- 파싱 실행 ---
        std::cout << "DEBUG: Starting parse..." << std::endl;
        TSTree *tree = ts_parser_parse_string(
            parser,
            NULL,
            source_code.c_str(),
            static_cast<uint32_t>(effective_length)
        );
        std::cout << "DEBUG: Parsing finished." << std::endl;

        // --- 복구 발생 여부 체크 ---
        if (bIsCollectionMode && ts_parser_has_recovery(parser)) {
            std::cout << "INFO: Recovery detected during collection. Exiting with code 10." << std::endl;
            // 메모리 정리 후 즉시 종료
            if (tree) ts_tree_delete(tree);
            ts_parser_delete(parser);
            if (library_handle) CLOSE_LIBRARY(library_handle);

            // 핵심: Python 스크립트에게 '스킵하라'는 신호(10)를 보냄
            return 10;
        }
        
        // --- 결과 출력 ---
        if (tree) {
            TSNode root_node = ts_tree_root_node(tree);
            char *tree_string = ts_node_string(root_node);
            std::cout << "\nParse Tree for " << language_name << ":\n" << tree_string << std::endl;
            free(tree_string);
            ts_tree_delete(tree);
        } else {
            std::cout << "WARNING: Parsing completed, but no tree was returned." << std::endl;
        }

        ts_parser_delete(parser);

    } catch (const std::exception& e) {
        std::cerr << "ERROR: " << e.what() << std::endl;
        if (library_handle) CLOSE_LIBRARY(library_handle);
        return 1;
    }

    // 핸들 해제
    if (library_handle) CLOSE_LIBRARY(library_handle);

    std::cout << "DEBUG: Program finished." << std::endl;
    return 0;
}