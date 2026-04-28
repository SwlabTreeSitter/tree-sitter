// ==========================================================
// TreeSitterCutFile
// ----------------------------------------------------------
// 무엇을 하는가:
//   소스 파일 하나를 받아서 파싱한 뒤 결과를 파일로 떨어뜨리는 CLI 도구.
//   파이썬 스크립트(평가/수집 파이프라인)가 파일마다 이 실행 파일을 호출해서 사용한다.
//
// 두 가지 동작 모드:
//   1) Collection — 파일을 끝까지 파싱하면서, 각 파서 상태에서 나타난
//                   구조후보(candidate)들을 학습 데이터로 수집한다.
//                   TEST(=1) 와 LEARN(=3) 두 변종 — TEST 는 정답지용으로 lexeme 텍스트를
//                   같이 적고, LEARN 은 통계 집계용이라 lexeme 을 적지 않는다.
//   2) Conversion — 커서 위치까지 파싱하고, 그 시점의 파서 상태(state path)를
//                   추출한다. 코드 자동완성에서 다음에 올 토큰을 추천할 때 쓰인다.
//
// 사용법:
//   Collection (TEST,  lexeme 포함):
//     TreeSitterCutFile.exe <lang> <lib> <file> 1
//
//   Collection (LEARN, lexeme 미포함):
//     TreeSitterCutFile.exe <lang> <lib> <file> 3
//
//   Conversion (커서 위치는 바이트 오프셋으로 지정):
//     TreeSitterCutFile.exe <lang> <lib> <file> <offset> 0|2
//       0 = 실제 자동완성 (커서 이후는 안 봄)
//       2 = 평가용 (전체 소스를 주되 커서 위치만 따로 알려줌. 렉서가 lookahead 가능)
//
//   인자 설명:
//     <lang>   : 언어 이름 ("c", "python", "haskell" 등). grammar 함수 이름에 쓰임
//                (예: tree_sitter_python).
//     <lib>    : 언어별 grammar 가 담긴 .so / .dll 파일 경로. 동적 로딩으로 불러온다.
//     <file>   : 파싱할 소스 파일 경로.
//     <offset> : 커서 위치 (파일 시작부터의 바이트 수).
//
// 결과물 (실행 디렉터리에 떨어짐):
//   Test.data          — 모드별 핵심 결과
//   logged_actions.txt — 파서가 수행한 액션 로그
//   debug_log*.txt     — 트리시터 자체 디버그 로그
//
// 참고:
//   이 도구는 표준 tree-sitter 가 아니라 자체 확장된 libtree-sitter 와 함께 빌드된다.
//   확장된 API(ts_parser_run_collection2 등)는 lib/src/parser.c 에 정의돼 있다.
// ==========================================================

#include <iostream>
#include <string>
#include <vector>
#include <fstream>
#include <sstream>
#include <algorithm> // for std::min
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

    // 컬렉션 (emit_lexeme=true: TEST 용 @<off>: <lex>, false: LEARN 용 @<off> 만)
    bool ts_parser_run_collection2(TSParser *self, TSTree *tree, const char *source_code, uint32_t length, FILE *OutputFile, bool emit_lexeme);

    // 컬렉션 모드 설정
    void ts_parser_set_collection_mode(TSParser *self, bool enabled);

    // 로그 덤프
    void ts_parser_write_logged_actions(TSParser *self, const char *filename);
}

// TSLanguage*를 반환하는 함수 포인터 타입을 정의 (동적 로딩용)
typedef TSLanguage *(*LanguageFunction)();


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

    int execution_mode = 0;
    bool byte_mode = false;      // 컨버전 모드에서 바이트 오프셋이 주어졌는지
    size_t byte_offset = 0;

    // ==========================================================
    // 1. 인자 파싱 및 검증
    // 사용법 1 (TEST collection,  lexeme 포함): exe lang dll file 1
    // 사용법 2 (Conversion):                    exe lang dll file <offset> 0|2
    // 사용법 3 (LEARN collection, lexeme 미포함): exe lang dll file 3
    // ==========================================================
    if (argc >= 4) {
        language_name = argv[1];
        library_path = argv[2];
        target_path = argv[3];

        if (argc == 6) {
            byte_mode = true;
            byte_offset = std::stoul(argv[4]);
            execution_mode = std::stoi(argv[5]);
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
        std::cerr << "  Collection (TEST):  " << argv[0] << " <lang> <dll> <file> 1" << std::endl;
        std::cerr << "  Collection (LEARN): " << argv[0] << " <lang> <dll> <file> 3" << std::endl;
        std::cerr << "  Conversion:         " << argv[0] << " <lang> <dll> <file> <offset> 0|2" << std::endl;
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
            if (byte_mode) {
                effective_length = (std::min)(source_code.length(), byte_offset);
                std::cout << "--- Stop at byte offset " << effective_length << " ---" << std::endl;
            }
            // 줄바꿈 보정 (layout 의존 언어만):
            // haskell 등에서는 \n이 layout 구분자이므로 포함해야 파싱이 올바르다.
            if (language_name == "haskell" && effective_length < source_code.length()) {
                if (source_code[effective_length] == '\r' &&
                    effective_length + 1 < source_code.length() &&
                    source_code[effective_length + 1] == '\n') {
                    effective_length += 2;  // \r\n
                } else if (source_code[effective_length] == '\n') {
                    effective_length += 1;  // \n
                }
            }
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

        // 컬렉션 모드일 때 (TEST=1, LEARN=3): SHIFT 시 리프에 reduce 후 GOTO 상태(S2)를 저장
        bool is_collection = (execution_mode == 1 || execution_mode == 3);
        if (is_collection) {
            ts_parser_set_collection_mode(parser, true);
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

        // 컬렉션 모드 해제
        if (is_collection) {
            ts_parser_set_collection_mode(parser, false);
        }

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
            if (is_collection) {
                // ------------------------------------------------------
                // [모드 1] Collection (TEST: lexeme 포함)
                // [모드 3] Collection (LEARN: lexeme 미포함)
                // ------------------------------------------------------
                bool emit_lexeme = (execution_mode == 1);
                std::cout << "DEBUG: Running Collection ("
                          << (emit_lexeme ? "TEST/with lexeme" : "LEARN/no lexeme")
                          << ")..." << std::endl;

                // smallbasic: 최종 파스트리에 ERROR 노드가 하나라도 있으면 파일 전체를 skip
                // (Python 측 LitDev 필터 통과 후 남은 파일에 대해서만 적용됨)
                if (language_name == "smallbasic" && tree && ts_node_has_error(ts_tree_root_node(tree))) {
                    std::cerr << "[SKIP] Parse error in smallbasic file: " << target_path << std::endl;
                    std::cout << "WARNING: Collection skipped (smallbasic whole-file skip policy)." << std::endl;
                } else {
                    FILE *collection_fp = fopen("Test.data", "w");
                    if (collection_fp) {
                        bool is_success = ts_parser_run_collection2(parser, tree, source_code.c_str(), static_cast<uint32_t>(effective_length), collection_fp, emit_lexeme);
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