

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

# Tree-sitter 시스템 아키텍처 및 동작 메커니즘

### 1. 개요
Tree-sitter는 소스 코드의 구문 분석(Parsing)을 위한 고성능 라이브러리로, **범용 코어 엔진(Core Engine)** 과 **개별 언어 모듈(Language Module)** 이 철저히 분리된 구조를 가진다. 이를 통해 단일 엔진으로 다수의 프로그래밍 언어(C, Python, Small Basic 등)를 처리하는 확장성을 확보하고 있다.

<br>

### 2. 시스템 아키텍처
경로 예시
```
C:\Work\
  tree-sitter\
  tree-sitter-python\
  tree-sitter-cpp\
  tree-sitter-smallbasic\
```

#### 2-1. 코어 엔진
- 위치: ```tree-sitter/lib/src``` (parser.c, lexer.c, stack.c 등)
- 역할: 실제 파싱 알고리즘을 수행하는 실행 장치
- 특징: 특정 언어에 종속되지 않은 순수 C 언어 로직으로 구현되어 있다.
- 핵심 파일:
  - lib.c: 엔진의 모든 소스 파일(parser.c, lexer.c 등)을 하나로 묶어 빌드하는 파일
  - parser.c: 파싱의 상태 전이와 스택 관리, 에러 복구를 담당 (+ 상태 정보 추출 로직 커스텀)
- 사용 방법:
  ```
  cd C:\Work\tree-sitter
  cargo build
  ```
  - target\debug\tree-sitter.exe 가 생성
  - 후에 ..\tree-sitter\target\debug\tree-sitter 형태로 사용된다.


#### 2-2. 언어 모듈
- 위치: ```tree-sitter-<language>/src``` (parser.c)
- 역할: 특정 언어(예: Small Basic)의 문법 규칙을 담고 있는 데이터베이스
- 생성 과정: grammar.js로 정의된 문법을, tree-sitter generate 명령어가 이를 분석하여 C 언어 형태의 거대 배열(State Table, Symbol Table)로 변환한다. [3-1. 생성](3-1.-생성)
- 인터페이스: 생성된 C 코드의 마지막에는 반드시 tree_sitter_\<language\>() 함수가 존재하며, 이는 엔진에게 문법 데이터(TSLanguage 구조체)의 메모리 주소를 전달하는 역할을 한다.

<br>

### 3. 언어 모듈별 동작 프로세스
``` cd tree-sitter-<language> ```
이 위치에서 생성(Generation) → 빌드(Build) → 런타임(Runtime)

#### 3-1. 생성
``` ..\tree-sitter\target\debug\tree-sitter generate --debug-build ```
- ..\tree-sitter\target\debug\tree-sitter(tree-sitter.exe)에 generate 인자
- 내부 로직
  - Input: grammar.js (문법 정의서, 현재 경로 tree-sitter-\<language\>에서 읽어옴)
  - Process: 문법을 분석하여 상태 기계를 계산한다.
  - Output: tree-sitter-\<language\>/src/parser.c (C 코드로 변환된 파싱 테이블 데이터(static const int table[]))

#### 3-2. 빌드
``` ..\tree-sitter\target\debug\tree-sitter build --debug ```
- ..\tree-sitter\target\debug\tree-sitter(tree-sitter.exe)에 build 인자
- 내부 로직
  - cl.exe가 tree-sitter-\<language\>/src/parser.c를 가지고 smallbasic.dll 생성
    (코어 엔진이 런타임에 동적으로 로드하여 사용하는 언어별 문법 데이터베이스)

#### 3-3. 런타임(파싱)
``` ..\tree-sitter\target\debug\tree-sitter parse --debug pretty .\examples\smallbasic\01_HelloWorld.sb ```
- ..\tree-sitter\target\debug\tree-sitter(tree-sitter.exe)에 parse 인자
- 내부 로직
  - 초기화: ts_parser_new()로 엔진 인스턴스를 생성
  - 언어 장착: ts_parser_set_language(parser, language)를 호출하여, 엔진에게 "지금부터 참조할 문법 테이블은 이것이다"라고 포인터를 전달
  - 파싱 수행

<br><br>

# 커스텀 파싱 엔진 검증을 위한 C++ 프로그램 (TreeSitterCutFile)

### 1. 개요
Tree-sitter 코어 엔진을 수정하여 중단점 기반 상태 추출 기능을 구현하였다. tree-sitter에서 제공하는 명령어로는 파일의 특정 행과 열까지만 읽기는 불가능하기 때문에 중단점(특정 행과 열)을 인자로 받을 수 있는 C++ 프로그램 TreeSitterCutFile을 제작하였다. TreeSitterCutFile은 CLI(Command Line Interface) 기반으로 커스텀 API가 의도대로 동작하는지 확인한다.


### 2. 프로그램 아키텍처 및 동작 흐름

#### 2-1. 동적/정적 언어 로딩
- Small Basic: parser.c를 실행 파일에 정적 링크(Static Link)하여 직접 호출한다.
- Others: C, Python 등의 언어들은 .dll 파일을 런타임에 동적 로드(Dynamic Load)한다.

#### 2-2. 좌표 매핑
- 인자로 (Row, Column) 좌표를 받지만, 파싱 엔진은 선형적인 Byte Offset을 사용한다.
- FindByteOffsetForPosition 함수를 통해 좌표 변환을 수행한다.
- 파서가 정확히 사용자의 커서 위치에서 멈출 수 있도록 effective_length를 계산하여 전달한다.

#### 2-3. 커스텀 엔진 제어
코어 엔진(api.h, parser.c)에 추가한 제어 함수들을 호출하여 파싱 모드를 설정한다.
- ts_parser_set_stop_position(parser, {row, col}): 파싱 중단 목표 지점을 주입한다.
- ts_parser_set_find_state_mode(parser, flag):
  - Mode 0 (State Extraction): 자동완성을 위한 현재 문맥의 State ID 추출.
  - Mode 1 (Data Collection): 문법 패턴 분석을 위한 파싱 액션 로그 수집.

#### 2-4. 파싱 실행
- ts_parser_parse_string -> ts_parser_parse_string_encoding -> **ts_parser_parse** (파싱루프)
- 실행 단계
  - ts_parser__advance() 내부에서 logged_actions 배열에 현재 어떤 행동을 했는지 실시간으로 기록
  - ts_parser__lex() 등에서 StopRow, StopColumn을 체크하여, 목표 지점에 도달하면 파싱을 멈춤

- 후처리 분석
  - Mode 1 (Collection): logged_actions 배열을 처음부터 끝까지 다시 훑어 문장 완성 패턴을 찾아서 Test.data 파일에 쓴다.
  - Mode 0 (State ID Extraction): TsParserFindClosestRecoverState를 호출하여, 파싱이 멈춘 지점(커서)에서 가장 가까운 에러 복구 상태(State ID)를 찾는다.



<br><br>



## swlab Links
- [진행상황 기록 노션](https://www.notion.so/tree-sitter-2238687479db805f9f88debfffb48a45)
- [vscode UI 추가](https://github.com/kimkyungjae1112/CodeCompletion) 

## 사용 방법

### 0. 폴더 구조 가정
```
C:\Work\
  tree-sitter\
  tree-sitter-python\
  tree-sitter-cpp\
  tree-sitter-smallbasic\
```
아래 명령어들은 이 구조를 기준으로 씁니다.
경로만 본인 환경에 맞게 바꾸면 됩니다.

### 1. tree-sitter 자체 빌드
```
cd C:\Work\tree-sitter
cargo build
```
- target\debug\tree-sitter.exe 가 생깁니다.
- 뒤에서 ..\tree-sitter\target\debug\tree-sitter 형태로 사용됩니다.


### 2. 언어별 파서 생성/빌드/테스트
예시 : Small Basic (tree-sitter-smallbasic)

```
cd C:\Work\tree-sitter-smallbasic

Generate: 문법 → C 코드(parser.c 등) 생성
..\tree-sitter\target\debug\tree-sitter generate --debug-build

Build: 생성된 C 코드로 파서 DLL 빌드
..\tree-sitter\target\debug\tree-sitter build --debug

Parse: 실제 파일을 파싱해서 상태 확인
..\tree-sitter\target\debug\tree-sitter parse --debug pretty .\examples\smallbasic\01_HelloWorld.sb

```
- 01_HelloWorld.sb 는 tree-sitter-smallbasic\examples\smallbasic 폴더 안에 있는 예제 파일
- 이때 파싱 상태를 기록한 텍스트 파일이 생기도록 코드가 짜여있음


### 3. C++ 인터페이스 프로그램(TreeSitterCutFile) 빌드
tree-sitter 코어 + parser.c + TreeSitterCutFile.cpp를 하나로 묶어서
TreeSitterCutFile.exe 를 만드는 단계

#### 3-1. Visual Studio 빌드 환경 열기 (powershell 또는 cmd)
```
C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build 경로에 있는
vcvars64.bat 파일을 터미널에 드래그 앤 드랍
```
이걸 실행하면 cl 컴파일러를 쓸 수 있는 환경이 세팅됩니다.


#### 3-2. TreeSitterCutFile 빌드
```
cd C:\Work\tree-sitter 
cl TreeSitterCutFile.cpp parser.c /MD /EHsc /std:c++17 /I./include /link /LIBPATH:./target/debug treesitter.lib /OUT:TreeSitterCutFile.exe  
```
**parser.c**를 수정했다면
- cargo build 다시 하고
- 위 cl ... 명령도 다시 해서 TreeSitterCutFile.exe 를 재빌드해야 합니다.
- 정적 라이브러리 + parser.c 를 같이 링크 하기 때문


### 4. TreeSitterCutFile 실행 예시
#### 4-1. 경로 및 형식
```
cd C:\Work\tree-sitter
.\TreeSitterCutFile.exe [언어 이름] [라이브러리 경로 or 생략] [파싱할 파일 경로] [행] [열] [모드]
```
- 마지막 인자:
  - 0 → 컨버전 모드(parse state id 반환)
  - 1 → 컬렉션 모드(상태 데이터 수집)

#### 4-2. 언어별 실행 예시
```
// smallbasic 은 다른 언어와 다르게 사용
// smallbasic 은 dll 파일이 없어 라이브러리 경로를 입력해주지 않아도 된다. 
.\TreeSitterCutFile.exe smallbasic C:\Work\tree-sitter-smallbasic\SB_Sample\02_FontYellowColorRecover2.sb 2 1 0

.\TreeSitterCutFile.exe cpp C:\Work\tree-sitter-cpp\cpp.dll C:\Work\tree-sitter-cpp\main.cpp 3 2 0

.\TreeSitterCutFile.exe python C:\Work\tree-sitter-python\python.dll C:\Work\tree-sitter-python\Test.py 3 2 0
```



## 수정 파일
**tree-sitter/lib/src/parser.c**

- TSLoggedActionArray logged_actions : 파싱 액션을 기록하기 위한 동적 배열
- uint32_t StopRow, StopColumn : 파싱을 중단할 목표 위치 (현재 커서 위치를 받음)

- ts_parser__advance()
    - Shift, Reduce, Accept 액션이 발생할 때 액션의 정보를 logged_actions에 저장
- ts_parser_handle_error()
    - tree-sitter의 오류 복구가 시작될 때, 해당 위치와 상태 ID를 포함한 Recover 액션 로그를 logged_actions에 저장
- TsParserFindClosestRecoverState() - 커스텀
    - 행, 열을 받아 가장 가까운 Recover Action을 찾아 해당 상태 ID를 반환하는 메서드
- ts_parser_set_stop_position() - 커스텀
    - 파싱을 중단할 목표 위치(행, 열) 설정하는 메서드
- ts_parser_parse() - balance: 라벨 이후
    - 파싱 상태 출력 및 parse state id 반환 

**tree-sitter/lib/include/tree_sitter/api.h**

- ts_parser_set_stop_position() - 커스텀
    - 외부에서 호출 가능하게 열어둠


**tree-sitter/crates/generate/src/build_tables.rs**

- build_tables(...) 메서드의 131라인 -> 생산규칙 출력

## 코드 로직

**컬렉션 단계의 동작 원리**

컬렉션의 주요 로직은 3단계로 진행된다.
*   ts_parser_parse() - balance: 라벨 이후, 2536라인 (최종 목표) 읽으면 됩니다.

**1단계: Shift 인덱싱**

*   전체 `logged_actions` 배열을 빠르게 순회하여 "엑스트라"가 아닌 모든 `SHIFT` 액션(실제 토큰)의 인덱스만 `ShiftIndices` 배열에 저장한다.
*   이 배열은 분석을 시작할 "시작점(커서)" 목록이 된다.
*   이것의 의미는 현재 커서의 위치를 나타낸다.
*   코드
<img width="2372" height="418" alt="image" src="https://github.com/user-attachments/assets/7de74779-f3bb-4b72-9fbf-135fd75e55b2" />

<br><br>

**2단계: "완전한 문법 단위" 경계 탐색**

*   `for (uint32_t i = 0...)` 루프는 `ShiftIndices` 배열을 순회하며 각 `SHIFT` 토큰을 문법 단위의 시작점(`CursorLogIndex`)으로 설정한다.
*   **가상 스택 시뮬레이션 (`SimStack`):** `for (uint32_t j = CursorLogIndex...)` 루프는 `CursorLogIndex`부터 파싱을 시뮬레이션한다.
    *   **`SHIFT` 처리:** `SHIFT`를 만나면 `SimStack`에 푸시(push)한다.
    *   SHIFT 처리 부분 코드
    *   <img width="1746" height="374" alt="image" src="https://github.com/user-attachments/assets/2ef6566c-be5e-473f-bfdf-42b3426f348f" />
    
    *   **`REDUCE` 처리:** `REDUCE` 액션을 만나면 스택에서 항목들을 팝(pop)해야 한다.
    *   REDUCE 처리 부분 코드
    *   <img width="1694" height="790" alt="image" src="https://github.com/user-attachments/assets/5a653213-4b1b-4b3c-a013-f88bad680067" />
    *   <img width="1700" height="778" alt="image" src="https://github.com/user-attachments/assets/f8d68145-436a-40ef-b478-d5b66aac6ba7" />


    *   **문법 단위 끝 찾기 (`ConsumesCursor`):** `REDUCE`가 스택에서 제거할 항목 중에 문법 단위의 시작점(`CursorLogIndex`)이 포함되는지 검사한다.
        *   **`if (ConsumesCursor)` (문법 단위 끝 발견):**
            *   `REDUCE`가 시작 토큰을 포함한다는 것은, `If`로 시작해서 `EndIf`로 끝나는 완전한 문법 단위를 찾았다는 의미이다.
            *   이 문법 단위의 마지막 토큰 위치(`EndLogIndex`)와 `Reduce` 액션의 위치(`finalReduceLogIndex`)를 저장하고 시뮬레이션을 중단(`break`)한다. 이 `break`는 경계 탐색 임무가 완료되었으므로 "3단계: 출력"으로 넘어가기 위해 의도된 동작이다.
        *   **`else` (중간 단계 `Reduce`):**
            *   `Clock.Hour`가 `Primary`로 축약되는 것처럼, 문법 단위 내부의 작은 `Reduce`이다.
            *   스택에서 `ID`, `.`, `ID`를 팝(pop)하고, 그 결과물인 `Primary`(논터미널)를 `IsTerminal = false`로 설정하여 스택에 다시 푸시(push)하고 시뮬레이션을 계속한다.

**3단계: 결과 출력**

*   "완전한 문법 단위"의 범위(시작 `i`부터 끝 `EndLogIndex`까지)가 확정되면, 이 범위 내의 모든 부분 시퀀스를 출력한다.
*   **모든 부분 시퀀스를 출력:** `for (uint32_t k = i...)` 루프는 `k` 값을 `i`부터 1씩 증가시키며 윈도우의 시작점을 한 칸씩 뒤로 민다.
*   **`StartState` 계산:** 각 윈도우(`k`)가 시작하기 직전의 파서 상태 ID를 `logged_actions`를 역방향으로 탐색하여 찾아냅니다. (예: `( Clock ...` 시퀀스의 `StartState`는 `(` 토큰의 `next_state` 값이다.)
*   **'상위 심볼' 헤더 출력:** `if (k == i && ...)` 블록은 전체 문법 단위(`k=i`일 때)에 대해서만 파싱 시뮬레이션을 한 번 더 수행한다(`headerStack`). 이 시뮬레이션은 중간 `Reduce`의 결과(논터미널, 예: `Expr`)를 스택에 반영하여 `1 Stmt_token9 Expr Stmt_token10 ...` 같은 라인을 출력한다.
*   **'터미널 심볼' 헤더 출력:** 모든 `k` 값에 대해, 해당 윈도우 시퀀스에 포함된 터미널 심볼(예: `ID`, `STR`)로만 구성된 헤더 라인(예: `1 Stmt_token9 ( ID . ID < ...`)을 출력한다.
*   **내용물(렉심) 출력:** `fprintf(OutputFile, " %u,%u: %s\n", ...)` 구문이 `k`부터 `EndLogIndex`까지의 실제 렉심(토큰 텍스트)과 위치(행,열)를 출력한다.
*   **루프 인덱스 갱신:** `k` 루프가 모두 끝나면, 바깥쪽 `i` 루프의 인덱스를 `EndLogIndex` 다음의 `Shift` 토큰의 인덱스로 "점프"시킨다. 이는 이미 분석된 `If`문의 하위 토큰들(예: `(`, `Clock` 등)을 건너뛰고 다음 문법 단위부터 분석을 재개하기 위함이다.



**컨버젼의 동작 원리**




<br>

# To-Do list
1. 컬렉션과 컨버젼을 명확하게 구분하도록 코드를 리펙토링 (옵션 추가) [done]
2. 터미널과 논터미널 심볼들의 이름이 번호로 되어있는 것을 사람이 이해하는 문자열로 변경하기
3. parse state, parse table, lexical grammar, syntax grammar 사람이 보기 편하게 출력하기 (우선순위 낮을 수 있음)
   - 현재 parse table을 출력하면 lookahead가 숫자로 되어있을 텐데, 심볼 또는 정규식으로 변환해서 출력
   - lexical grammar, syntax grammar 에 나타나는 terminal, nonterminal 도 심볼 또는 정규식으로 대체해서 출력
   - c11parser/action_table.txt, goto_table.txt, prod_rules.txt 와 같이 코드 컴플리션 도구의 디버깅용으로 파일 저장
4. industry에서 관심있어하는 code completion 방법과 결합
   - 코드 컴플리션 경연 대회 [https://jetbrains-research.github.io/ase2025-context-collection-workshop/]
   - Challenge on Optimization of Context Collection for Code Completion [https://arxiv.org/pdf/2510.04349]

<br>

## 2번 To-Do list
Stmt: $ => choice(
        $.ExprStatement,
        seq(/[Ww][Hh][Ii][Ll][Ee]/, $.Expr, repeat($.CRStmtCRs), /[Ee][Nn][Dd][Ww][Hh][Ii][Ll][Ee]/),
        seq($.ID, ":"),
        seq(/[Gg][Oo][Tt][Oo]/, $.ID),
        seq(/[Ff][Oo][Rr]/, $.ID, "=", $.Expr, /[Tt][Oo]/, $.Expr, optional($.OptStep), repeat($.CRStmtCRs), /[Ee][Nn][Dd][Ff][Oo][Rr]/),
        seq(/[Ss][Uu][Bb]/, $.ID, $.CRStmtCRs, /[Ee][Nn][Dd][Ss][Uu][Bb]/),
        seq(/[Ii][Ff]/, $.Expr, /[Tt][Hh][Ee][Nn]/, repeat($.CRStmtCRs), $.MoreThanZeroElseIf)
      ),

1. Grammar에 있는 Terminal, Non-Terminal 이름들을 유지시켜줘야 한다.
    1.1 이름을 알아야 gpt 에게 코드 생성을 요청할 수 있기 때문에..
2. non-terminal -> 스트링 매핑 찾기
    2.1 tree-sitter 에서 non-terminal 을 숫자로 바꿈(최적화), 그래서 숫자로 바꾸기 전에 이름을 저장할 필요가 있다.
    2.2 숫자 이름 mapping 되어 있는 것을 저장한다. 
3. terminal -> 우리가 직접 따로 뽑아서 매뉴얼하게 이름을 붙인다거나, gpt 에게 일 시키기.
    3.1 정규식이라서 이름이 없다.

// 정규식에 해당하는 토큰인데 어떤 정규식인지 알고싶다.
// 이게 러스트 코드에선 어떻게 컨버전 했는지, 숫자로 변환했는지 알고싶다.
build_tables.rs, grammar.js, parser.c 파일들을 분석을 하면 최종 코드가 아마도 효율성을 위해서 터미널 심볼, 논터미널 심볼들이 숫자로 변경된것으로 파악된다.
하지만 나는 grammar.js 에 있는 사람이 읽을 수 있는 심볼로 이해를 하고 싶다.
또는 사람이 이해할 수 있는 논터미널 심볼로 이해하고 싶다.
터미널 같은 경우는 터미널 심볼을 grammar.js로 직접 작성한 경우라면 그 심볼 이름으로도 알고 싶고, 논터미널의 경우 사람이 심볼 이름을 안 정할수 있는데, 그럼 정규식으로 쓸거임
논터미널의 숫자와 이름의 관계를 알고싶다.
러스트 코드에선 어디에 저장이 되어 있을까?
그 정보를 저장하려면 러스트 코드를 어떤 방식으로 작성하고 끼워넣어야할까?
