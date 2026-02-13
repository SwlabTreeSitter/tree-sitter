#ifndef TREE_SITTER_PARSER_H_
#define TREE_SITTER_PARSER_H_

#ifdef __cplusplus
extern "C" {
#endif

#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>

#include "tree_sitter/api.h"  // TSPoint

#define ts_builtin_sym_error ((TSSymbol)-1)
#define ts_builtin_sym_end 0
#define TREE_SITTER_SERIALIZATION_BUFFER_SIZE 1024

#ifndef TREE_SITTER_API_H_
typedef uint16_t TSStateId;
typedef uint16_t TSSymbol;
typedef uint16_t TSFieldId;
typedef struct TSLanguage TSLanguage;
typedef struct TSLanguageMetadata {
  uint8_t major_version;
  uint8_t minor_version;
  uint8_t patch_version;
} TSLanguageMetadata;
#endif

typedef struct {
  TSFieldId field_id;
  uint8_t child_index;
  bool inherited;
} TSFieldMapEntry;

// Used to index the field and supertype maps.
typedef struct {
  uint16_t index;
  uint16_t length;
} TSMapSlice;

typedef struct {
  bool visible;
  bool named;
  bool supertype;
} TSSymbolMetadata;

typedef struct TSLexer TSLexer;

struct TSLexer {
  int32_t lookahead;
  TSSymbol result_symbol;
  void (*advance)(TSLexer *, bool);
  void (*mark_end)(TSLexer *);
  uint32_t (*get_column)(TSLexer *);
  bool (*is_at_included_range_start)(const TSLexer *);
  bool (*eof)(const TSLexer *);
  void (*log)(const TSLexer *, const char *, ...);
};

typedef enum {
  TSParseActionTypeShift,
  TSParseActionTypeReduce,
  TSParseActionTypeAccept,
  TSParseActionTypeRecover,
} TSParseActionType;

typedef union {
  struct {
    uint8_t type;
    TSStateId state;
    bool extra;
    bool repetition;
  } shift;
  struct {
    uint8_t type;
    uint8_t child_count;
    TSSymbol symbol;
    int16_t dynamic_precedence;
    uint16_t production_id;
  } reduce;
  uint8_t type;
} TSParseAction;

// 파싱 중 발생한 하나의 액션을 기록
typedef struct {
  TSParseActionType type;   // 액션의 종류 (SHIFT, REDUCE, ACCEPT, RECOVER)
  TSStateId current_state;  // 해당 액션을 수행하기 직전의 파서 상태 ID
  TSStateId next_state;     // 액션 수행 후 이동한 파서 상태 ID
  TSSymbol symbol;          // Shift인 경우 : 읽어들인 토큰의 심볼 번호
                            // Reduce인 경우 : 축약되는 심볼 (규칙의 LHS) 번호

  char *lexeme;             // (Shift 전용) 소스 코드에 적혀 있던 실제 문자열
  uint32_t child_count;     // (Reduce 전용) 축약될 때 스택에서 몇 개를 꺼냈는지
  bool is_virtual;          // (V-Shift 전용) Recover로 인한 가짜 토큰 여부 플래그

  bool extra;               
  TSPoint start_point;
} TSLoggedAction;

// typedef struct {
//   TSParseActionType type;
//   TSStateId current_state;
//   TSStateId next_state;
//   TSSymbol symbol;
//   uint32_t child_count;
//   bool is_virtual;
//   bool extra;
//   uint32_t start_byte;
// } TSCleanLog;

typedef struct {
  uint16_t lex_state;
  uint16_t external_lex_state;
} TSLexMode;

typedef struct {
  uint16_t lex_state;
  uint16_t external_lex_state;
  uint16_t reserved_word_set_id;
} TSLexerMode;

typedef union {
  TSParseAction action;
  struct {
    uint8_t count;
    bool reusable;
  } entry;
} TSParseActionEntry;

typedef struct {
  int32_t start;
  int32_t end;
} TSCharacterRange;

struct TSLanguage {
  uint32_t abi_version;
  uint32_t symbol_count;
  uint32_t alias_count;
  uint32_t token_count;
  uint32_t external_token_count;
  uint32_t state_count;
  uint32_t large_state_count;
  uint32_t production_id_count;
  uint32_t field_count;
  uint16_t max_alias_sequence_length;
  const uint16_t *parse_table;
  const uint16_t *small_parse_table;
  const uint32_t *small_parse_table_map;
  const TSParseActionEntry *parse_actions;
  const char * const *symbol_names;
  const char * const *field_names;
  const TSMapSlice *field_map_slices;
  const TSFieldMapEntry *field_map_entries;
  const TSSymbolMetadata *symbol_metadata;
  const TSSymbol *public_symbol_map;
  const uint16_t *alias_map;
  const TSSymbol *alias_sequences;
  const TSLexerMode *lex_modes;
  bool (*lex_fn)(TSLexer *, TSStateId);
  bool (*keyword_lex_fn)(TSLexer *, TSStateId);
  TSSymbol keyword_capture_token;
  struct {
    const bool *states;
    const TSSymbol *symbol_map;
    void *(*create)(void);
    void (*destroy)(void *);
    bool (*scan)(void *, TSLexer *, const bool *symbol_whitelist);
    unsigned (*serialize)(void *, char *);
    void (*deserialize)(void *, const char *, unsigned);
  } external_scanner;
  const TSStateId *primary_state_ids;
  const char *name;
  const TSSymbol *reserved_words;
  uint16_t max_reserved_word_set_size;
  uint32_t supertype_count;
  const TSSymbol *supertype_symbols;
  const TSMapSlice *supertype_map_slices;
  const TSSymbol *supertype_map_entries;
  TSLanguageMetadata metadata;
};

static inline bool set_contains(const TSCharacterRange *ranges, uint32_t len, int32_t lookahead) {
  uint32_t index = 0;
  uint32_t size = len - index;
  while (size > 1) {
    uint32_t half_size = size / 2;
    uint32_t mid_index = index + half_size;
    const TSCharacterRange *range = &ranges[mid_index];
    if (lookahead >= range->start && lookahead <= range->end) {
      return true;
    } else if (lookahead > range->end) {
      index = mid_index;
    }
    size -= half_size;
  }
  const TSCharacterRange *range = &ranges[index];
  return (lookahead >= range->start && lookahead <= range->end);
}

/*
 *  Lexer Macros
 */

#ifdef _MSC_VER
#define UNUSED __pragma(warning(suppress : 4101))
#else
#define UNUSED __attribute__((unused))
#endif

#define START_LEXER()           \
  bool result = false;          \
  bool skip = false;            \
  UNUSED                        \
  bool eof = false;             \
  int32_t lookahead;            \
  goto start;                   \
  next_state:                   \
  lexer->advance(lexer, skip);  \
  start:                        \
  skip = false;                 \
  lookahead = lexer->lookahead;

#define ADVANCE(state_value) \
  {                          \
    state = state_value;     \
    goto next_state;         \
  }

#define ADVANCE_MAP(...)                                              \
  {                                                                   \
    static const uint16_t map[] = { __VA_ARGS__ };                    \
    for (uint32_t i = 0; i < sizeof(map) / sizeof(map[0]); i += 2) {  \
      if (map[i] == lookahead) {                                      \
        state = map[i + 1];                                           \
        goto next_state;                                              \
      }                                                               \
    }                                                                 \
  }

#define SKIP(state_value) \
  {                       \
    skip = true;          \
    state = state_value;  \
    goto next_state;      \
  }

#define ACCEPT_TOKEN(symbol_value)     \
  result = true;                       \
  lexer->result_symbol = symbol_value; \
  lexer->mark_end(lexer);

#define END_STATE() return result;

/*
 *  Parse Table Macros
 */

#define SMALL_STATE(id) ((id) - LARGE_STATE_COUNT)

#define STATE(id) id

#define ACTIONS(id) id

#define SHIFT(state_value)            \
  {{                                  \
    .shift = {                        \
      .type = TSParseActionTypeShift, \
      .state = (state_value)          \
    }                                 \
  }}

#define SHIFT_REPEAT(state_value)     \
  {{                                  \
    .shift = {                        \
      .type = TSParseActionTypeShift, \
      .state = (state_value),         \
      .repetition = true              \
    }                                 \
  }}

#define SHIFT_EXTRA()                 \
  {{                                  \
    .shift = {                        \
      .type = TSParseActionTypeShift, \
      .extra = true                   \
    }                                 \
  }}

#define REDUCE(symbol_name, children, precedence, prod_id) \
  {{                                                       \
    .reduce = {                                            \
      .type = TSParseActionTypeReduce,                     \
      .symbol = symbol_name,                               \
      .child_count = children,                             \
      .dynamic_precedence = precedence,                    \
      .production_id = prod_id                             \
    },                                                     \
  }}

#define RECOVER()                    \
  {{                                 \
    .type = TSParseActionTypeRecover \
  }}

#define ACCEPT_INPUT()              \
  {{                                \
    .type = TSParseActionTypeAccept \
  }}

#ifdef __cplusplus
}
#endif

#endif  // TREE_SITTER_PARSER_H_
