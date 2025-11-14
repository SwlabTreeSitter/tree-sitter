// #include <iostream>
// #include <string>
// #include <vector>
// #include <fstream>
// #include <sstream>
// #include <algorithm> // for std::min
// #include <limits>    // for UINT32_MAX if needed by older compilers
// #include "lib/include/tree_sitter/api.h"
// // ------------------------------------

// // 플랫폼(운영체제)에 따라 동적 라이브러리 로딩을 위한 헤더를 포함합니다.
// #ifdef _WIN32
// #include <windows.h>
// #else
// #include <dlfcn.h>
// #endif

// // --- 정적으로 링크된 언어 함수 선언 (프로젝트에 포함된 언어) ---
// // 이 함수들의 실제 구현은 컴파일 시 함께 링크되어야 합니다.
// extern "C" TSLanguage *tree_sitter_smallbasic();
// // extern "C" TSLanguage *tree_sitter_c(); // 예시: C 언어도 정적으로 포함했다면

// // TSLanguage*를 반환하는 함수 포인터 타입을 정의합니다. (동적 로딩용)
// typedef TSLanguage *(*LanguageFunction)();


// // ========================[ 헬퍼 함수: 위치 -> 바이트 오프셋 ]========================
// // 문자열에서 특정 행, 열(0-based)에 해당하는 바이트 오프셋(byte offset)을 찾는 함수
// // 참고: 탭 및 UTF-8 처리가 단순화되어 있어 완벽하지 않을 수 있습니다.
// size_t FindByteOffsetForPosition(const std::string& text, uint32_t target_row, uint32_t target_col) {
//     size_t current_offset = 0;
//     uint32_t current_row = 0; // 0-based index
//     uint32_t current_col = 0; // 0-based index
//     const uint32_t tab_width = 4; // 탭 너비를 4칸으로 가정

//     while (current_offset < text.length()) {
//         // 목표 위치에 도달했는지 확인 (현재 위치가 목표 위치 이상이면 중단)
//         if (current_row > target_row || (current_row == target_row && current_col > target_col)) {
//             return current_offset;
//         }

//         unsigned char current_char = static_cast<unsigned char>(text[current_offset]);

//         // 줄바꿈 처리 (LF, CRLF)
//         if (current_char == '\n') {
//             current_row++;
//             current_col = 0;
//             current_offset++;
//         } else if (current_char == '\r' && (current_offset + 1 < text.length() && text[current_offset + 1] == '\n')) {
//             current_row++;
//             current_col = 0;
//             current_offset += 2;
//         }
//         // 탭 처리
//         else if (current_char == '\t') {
//             current_col = ((current_col / tab_width) + 1) * tab_width;
//             current_offset++;
//         }
//         // 일반 문자 처리 (간단한 UTF-8 멀티바이트 건너뛰기 시도)
//         else {
//              current_col++;
//              current_offset++;
//              if (current_char >= 0xC0) { // 멀티바이트 시작 바이트 가능성 (2바이트 이상)
//                  while (current_offset < text.length() && (static_cast<unsigned char>(text[current_offset]) & 0xC0) == 0x80) {
//                      current_offset++; // 후속 바이트 건너뛰기
//                  }
//              }
//         }
//     }
//     // 목표 위치를 찾지 못했거나 문자열 끝에 도달하면 전체 길이를 반환
//     return text.length();
// }
// // ====================================================================


// int main(int argc, char* argv[]) {
//     std::cout << "DEBUG: Program started." << std::endl;

//     // --- 1. 명령줄 인자 파싱 ---
//     if (argc < 3) {
//         std::cerr << "Usage: " << argv[0] << " <lang> [<lib_path>] <file_path> [<stop_row> <stop_col>]" << std::endl;
//         std::cerr << "\n  Examples:" << std::endl;
//         std::cerr << "    " << argv[0] << " smallbasic ./test.sb" << std::endl;
//         std::cerr << "    " << argv[0] << " smallbasic ./test.sb 5 10" << std::endl;
//         std::cerr << "    " << argv[0] << " python ./python.dll ./test.py 20 5" << std::endl;
//         return 1;
//     }

//     std::string language_name = argv[1];
//     TSLanguage *language = nullptr;
//     const char* file_path = nullptr;
//     HMODULE library_handle = nullptr; // Windows DLL 핸들
//     void* library_handle_unix = nullptr; // POSIX dylib/so 핸들

//     bool stop_position_provided = false;
//     uint32_t stop_row = 0; // 1-based index from user
//     uint32_t stop_col = 0; // 1-based index from user
//     uint32_t read_row = 0; // 1-based index from user
//     uint32_t read_col = 0; // 1-based index from user
//     bool bIsCollectionOrParseStateID = false;


//     // --- 2. 언어 로딩 (정적/동적 분기) 및 인자 해석 ---
//     try {
//         if (language_name == "smallbasic") {
//             std::cout << "DEBUG: Loading statically-linked language: smallbasic" << std::endl;
//             language = tree_sitter_smallbasic();
//             if (argc < 3) throw std::invalid_argument("File path is missing for static language.");
//             file_path = argv[2];
//             if (argc == 5) { // 프로그램이름 lang 파일경로 행 열
//                 stop_position_provided = true;
//                 stop_row = read_row = std::stoul(argv[3]);
//                 stop_col = read_col = std::stoul(argv[4]);
//                 bIsCollectionOrParseStateID = (bool)argv[5];
//             } else if (argc != 3) {
//                 throw std::invalid_argument("Incorrect number of arguments for static language.");
//             }
//         }
//         // else if (language_name == "c") { /* 다른 정적 언어 처리 */ }
//         else {
//             std::cout << "DEBUG: Attempting to dynamically load language: " << language_name << std::endl;
//             if (argc < 4) { // 프로그램이름 lang dll경로 파일경로
//                 throw std::invalid_argument("Path to dynamic library and file path are required.");
//             }
//             const char* library_path = argv[2];
//             file_path = argv[3];

//             #ifdef _WIN32
//                 library_handle = LoadLibraryA(library_path);
//                 if (!library_handle) {
//                     throw std::runtime_error("Could not load library " + std::string(library_path) + ". GetLastError() = " + std::to_string(GetLastError()));
//                 }
//             #else
//                 library_handle_unix = dlopen(library_path, RTLD_LAZY);
//                 if (!library_handle_unix) {
//                     throw std::runtime_error("Could not load library " + std::string(library_path) + ": " + dlerror());
//                 }
//             #endif
//             std::cout << "DEBUG: Library loaded successfully." << std::endl;

//             std::string language_func_name = "tree_sitter_" + language_name;
//             std::cout << "DEBUG: Searching for function: '" << language_func_name << "'..." << std::endl;
//             LanguageFunction language_function = nullptr;
//             #ifdef _WIN32
//                 language_function = (LanguageFunction)GetProcAddress(library_handle, language_func_name.c_str());
//             #else
//                 language_function = (LanguageFunction)dlsym(library_handle_unix, language_func_name.c_str());
//             #endif

//             if (!language_function) {
//                 throw std::runtime_error("Could not find function '" + language_func_name + "' in library.");
//             }
//             std::cout << "DEBUG: Function found." << std::endl;
            
//             language = language_function();
//             if (!language) {
//                 throw std::runtime_error("Failed to get language pointer from function.");
//             }

//             if (argc == 6) { // 프로그램이름 lang dll경로 파일경로 행 열
//                 stop_position_provided = true;
//                 stop_row = read_row = std::stoul(argv[4]);
//                 stop_col = read_col = std::stoul(argv[5]);
//                 bIsCollectionOrParseStateID = (bool)argv[6];
//             } else if (argc != 4) {
//                  throw std::invalid_argument("Incorrect number of arguments for dynamic language.");
//             }
//         }

//         // --- 3. 파싱 준비 ---
//         if (!language || !file_path) {
//             throw std::runtime_error("Could not determine language or file path from arguments.");
//         }

//         TSParser *parser = ts_parser_new();
//         ts_parser_set_language(parser, language);
//         std::cout << "DEBUG: Parser created and language set." << std::endl;
//         ts_parser_set_threshold_read_cursor(parser, {read_row, read_col});
//         ts_parser_set_find_state_mode(parser, bIsCollectionOrParseStateID);
        
//         // --- 4. 파일 읽기 및 문자열 자르기 ---
//         std::cout << "DEBUG: Reading source file: " << file_path << std::endl;
//         std::ifstream file(file_path);
//         if (!file) {
//             throw std::runtime_error("Could not open source file " + std::string(file_path));
//         }
//         std::stringstream buffer;
//         buffer << file.rdbuf();
//         std::string source_code = buffer.str();
//         std::cout << "DEBUG: Source file read (" << source_code.length() << " bytes)." << std::endl;

//         size_t effective_length = source_code.length();

//         if (stop_position_provided) {
//             std::cout << "--- Stop position requested at row " << stop_row << ", col " << stop_col << " ---" << std::endl;
            
//             // 사용자 입력(1-based)을 0-based index로 변환하여 바이트 오프셋 계산
//             size_t stop_offset = FindByteOffsetForPosition(source_code, stop_row - 1, stop_col - 1);
            
//             effective_length = source_code.length() < stop_offset ? source_code.length() : stop_offset;
            
//             std::cout << "DEBUG: Effective parsing length set to " << effective_length << " bytes." << std::endl;
//         }

//         // --- 5. 파싱 실행 ---
//         std::cout << "DEBUG: Starting parse..." << std::endl;
//         TSTree *tree = ts_parser_parse_string(
//             parser,
//             NULL,
//             source_code.c_str(),
//             static_cast<uint32_t>(effective_length)
//         );
//         std::cout << "DEBUG: Parsing finished." << std::endl;

//         // --- 6. 결과 출력 및 정리 ---
//         if (tree) {
//             TSNode root_node = ts_tree_root_node(tree);
//             char *tree_string = ts_node_string(root_node);
//             std::cout << "\nParse Tree for " << language_name << ":\n" << tree_string << std::endl;
            
//             free(tree_string);
//             ts_tree_delete(tree);
            
//             // 만약 Tree-sitter 라이브러리를 수정하여 로그 기능을 활성화했다면,
//             // 여기에 Test.data 파일 생성 로직 등을 넣을 수 있습니다.
//             // if (parser->logged_actions.size > 0) { /* ... 분석 코드 ... */ }

//         } else {
//             std::cout << "WARNING: Parsing completed, but no tree was returned (possibly due to stop position or error)." << std::endl;
//         }

//         ts_parser_delete(parser);

//     } catch (const std::exception& e) {
//         std::cerr << "ERROR: " << e.what() << std::endl;
//         // 동적으로 로드한 라이브러리 핸들 해제 (오류 발생 시)
//         #ifdef _WIN32
//             if (library_handle) FreeLibrary(library_handle);
//         #else
//             if (library_handle_unix) dlclose(library_handle_unix);
//         #endif
//         return 1; // 오류 코드로 종료
//     }

//     // 동적으로 로드한 라이브러리 핸들 해제 (정상 종료 시)
//     #ifdef _WIN32
//         if (library_handle) FreeLibrary(library_handle);
//     #else
//         if (library_handle_unix) dlclose(library_handle_unix);
//     #endif

//     std::cout << "DEBUG: Program finished." << std::endl;
//     return 0; // 정상 종료
// }

#include <iostream>
#include <string>
#include <vector>
#include <fstream>
#include <sstream>
#include <algorithm> // for std::min
#include <limits>    // for UINT32_MAX if needed by older compilers
#include "lib/include/tree_sitter/api.h"
// ------------------------------------

// 플랫폼(운영체제)에 따라 동적 라이브러리 로딩을 위한 헤더를 포함합니다.
#ifdef _WIN32
#include <windows.h>
#else
#include <dlfcn.h>
#endif

// --- 정적으로 링크된 언어 함수 선언 (프로젝트에 포함된 언어) ---
// 이 함수들의 실제 구현은 컴파일 시 함께 링크되어야 합니다.
extern "C" TSLanguage *tree_sitter_smallbasic();
// extern "C" TSLanguage *tree_sitter_c(); // 예시: C 언어도 정적으로 포함했다면

// TSLanguage*를 반환하는 함수 포인터 타입을 정의합니다. (동적 로딩용)
typedef TSLanguage *(*LanguageFunction)();


// ========================[ 헬퍼 함수: 위치 -> 바이트 오프셋 ]========================
// 문자열에서 특정 행, 열(0-based)에 해당하는 바이트 오프셋(byte offset)을 찾는 함수
// 참고: 탭 및 UTF-8 처리가 단순화되어 있어 완벽하지 않을 수 있습니다.
size_t FindByteOffsetForPosition(const std::string& text, uint32_t target_row, uint32_t target_col) {
    size_t current_offset = 0;
    uint32_t current_row = 0; // 0-based index
    uint32_t current_col = 0; // 0-based index
    const uint32_t tab_width = 4; // 탭 너비를 4칸으로 가정

    while (current_offset < text.length()) {
        // 목표 위치에 도달했는지 확인 (현재 위치가 목표 위치 '이상'이면 중단)
        // (수정: > 를 >= 로 변경하여 정확히 해당 위치에서 멈춤)
        if (current_row > target_row || (current_row == target_row && current_col >= target_col)) {
             return current_offset;
        }

        unsigned char current_char = static_cast<unsigned char>(text[current_offset]);

        // 줄바꿈 처리 (LF, CRLF)
        if (current_char == '\n') {
            current_row++;
            current_col = 0;
            current_offset++;
        } else if (current_char == '\r' && (current_offset + 1 < text.length() && text[current_offset + 1] == '\n')) {
            current_row++;
            current_col = 0;
            current_offset += 2;
        }
        // 탭 처리
        else if (current_char == '\t') {
            current_col = ((current_col / tab_width) + 1) * tab_width;
            current_offset++;
        }
        // 일반 문자 처리 (간단한 UTF-8 멀티바이트 건너뛰기 시도)
        else {
             current_col++;
             current_offset++;
             if (current_char >= 0xC0) { // 멀티바이트 시작 바이트 가능성 (2바이트 이상)
                 while (current_offset < text.length() && (static_cast<unsigned char>(text[current_offset]) & 0xC0) == 0x80) {
                     current_offset++; // 후속 바이트 건너뛰기
                 }
             }
        }
    }
    // 목표 위치를 찾지 못했거나 문자열 끝에 도달하면 전체 길이를 반환
    return text.length();
}
// ====================================================================


int main(int argc, char* argv[]) {
    std::cout << "DEBUG: Program started." << std::endl;

    // --- 1. 명령줄 인자 파싱 ---
    // (Usage 메시지는 [flag] 인자를 포함하도록 업데이트)
    if (argc < 3) {
        std::cerr << "Usage: " << argv[0] << " <lang> [<lib_path>] <file_path> [<stop_row> <stop_col> <flag>]" << std::endl;
        std::cerr << "\n  <flag>: 0 = Collection Mode, 1 = Parse State ID Mode" << std::endl;
        std::cerr << "\n  Examples:" << std::endl;
        std::cerr << "    " << argv[0] << " smallbasic ./test.sb" << std::endl;
        std::cerr << "    " << argv[0] << " smallbasic ./test.sb 5 10 0" << std::endl;
        std::cerr << "    " << argv[0] << " python ./python.dll ./test.py 20 5 1" << std::endl;
        return 1;
    }

    std::string language_name = argv[1];
    TSLanguage *language = nullptr;
    const char* file_path = nullptr;
    HMODULE library_handle = nullptr; // Windows DLL 핸들
    void* library_handle_unix = nullptr; // POSIX dylib/so 핸들

    bool stop_position_provided = false;
    uint32_t stop_row = 0; // 1-based index from user
    uint32_t stop_col = 0; // 1-based index from user
    uint32_t read_row = 0; // 1-based index from user
    uint32_t read_col = 0; // 1-based index from user
    bool bIsCollectionOrParseStateID = false; // 기본값 false (컬렉션 모드)


    // --- 2. 언어 로딩 (정적/동적 분기) 및 인자 해석 ---
    try {
        if (language_name == "smallbasic") {
            std::cout << "DEBUG: Loading statically-linked language: smallbasic" << std::endl;
            language = tree_sitter_smallbasic();
            if (argc < 3) throw std::invalid_argument("File path is missing for static language.");
            file_path = argv[2];
            
            // (수정: argc == 5 를 argc == 6 으로 변경)
            // 프로그램이름(1) lang(2) 파일경로(3) 행(4) 열(5) 플래그(6)
            if (argc == 6) { 
                stop_position_provided = true;
                stop_row = read_row = std::stoul(argv[3]);
                stop_col = read_col = std::stoul(argv[4]);
                
                // (수정: (bool)argv[5] 를 문자열 비교로 변경)
                std::string flag_str = argv[5];
                bIsCollectionOrParseStateID = (flag_str != "0"); // "0"이 아니면(e.g. "1") true
                std::cout << "DEBUG: Flag set to: " << (bIsCollectionOrParseStateID ? "Parse State ID Mode" : "Collection Mode") << std::endl;

            } else if (argc != 3) {
                // (argc가 3도 아니고 6도 아니면 오류)
                throw std::invalid_argument("Incorrect number of arguments for static language. Expected 3 or 6.");
            }
        }
        // else if (language_name == "c") { /* 다른 정적 언어 처리 */ }
        else {
            std::cout << "DEBUG: Attempting to dynamically load language: " << language_name << std::endl;
            if (argc < 4) { // 프로그램이름 lang dll경로 파일경로
                throw std::invalid_argument("Path to dynamic library and file path are required.");
            }
            const char* library_path = argv[2];
            file_path = argv[3];

            #ifdef _WIN32
                library_handle = LoadLibraryA(library_path);
                if (!library_handle) {
                    throw std::runtime_error("Could not load library " + std::string(library_path) + ". GetLastError() = " + std::to_string(GetLastError()));
                }
            #else
                library_handle_unix = dlopen(library_path, RTLD_LAZY);
                if (!library_handle_unix) {
                    throw std::runtime_error("Could not load library " + std::string(library_path) + ": " + dlerror());
                }
            #endif
            std::cout << "DEBUG: Library loaded successfully." << std::endl;

            std::string language_func_name = "tree_sitter_" + language_name;
            std::cout << "DEBUG: Searching for function: '" << language_func_name << "'..." << std::endl;
            LanguageFunction language_function = nullptr;
            #ifdef _WIN32
                language_function = (LanguageFunction)GetProcAddress(library_handle, language_func_name.c_str());
            #else
                language_function = (LanguageFunction)dlsym(library_handle_unix, language_func_name.c_str());
            #endif

            if (!language_function) {
                throw std::runtime_error("Could not find function '" + language_func_name + "' in library.");
            }
            std::cout << "DEBUG: Function found." << std::endl;
            
            language = language_function();
            if (!language) {
                throw std::runtime_error("Failed to get language pointer from function.");
            }

            // (수정: argc == 6 를 argc == 7 로 변경)
            // 프로그램이름(1) lang(2) dll경로(3) 파일경로(4) 행(5) 열(6) 플래그(7)
            if (argc == 7) { 
                stop_position_provided = true;
                stop_row = read_row = std::stoul(argv[4]);
                stop_col = read_col = std::stoul(argv[5]);

                // (수정: (bool)argv[6] 를 문자열 비교로 변경)
                std::string flag_str = argv[6];
                bIsCollectionOrParseStateID = (flag_str != "0"); // "0"이 아니면(e.g. "1") true
                std::cout << "DEBUG: Flag set to: " << (bIsCollectionOrParseStateID ? "Parse State ID Mode" : "Collection Mode") << std::endl;

            } else if (argc != 4) {
                 // (argc가 4도 아니고 7도 아니면 오류)
                throw std::invalid_argument("Incorrect number of arguments for dynamic language. Expected 4 or 7.");
            }
        }

        // --- 3. 파싱 준비 ---
        if (!language || !file_path) {
            throw std::runtime_error("Could not determine language or file path from arguments.");
        }
        
        // (stop_position이 제공되었을 때만 row/col/flag를 설정하도록 로직 변경)
        if (!stop_position_provided) {
            read_row = 0;
            read_col = 0;
            bIsCollectionOrParseStateID = false; // 위치 정보 없으면 무조건 컬렉션 모드 (0,0)
        }

        TSParser *parser = ts_parser_new();
        ts_parser_set_language(parser, language);
        std::cout << "DEBUG: Parser created and language set." << std::endl;

        ts_parser_set_stop_position(parser, {stop_row, stop_col});
        ts_parser_set_find_state_mode(parser, bIsCollectionOrParseStateID);
        
        // --- 4. 파일 읽기 및 문자열 자르기 ---
        std::cout << "DEBUG: Reading source file: " << file_path << std::endl;
        std::ifstream file(file_path);
        if (!file) {
            throw std::runtime_error("Could not open source file " + std::string(file_path));
        }
        std::stringstream buffer;
        buffer << file.rdbuf();
        std::string source_code = buffer.str();
        std::cout << "DEBUG: Source file read (" << source_code.length() << " bytes)." << std::endl;

        size_t effective_length = source_code.length();

        if (stop_position_provided) {
            std::cout << "--- Stop position requested at row " << stop_row << ", col " << stop_col << " ---" << std::endl;
            
            // 사용자 입력(1-based)을 0-based index로 변환하여 바이트 오프셋 계산
            // (FindByteOffsetForPosition은 0-based를 기대함)
            size_t stop_offset = FindByteOffsetForPosition(source_code, stop_row > 0 ? stop_row - 1 : 0, stop_col > 0 ? stop_col - 1 : 0);
            
            effective_length = source_code.length() < stop_offset ? source_code.length() : stop_offset;
            
            std::cout << "DEBUG: Effective parsing length set to " << effective_length << " bytes (target offset: " << stop_offset << ")." << std::endl;
        }

        // --- 5. 파싱 실행 ---
        std::cout << "DEBUG: Starting parse..." << std::endl;
        TSTree *tree = ts_parser_parse_string(
            parser,
            NULL,
            source_code.c_str(),
            static_cast<uint32_t>(effective_length)
        );
        std::cout << "DEBUG: Parsing finished." << std::endl;

        // --- 6. 결과 출력 및 정리 ---
        if (tree) {
            TSNode root_node = ts_tree_root_node(tree);
            char *tree_string = ts_node_string(root_node);
            std::cout << "\nParse Tree for " << language_name << ":\n" << tree_string << std::endl;
            
            free(tree_string);
            ts_tree_delete(tree);
            
        } else {
            std::cout << "WARNING: Parsing completed, but no tree was returned (possibly due to stop position or error)." << std::endl;
        }

        ts_parser_delete(parser);

    } catch (const std::exception& e) {
        std::cerr << "ERROR: " << e.what() << std::endl;
        // 동적으로 로드한 라이브러리 핸들 해제 (오류 발생 시)
        #ifdef _WIN32
            if (library_handle) FreeLibrary(library_handle);
        #else
            if (library_handle_unix) dlclose(library_handle_unix);
        #endif
        return 1; // 오류 코드로 종료
    }

    // 동적으로 로드한 라이브러리 핸들 해제 (정상 종료 시)
    #ifdef _WIN32
        if (library_handle) FreeLibrary(library_handle);
    #else
        if (library_handle_unix) dlclose(library_handle_unix);
    #endif

    std::cout << "DEBUG: Program finished." << std::endl;
    return 0; // 정상 종료
}