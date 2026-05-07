// ==========================================================
// TreeSitterCutFile
// ----------------------------------------------------------
//  무엇을 하는가:                           
//      fork 된 tree-sitter 에 추가한 컬렉션과 컨버전을 위한 커스텀 함수들을
//      호출해 파싱과 함께 필요한 정보들을 뽑아내는 CLI 도구.
//
//  동작 모드:
//      [original]
//          0 - Conversion (without lookahead) : 커서 시점 state path 추출
//          1 - Collection (with lexeme)       : 전체 파싱, (state, 구조 후보) 출력. lexeme 포함 (TEST 평가 디버깅용)
//      [modified]
//          2 - Conversion (with lookahead)    : 커서 시점 state path 추출. 전체 소스를 제공해 렉서 lookahead 허용.
//          3 - Collection (without lexeme)    : 전체 파싱, (state, 구조 후보) 출력. lexeme 미포함 (LEARN 시 lexeme이 노이즈가 되는 경우 방지 위함)
//
//  사용법:
//      Conversion: TreeSitterCutFile.exe <lang> <lib> <file> <offset> 0
//                  TreeSitterCutFile.exe <lang> <lib> <file> <offset> 2
//      Collection: TreeSitterCutFile.exe <lang> <lib> <file> 1
//                  TreeSitterCutFile.exe <lang> <lib> <file> 3
//
//  인자 설명:
//     <lang>   : tree-sitter-<lang>의  <lang> (언어 이름)
//     <lib>    : 언어별 grammar 가 담긴 .so / .dll 파일 경로
//     <file>   : 파싱할 소스 파일 경로
//     <offset> : 커서 위치 (파일 시작부터의 바이트 수)
//
//  결과물:
//   Test.data          — 모드별 실행 결과
//   logged_actions.txt — 파서가 수행한 액션 로그
//   debug_log*.txt     — 트리시터 자체 디버그 로그
//
// ==========================================================

#include <iostream>
#include <string>
#include <vector>
#include <fstream>
#include <sstream>
#include <algorithm> // for std::min
#include "lib/include/tree_sitter/api.h"

// [플랫폼 호환성 추상화]
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
    #define GET_ERROR_MSG() (dlerror() ? std::string(dlerror()) : std::string("Unknown error"))
#endif


// 커스텀 함수 선언은 api.h 의 Custom 블록에 모여 있음

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
    bool byte_mode = false;
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
        // 3. 실행 길이 결정
        // ==========================================================
        if (execution_mode == 0 || execution_mode == 2) {
            if (byte_mode) {
                effective_length = (std::min)(source_code.length(), byte_offset);
                std::cout << "--- Stop at byte offset " << effective_length << " ---" << std::endl;
            }
            
            // TODO: layout 보정 유지/제거 결정 필요
            // - Haskell layout 보정: \n 이 statement 종결자
            // - 커서가 줄바꿈 직전이면 그 줄바꿈까지 포함 -> "줄을 마친" state 캡처
            // - Haskell의 컨버전 파싱에서 최대한 현재 커서 위치의 state를 올바르게 잡기 위해 추가한 보정
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
            // 컬렉션 모드는 파일 전체를 파싱
            std::cout << "DEBUG: Full mode (Length: " << effective_length << ")" << std::endl;
        }

        // ==========================================================
        // 4. 일반 파싱 수행 (모든 모드 공통)
        //    Collection (1/3): 결과 tree 가 run_collection2 의 입력으로 사용됨
        //    Conversion (0/2): 결과 tree 미사용. 이후 별도로 재파싱함
        //                      디버깅 시 debug_log.txt, logged_actions.txt 사용하기 위함
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
            
        // 로그 덤프: logged_actions.txt 저장
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
                std::cout << "DEBUG: Running Conversion (mode " << execution_mode << ")..." << std::endl;

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
                    ts_state_path_write(&path2, test_data_fp);
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