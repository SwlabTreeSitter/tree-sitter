# Conversion (커서 시점 state 집합 추출) — 설계 문서

## 1. 개요

컨버전 (Conversion) 은 코드 자동완성을 위한 **구조 후보 lookup 진입 단계** 다.
사용자가 편집기에서 자동완성을 트리거하면, 커서 위치까지의 소스를 받아
*그 시점에 파서가 도달 가능한 모든 LR state 들의 합집합* 을 추출한다.
이 state 집합을 `candidates.json` 에서 조회하여 가장 빈도 높은 구조후보들이
자동완성 후보로 표시된다.

- **컬렉션** = 학습 단계 (LEARN 세트로 `state → 구조후보` DB 빌드)
- **컨버전** = 검색 단계 (커서 시점 state 추출 → DB lookup)

선행 연구가 단일 LR 파서로 *단일 state* 만 추출한 반면, 우리는 모호성을 지닌
언어를 지원하기 위해 **GLR 기반 state 합집합** 추출이 필요했다.

---

## 2. 입출력

**입력** — 두 진입점

| 모드 | 입력 | 의도 |
|---|---|---|
| **mode 0** | 잘린 소스 (커서 위치까지 자른 소스) | 끝 (EOF) 까지 파싱. 가장 단순한 진입 |
| **mode 2** | 전체 소스 + `cursor_byte` | 커서 byte 까지만 파싱하되, *커서 너머* 는 외부 스캐너의 lookahead 로 활용. 잘린 소스의 강제 EOF 회피 |

**중간 상태** — 진행 중인 GLR stack 의 여러 version 들. *그 시점 상태* 자체가 컨버전의 작업물.

**최종 산출물** — `TSStatePath`

```c
typedef struct {
  TSStateId states[MAX_PATH_SIZE];   // state IDs (MAX_PATH_SIZE = 256)
  uint32_t count;                    // state 개수
} TSStatePath;
```

state 의 *합집합* (중복 없음). 호출자가 이 state 들로 `candidates.json` 의 entry 들을 조회.

**관여 컴포넌트**

```
VS Code extension                ← 자동완성 트리거
  └─ TreeSitterCutFile.exe       ← C++ 실행파일 (mode 0 / mode 2)
       └─ ts_parser_parse_string_for_conversion[_with_lookahead]   ← API
            └─ ts_parser_parse_for_conversion                       ← 본진
```

c.f. vs code extension 사용법 : code-completion-extension/README.md

---

## 3. 알고리즘 변화 (기존 → 새 접근)

### 3.1 기존 논문 — 단일 LR + reduce 연쇄 도달 state 집합

[선행 연구](https://dl.acm.org/doi/epdf/10.1145/3605098.3635944) 의 Algorithm 2 는
LR 파서로 사용자 입력을 처음부터 커서 위치까지 파싱하다 **stuck** 된 state 를
발견한 뒤, 그 state + stack 으로 **reduce 만으로 도달 가능한 모든 state** (=
reduce 연쇄로 닿는 state 들의 집합) 를 계산해 *커서 시점에 가능한 state 집합*
을 도출한다.

**왜 reduce 만 따라가는가** — LR 의 reduce 는 *새 토큰을 읽지 않고* stack 만
재구성하는 연산이다. 커서 시점 (= 더 이상 입력 안 읽음) 에서도 reduce 들은
계속 발동될 수 있고, 발동될 때마다 *다른 state* 가 후보로 등장. 모든 가능한
후보를 빠뜨리지 않으려면 *reduce 연쇄로 닿는 state 전체* 가 필요하다.

핵심 메커니즘 (재귀적 reduce 도달):

```pseudocode
function CurrentStates(state, stack):
    PRD ← state 에서의 모든 reduce production 들
    result ← ∅
    for (A ← rhs) ∈ PRD:
        stack 에서 |rhs| 개 pop, GOTO(top, A) = state1
        result ← result ∪ CurrentStates(state1, stack1)
    return {state} ∪ result
```

자세한 알고리즘은 논문 Algorithm 2.


### 3.2 한계 — 모호성 있는 grammar + 트리시터 특수성

Algorithm 2 는 *단일 LR stack* 전제. 두 가지 한계:

**한계 (a) — 모호성 있는 grammar**

- 현실 언어의 문법이 모호함 / LR conflict 있음
- 단일 LR 파서는 *deterministic 결정* 만 가능 → 모호한 자리에서 막힘
- GLR: 모호한 자리에서 *stack 을 분기* — 여러 가능성을 *동시에* 탐색
- 분기된 path 들이 stack version 들로 동시 살아 있음
- 파싱 진행하다 잘못된 path 는 소멸, 맞는 path 만 살아남음 (정상 종료 시)
-  *커서 시점* 에는 *여러 version 이 살아있을 가능성* — 어느 게 맞는지 아직 결정 안 됨

→ 따라서 *살아있는 모든 version 의 state* 가 필요함

**한계 (b) — 커서 경계의 미묘함 (트리시터 GLR 고유)**

- 외부 스캐너의 *커서 너머 read-ahead*
- 0-size epsilon 토큰 (Python `INDENT`/`DEDENT`, Haskell `TIGHT_DOT` 등)
- "끝낸 것" vs "끝내려는 참" 의 모호함 (경계에 닿는 external 토큰)

→ 단순 *stuck 감지* 로는 부족. *언제 freeze 할지* 의 미묘한 결정 필요.

### 3.3 우리의 접근 — GLR + 각 version 의 reduce 연쇄 도달 state 집합

트리시터 (GLR) 의 *여러 stack version* 으로 모호성을 처리한 뒤, 각 version 에
Algorithm 2 의 GLR 적응판을 적용:

1. **GLR 파싱** — 여러 version 이 동시에 진행하다 커서에 도달
   (각 version 의 *그 시점 state 보존* — 보존 메커니즘은 §5)
2. **각 surviving version 에 reduce 연쇄 도달 적용**
3. **모든 version 의 결과 합집합** = TSStatePath

자세한 알고리즘은 §5.

---

## 4. 호출 흐름

```
VS Code extension (자동완성 트리거)
  ↓
TreeSitterCutFile.exe <lang> <lib> <file> <mode>
  ↓
[진입점 — mode 별로 다름]
  - mode 0 (잘린 소스):     ts_parser_parse_string_for_conversion(parser, NULL, src, len)
  - mode 2 (전체 + cursor): ts_parser_parse_string_for_conversion_with_lookahead(parser, NULL, src, full_len, cursor_byte)
  ↓
[본진 — 두 mode 공통]
  ts_parser_parse_for_conversion(...)
       ├─ ts_parser__advance_for_conversion()   (parser.c, 각 version 의 advance + 경계 검사)
       └─ ts_stack_simulate_conversion()         (stack.c, 각 version 의 simulate)
```

→ 결과 `TSStatePath` 를 stdout 또는 호출자 파이프로 반환 → VS Code extension 이 `candidates.json` lookup.

---

## 5. 컨버전 알고리즘

**알고리즘 코드 위치**:
- `ts_parser_parse_for_conversion` (parser.c) — *ParseForConversion* 의 구현
- `ts_stack_simulate_conversion` (stack.c) — *CurrentStatesGLR* 의 구현

```pseudocode
function ParseForConversion(source, cursor):
    parse source using GLR until cursor position is reached    // ①

    final_union ← ∅
    for each surviving stack version v:                          // ②
        final_union ← final_union ∪ CurrentStatesGLR(v)
    return final_union


function CurrentStatesGLR(version, GSS):
    top_node ← GSS.heads[version]
    return DFS(top_node.state, top_node, visited ← ∅)

function DFS(state, node, visited):
    if (state, node) ∈ visited: return ∅
    visited ← visited ∪ {(state, node)}
    result ← {state}

    PRD ← state 에서의 모든 reduce production 들
    for (A ← rhs) ∈ PRD:
        for each path popping |rhs| nodes through GSS links:     // GSS 의 다중 경로
            node_after ← node after popping along this path
            state_after ← GOTO(node_after.state, A)
            result ← result ∪ DFS(state_after, node_after, visited)
    return result
```

기본 알고리즘은 *GLR 파싱 + 각 surviving version 의 reduce 연쇄 도달 + 합집합*.
위 코드의 ①② 두 군데에 트리시터 트리 특성상의 보완 로직이 들어간다.

### 왜 '_for_conversion' 별도 함수들인가 — fork 의 이유

트리시터에는 이미 `ts_parser_parse` / `ts_parser__advance` 함수가 있다. 그러나 이를 그대로 쓰지 않고 컨버전 전용으로 `ts_parser_parse_for_conversion` / `ts_parser__advance_for_conversion` 을 fork 했다.

이유는 *일반 파싱과 컨버전의 목표가 상충* 하기 때문. 일반 파싱은 *입력 전체를 성공적으로 파싱* 해서 트리를 만드는 게 목표라, 커서 위치에서 파싱이 중단될 때 *에러 복구* 가 자동으로 진행되는 경우가 있다. 이 경우 정확한 state를 포착하지 못하는 한계가 있기에 파싱 중단 시점에 에러 복구를 호출하지 않도록 커스텀하여 별도 작성했다.


### 보완이 필요한 이유

GLR stack 은 *여러 version* 을 가지며 각 version 은 *active* (진행 중) 또는 *halted* (멈춤) 상태. `CurrentStatesGLR` 은 살아남은 모든 version (active + halted) 에 호출되어 합집합을 만든다.

위 ①② 자리에 두 가지 보완:

#### 1. (①) 커서 도달 시 active → halted 전환

커서에 도달한 version 은 그 자리에서 멈춰 halted 로 전환 (`freeze`). 단, 일부 모호한 경계 토큰 (Python `_indent` 같은 0-byte external) 에선 *복사본만 halted 로 만들고 원본은 SHIFT 계속* (`halted copy`) — pre-shift / post-shift state 양쪽 모두 자동완성 후보로 보존.


#### 2. (②) halted version 의 즉시 simulate — condense 방어

`condense_stack` 이 매 iteration 후 halted 를 *그대로 제거* (일반 파싱의 정리 로직). 컨버전에선 halted 가 *커서 위치 state* 의 후보 → **condense 전에 simulate 결과를 `final_union` 에 미리 추가** 해야 한다.

#### 3. 0-byte external 토큰 확장

트리시터의 외부 스캐너가 산출하는 *0-byte external 토큰* (Python `INDENT`, Haskell `TIGHT_DOT` 등) 은 byte 를 차지하지 않으면서 state 전이를 일으킨다. 잘린 소스에선 *실제 lex 안 됐지만* 문법상 *그 토큰을 SHIFT 한 자리* 도 자동완성 후보가 될 수 있다.

따라서 `CurrentStatesGLR` 은 *DFS (reduce 연쇄) 외에 가상 SHIFT 체인* 으로 도달 가능한 state 들도 추가로 합집합에 포함한다.

---

①② 위치별 보완의 세부 메커니즘은 `advance_for_conversion` / `parse_for_conversion`
의 인라인 주석에서 다룬다.

---

## 부록 A — advance_for_conversion 의 경계 검사

`ts_parser__advance_for_conversion` 의 *3 단계 커서 경계 검사* 결정 트리와 12 케이스 표.

### 결정 트리 (Lex 경로)

```
                       ┌─────────────────────────┐
                       │    Lex 결과 도착        │
                       └───────────┬─────────────┘
                                   │
                      ┌────────────┴────────────┐
                      │                         │
               pos >= target               pos < target
                (커서 도달)                (커서 미도달)
                      │                         │
         ┌────────────┼────────────┐            │
         ▼            ▼            ▼            │
     ① NULL       ② EOF/err   ③④ 0-size        │
       freeze      freeze     invalid→freeze    │
                              valid→halt+SHIFT  │
                                                │
                      ┌─────────────────────────┘
                      │
      ┌───────────────┼──────────────┬──────────────┐
      ▼               ▼              ▼              ▼
   ① EOF/err    ② NULL+lexer     ③' 0-size      ④' size>0
    freeze       도달            +lexer 도달     + 경계 비교
                 freeze          invalid→freeze  token_end > target
                                 valid→halt+     → freeze
                                   fall-through  token_end == target
                                                 (ext) → halt+
                                                   fall-through
                                                 token_end < target
                                                 → 정상 진행
```

### 12 케이스 표

`position` vs `target_length` × 토큰 종류로 결정:

| 위치 | 토큰 | 결정 |
|---|---|---|
| pos >= target | NULL | freeze |
| pos >= target | sym:end / error | freeze |
| pos >= target | 0-size, action 없음 | freeze |
| pos >= target | 0-size, action 있음 | halted copy + SHIFT |
| pos < target | end / (error + lex past) | freeze |
| pos < target | NULL + lex past target | freeze |
| pos < target | 0-size + lex at target, action 없음 | freeze |
| pos < target | 0-size + lex at target, action 있음 | halted copy + SHIFT |
| pos < target | size>0, token_end > target | freeze |
| pos < target | size>0, token_end == target (external) | halted copy + SHIFT |
| pos < target | size>0, token_end < target | 정상 진행 |
| cache-hit, size>0 | (boundary 검사 별도, 4 케이스) | (lex 분기와 동일 패턴) |

