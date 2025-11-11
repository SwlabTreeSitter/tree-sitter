# tree-sitter

[![DOI](https://zenodo.org/badge/14164618.svg)](https://zenodo.org/badge/latestdoi/14164618)
[![discord][discord]](https://discord.gg/w7nTvsVJhm)
[![matrix][matrix]](https://matrix.to/#/#tree-sitter-chat:matrix.org)

Tree-sitter is a parser generator tool and an incremental parsing library. It can build a concrete syntax tree for a source file and efficiently update the syntax tree as the source file is edited. Tree-sitter aims to be:

- **General** enough to parse any programming language
- **Fast** enough to parse on every keystroke in a text editor
- **Robust** enough to provide useful results even in the presence of syntax errors
- **Dependency-free** so that the runtime library (which is written in pure C) can be embedded in any application

## Links
- [Documentation](https://tree-sitter.github.io)
- [Rust binding](lib/binding_rust/README.md)
- [WASM binding](lib/binding_web/README.md)
- [Command-line interface](crates/cli/README.md)

[discord]: https://img.shields.io/discord/1063097320771698699?logo=discord&label=discord
[matrix]: https://img.shields.io/matrix/tree-sitter-chat%3Amatrix.org?logo=matrix&label=matrix

<br><br>

## swlab Links
- [진행상황 기록 노션](https://www.notion.so/tree-sitter-2238687479db805f9f88debfffb48a45)
- [vscode UI 추가](https://github.com/kimkyungjae1112/CodeCompletion) 

## 사용 방법

1. cargo build 명령어

2. 테스트하려는 언어의 디렉터리에서 아래 명령어들을 순서대로 실행한다. (예: tree-sitter-python)

```rust
Generate: 문법 변경 사항을 C 코드로 생성한다.
..\tree-sitter\target\debug\tree-sitter generate --debug-build

Build: 생성된 C 코드를 컴파일하여 파서 라이브러리를 빌드한다.
..\tree-sitter\target\debug\tree-sitter build --debug

Parse: 빌드된 로컬 파서로 실제 파일을 파싱하여 테스트한다.
..\tree-sitter\target\debug\tree-sitter parse --debug pretty [파일이름]
```

3-1. 이후 파싱 상태를 기록한 파일이 해당 경로에 생긴다. (예: test.txt)

3-2. C++ 실행 프로그램 제작, 파일의 특정 행열까지 읽은 후 거기까지 내용을 tree-sitter에 전달

cl 컴파일러 이용
```
cl TreeSitterCutFile.cpp parser.c /MD /EHsc /std:c++17 /I./include /link /LIBPATH:./target/debug treesitter.lib /OUT:TreeSitterCutFile.exe  
```

실행법
```
.\[프로그램 이름] [언어 이름] [라이브러리 경로] [파싱할 파일 경로] [행 열]
```

```
// smallbasic 은 다른 언어와 다르게 사용
.\TreeSitterCutFile.exe smallbasic C:\Work\tree-sitter-smallbasic\SB_Sample\02_FontYellowColorRecover2.sb 2 1

.\TreeSitterCutFile.exe cpp C:\Work\tree-sitter-cpp\cpp.dll C:\Work\tree-sitter-cpp\main.cpp 3 2

.\TreeSitterCutFile.exe python C:\Work\tree-sitter-python\python.dll C:\Work\tree-sitter-python\Test.py 3 2
```



## 수정 파일
**parser.c**

- TSLoggedActionArray logged_actions : 파싱 액션을 기록하기 위한 동적 배열
- uint32_t StopRow, StopColumn : 파싱을 중단할 목표 위치 (현재 커서 위치를 받음)

- ts_parser__advance()
    - Shift, Reduce, Accept 액션이 발생할 때 액션의 정보를 logged_actions에 저장
- ts_parser_handle_error()
    - tree-sitter의 오류 복구가 시작될 때, 해당 위치와 상태 ID를 포함한 Recover 액션 로그를 logged_actions에 저장
- ts_parser__lex()
    - 어휘 분석기가 토큰을 읽기 전에 현재 위치가 중단점(StopRow, StopColumn)을 지났는지 확인
    - 만약 지났다면 강제로 EOF 토큰을 반환하여 파서의 파싱을 종료하게 만듬
- TsParserFindClosestRecoverState() - 커스텀
    - 행, 열을 받아 가장 가까운 Recover Action을 찾아 해당 상태 ID를 반환하는 메서드
- ts_parser_set_stop_position() - 커스텀
    - 파싱을 중단할 목표 위치(행, 열) 설정하는 메서드

**api.h**

- ts_parser_set_stop_position() - 커스텀
    - 외부에서 호출 가능하게 열어둠




## 코드 로직

**1. 개요**

이 분석 코드는 표준 Tree-sitter 라이브러리(parser.c)에서 작동하지 않으며, `parser.c` 파일이 다음과 같이 사전에 수정되어야 합니다.

*   **`TSLoggedAction` 구조체 정의:** `SHIFT`, `REDUCE`, `RECOVER` 액션의 상세 정보를 저장할 수 있는 커스텀 구조체가 정의되어 있어야 합니다.
*   **`TSParser` 구조체 확장:** `struct TSParser` 내부에 다음 멤버 변수가 추가되어 있어야 합니다.
    *   `TSLoggedActionArray logged_actions;`: 파싱 액션을 기록할 동적 배열.
    *   `uint32_t StopRow;`: 오류를 찾을 기준 커서의 행 (1-based).
    *   `uint32_t StopColumn;`: 오류를 찾을 기준 커서의 열 (1-based).
*   **`ts_parser__advance` 수정:** `SHIFT` 및 `REDUCE` 액션이 발생할 때마다 `TSLoggedAction` 객체를 생성하여 `self->logged_actions` 배열에 `array_push` 하도록 수정되어 있어야 합니다.
*   **`ts_parser__handle_error` 수정:** 오류 복구가 시작될 때 `TSParseActionTypeRecover` 타입의 `TSLoggedAction`을 생성하고, `next_state` (오류 발생 시점의 상태 ID)와 `symbol` (오류 유발 토큰 ID)을 `logged_actions` 배열에 `array_push` 하도록 수정되어 있어야 합니다.
*   **`TsParserFindClosestRecoverState` 함수 구현:** `parser.c` 파일 내 어딘가에 이 분석 코드가 호출하는 `TsParserFindClosestRecoverState` 함수가 구현되어 있어야 합니다.

**2. 동작 원리**

분석기는 크게 3단계로 동작합니다.

**2.1. 1단계: Shift 인덱싱**

*   전체 `logged_actions` 배열을 빠르게 순회하여 "엑스트라"가 아닌 모든 `SHIFT` 액션(실제 토큰)의 인덱스만 `ShiftIndices` 배열에 저장합니다.
*   이 배열은 분석을 시작할 "시작점(커서)" 목록이 됩니다.

**2.2. 2단계: "완전한 문법 단위" 경계 탐색**

*   `for (uint32_t i = 0...)` 루프는 `ShiftIndices` 배열을 순회하며 각 `SHIFT` 토큰을 문법 단위의 시작점(`CursorLogIndex`)으로 설정합니다.
*   **가상 스택 시뮬레이션 (`SimStack`):** `for (uint32_t j = CursorLogIndex...)` 루프는 `CursorLogIndex`부터 파싱을 시뮬레이션합니다.
    *   **`SHIFT` 처리:** `SHIFT`를 만나면 `SimStack`에 푸시(push)합니다.
    *   **`REDUCE` 처리:** `REDUCE` 액션을 만나면 스택에서 항목들을 팝(pop)해야 합니다.
    *   **문법 단위 끝 찾기 (`ConsumesCursor`):** `REDUCE`가 스택에서 제거할 항목 중에 문법 단위의 시작점(`CursorLogIndex`)이 포함되는지 검사합니다.
        *   **`if (ConsumesCursor)` (문법 단위 끝 발견):**
            *   `REDUCE`가 시작 토큰을 포함한다는 것은, `If`로 시작해서 `EndIf`로 끝나는 완전한 문법 단위("청크")를 찾았다는 의미입니다.
            *   이 문법 단위의 마지막 토큰 위치(`EndLogIndex`)와 `Reduce` 액션의 위치(`finalReduceLogIndex`)를 저장하고 시뮬레이션을 중단(`break`)합니다. 이 `break`는 경계 탐색 임무가 완료되었으므로 "2.3단계: 슬라이딩 윈도우 출력"으로 넘어가기 위해 의도된 동작입니다.
        *   **`else` (중간 단계 `Reduce`):**
            *   `Clock.Hour`가 `Primary`로 축약되는 것처럼, 문법 단위 내부의 작은 `Reduce`입니다.
            *   스택에서 `ID`, `.`, `ID`를 팝(pop)하고, 그 결과물인 `Primary`(논터미널)를 `IsTerminal = false`로 설정하여 스택에 다시 푸시(push)하고 시뮬레이션을 계속합니다.
    *   **오류 처리 (`bIsRecover`):** 시뮬레이션 중 `RECOVER` 액션을 만나면 `bIsRecover` 플래그를 `true`로 설정합니다. (단, 현재 코드에서는 이 플래그를 사용하지 않아 분석이 오류를 무시하고 계속 진행됩니다.)

**2.3. 3단계: 슬라이딩 윈도우 출력 (k 루프)**

*   "완전한 문법 단위"의 범위(시작 `i`부터 끝 `EndLogIndex`까지)가 확정되면, 이 범위 내의 모든 부분 시퀀스를 출력합니다.
*   **슬라이딩 윈도우 생성:** `for (uint32_t k = i...)` 루프는 `k` 값을 `i`부터 1씩 증가시키며 윈도우의 시작점을 한 칸씩 뒤로 밉니다.
*   **`StartState` 계산:** 각 윈도우(`k`)가 시작하기 직전의 파서 상태 ID를 `logged_actions`를 역방향으로 탐색하여 찾아냅니다. (예: `( Clock ...` 시퀀스의 `StartState`는 `(` 토큰의 `next_state` 값입니다.)
*   **'상위 심볼' 헤더 출력:** `if (k == i && ...)` 블록은 전체 문법 단위(`k=i`일 때)에 대해서만 파싱 시뮬레이션을 한 번 더 수행합니다(`headerStack`). 이 시뮬레이션은 중간 `Reduce`의 결과(논터미널, 예: `Expr`)를 스택에 반영하여 `1 Stmt_token9 Expr Stmt_token10 ...` 같은 라인을 출력합니다.
*   **'터미널 심볼' 헤더 출력:** 모든 `k` 값에 대해, 해당 윈도우 시퀀스에 포함된 터미널 심볼(예: `ID`, `STR`)로만 구성된 헤더 라인(예: `1 Stmt_token9 ( ID . ID < ...`)을 출력합니다.
*   **내용물(렉심) 출력:** `fprintf(OutputFile, " %u,%u: %s\n", ...)` 구문이 `k`부터 `EndLogIndex`까지의 실제 렉심(토큰 텍스트)과 위치(행,열)를 출력합니다.
*   **루프 인덱스 갱신:** `k` 루프가 모두 끝나면, 바깥쪽 `i` 루프의 인덱스를 `EndLogIndex` 다음의 `Shift` 토큰의 인덱스로 "점프"시킵니다. 이는 이미 분석된 `If`문의 하위 토큰들(예: `(`, `Clock` 등)을 건너뛰고 다음 문법 단위부터 분석을 재개하기 위함입니다.

