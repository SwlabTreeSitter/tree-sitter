#include <iostream>
#include <string>
#include <vector>
#include <fstream>
#include <sstream>
#include "lib/include/tree_sitter/api.h"

// 플랫폼(운영체제)에 따라 동적 라이브러리 로딩을 위한 헤더를 포함합니다.
#ifdef _WIN32
#include <windows.h>
#else
#include <dlfcn.h>
#endif

// --- 정적으로 링크된 언어 함수 선언 ---
extern "C" TSLanguage *tree_sitter_smallbasic();

// TSLanguage*를 반환하는 함수 포인터 타입을 정의합니다.
typedef TSLanguage *(*LanguageFunction)();

int main(int argc, char* argv[]) {
    // --- 1. 명령줄 인자 파싱 로직 강화 ---
    if (argc < 3) {
        std::cerr << "Usage: " << argv[0] << " <lang> [<lib_path>] <file_path> [<stop_row> <stop_col>]" << std::endl;
        std::cerr << "\n  Examples:" << std::endl;
        std::cerr << "    ./my_parser smallbasic ./test.sb" << std::endl;
        std::cerr << "    ./my_parser smallbasic ./test.sb 5 10" << std::endl;
        std::cerr << "    ./my_parser python ./python.dll ./test.py 20 5" << std::endl;
        return 1;
    }

    std::string language_name = argv[1];
    TSLanguage *language = nullptr;
    const char* file_path = nullptr;

    bool stop_position_provided = false;
    uint32_t stop_row = 0;
    uint32_t stop_col = 0;

    // --- 2. 언어 로딩 (정적/동적 분기) 및 인자 해석 ---
    if (language_name == "smallbasic") {
        language = tree_sitter_smallbasic();
        file_path = argv[2];
        // 정적 언어의 경우, 인자가 5개이면 중단점이 제공된 것입니다.
        if (argc == 5) {
            stop_position_provided = true;
            stop_row = std::stoul(argv[3]);
            stop_col = std::stoul(argv[4]);
        }
    } 
    else {
        // 동적 언어의 경우, 최소 4개의 인자가 필요합니다.
        if (argc < 4) {
            std::cerr << "Error: Path to dynamic library is required for language '" << language_name << "'." << std::endl;
            return 1;
        }
        const char* library_path = argv[2];
        file_path = argv[3];

        // 동적 라이브러리 로드
        #ifdef _WIN32
            HMODULE library = LoadLibraryA(library_path);
            if (!library) { /* 에러 처리 */ return 1; }
        #else
            void* library = dlopen(library_path, RTLD_LAZY);
            if (!library) { /* 에러 처리 */ return 1; }
        #endif

        // 언어 함수 찾기
        std::string language_func_name = "tree_sitter_" + language_name;
        LanguageFunction language_function = nullptr;
        #ifdef _WIN32
            language_function = (LanguageFunction)GetProcAddress(library, language_func_name.c_str());
        #else
            language_function = (LanguageFunction)dlsym(library, language_func_name.c_str());
        #endif

        if (!language_function) { /* 에러 처리 */ return 1; }
        language = language_function();

        // 동적 언어의 경우, 인자가 6개이면 중단점이 제공된 것입니다.
        if (argc == 6) {
            stop_position_provided = true;
            stop_row = std::stoul(argv[4]);
            stop_col = std::stoul(argv[5]);
        }
    }
    
    // --- 3. 파싱 준비 및 중단점 설정 ---
    if (!language || !file_path) {
        std::cerr << "Error: Could not determine language or file path from arguments." << std::endl;
        return 1;
    }

    TSParser *parser = ts_parser_new();
    ts_parser_set_language(parser, language);
    
    // (핵심) 중단점 인자가 제공된 경우에만 함수를 호출합니다.
    if (stop_position_provided) {
        // TSPoint는 0-based index이므로, 사용자 입력에서 1을 빼줍니다.
        TSPoint stop_point = {stop_row - 1, stop_col - 1};
        ts_parser_set_stop_position(parser, stop_point);
        std::cout << "--- Stop position set at row " << stop_row << ", col " << stop_col << " ---" << std::endl;
    }

    // --- 4. 파싱 실행 및 결과 출력 (이하 공통 로직) ---
    std::ifstream file(file_path);
    if (!file) { /* ... 에러 처리 ... */ }
    std::stringstream buffer;
    buffer << file.rdbuf();
    std::string source_code = buffer.str();

    TSTree *tree = ts_parser_parse_string(parser, NULL, source_code.c_str(), source_code.length());

    if (tree) {
        TSNode root_node = ts_tree_root_node(tree);
        char *tree_string = ts_node_string(root_node);
        std::cout << "\nParse Tree for " << language_name << ":\n" << tree_string << std::endl;
        
        free(tree_string);
        ts_tree_delete(tree);
        std::cout << "\nAnalysis files (e.g., Test.data) have been generated." << std::endl;
    }

    ts_parser_delete(parser);
    return 0;
}