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

extern "C" {
    // 컨버전 (실제 코드 완성용: 소스를 커서 위치에서 잘라서 전달)
    TSStatePath ts_parser_parse_string_for_conversion(TSParser *self, const TSTree *old_tree, const char *string, uint32_t length);
    // 컨버전 평가용: 전체 소스를 전달하되 커서 위치만 별도로 지정
    TSStatePath ts_parser_parse_string_for_conversion_with_lookahead(TSParser *self, const TSTree *old_tree, const char *string, uint32_t full_length, uint32_t cursor_byte);
    void ts_parser_write_conversion_result(TSParser *self, TSStatePath *path, FILE *fp);

    // 컬렉션
    bool ts_parser_run_collection2(TSTree *tree, const char *source_code, uint32_t length, FILE *OutputFile);

    // 로그 덤프
    void ts_parser_write_logged_actions(TSParser *self, const char *filename);
}

// TSLanguage*를 반환하는 함수 포인터 타입을 정의 (동적 로딩용)
typedef TSLanguage *(*LanguageFunction)();


// 헬퍼 함수: 위치 -> 바이트 오프셋
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

// 로커 콜백 (트리시터 자체 로그 기록용)
void LogToFileCallback(void *payload, TSLogType type, const char *buffer) {
    FILE *fp = (FILE *)payload;
    if (fp) {
        fprintf(fp, "[%s] %s\n", (type == TSLogTypeParse ? "Parse" : "Lex"), buffer);
    }
}

// [Main]
int main(int argc, char* argv[]) {
    std::cout << "DEBUG: Program started." << std::endl;

    // 인자 파싱 변수
    std::string language_name;
    const char* library_path = nullptr;
    const char* target_path = nullptr;

    LibraryHandle library_handle = nullptr;

    uint32_t stop_row = 0;
    uint32_t stop_col = 0;

    int execution_mode = 0;

    // ==========================================================
    // 1. 인자 파싱 및 검증
    // 사용법 1 (컬렉션): exe lang dll file 1
    // 사용법 2 (컨버전): exe lang dll file row col 0
    // ==========================================================
    if (argc >= 4) {
        language_name = argv[1];
        library_path = argv[2];
        target_path = argv[3];

        if (argc == 7) {
            stop_row = std::stoul(argv[4]);
            stop_col = std::stoul(argv[5]);
            execution_mode = std::stoi(argv[6]);
        }
        else if (argc == 5) {
            execution_mode = std::stoi(argv[4]);
        }
        else if (argc == 4) {
            execution_mode = 0;
        }
        else {
            goto usage_error;
        }
    } else {
    usage_error:
        std::cerr << "Usage:" << std::endl;
        std::cerr << "  Collection:          " << argv[0] << " <lang> <dll> <file> 1" << std::endl;
        std::cerr << "  Conversion:          " << argv[0] << " <lang> <dll> <file> <row> <col> 0" << std::endl;
        std::cerr << "  Conversion (eval):   " << argv[0] << " <lang> <dll> <file> <row> <col> 2" << std::endl;
        return 1;
    }

    // ==========================================================
    // 2. 언어 로딩 (동적 로딩으로 통일)
    // ==========================================================
    try {
        // DLL 파일 열기
        library_handle = LOAD_LIBRARY(library_path);
        // std::cout << "DEBUG: Loading dynamic library: " << library_path << std::endl;
        if (!library_handle) { throw std::runtime_error("Could not load library: " + GET_ERROR_MSG()); }

        // 함수 심볼 찾기 (tree_sitter_언어이름)
        std::string language_func_name = "tree_sitter_" + language_name;
        // std::cout << "DEBUG: Searching for function: '" << language_func_name << "'..." << std::endl;
        LanguageFunction language_function = (LanguageFunction)GET_PROC_ADDRESS(library_handle, language_func_name.c_str());
        if (!language_function) { throw std::runtime_error("Could not find function '" + language_func_name + "' in library."); }

        // 언어 포인터 획득
        TSLanguage *language = language_function();
        if (!language) { throw std::runtime_error("Failed to get language pointer from function."); }

        // 파싱 준비
        TSParser *parser = ts_parser_new();
        ts_parser_set_language(parser, language);
        // std::cout << "DEBUG: Parser created and language set." << std::endl;

        // 파일 읽기
        std::ifstream file(target_path);
        if (!file) { throw std::runtime_error("Could not open source file " + std::string(target_path)); }
        std::stringstream buffer;
        buffer << file.rdbuf();
        std::string source_code = buffer.str();

        // 파싱 길이 결정
        size_t effective_length = source_code.length();

        // ==========================================================
        // 3. 실행 길이(Position) 결정
        // ==========================================================
        if (execution_mode == 0 || execution_mode == 2) {
            std::cout << "--- Stop position requested at row " << stop_row << ", col " << stop_col << " ---" << std::endl;
            size_t stop_offset = FindByteOffsetForPosition(source_code, stop_row > 0 ? stop_row - 1 : 0, stop_col > 0 ? stop_col - 1 : 0);
            effective_length = (std::min)(source_code.length(), stop_offset);
            std::cout << "DEBUG: Effective parsing length set to " << effective_length << " bytes." << std::endl;
        } else {
            // 컬렉션 모드(1)는 파일 전체를 파싱합니다.
            std::cout << "DEBUG: Full mode (Length: " << effective_length << ")" << std::endl;
        }

        // ==========================================================
        // 4. 일반 파싱 수행
        // ==========================================================
        // 로깅 시작 debug_log.txt
        FILE *debug_fp = nullptr;
        debug_fp = fopen("debug_log.txt", "w");
        if (debug_fp) {
            TSLogger logger;
            logger.payload = debug_fp;
            logger.log = LogToFileCallback;
            ts_parser_set_logger(parser, logger);
        }

        // 파싱 실행
        std::cout << "DEBUG: Parsing start ..." << std::endl;
        TSTree *tree = ts_parser_parse_string(
            parser,
            NULL,
            source_code.c_str(),
            static_cast<uint32_t>(effective_length)
        );
        std::cout << "DEBUG: Parsing finished." << std::endl;

        // 로깅 종료
        if (debug_fp) {
            ts_parser_set_logger(parser, {0}); // 로거 해제
            fclose(debug_fp);
        }
            
        // [로그 덤프] logged_actions.txt 저장
        ts_parser_write_logged_actions(parser, "logged_actions.txt");

        // ==========================================================
        // 5. 모드별 후처리 로직 분기
        // ==========================================================
            if (execution_mode == 1) {
                // ------------------------------------------------------
                // [모드 1] Collection
                // ------------------------------------------------------
                std::cout << "DEBUG: Running Collection..." << std::endl;

                FILE *collection_fp = fopen("Test.data", "w");
                if (collection_fp) {
                    bool is_success = ts_parser_run_collection2(tree, source_code.c_str(), static_cast<uint32_t>(effective_length), collection_fp);
                    fclose(collection_fp);

                    if (!is_success) {
                        std::cerr << "[SKIP] Recovery detected in file: " << target_path << std::endl;
                        std::cout << "WARNING: Collection skipped due to parse errors." << std::endl;
                        remove("Test.data"); // 오염된 데이터 파일 삭제
                    } else {
                        std::cout << "DEBUG: Collection completed successfully." << std::endl;
                    }
                } else {
                    std::cerr << "ERROR: Could not open Test.data for writing." << std::endl;
                }
            } 
            else if (execution_mode == 0 || execution_mode == 2) {
                // ------------------------------------------------------
                // [모드 0] Conversion (실제 코드 완성: 잘린 소스)
                // [모드 2] Conversion Eval (평가용: 전체 소스 + 커서 위치)
                // ------------------------------------------------------
                const char *mode_label = (execution_mode == 2)
                    ? "Updated Conversion (eval/lookahead)"
                    : "Updated Conversion";
                std::cout << "DEBUG: Running " << mode_label << "..." << std::endl;

                // conversion parse 로깅
                FILE *conv_fp = fopen("debug_log_conv.txt", "w");
                if (conv_fp) {
                    TSLogger conv_logger;
                    conv_logger.payload = conv_fp;
                    conv_logger.log = LogToFileCallback;
                    ts_parser_set_logger(parser, conv_logger);
                }

                TSStatePath path2;
                if (execution_mode == 2) {
                    // 전체 소스를 전달하고 커서 위치만 별도로 지정
                    // 렉서/외부 스캐너가 커서 이후를 lookahead로 활용 가능
                    uint32_t full_length = static_cast<uint32_t>(source_code.length());
                    uint32_t cursor_byte = static_cast<uint32_t>(effective_length);
                    path2 = ts_parser_parse_string_for_conversion_with_lookahead(
                        parser,
                        NULL,
                        source_code.c_str(),
                        full_length,
                        cursor_byte
                    );
                } else {
                    path2 = ts_parser_parse_string_for_conversion(
                        parser,
                        NULL,
                        source_code.c_str(),
                        static_cast<uint32_t>(effective_length)
                    );
                }

                if (conv_fp) {
                    ts_parser_set_logger(parser, {0});
                    fclose(conv_fp);
                }

                // Python 스크립트용 출력
                std::cout << "@@PREDICT:";
                for (int i = 0; i < path2.count; i++) {
                    std::cout << " " << path2.states[i];
                }
                std::cout << std::endl;

                FILE *test_data_fp = fopen("Test.data", "w");
                if (test_data_fp) {
                    ts_parser_write_conversion_result(parser, &path2, test_data_fp);
                    fclose(test_data_fp);
                }
            }
            
            // ==========================================================
            // 6. 결과 출력 및 리소스 정리
            // ==========================================================
            if (tree) {
                TSNode root_node = ts_tree_root_node(tree);
                char *tree_string = ts_node_string(root_node);
                std::cout << "\nParse Tree for " << language_name << ":\n" << tree_string << std::endl;
                free(tree_string);
                ts_tree_delete(tree);
            } else {
                std::cout << "WARNING: Parsing completed, but no tree was returned." << std::endl;
            }
        
        // 파서 해제
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