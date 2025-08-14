parse action 을 저장하는 컨테이너 
```
typedef Array(TSParseAction) TSParseActionArray;
```

<br>

후보 심볼들을 찾기 위해 parse action 과 다음 상태 등을 저장하는 컨테이너
```
typedef struct {
  TSParseActionType type;   // Shift / Reduce / Accept

  // Shift: 해당 액션에서 소비한 토큰 심볼
  // Reduce: 축약된 비단말 심볼
  TSSymbol symbol;          
  uint32_t child_count;     // reduce 액션에 축약되는 심볼 갯수
  TSStateId next_state;     // 다음에 갈 상태를 가리킨다
  bool extra;               // Parse Action 규칙 참조
  bool repetition;          // Parse Action 규칙 참조
} TSLoggedAction;

typedef Array(TSLoggedAction) TSLoggedActionArray;
```

<br>

파서의 동작은 **ts_parser__advance** 함수로 switch 문에서 위 컨테이너들에 정보를 저장한다.
- shift
- reduce
- accept

<br>

goto balance: 라벨을 따라가면 parse action log 를 .txt 파일에 저장하는 로직과 후보 심볼을 찾는 로직이 있다.
- parse action log : 2325 line
- 후보 심볼 탐색 : 2393 line