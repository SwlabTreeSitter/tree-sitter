#include <time.h>
#include <stdio.h>
#include <limits.h>
#include <stdbool.h>
#include <inttypes.h>
#include "tree_sitter/api.h"
#include "./alloc.h"
#include "./array.h"
#include "./atomic.h"
#include "./clock.h"
#include "./error_costs.h"
#include "./get_changed_ranges.h"
#include "./language.h"
#include "./length.h"
#include "./lexer.h"
#include "./reduce_action.h"
#include "./reusable_node.h"
#include "./stack.h"
#include "./subtree.h"
#include "./tree.h"
#include "./ts_assert.h"
#include "./wasm_store.h"

#define array_copy(src, dest) do { \
    array_init(dest); \
    if ((src).size > 0) { \
        array_reserve((dest), (src).size); \
        memcpy((dest)->contents, (src).contents, (src).size * sizeof(*(src).contents)); \
        (dest)->size = (src).size; \
    } \
} while (0)

#define LOG(...)                                                                            \
  if (self->lexer.logger.log || self->dot_graph_file) {                                     \
    snprintf(self->lexer.debug_buffer, TREE_SITTER_SERIALIZATION_BUFFER_SIZE, __VA_ARGS__); \
    ts_parser__log(self);                                                                   \
  }

#define LOG_LOOKAHEAD(symbol_name, size)                      \
  if (self->lexer.logger.log || self->dot_graph_file) {       \
    char *buf = self->lexer.debug_buffer;                     \
    const char *symbol = symbol_name;                         \
    int off = snprintf(                                       \
      buf,                                                    \
      TREE_SITTER_SERIALIZATION_BUFFER_SIZE,                  \
      "lexed_lookahead sym:"                                  \
    );                                                        \
    for (                                                     \
      int i = 0;                                              \
      symbol[i] != '\0'                                       \
      && off < TREE_SITTER_SERIALIZATION_BUFFER_SIZE;         \
      i++                                                     \
    ) {                                                       \
      switch (symbol[i]) {                                    \
      case '\t': buf[off++] = '\\'; buf[off++] = 't'; break;  \
      case '\n': buf[off++] = '\\'; buf[off++] = 'n'; break;  \
      case '\v': buf[off++] = '\\'; buf[off++] = 'v'; break;  \
      case '\f': buf[off++] = '\\'; buf[off++] = 'f'; break;  \
      case '\r': buf[off++] = '\\'; buf[off++] = 'r'; break;  \
      case '\\': buf[off++] = '\\'; buf[off++] = '\\'; break; \
      default:   buf[off++] = symbol[i]; break;               \
      }                                                       \
    }                                                         \
    snprintf(                                                 \
      buf + off,                                              \
      TREE_SITTER_SERIALIZATION_BUFFER_SIZE - off,            \
      ", size:%u",                                            \
      size                                                    \
    );                                                        \
    ts_parser__log(self);                                     \
  }

#define LOG_STACK()                                                              \
  if (self->dot_graph_file) {                                                    \
    ts_stack_print_dot_graph(self->stack, self->language, self->dot_graph_file); \
    fputs("\n\n", self->dot_graph_file);                                         \
  }

#define LOG_TREE(tree)                                                      \
  if (self->dot_graph_file) {                                               \
    ts_subtree_print_dot_graph(tree, self->language, self->dot_graph_file); \
    fputs("\n", self->dot_graph_file);                                      \
  }

#define SYM_NAME(symbol) ts_language_symbol_name(self->language, symbol)

#define TREE_NAME(tree) SYM_NAME(ts_subtree_symbol(tree))

static const unsigned MAX_VERSION_COUNT = 6;
static const unsigned MAX_VERSION_COUNT_OVERFLOW = 4;
static const unsigned MAX_SUMMARY_DEPTH = 16;
static const unsigned MAX_COST_DIFFERENCE = 18 * ERROR_COST_PER_SKIPPED_TREE;
static const unsigned OP_COUNT_PER_PARSER_TIMEOUT_CHECK = 100;

typedef struct {
  Subtree token;
  Subtree last_external_token;
  uint32_t byte_index;
} TokenCache;

// 파싱 액션을 저장할 타입 선언
typedef Array(TSParseAction) TSParseActionArray;

// 파싱 로그를 저장할 타입 선언
typedef Array(TSLoggedAction) TSLoggedActionArray;

typedef Array(TSSymbol) TSSymbolArray;

struct TSParser {
  Lexer lexer;
  Stack *stack;
  SubtreePool tree_pool;
  const TSLanguage *language;
  TSWasmStore *wasm_store;
  ReduceActionSet reduce_actions;

  TSLoggedActionArray logged_actions; // 파싱 로그 저장 자료구조 
  uint32_t cursor_row;   // 커서 위치
  uint32_t cursor_col;
  bool bIsCollectionOrParseStateID; // 컨버전, 컬렉션 모드 설정 변수

  Subtree finished_tree;  // 최종 선택된 트리
  SubtreeArray trailing_extras;
  SubtreeArray trailing_extras2;
  SubtreeArray scratch_trees;
  TokenCache token_cache;
  ReusableNode reusable_node;
  void *external_scanner_payload;
  FILE *dot_graph_file;
  TSClock end_clock;
  TSDuration timeout_duration;
  unsigned accept_count;
  unsigned operation_count;
  const volatile size_t *cancellation_flag;
  Subtree old_tree;
  TSRangeArray included_range_differences;
  TSParseOptions parse_options;
  TSParseState parse_state;
  unsigned included_range_difference_index;
  bool has_scanner_error;
  bool canceled_balancing;
  bool has_error;
  // 외부 스캐너가 실패했을 때 도달한 최대 바이트 위치
  // (ts_parser__advance_for_conversion에서 커서 경계 판단에 사용)
  uint32_t ext_scan_fail_max_position;
  // 파싱 중 size==0으로 반환된 external token의 인덱스 bitmask
  // (시뮬레이션에서 0-byte external token만 가상 SHIFT 탐색하기 위해 사용)
  uint64_t zero_byte_ext_mask;
};

typedef struct {
  unsigned cost;
  unsigned node_count;
  int dynamic_precedence;
  bool is_in_error;
} ErrorStatus;

typedef enum {
  ErrorComparisonTakeLeft,
  ErrorComparisonPreferLeft,
  ErrorComparisonNone,
  ErrorComparisonPreferRight,
  ErrorComparisonTakeRight,
} ErrorComparison;

typedef struct {
  const char *string;
  uint32_t length;
} TSStringInput;

// StringInput

static const char *ts_string_input_read(
  void *_self,
  uint32_t byte,
  TSPoint point,
  uint32_t *length
) {
  (void)point;
  TSStringInput *self = (TSStringInput *)_self;
  if (byte >= self->length) {
    *length = 0;
    return "";
  } else {
    *length = self->length - byte;
    return self->string + byte;
  }
}

// Parser - Private

static void ts_parser__log(TSParser *self) {
  if (self->lexer.logger.log) {
    self->lexer.logger.log(
      self->lexer.logger.payload,
      TSLogTypeParse,
      self->lexer.debug_buffer
    );
  }

  if (self->dot_graph_file) {
    fprintf(self->dot_graph_file, "graph {\nlabel=\"");
    for (char *chr = &self->lexer.debug_buffer[0]; *chr != 0; chr++) {
      if (*chr == '"' || *chr == '\\') fputc('\\', self->dot_graph_file);
      fputc(*chr, self->dot_graph_file);
    }
    fprintf(self->dot_graph_file, "\"\n}\n\n");
  }
}

static bool ts_parser__breakdown_top_of_stack(
  TSParser *self,
  StackVersion version
) {
  bool did_break_down = false;
  bool pending = false;

  do {
    StackSliceArray pop = ts_stack_pop_pending(self->stack, version);
    if (!pop.size) break;

    did_break_down = true;
    pending = false;
    for (uint32_t i = 0; i < pop.size; i++) {
      StackSlice slice = *array_get(&pop, i);
      TSStateId state = ts_stack_state(self->stack, slice.version);
      Subtree parent = *array_front(&slice.subtrees);

      for (uint32_t j = 0, n = ts_subtree_child_count(parent); j < n; j++) {
        Subtree child = ts_subtree_children(parent)[j];
        pending = ts_subtree_child_count(child) > 0;

        if (ts_subtree_is_error(child)) {
          state = ERROR_STATE;
        } else if (!ts_subtree_extra(child)) {
          state = ts_language_next_state(self->language, state, ts_subtree_symbol(child));
        }

        ts_subtree_retain(child);
        ts_stack_push(self->stack, slice.version, child, pending, state);
      }

      for (uint32_t j = 1; j < slice.subtrees.size; j++) {
        Subtree tree = *array_get(&slice.subtrees, j);
        ts_stack_push(self->stack, slice.version, tree, false, state);
      }

      ts_subtree_release(&self->tree_pool, parent);
      array_delete(&slice.subtrees);

      LOG("breakdown_top_of_stack tree:%s", TREE_NAME(parent));
      LOG_STACK();
    }
  } while (pending);

  return did_break_down;
}

static void ts_parser__breakdown_lookahead(
  TSParser *self,
  Subtree *lookahead,
  TSStateId state,
  ReusableNode *reusable_node
) {
  bool did_descend = false;
  Subtree tree = reusable_node_tree(reusable_node);
  while (ts_subtree_child_count(tree) > 0 && ts_subtree_parse_state(tree) != state) {
    LOG("state_mismatch sym:%s", TREE_NAME(tree));
    reusable_node_descend(reusable_node);
    tree = reusable_node_tree(reusable_node);
    did_descend = true;
  }

  if (did_descend) {
    ts_subtree_release(&self->tree_pool, *lookahead);
    *lookahead = tree;
    ts_subtree_retain(*lookahead);
  }
}

static ErrorComparison ts_parser__compare_versions(
  TSParser *self,
  ErrorStatus a,
  ErrorStatus b
) {
  (void)self;
  if (!a.is_in_error && b.is_in_error) {
    if (a.cost < b.cost) {
      return ErrorComparisonTakeLeft;
    } else {
      return ErrorComparisonPreferLeft;
    }
  }

  if (a.is_in_error && !b.is_in_error) {
    if (b.cost < a.cost) {
      return ErrorComparisonTakeRight;
    } else {
      return ErrorComparisonPreferRight;
    }
  }

  if (a.cost < b.cost) {
    if ((b.cost - a.cost) * (1 + a.node_count) > MAX_COST_DIFFERENCE) {
      return ErrorComparisonTakeLeft;
    } else {
      return ErrorComparisonPreferLeft;
    }
  }

  if (b.cost < a.cost) {
    if ((a.cost - b.cost) * (1 + b.node_count) > MAX_COST_DIFFERENCE) {
      return ErrorComparisonTakeRight;
    } else {
      return ErrorComparisonPreferRight;
    }
  }

  if (a.dynamic_precedence > b.dynamic_precedence) return ErrorComparisonPreferLeft;
  if (b.dynamic_precedence > a.dynamic_precedence) return ErrorComparisonPreferRight;
  return ErrorComparisonNone;
}

static ErrorStatus ts_parser__version_status(
  TSParser *self,
  StackVersion version
) {
  unsigned cost = ts_stack_error_cost(self->stack, version);
  bool is_paused = ts_stack_is_paused(self->stack, version);
  if (is_paused) cost += ERROR_COST_PER_SKIPPED_TREE;
  return (ErrorStatus) {
    .cost = cost,
    .node_count = ts_stack_node_count_since_error(self->stack, version),
    .dynamic_precedence = ts_stack_dynamic_precedence(self->stack, version),
    .is_in_error = is_paused || ts_stack_state(self->stack, version) == ERROR_STATE
  };
}

static bool ts_parser__better_version_exists(
  TSParser *self,
  StackVersion version,
  bool is_in_error,
  unsigned cost
) {
  if (self->finished_tree.ptr && ts_subtree_error_cost(self->finished_tree) <= cost) {
    return true;
  }

  Length position = ts_stack_position(self->stack, version);
  ErrorStatus status = {
    .cost = cost,
    .is_in_error = is_in_error,
    .dynamic_precedence = ts_stack_dynamic_precedence(self->stack, version),
    .node_count = ts_stack_node_count_since_error(self->stack, version),
  };

  for (StackVersion i = 0, n = ts_stack_version_count(self->stack); i < n; i++) {
    if (i == version ||
        !ts_stack_is_active(self->stack, i) ||
        ts_stack_position(self->stack, i).bytes < position.bytes) continue;
    ErrorStatus status_i = ts_parser__version_status(self, i);
    switch (ts_parser__compare_versions(self, status, status_i)) {
      case ErrorComparisonTakeRight:
        return true;
      case ErrorComparisonPreferRight:
        if (ts_stack_can_merge(self->stack, i, version)) return true;
        break;
      default:
        break;
    }
  }

  return false;
}

static bool ts_parser__call_main_lex_fn(TSParser *self, TSLexerMode lex_mode) {
  if (ts_language_is_wasm(self->language)) {
    return ts_wasm_store_call_lex_main(self->wasm_store, lex_mode.lex_state);
  } else {
    return self->language->lex_fn(&self->lexer.data, lex_mode.lex_state);
  }
}

static bool ts_parser__call_keyword_lex_fn(TSParser *self) {
  if (ts_language_is_wasm(self->language)) {
    return ts_wasm_store_call_lex_keyword(self->wasm_store, 0);
  } else {
    return self->language->keyword_lex_fn(&self->lexer.data, 0);
  }
}

static void ts_parser__external_scanner_create(
  TSParser *self
) {
  if (self->language && self->language->external_scanner.states) {
    if (ts_language_is_wasm(self->language)) {
      self->external_scanner_payload = (void *)(uintptr_t)ts_wasm_store_call_scanner_create(
        self->wasm_store
      );
      if (ts_wasm_store_has_error(self->wasm_store)) {
        self->has_scanner_error = true;
      }
    } else if (self->language->external_scanner.create) {
      self->external_scanner_payload = self->language->external_scanner.create();
    }
  }
}

static void ts_parser__external_scanner_destroy(
  TSParser *self
) {
  if (
    self->language &&
    self->external_scanner_payload &&
    self->language->external_scanner.destroy &&
    !ts_language_is_wasm(self->language)
  ) {
    self->language->external_scanner.destroy(
      self->external_scanner_payload
    );
  }
  self->external_scanner_payload = NULL;
}

static unsigned ts_parser__external_scanner_serialize(
  TSParser *self
) {
  if (ts_language_is_wasm(self->language)) {
    return ts_wasm_store_call_scanner_serialize(
      self->wasm_store,
      (uintptr_t)self->external_scanner_payload,
      self->lexer.debug_buffer
    );
  } else {
    uint32_t length = self->language->external_scanner.serialize(
      self->external_scanner_payload,
      self->lexer.debug_buffer
    );
    ts_assert(length <= TREE_SITTER_SERIALIZATION_BUFFER_SIZE);
    return length;
  }
}

static void ts_parser__external_scanner_deserialize(
  TSParser *self,
  Subtree external_token
) {
  const char *data = NULL;
  uint32_t length = 0;
  if (external_token.ptr) {
    data = ts_external_scanner_state_data(&external_token.ptr->external_scanner_state);
    length = external_token.ptr->external_scanner_state.length;
  }

  if (ts_language_is_wasm(self->language)) {
    ts_wasm_store_call_scanner_deserialize(
      self->wasm_store,
      (uintptr_t)self->external_scanner_payload,
      data,
      length
    );
    if (ts_wasm_store_has_error(self->wasm_store)) {
      self->has_scanner_error = true;
    }
  } else {
    self->language->external_scanner.deserialize(
      self->external_scanner_payload,
      data,
      length
    );
  }
}

static bool ts_parser__external_scanner_scan(
  TSParser *self,
  TSStateId external_lex_state
) {
  if (ts_language_is_wasm(self->language)) {
    bool result = ts_wasm_store_call_scanner_scan(
      self->wasm_store,
      (uintptr_t)self->external_scanner_payload,
      external_lex_state * self->language->external_token_count
    );
    if (ts_wasm_store_has_error(self->wasm_store)) {
      self->has_scanner_error = true;
    }
    return result;
  } else {
    const bool *valid_external_tokens = ts_language_enabled_external_tokens(
      self->language,
      external_lex_state
    );
    return self->language->external_scanner.scan(
      self->external_scanner_payload,
      &self->lexer.data,
      valid_external_tokens
    );
  }
}

static bool ts_parser__can_reuse_first_leaf(
  TSParser *self,
  TSStateId state,
  Subtree tree,
  TableEntry *table_entry
) {
  TSSymbol leaf_symbol = ts_subtree_leaf_symbol(tree);
  TSStateId leaf_state = ts_subtree_leaf_parse_state(tree);
  TSLexerMode current_lex_mode = ts_language_lex_mode_for_state(self->language, state);
  TSLexerMode leaf_lex_mode = ts_language_lex_mode_for_state(self->language, leaf_state);

  // At the end of a non-terminal extra node, the lexer normally returns
  // NULL, which indicates that the parser should look for a reduce action
  // at symbol `0`. Avoid reusing tokens in this situation to ensure that
  // the same thing happens when incrementally reparsing.
  if (current_lex_mode.lex_state == (uint16_t)(-1)) return false;

  // If the token was created in a state with the same set of lookaheads, it is reusable.
  if (
    table_entry->action_count > 0 &&
    memcmp(&leaf_lex_mode, &current_lex_mode, sizeof(TSLexerMode)) == 0 &&
    (
      leaf_symbol != self->language->keyword_capture_token ||
      (!ts_subtree_is_keyword(tree) && ts_subtree_parse_state(tree) == state)
    )
  ) return true;

  // Empty tokens are not reusable in states with different lookaheads.
  if (ts_subtree_size(tree).bytes == 0 && leaf_symbol != ts_builtin_sym_end) return false;

  // If the current state allows external tokens or other tokens that conflict with this
  // token, this token is not reusable.
  return current_lex_mode.external_lex_state == 0 && table_entry->is_reusable;
}

// 텍스트를 분석해서 Subtree(Leaf Node) 생성
static Subtree ts_parser__lex(
  TSParser *self,
  StackVersion version,
  TSStateId parse_state
) {
  TSLexerMode lex_mode = ts_language_lex_mode_for_state(self->language, parse_state);
  if (lex_mode.lex_state == (uint16_t)-1) {
    LOG("no_lookahead_after_non_terminal_extra");
    return NULL_SUBTREE;
  }

  const Length start_position = ts_stack_position(self->stack, version);
  const Subtree external_token = ts_stack_last_external_token(self->stack, version);

  bool found_external_token = false;
  bool error_mode = parse_state == ERROR_STATE;
  bool skipped_error = false;
  bool called_get_column = false;
  int32_t first_error_character = 0;
  Length error_start_position = length_zero();
  Length error_end_position = length_zero();
  uint32_t lookahead_end_byte = 0;
  uint32_t external_scanner_state_len = 0;
  bool external_scanner_state_changed = false;
  ts_lexer_reset(&self->lexer, start_position);

  for (;;) {
    bool found_token = false;
    Length current_position = self->lexer.current_position;
    ColumnData column_data = self->lexer.column_data;

    if (lex_mode.external_lex_state != 0) {
      LOG(
        "lex_external state:%d, row:%u, column:%u",
        lex_mode.external_lex_state,
        current_position.extent.row,
        current_position.extent.column
      );
      ts_lexer_start(&self->lexer);
      ts_parser__external_scanner_deserialize(self, external_token);
      found_token = ts_parser__external_scanner_scan(self, lex_mode.external_lex_state);
      if (self->has_scanner_error) return NULL_SUBTREE;
      ts_lexer_finish(&self->lexer, &lookahead_end_byte);

      if (found_token) {
        external_scanner_state_len = ts_parser__external_scanner_serialize(self);
        external_scanner_state_changed = !ts_external_scanner_state_eq(
          ts_subtree_external_scanner_state(external_token),
          self->lexer.debug_buffer,
          external_scanner_state_len
        );

        // Avoid infinite loops caused by the external scanner returning empty tokens.
        // Empty tokens are needed in some circumstances, e.g. indent/dedent tokens
        // in Python. Ignore the following classes of empty tokens:
        //
        // * Tokens produced during error recovery. When recovering from an error,
        //   all tokens are allowed, so it's easy to accidentally return unwanted
        //   empty tokens.
        // * Tokens that are marked as 'extra' in the grammar. These don't change
        //   the parse state, so they would definitely cause an infinite loop.
        if (
          self->lexer.token_end_position.bytes <= current_position.bytes &&
          !external_scanner_state_changed
        ) {
          TSSymbol symbol = self->language->external_scanner.symbol_map[self->lexer.data.result_symbol];
          TSStateId next_parse_state = ts_language_next_state(self->language, parse_state, symbol);
          bool token_is_extra = (next_parse_state == parse_state);
          if (error_mode || !ts_stack_has_advanced_since_error(self->stack, version) || token_is_extra) {
            LOG(
              "ignore_empty_external_token symbol:%s",
              SYM_NAME(self->language->external_scanner.symbol_map[self->lexer.data.result_symbol])
            );
            found_token = false;
          }
        }
      }

      if (found_token) {
        found_external_token = true;
        called_get_column = self->lexer.did_get_column;
        break;
      }

      // 외부 스캐너가 실패했을 때 도달한 최대 위치를 저장 (리셋 전)
      self->ext_scan_fail_max_position = self->lexer.current_position.bytes;

      ts_lexer_reset(&self->lexer, current_position);
      self->lexer.column_data = column_data;
    }

    LOG(
      "lex_internal state:%d, row:%u, column:%u",
      lex_mode.lex_state,
      current_position.extent.row,
      current_position.extent.column
    );
    ts_lexer_start(&self->lexer);
    found_token = ts_parser__call_main_lex_fn(self, lex_mode);
    ts_lexer_finish(&self->lexer, &lookahead_end_byte);
    if (found_token) break;

    if (!error_mode) {
      error_mode = true;
      lex_mode = ts_language_lex_mode_for_state(self->language, ERROR_STATE);
      ts_lexer_reset(&self->lexer, start_position);
      continue;
    }

    if (!skipped_error) {
      LOG("skip_unrecognized_character");
      skipped_error = true;
      error_start_position = self->lexer.token_start_position;
      error_end_position = self->lexer.token_start_position;
      first_error_character = self->lexer.data.lookahead;
    }

    if (self->lexer.current_position.bytes == error_end_position.bytes) {
      if (self->lexer.data.eof(&self->lexer.data)) {
        self->lexer.data.result_symbol = ts_builtin_sym_error;
        break;
      }
      self->lexer.data.advance(&self->lexer.data, false);
    }

    error_end_position = self->lexer.current_position;
  }

  Subtree result;
  if (skipped_error) {
    Length padding = length_sub(error_start_position, start_position);
    Length size = length_sub(error_end_position, error_start_position);
    uint32_t lookahead_bytes = lookahead_end_byte - error_end_position.bytes;
    result = ts_subtree_new_error(
      &self->tree_pool,
      first_error_character,
      padding,
      size,
      lookahead_bytes,
      parse_state,
      self->language
    );
  } else {
    bool is_keyword = false;
    TSSymbol symbol = self->lexer.data.result_symbol;
    Length padding = length_sub(self->lexer.token_start_position, start_position);
    Length size = length_sub(self->lexer.token_end_position, self->lexer.token_start_position);
    uint32_t lookahead_bytes = lookahead_end_byte - self->lexer.token_end_position.bytes;

    if (found_external_token) {
      // size==0이면 0-byte external token → bitmask에 기록 (시뮬레이션 필터링용)
      uint32_t ext_idx = (uint32_t)self->lexer.data.result_symbol;
      if (size.bytes == 0 && ext_idx < 64) {
        self->zero_byte_ext_mask |= (1ULL << ext_idx);
      }
      symbol = self->language->external_scanner.symbol_map[symbol];
    } else if (symbol == self->language->keyword_capture_token && symbol != 0) {
      uint32_t end_byte = self->lexer.token_end_position.bytes;
      ts_lexer_reset(&self->lexer, self->lexer.token_start_position);
      ts_lexer_start(&self->lexer);

      is_keyword = ts_parser__call_keyword_lex_fn(self);

      if (
        is_keyword &&
        self->lexer.token_end_position.bytes == end_byte &&
        (
          ts_language_has_actions(self->language, parse_state, self->lexer.data.result_symbol) ||
          ts_language_is_reserved_word(self->language, parse_state, self->lexer.data.result_symbol)
        )
      ) {
        symbol = self->lexer.data.result_symbol;
      }
    }

    result = ts_subtree_new_leaf(
      &self->tree_pool,
      symbol,
      padding,
      size,
      lookahead_bytes,
      parse_state,
      found_external_token,
      called_get_column,
      is_keyword,
      self->language
    );

    if (found_external_token) {
      MutableSubtree mut_result = ts_subtree_to_mut_unsafe(result);
      ts_external_scanner_state_init(
        &mut_result.ptr->external_scanner_state,
        self->lexer.debug_buffer,
        external_scanner_state_len
      );
      mut_result.ptr->has_external_scanner_state_change = external_scanner_state_changed;
    }
  }

  LOG_LOOKAHEAD(
    SYM_NAME(ts_subtree_symbol(result)),
    ts_subtree_total_size(result).bytes
  );
  return result;
}

static Subtree ts_parser__get_cached_token(
  TSParser *self,
  TSStateId state,
  size_t position,
  Subtree last_external_token,
  TableEntry *table_entry
) {
  TokenCache *cache = &self->token_cache;
  if (
    cache->token.ptr && cache->byte_index == position &&
    ts_subtree_external_scanner_state_eq(cache->last_external_token, last_external_token)
  ) {
    ts_language_table_entry(self->language, state, ts_subtree_symbol(cache->token), table_entry);
    if (ts_parser__can_reuse_first_leaf(self, state, cache->token, table_entry)) {
      ts_subtree_retain(cache->token);
      return cache->token;
    }
  }
  return NULL_SUBTREE;
}

static void ts_parser__set_cached_token(
  TSParser *self,
  uint32_t byte_index,
  Subtree last_external_token,
  Subtree token
) {
  TokenCache *cache = &self->token_cache;
  if (token.ptr) ts_subtree_retain(token);
  if (last_external_token.ptr) ts_subtree_retain(last_external_token);
  if (cache->token.ptr) ts_subtree_release(&self->tree_pool, cache->token);
  if (cache->last_external_token.ptr) ts_subtree_release(&self->tree_pool, cache->last_external_token);
  cache->token = token;
  cache->byte_index = byte_index;
  cache->last_external_token = last_external_token;
}

static bool ts_parser__has_included_range_difference(
  const TSParser *self,
  uint32_t start_position,
  uint32_t end_position
) {
  return ts_range_array_intersects(
    &self->included_range_differences,
    self->included_range_difference_index,
    start_position,
    end_position
  );
}

static Subtree ts_parser__reuse_node(
  TSParser *self,
  StackVersion version,
  TSStateId *state,
  uint32_t position,
  Subtree last_external_token,
  TableEntry *table_entry
) {
  Subtree result;
  while ((result = reusable_node_tree(&self->reusable_node)).ptr) {
    uint32_t byte_offset = reusable_node_byte_offset(&self->reusable_node);
    uint32_t end_byte_offset = byte_offset + ts_subtree_total_bytes(result);

    // Do not reuse an EOF node if the included ranges array has changes
    // later on in the file.
    if (ts_subtree_is_eof(result)) end_byte_offset = UINT32_MAX;

    if (byte_offset > position) {
      LOG("before_reusable_node symbol:%s", TREE_NAME(result));
      break;
    }

    if (byte_offset < position) {
      LOG("past_reusable_node symbol:%s", TREE_NAME(result));
      if (end_byte_offset <= position || !reusable_node_descend(&self->reusable_node)) {
        reusable_node_advance(&self->reusable_node);
      }
      continue;
    }

    if (!ts_subtree_external_scanner_state_eq(self->reusable_node.last_external_token, last_external_token)) {
      LOG("reusable_node_has_different_external_scanner_state symbol:%s", TREE_NAME(result));
      reusable_node_advance(&self->reusable_node);
      continue;
    }

    const char *reason = NULL;
    if (ts_subtree_has_changes(result)) {
      reason = "has_changes";
    } else if (ts_subtree_is_error(result)) {
      reason = "is_error";
    } else if (ts_subtree_missing(result)) {
      reason = "is_missing";
    } else if (ts_subtree_is_fragile(result)) {
      reason = "is_fragile";
    } else if (ts_parser__has_included_range_difference(self, byte_offset, end_byte_offset)) {
      reason = "contains_different_included_range";
    }

    if (reason) {
      LOG("cant_reuse_node_%s tree:%s", reason, TREE_NAME(result));
      if (!reusable_node_descend(&self->reusable_node)) {
        reusable_node_advance(&self->reusable_node);
        ts_parser__breakdown_top_of_stack(self, version);
        *state = ts_stack_state(self->stack, version);
      }
      continue;
    }

    TSSymbol leaf_symbol = ts_subtree_leaf_symbol(result);
    ts_language_table_entry(self->language, *state, leaf_symbol, table_entry);
    if (!ts_parser__can_reuse_first_leaf(self, *state, result, table_entry)) {
      LOG(
        "cant_reuse_node symbol:%s, first_leaf_symbol:%s",
        TREE_NAME(result),
        SYM_NAME(leaf_symbol)
      );
      reusable_node_advance_past_leaf(&self->reusable_node);
      break;
    }

    LOG("reuse_node symbol:%s", TREE_NAME(result));
    ts_subtree_retain(result);
    return result;
  }

  return NULL_SUBTREE;
}

// Determine if a given tree should be replaced by an alternative tree.
//
// The decision is based on the trees' error costs (if any), their dynamic precedence,
// and finally, as a default, by a recursive comparison of the trees' symbols.
static bool ts_parser__select_tree(TSParser *self, Subtree left, Subtree right) {
  if (!left.ptr) return true;
  if (!right.ptr) return false;

  if (ts_subtree_error_cost(right) < ts_subtree_error_cost(left)) {
    LOG("select_smaller_error symbol:%s, over_symbol:%s", TREE_NAME(right), TREE_NAME(left));
    return true;
  }

  if (ts_subtree_error_cost(left) < ts_subtree_error_cost(right)) {
    LOG("select_smaller_error symbol:%s, over_symbol:%s", TREE_NAME(left), TREE_NAME(right));
    return false;
  }

  if (ts_subtree_dynamic_precedence(right) > ts_subtree_dynamic_precedence(left)) {
    LOG("select_higher_precedence symbol:%s, prec:%" PRId32 ", over_symbol:%s, other_prec:%" PRId32,
        TREE_NAME(right), ts_subtree_dynamic_precedence(right), TREE_NAME(left),
        ts_subtree_dynamic_precedence(left));
    return true;
  }

  if (ts_subtree_dynamic_precedence(left) > ts_subtree_dynamic_precedence(right)) {
    LOG("select_higher_precedence symbol:%s, prec:%" PRId32 ", over_symbol:%s, other_prec:%" PRId32,
        TREE_NAME(left), ts_subtree_dynamic_precedence(left), TREE_NAME(right),
        ts_subtree_dynamic_precedence(right));
    return false;
  }

  if (ts_subtree_error_cost(left) > 0) return true;

  int comparison = ts_subtree_compare(left, right, &self->tree_pool);
  switch (comparison) {
    case -1:
      LOG("select_earlier symbol:%s, over_symbol:%s", TREE_NAME(left), TREE_NAME(right));
      return false;
      break;
    case 1:
      LOG("select_earlier symbol:%s, over_symbol:%s", TREE_NAME(right), TREE_NAME(left));
      return true;
    default:
      LOG("select_existing symbol:%s, over_symbol:%s", TREE_NAME(left), TREE_NAME(right));
      return false;
  }
}

// Determine if a given tree's children should be replaced by an alternative
// array of children.
static bool ts_parser__select_children(
  TSParser *self,
  Subtree left,
  const SubtreeArray *children
) {
  array_assign(&self->scratch_trees, children);

  // Create a temporary subtree using the scratch trees array. This node does
  // not perform any allocation except for possibly growing the array to make
  // room for its own heap data. The scratch tree is never explicitly released,
  // so the same 'scratch trees' array can be reused again later.
  MutableSubtree scratch_tree = ts_subtree_new_node(
    ts_subtree_symbol(left),
    &self->scratch_trees,
    0,
    self->language
  );

  return ts_parser__select_tree(
    self,
    left,
    ts_subtree_from_mut(scratch_tree)
  );
}

static void ts_parser__shift(
  TSParser *self,
  StackVersion version,
  TSStateId state,
  Subtree lookahead,
  bool extra
) {
  bool is_leaf = ts_subtree_child_count(lookahead) == 0;
  Subtree subtree_to_push = lookahead;
  if (extra != ts_subtree_extra(lookahead) && is_leaf) {
    MutableSubtree result = ts_subtree_make_mut(&self->tree_pool, lookahead);
    ts_subtree_set_extra(&result, extra);
    subtree_to_push = ts_subtree_from_mut(result);
  }

  ts_stack_push(self->stack, version, subtree_to_push, !is_leaf, state);
  if (ts_subtree_has_external_tokens(subtree_to_push)) {
    ts_stack_set_last_external_token(
      self->stack, version, ts_subtree_last_external_token(subtree_to_push)
    );
  }
}

static StackVersion ts_parser__reduce(
  TSParser *self,
  StackVersion version,   // 현재 reduce를 수행할 스택 버전
  TSSymbol symbol,        // 새로 생성할 비단말 심볼
  uint32_t count,         // 스택에서 pop할 자식 개수
  int dynamic_precedence,
  uint16_t production_id,
  bool is_fragile,
  bool end_of_non_terminal_extra
) {

  // 기준점(reduce 시작 시점의 version 수) 기록
  uint32_t initial_version_count = ts_stack_version_count(self->stack);

  // 스택에서 count개 노드 pop
  // 스택이 이전에 GLR 분기로 인해 여러 버전이 합쳐진 경우, 경로가 여러개일 수 있음
  // 각 경로마다 하나의 StackSlice를 만들어 배열로 반환
  // 이 배열의 크기만큼 새로운 스택 버전 파생 (Re-split)

  // Pop the given number of nodes from the given version of the parse stack.
  // If stack versions have previously merged, then there may be more than one
  // path back through the stack. For each path, create a new parent node to
  // contain the popped children, and push it onto the stack in place of the
  // children.
  StackSliceArray pop = ts_stack_pop_count(self->stack, version, count);
  
  // 제거된 스택 버전의 개수: 인덱스 보정용
  uint32_t removed_version_count = 0;
  uint32_t halted_version_count = ts_stack_halted_version_count(self->stack);
  
  
  for (uint32_t i = 0; i < pop.size; i++) {
    StackSlice slice = *array_get(&pop, i);
    
    // 인덱스 보정: 현재 진짜 버전 번호 = slice에 적힌 번호 - 앞서 제거된 개수
    StackVersion slice_version = slice.version - removed_version_count;

    // 성능 안전장치
    // This is where new versions are added to the parse stack. The versions
    // will all be sorted and truncated at the end of the outer parsing loop.
    // Allow the maximum version count to be temporarily exceeded, but only
    // by a limited threshold.
    if (slice_version > MAX_VERSION_COUNT + MAX_VERSION_COUNT_OVERFLOW + halted_version_count) {
      ts_stack_remove_version(self->stack, slice_version);
      ts_subtree_array_delete(&self->tree_pool, &slice.subtrees);
      removed_version_count++;
      while (i + 1 < pop.size) {
        LOG("aborting reduce with too many versions")
        StackSlice next_slice = *array_get(&pop, i + 1);
        if (next_slice.version != slice.version) break;
        ts_subtree_array_delete(&self->tree_pool, &next_slice.subtrees);
        i++;
      }
      continue;
    }

    // 스택에서 꺼낸 자식들의 맨 끝부분에 달린 Extra 토큰들(주석이나 공백) 임시 제거
    // Extra tokens on top of the stack should not be included in this new parent
    // node. They will be re-pushed onto the stack after the parent node is
    // created and pushed.
    SubtreeArray children = slice.subtrees;
    ts_subtree_array_remove_trailing_extras(&children, &self->trailing_extras);

    // children 배열의 내용을 복사하여 부모 노드 생성
    MutableSubtree parent = ts_subtree_new_node(
      symbol, &children, production_id, self->language
    );

    // 여러 갈래로 pop 했는데, 동일한 출발점으로 수렴하는 경로가 있는 경우
    // ts_parser__select_children 함수로 가장 적합한 하나만 선택
    // This pop operation may have caused multiple stack versions to collapse
    // into one, because they all diverged from a common state. In that case,
    // choose one of the arrays of trees to be the parent node's children, and
    // delete the rest of the tree arrays.
    while (i + 1 < pop.size) {
      StackSlice next_slice = *array_get(&pop, i + 1);
      if (next_slice.version != slice.version) break;
      i++;

      SubtreeArray next_slice_children = next_slice.subtrees;
      ts_subtree_array_remove_trailing_extras(&next_slice_children, &self->trailing_extras2);

      if (ts_parser__select_children(
        self,
        ts_subtree_from_mut(parent),
        &next_slice_children
      )) {
        ts_subtree_array_clear(&self->tree_pool, &self->trailing_extras);
        ts_subtree_release(&self->tree_pool, ts_subtree_from_mut(parent));
        array_swap(&self->trailing_extras, &self->trailing_extras2);
        parent = ts_subtree_new_node(
          symbol, &next_slice_children, production_id, self->language
        );
      } else {
        array_clear(&self->trailing_extras2);
        ts_subtree_array_delete(&self->tree_pool, &next_slice.subtrees);
      }
    }

    // pop이 끝난 후 현재 스택의 꼭대기 상태 확인
    TSStateId state = ts_stack_state(self->stack, slice_version);
    // goto 테이블 조회해 다음 상태 계산
    TSStateId next_state = ts_language_next_state(self->language, state, symbol);
    if (end_of_non_terminal_extra && next_state == state) {
      parent.ptr->extra = true;
    }
    if (is_fragile || pop.size > 1 || initial_version_count > 1) {
      parent.ptr->fragile_left = true;
      parent.ptr->fragile_right = true;
      parent.ptr->parse_state = TS_TREE_STATE_NONE;
    } else {
      parent.ptr->parse_state = state;
    }
    parent.ptr->dynamic_precedence += dynamic_precedence;

    // 완성된 부모와 next_state를 스택에 올림
    // Push the parent node onto the stack, along with any extra tokens that
    // were previously on top of the stack.
    ts_stack_push(self->stack, slice_version, ts_subtree_from_mut(parent), false, next_state);
    for (uint32_t j = 0; j < self->trailing_extras.size; j++) {
      ts_stack_push(self->stack, slice_version, *array_get(&self->trailing_extras, j), false, next_state);
    }

    // 같은 상태에 도달한 버전들 병합
    for (StackVersion j = 0; j < slice_version; j++) {
      if (j == version) continue;
      if (ts_stack_merge(self->stack, j, slice_version)) {
        removed_version_count++;
        break;
      }
    }
  }

  // Return the first new stack version that was created.
  return ts_stack_version_count(self->stack) > initial_version_count
    ? initial_version_count
    : STACK_VERSION_NONE;
}

static void ts_parser__accept(
  TSParser *self,
  StackVersion version,
  Subtree lookahead
) {
  ts_assert(ts_subtree_is_eof(lookahead));
  ts_stack_push(self->stack, version, lookahead, false, 1);

  StackSliceArray pop = ts_stack_pop_all(self->stack, version);
  for (uint32_t i = 0; i < pop.size; i++) {
    SubtreeArray trees = array_get(&pop, i)->subtrees;

    Subtree root = NULL_SUBTREE;
    for (uint32_t j = trees.size - 1; j + 1 > 0; j--) {
      Subtree tree = *array_get(&trees, j);
      if (!ts_subtree_extra(tree)) {
        ts_assert(!tree.data.is_inline);
        uint32_t child_count = ts_subtree_child_count(tree);
        const Subtree *children = ts_subtree_children(tree);
        for (uint32_t k = 0; k < child_count; k++) {
          ts_subtree_retain(children[k]);
        }
        array_splice(&trees, j, 1, child_count, children);
        root = ts_subtree_from_mut(ts_subtree_new_node(
          ts_subtree_symbol(tree),
          &trees,
          tree.ptr->production_id,
          self->language
        ));
        ts_subtree_release(&self->tree_pool, tree);
        break;
      }
    }

    ts_assert(root.ptr);
    self->accept_count++;

    if (self->finished_tree.ptr) {
      if (ts_parser__select_tree(self, self->finished_tree, root)) {
        ts_subtree_release(&self->tree_pool, self->finished_tree);
        self->finished_tree = root;
      } else {
        ts_subtree_release(&self->tree_pool, root);
      }
    } else {
      self->finished_tree = root;
    }
  }

  ts_stack_remove_version(self->stack, array_get(&pop, 0)->version);
  ts_stack_halt(self->stack, version);
}

// [custom] 에러 복구 중 Reduce 시도 함수
static bool ts_parser__do_all_potential_reductions(
  TSParser *self,
  StackVersion starting_version,
  TSSymbol lookahead_symbol
) {
  uint32_t initial_version_count = ts_stack_version_count(self->stack);

  bool can_shift_lookahead_symbol = false;
  StackVersion version = starting_version;
  // GLR 스택 순회 및 병합 (무한 루프)
  for (unsigned i = 0; true; i++) {
    uint32_t version_count = ts_stack_version_count(self->stack);
    if (version >= version_count) break;

    bool merged = false;
    for (StackVersion j = initial_version_count; j < version; j++) {
      if (ts_stack_merge(self->stack, j, version)) {
        merged = true;
        break;
      }
    }
    if (merged) continue;

    // 탐색할 기호 범위 설정 (2가지 모드)
    TSStateId state = ts_stack_state(self->stack, version);
    bool has_shift_action = false;
    array_clear(&self->reduce_actions);

    TSSymbol first_symbol, end_symbol;
    if (lookahead_symbol != 0) {
      // 모드 1: 특정 기호 검증 모드
      first_symbol = lookahead_symbol;
      end_symbol = lookahead_symbol + 1;
    } else {
      // 모드 2: 모든 기호에 대해 reduce 모드
      first_symbol = 1;
      end_symbol = self->language->token_count;
    }

    // 파싱 액션 수집
    for (TSSymbol symbol = first_symbol; symbol < end_symbol; symbol++) {
      TableEntry entry;
      ts_language_table_entry(self->language, state, symbol, &entry);
      for (uint32_t j = 0; j < entry.action_count; j++) {
        TSParseAction action = entry.actions[j];
        switch (action.type) {
          case TSParseActionTypeShift:
          case TSParseActionTypeRecover:
            if (!action.shift.extra && !action.shift.repetition) has_shift_action = true;
            break;
          case TSParseActionTypeReduce:
            if (action.reduce.child_count > 0) {
              ts_reduce_action_set_add(&self->reduce_actions, (ReduceAction) {
                .symbol = action.reduce.symbol,
                .count = action.reduce.child_count,
                .dynamic_precedence = action.reduce.dynamic_precedence,
                .production_id = action.reduce.production_id,
              });
            }
            break;
          default:
            break;
        }
      }
    }

    // 수집된 모든 reduce 강제 실행
    StackVersion reduction_version = STACK_VERSION_NONE;
    for (uint32_t j = 0; j < self->reduce_actions.size; j++) {
      ReduceAction action = *array_get(&self->reduce_actions, j);

      // 현재 상태(Reduce 직전) 백업
      TSStateId state_before_reduce = ts_stack_state(self->stack, version);

      // 실제 Reduce 실행
      reduction_version = ts_parser__reduce(
        self, version, action.symbol, action.count,
        action.dynamic_precedence, action.production_id,
        true, false
      );

      // --------------------------- 데이터 저장 ---------------------------------
      // Reduce가 성공해서 새로운 버전이 생기면 로그
      if (reduction_version != STACK_VERSION_NONE) {
        // Reduce 후 이동한 상태(GOTO) 확인
        TSStateId goto_state = ts_stack_state(self->stack, reduction_version);
        
        TSLoggedAction v_reduce_log = (TSLoggedAction) {
            .type = TSParseActionTypeReduce,
            .symbol = action.symbol,       // 축약된 심볼 (예: Expr)
            .child_count = action.count,   // 자식 개수
            .current_state = state_before_reduce, // 시작점
            .next_state = goto_state,      // 도착점 (Parent)
            .is_virtual = true             // 에러 복구 중 발생했으므로 가상 취급
        };
        array_push(&self->logged_actions, v_reduce_log);
        // -----------------------------------------------------------------
      }
    }

    if (has_shift_action) {
      can_shift_lookahead_symbol = true;
    } else if (reduction_version != STACK_VERSION_NONE && i < MAX_VERSION_COUNT) {
      ts_stack_renumber_version(self->stack, reduction_version, version);
      continue;
    } else if (lookahead_symbol != 0) {
      ts_stack_remove_version(self->stack, version);
    }

    if (version == starting_version) {
      version = version_count;
    } else {
      version++;
    }
  }

  return can_shift_lookahead_symbol;
}

static bool ts_parser__recover_to_state(
  TSParser *self,
  StackVersion version,
  unsigned depth,
  TSStateId goal_state
) {
  StackSliceArray pop = ts_stack_pop_count(self->stack, version, depth);
  StackVersion previous_version = STACK_VERSION_NONE;

  for (unsigned i = 0; i < pop.size; i++) {
    StackSlice slice = *array_get(&pop, i);

    if (slice.version == previous_version) {
      ts_subtree_array_delete(&self->tree_pool, &slice.subtrees);
      array_erase(&pop, i--);
      continue;
    }

    if (ts_stack_state(self->stack, slice.version) != goal_state) {
      ts_stack_halt(self->stack, slice.version);
      ts_subtree_array_delete(&self->tree_pool, &slice.subtrees);
      array_erase(&pop, i--);
      continue;
    }

    SubtreeArray error_trees = ts_stack_pop_error(self->stack, slice.version);
    if (error_trees.size > 0) {
      ts_assert(error_trees.size == 1);
      Subtree error_tree = *array_get(&error_trees, 0);
      uint32_t error_child_count = ts_subtree_child_count(error_tree);
      if (error_child_count > 0) {
        array_splice(&slice.subtrees, 0, 0, error_child_count, ts_subtree_children(error_tree));
        for (unsigned j = 0; j < error_child_count; j++) {
          ts_subtree_retain(*array_get(&slice.subtrees, j));
        }
      }
      ts_subtree_array_delete(&self->tree_pool, &error_trees);
    }

    ts_subtree_array_remove_trailing_extras(&slice.subtrees, &self->trailing_extras);

    if (slice.subtrees.size > 0) {
      Subtree error = ts_subtree_new_error_node(&slice.subtrees, true, self->language);
      ts_stack_push(self->stack, slice.version, error, false, goal_state);
    } else {
      array_delete(&slice.subtrees);
    }

    for (unsigned j = 0; j < self->trailing_extras.size; j++) {
      Subtree tree = *array_get(&self->trailing_extras, j);
      ts_stack_push(self->stack, slice.version, tree, false, goal_state);
    }

    previous_version = slice.version;
  }

  return previous_version != STACK_VERSION_NONE;
}

// [info] 에러 처리 함수
// 두 가지 복구 전략(1. 과거로 되감기, 2. 토큰 버리기)을 동시에 시도하여
// 파싱 경로를 분기시키고, 최적의 복구 경로를 탐색하도록 함
static void ts_parser__recover(
  TSParser *self,
  StackVersion version,
  Subtree lookahead
) {
  bool did_recover = false;
  unsigned previous_version_count = ts_stack_version_count(self->stack);
  Length position = ts_stack_position(self->stack, version);
  StackSummary *summary = ts_stack_get_summary(self->stack, version);
  unsigned node_count_since_error = ts_stack_node_count_since_error(self->stack, version);
  unsigned current_error_cost = ts_stack_error_cost(self->stack, version);

  // When the parser is in the error state, there are two strategies for recovering with a
  // given lookahead token:
  // 1. Find a previous state on the stack in which that lookahead token would be valid. Then,
  //    create a new stack version that is in that state again. This entails popping all of the
  //    subtrees that have been pushed onto the stack since that previous state, and wrapping
  //    them in an ERROR node.
  // 2. Wrap the lookahead token in an ERROR node, push that ERROR node onto the stack, and
  //    move on to the next lookahead token, remaining in the error state.
  //
  // First, try the strategy 1. Upon entering the error state, the parser recorded a summary
  // of the previous parse states and their depths. Look at each state in the summary, to see
  // if the current lookahead token would be valid in that state.
  if (summary && !ts_subtree_is_error(lookahead)) {
    for (unsigned i = 0; i < summary->size; i++) {
      StackSummaryEntry entry = *array_get(summary, i);

      if (entry.state == ERROR_STATE) continue;
      if (entry.position.bytes == position.bytes) continue;
      unsigned depth = entry.depth;
      if (node_count_since_error > 0) depth++;

      // Do not recover in ways that create redundant stack versions.
      bool would_merge = false;
      for (unsigned j = 0; j < previous_version_count; j++) {
        if (
          ts_stack_state(self->stack, j) == entry.state &&
          ts_stack_position(self->stack, j).bytes == position.bytes
        ) {
          would_merge = true;
          break;
        }
      }
      if (would_merge) continue;

      // Do not recover if the result would clearly be worse than some existing stack version.
      unsigned new_cost =
        current_error_cost +
        entry.depth * ERROR_COST_PER_SKIPPED_TREE +
        (position.bytes - entry.position.bytes) * ERROR_COST_PER_SKIPPED_CHAR +
        (position.extent.row - entry.position.extent.row) * ERROR_COST_PER_SKIPPED_LINE;
      if (ts_parser__better_version_exists(self, version, false, new_cost)) break;

      // If the current lookahead token is valid in some previous state, recover to that state.
      // Then stop looking for further recoveries.
      if (ts_language_has_actions(self->language, entry.state, ts_subtree_symbol(lookahead))) {
        if (ts_parser__recover_to_state(self, version, depth, entry.state)) {
          did_recover = true;
          LOG("recover_to_previous state:%u, depth:%u", entry.state, depth);
          LOG_STACK();
          break;
        }
      }
    }
  }

  // In the process of attempting to recover, some stack versions may have been created
  // and subsequently halted. Remove those versions.
  for (unsigned i = previous_version_count; i < ts_stack_version_count(self->stack); i++) {
    if (!ts_stack_is_active(self->stack, i)) {
      LOG("removed paused version:%u", i);
      ts_stack_remove_version(self->stack, i--);
      LOG_STACK();
    }
  }

  // If the parser is still in the error state at the end of the file, just wrap everything
  // in an ERROR node and terminate.
  if (ts_subtree_is_eof(lookahead)) {
    LOG("recover_eof");
    SubtreeArray children = array_new();
    Subtree parent = ts_subtree_new_error_node(&children, false, self->language);
    ts_stack_push(self->stack, version, parent, false, 1);
    ts_parser__accept(self, version, lookahead);
    return;
  }

  // If strategy 1 succeeded, a new stack version will have been created which is able to handle
  // the current lookahead token. Now, in addition, try strategy 2 described above: skip the
  // current lookahead token by wrapping it in an ERROR node.

  // Don't pursue this additional strategy if there are already too many stack versions.
  if (did_recover && ts_stack_version_count(self->stack) > MAX_VERSION_COUNT) {
    ts_stack_halt(self->stack, version);
    ts_subtree_release(&self->tree_pool, lookahead);
    return;
  }

  if (
    did_recover &&
    ts_subtree_has_external_scanner_state_change(lookahead)
  ) {
    ts_stack_halt(self->stack, version);
    ts_subtree_release(&self->tree_pool, lookahead);
    return;
  }

  // Do not recover if the result would clearly be worse than some existing stack version.
  unsigned new_cost =
    current_error_cost + ERROR_COST_PER_SKIPPED_TREE +
    ts_subtree_total_bytes(lookahead) * ERROR_COST_PER_SKIPPED_CHAR +
    ts_subtree_total_size(lookahead).extent.row * ERROR_COST_PER_SKIPPED_LINE;
  if (ts_parser__better_version_exists(self, version, false, new_cost)) {
    ts_stack_halt(self->stack, version);
    ts_subtree_release(&self->tree_pool, lookahead);
    return;
  }

  // If the current lookahead token is an extra token, mark it as extra. This means it won't
  // be counted in error cost calculations.
  unsigned n;
  const TSParseAction *actions = ts_language_actions(self->language, 1, ts_subtree_symbol(lookahead), &n);
  if (n > 0 && actions[n - 1].type == TSParseActionTypeShift && actions[n - 1].shift.extra) {
    MutableSubtree mutable_lookahead = ts_subtree_make_mut(&self->tree_pool, lookahead);
    ts_subtree_set_extra(&mutable_lookahead, true);
    lookahead = ts_subtree_from_mut(mutable_lookahead);
  }

  // Wrap the lookahead token in an ERROR.
  LOG("skip_token symbol:%s", TREE_NAME(lookahead));
  SubtreeArray children = array_new();
  array_reserve(&children, 1);
  array_push(&children, lookahead);
  MutableSubtree error_repeat = ts_subtree_new_node(
    ts_builtin_sym_error_repeat,
    &children,
    0,
    self->language
  );

  // If other tokens have already been skipped, so there is already an ERROR at the top of the
  // stack, then pop that ERROR off the stack and wrap the two ERRORs together into one larger
  // ERROR.
  if (node_count_since_error > 0) {
    StackSliceArray pop = ts_stack_pop_count(self->stack, version, 1);

    // TODO: Figure out how to make this condition occur.
    // See https://github.com/atom/atom/issues/18450#issuecomment-439579778
    // If multiple stack versions have merged at this point, just pick one of the errors
    // arbitrarily and discard the rest.
    if (pop.size > 1) {
      for (unsigned i = 1; i < pop.size; i++) {
        ts_subtree_array_delete(&self->tree_pool, &array_get(&pop, i)->subtrees);
      }
      while (ts_stack_version_count(self->stack) > array_get(&pop, 0)->version + 1) {
        ts_stack_remove_version(self->stack, array_get(&pop, 0)->version + 1);
      }
    }

    ts_stack_renumber_version(self->stack, array_get(&pop, 0)->version, version);
    array_push(&array_get(&pop, 0)->subtrees, ts_subtree_from_mut(error_repeat));
    error_repeat = ts_subtree_new_node(
      ts_builtin_sym_error_repeat,
      &array_get(&pop, 0)->subtrees,
      0,
      self->language
    );
  }

  // Push the new ERROR onto the stack.
  ts_stack_push(self->stack, version, ts_subtree_from_mut(error_repeat), false, ERROR_STATE);
  if (ts_subtree_has_external_tokens(lookahead)) {
    ts_stack_set_last_external_token(
      self->stack, version, ts_subtree_last_external_token(lookahead)
    );
  }

  bool has_error = true;
  for (unsigned i = 0; i < ts_stack_version_count(self->stack); i++) {
    ErrorStatus status = ts_parser__version_status(self, i);
    if (!status.is_in_error) {
      has_error = false;
      break;
    }
  }
  self->has_error = has_error;
}

// [custom] ts_parser__condense_stack의 호출로 에러 복구를 준비하는 함수
// 분기 1: v-shift 시도
// 분기 2: ts_parser__recover
static void ts_parser__handle_error(
  TSParser *self,
  StackVersion version,
  Subtree lookahead
) {
  // --------------------------- 데이터 저장 ---------------------------------
  TSStateId state_at_error = ts_stack_state(self->stack, version);
  Length error_pos = length_add(ts_stack_position(self->stack, version), ts_subtree_padding(lookahead));
  
  TSLoggedAction recovery_action_log = (TSLoggedAction) {
    .type = TSParseActionTypeRecover,
    .start_point = error_pos.extent,       // 에러가 발생한 정확한 좌표
    .next_state = state_at_error,          // 에러 당시의 파서 상태
    .symbol = ts_subtree_symbol(lookahead) // 문법에 맞지 않아 에러를 유발한 토큰
  };
  array_push(&self->logged_actions, recovery_action_log);
  // -----------------------------------------------------------------
  uint32_t previous_version_count = ts_stack_version_count(self->stack);

  // lookahead를 무시하고, 현재 상태에서 가능한 모든 reduce를 실행해본다
  // 상위 상태에서 lookahead가 유효할 수도 있기 때문
  // Perform any reductions that can happen in this state, regardless of the lookahead. After
  // skipping one or more invalid tokens, the parser might find a token that would have allowed
  // a reduction to take place.
  ts_parser__do_all_potential_reductions(self, version, 0);

  // previous_version_count(handle_error 진입 시점)와 
  // version_count(potential reductions 후)의 차이가 새로 만들어진 버전 수
  uint32_t version_count = ts_stack_version_count(self->stack);
  Length position = ts_stack_position(self->stack, version);

  // Push a discontinuity onto the stack. Merge all of the stack versions that
  // were created in the previous step.
  bool did_insert_missing_token = false;
  for (StackVersion v = version; v < version_count;) {

    // missing token 삽입 시도
    if (!did_insert_missing_token) {
      TSStateId state = ts_stack_state(self->stack, v);

      // 원본과 reduce로 만들어진 모든 버전 순회
      for (
        TSSymbol missing_symbol = 1;
        missing_symbol < (uint16_t)self->language->token_count;
        missing_symbol++
      ) {
        TSStateId state_after_missing_symbol = ts_language_next_state(
          self->language, state, missing_symbol
        );
        // state_after_missing == 0 이면 invalid 전이 -> skip
        // state_after_missing == state 이면 상태 변화 없음 -> skip
        if (state_after_missing_symbol == 0 || state_after_missing_symbol == state) {
          continue;
        }

        // 가상 토큰을 하나 넣은 뒤의 상태에서 lookahead로 reduce가 가능한가?
        if (ts_language_has_reduce_action(
          self->language,
          state_after_missing_symbol,
          ts_subtree_leaf_symbol(lookahead)
        )) {
          // In case the parser is currently outside of any included range, the lexer will
          // snap to the beginning of the next included range. The missing token's padding
          // must be assigned to position it within the next included range.
          ts_lexer_reset(&self->lexer, position);
          ts_lexer_mark_end(&self->lexer);
          Length padding = length_sub(self->lexer.token_end_position, position);
          uint32_t lookahead_bytes = ts_subtree_total_bytes(lookahead) + ts_subtree_lookahead_bytes(lookahead);

          // 현재 버전 복사해서 새 버전 만듦
          StackVersion version_with_missing_tree = ts_stack_copy_version(self->stack, v);
          
          // 가상 토큰 노드 생성
          Subtree missing_tree = ts_subtree_new_missing_leaf(
            &self->tree_pool, missing_symbol,
            padding, lookahead_bytes,
            self->language
          );

          // 복사된 버전에 가상 토큰 push, state_after_missing_symbol 상태로 전이
          ts_stack_push(
            self->stack, version_with_missing_tree,
            missing_tree, false,
            state_after_missing_symbol
          );
          // --------------------------- 데이터 저장 ---------------------------------
          // 가짜 토큰(Missing Node)을 통해 이동한 상태(Virtual Shift)를 기록
          TSLoggedAction virtual_shift_log = (TSLoggedAction) {
            .type = TSParseActionTypeShift,
            .start_point = position.extent, // 가짜 토큰의 위치
            .current_state = state,
            .next_state = state_after_missing_symbol,
            .symbol = missing_symbol,       // 가짜 토큰 심볼
            .lexeme = "virtual",
            .extra = false,
            .is_virtual = true              // 가짜임을 표시
          };
          array_push(&self->logged_actions, virtual_shift_log);
          // -----------------------------------------------------------------
          
          // 가상 토큰 삽입 후, lookahead를 보고 reduce 시도
          if (ts_parser__do_all_potential_reductions(
            self, version_with_missing_tree,
            ts_subtree_leaf_symbol(lookahead)
          )) {
            LOG(
              "recover_with_missing symbol:%s, state:%u",
              SYM_NAME(missing_symbol),
              ts_stack_state(self->stack, version_with_missing_tree)
            );
            did_insert_missing_token = true;
            break;
          }
        }
      }
    }
    // 가상 토큰 삽입 여부와 관계없이,
    // 원래의 스택 버전은 ERROR_STATE(상태 0)로 강제 밀어 넣음
    ts_stack_push(self->stack, v, NULL_SUBTREE, false, ERROR_STATE);

    // 현재 버전과 redue로 새로 생긴 결과들만 순회
    v = (v == version) ? previous_version_count : v + 1;
  }

  // reduce로 생긴 버전들 병합
  for (unsigned i = previous_version_count; i < version_count; i++) {
    bool did_merge = ts_stack_merge(self->stack, version, previous_version_count);
    ts_assert(did_merge);
  }

  ts_stack_record_summary(self->stack, version, MAX_SUMMARY_DEPTH);

  // (증분 파싱)
  // Begin recovery with the current lookahead node, rather than waiting for the
  // next turn of the parse loop. This ensures that the tree accounts for the
  // current lookahead token's "lookahead bytes" value, which describes how far
  // the lexer needed to look ahead beyond the content of the token in order to
  // recognize it.
  if (ts_subtree_child_count(lookahead) > 0) {
    ts_parser__breakdown_lookahead(self, &lookahead, ERROR_STATE, &self->reusable_node);
  }

  // ERROR_STATE로 진입한 스택을 가지고 바로 복구 시도
  // ERROR_STATE 없이 가상 토큰이 push된 버전들은 남아있음
  ts_parser__recover(self, version, lookahead);

  LOG_STACK();
}

static bool ts_parser__check_progress(TSParser *self, Subtree *lookahead, const uint32_t *position, unsigned operations) {
  self->operation_count += operations;
  if (self->operation_count >= OP_COUNT_PER_PARSER_TIMEOUT_CHECK) {
    self->operation_count = 0;
  }
  if (position != NULL) {
    self->parse_state.current_byte_offset = *position;
    self->parse_state.has_error = self->has_error;
  }
  if (
    self->operation_count == 0 &&
    (
      // TODO(amaanq): remove cancellation flag & clock checks before 0.26
      (self->cancellation_flag && atomic_load(self->cancellation_flag)) ||
      (!clock_is_null(self->end_clock) && clock_is_gt(clock_now(), self->end_clock)) ||
      (self->parse_options.progress_callback && self->parse_options.progress_callback(&self->parse_state))
    )
  ) {
    if (lookahead && lookahead->ptr) {
      ts_subtree_release(&self->tree_pool, *lookahead);
    }
    return false;
  }
  return true;
}

// [custom] 파싱 루프 함수
// 현재 상태(state)와 입력 토큰(lookahead)을 보고 다음 행동(Action)을 결정
static bool ts_parser__advance(
  TSParser *self,
  StackVersion version,
  bool allow_node_reuse
) {
  // 1. 스택에서 현재 문맥 읽기
  // 현재 문맥: 
  //    스택 top에서 현재 버전의 state (ID), 
  //    position (바이트 위치), 
  //    외부 스캐너가 마지막으로 반환한 토큰 (external scanner 상태 복원용)
  TSStateId state = ts_stack_state(self->stack, version);
  uint32_t position = ts_stack_position(self->stack, version).bytes;
  Subtree last_external_token = ts_stack_last_external_token(self->stack, version);

  // 재사용 여부, lookahead 토큰, table_entry(파싱 테이블에서 꺼낸 액션 목록) 초기화
  bool did_reuse = true;
  Subtree lookahead = NULL_SUBTREE;
  TableEntry table_entry = {.action_count = 0};

  // 2. 토큰 확보 (재사용 노드 시도)
  // 렉서 실행을 건너뛰고 old_tree에서 토큰을 꺼내 씀
  // If possible, reuse a node from the previous syntax tree.
  if (allow_node_reuse) {
      // allow_node_reuse = true  조건:
      //  1) old_tree가 존재 (증분 파싱)
      //  2) version_count == 1 (GLR 분기 없음, 단일 경로)
    lookahead = ts_parser__reuse_node(
      self, version, &state, position, last_external_token, &table_entry
    );
  }

  // 2. 토큰 확보 (캐시된 토큰 시도)
  // GLR에서 동일 position을 여러 version이 처리할 때 캐시 적중
  // 렉서 실행을 건너뛰고 재사용
  // If no node from the previous syntax tree could be reused, then try to
  // reuse the token previously returned by the lexer.
  if (!lookahead.ptr) {
    did_reuse = false;
    lookahead = ts_parser__get_cached_token(
      self, state, position, last_external_token, &table_entry
    );
  }

  bool needs_lex = !lookahead.ptr;
  for (;;) {
    // 3. Lexing (새로운 토큰 읽기)
    // Otherwise, re-run the lexer.
    if (needs_lex) {
      needs_lex = false;
      lookahead = ts_parser__lex(self, version, state);  // Lexer 실행
      if (self->has_scanner_error) return false;

      // 토큰이 발견되면
      if (lookahead.ptr) {
        ts_parser__set_cached_token(self, position, last_external_token, lookahead);
        // 현재 상태(state)에서 이 토큰(lookahead)을 만났을 때의 모든 후보 액션을
        // 파싱 테이블에서 찾아 table_entry에 저장
        ts_language_table_entry(self->language, state, ts_subtree_symbol(lookahead), &table_entry);
      }

      // When parsing a non-terminal extra, a null lookahead indicates the
      // end of the rule. The reduction is stored in the EOF table entry.
      // After the reduction, the lexer needs to be run again.
      else {
        // EOF 심볼로 액션을 조회
        ts_language_table_entry(self->language, state, ts_builtin_sym_end, &table_entry);
      }
    }

    // 인터럽트 체크
    // If a cancellation flag, timeout, or progress callback was provided, then check every
    // time a fixed number of parse actions has been processed.
    if (!ts_parser__check_progress(self, &lookahead, &position, 1)) {
      return false;
    }

    // 4. 액션 실행 루프 (핵심 로직)
    // table_entry에 담긴 액션들을 순서대로 처리
    // Process each parse action for the current lookahead token in
    // the current state. If there are multiple actions, then this is
    // an ambiguous state. REDUCE actions always create a new stack
    // version, whereas SHIFT actions update the existing stack version
    // and terminate this loop.
    bool did_reduce = false;
    StackVersion last_reduction_version = STACK_VERSION_NONE;
    for (uint32_t i = 0; i < table_entry.action_count; i++) {
      TSParseAction action = table_entry.actions[i];

      switch (action.type) {
        case TSParseActionTypeShift: {
          if (action.shift.repetition) break;
          TSStateId next_state;
          if (action.shift.extra) {
            next_state = state;
            LOG("shift_extra");
          } else {
            next_state = action.shift.state;
            LOG("shift state:%u", next_state);
          }

          // 예전에 만들어둔 트리의 덩어리(Node)를 재활용하려고 가져온 경우 (증분 파싱)
          if (ts_subtree_child_count(lookahead) > 0) {
            ts_parser__breakdown_lookahead(self, &lookahead, state, &self->reusable_node);
            next_state = ts_language_next_state(self->language, state, ts_subtree_symbol(lookahead));
          } 

          // --------------------------- 데이터 저장 ---------------------------------
          // lookahead 파악
          TSSymbol tok_sym = ts_subtree_leaf_symbol(lookahead);

          // 소스 코드에서 직접 lexeme 복사
          uint32_t start_byte = self->lexer.token_start_position.bytes;
          uint32_t end_byte = self->lexer.token_end_position.bytes;
          uint32_t lexeme_len = end_byte - start_byte;

          char *lexeme_copy = NULL;
          if (lexeme_len > 0) {
            uint32_t bytes_read = 0;
            const char *source_chunk = self->lexer.input.read (
              self->lexer.input.payload,
              start_byte,
              self->lexer.token_start_position.extent,
              &bytes_read
            );
            if (source_chunk && bytes_read >= lexeme_len) {
              lexeme_copy = (char *)ts_malloc(lexeme_len + 1);
              memcpy(lexeme_copy, source_chunk, lexeme_len);
              lexeme_copy[lexeme_len] = '\0';
            }
          }

          // 가공된 로그 기록
          TSLoggedAction la_shift = (TSLoggedAction) {
            .type = TSParseActionTypeShift,
            .current_state = state,
            .next_state = next_state,
            .symbol = tok_sym,
            .lexeme = lexeme_copy,
            .child_count = 0,
            .is_virtual = false,
            .extra = action.shift.extra,
            .start_point = self->lexer.token_start_position.extent
          };
          array_push(&self->logged_actions, la_shift);
          // -----------------------------------------------------------------

          // 스택에 lookahead push
          // 현재 version의 state -> next_state로 전환
          ts_parser__shift(self, version, next_state, lookahead, action.shift.extra);
          
          // 재사용 노드를 소비했으면
          // 재사용 노드 커서를 다음 노드로 이동
          if (did_reuse) reusable_node_advance(&self->reusable_node);
          return true;
        }

        case TSParseActionTypeReduce: {
          // 상황 판단
          bool is_fragile = table_entry.action_count > 1;           // 모호함
          bool end_of_non_terminal_extra = lookahead.ptr == NULL;   // Null이면 EOF
          // LOG("reduce sym:%s, child_count:%u", SYM_NAME(action.reduce.symbol), action.reduce.child_count);

          // ts_parser__reduce
          // 트리시터는 원본 프로세스(version)는 그대로 둔 채, 
          // 원본을 복제하여 Reduce 연산을 적용한 새로운 버전들을 heads 배열 끝에 추가(Push)

          // reduction_version : 이번 reduce 연산을 통해
          // heads 배열에서 새로 생긴 버전들의 시작 인덱스
          StackVersion reduction_version = ts_parser__reduce(
            self, version, action.reduce.symbol, action.reduce.child_count,
            action.reduce.dynamic_precedence, action.reduce.production_id,
            is_fragile, end_of_non_terminal_extra
          );

          // --------------------------- 데이터 저장 ---------------------------------
          // 가공된 로그 기록
          // 분기된 새 버전들
          if (reduction_version != STACK_VERSION_NONE) {
            uint32_t current_count = ts_stack_version_count(self->stack);
            for (StackVersion v = reduction_version; v < current_count; v++) {
              TSStateId goto_state_new = ts_stack_state(self->stack, v);
              LOG("reduce sym:%s, child_count:%u, goto:%u, version:%u", 
                  SYM_NAME(action.reduce.symbol), action.reduce.child_count, goto_state_new, v);

              TSLoggedAction la_red = (TSLoggedAction) {
                .type = TSParseActionTypeReduce,
                .current_state = state,
                .next_state = goto_state_new,
                .symbol = action.reduce.symbol,         // LHS 비단말
                .child_count = action.reduce.child_count,
                .is_virtual = false,
                .extra = false
              };
              array_push(&self->logged_actions, la_red);
            }
          }
          // -----------------------------------------------------------------
          did_reduce = true;
          if (reduction_version != STACK_VERSION_NONE) {
            last_reduction_version = reduction_version;
          }
          break;
        }

        case TSParseActionTypeAccept: {
          LOG("accept");
          // --------------------------- 데이터 저장 ---------------------------------
          // 가공된 로그 기록
          TSLoggedAction la_acc = (TSLoggedAction) {
            .type = TSParseActionTypeAccept,
            .current_state = state,
            .symbol = ts_builtin_sym_end,
            .child_count = 0,
            .is_virtual = false,
            .extra = false
          };
          array_push(&self->logged_actions, la_acc);
          // -----------------------------------------------------------------

          ts_parser__accept(self, version, lookahead);
          return true;
        }

        case TSParseActionTypeRecover: {
          // 파싱 테이블을 조회했더니, 액션 목록에 RECVOER가 존재. 명시적 에러 처리
            // grammar.js에서 직접 에러 처리를 정의했거나
            // 파서 생성기가 테이블에 액션을 정의한 경우

          // --------------------------- 데이터 저장 ---------------------------------
          // 에러 복구 진입 시점에 바로 기록
          // 현재 상태: 에러를 감지한 시점
          TSStateId state_at_recover = ts_stack_state(self->stack, version);
          // 현재 위치: 에러 발생 위치
          Length error_pos = length_add(ts_stack_position(self->stack, version),ts_subtree_padding(lookahead));
          TSLoggedAction la_recover = (TSLoggedAction) {
            .type = TSParseActionTypeRecover,
            .current_state = state_at_recover,
            .symbol = ts_subtree_symbol(lookahead),
            .start_point = error_pos.extent
          };
          array_push(&self->logged_actions, la_recover);
          // -----------------------------------------------------------------
          if (ts_subtree_child_count(lookahead) > 0) {
            ts_parser__breakdown_lookahead(self, &lookahead, ERROR_STATE, &self->reusable_node);
          }

          ts_parser__recover(self, version, lookahead);
          if (did_reuse) reusable_node_advance(&self->reusable_node);
          return true;
        }
      }
    }
    // case 1: reduce 액션만 존재한 경우
    // case 2: table_entry.action_count == 0 (파싱 테이블에 아무 액션 없음)

    // (case 1) reduce 성공 후 상태 업데이트
    // If a reduction was performed, then replace the current stack version
    // with one of the stack versions created by a reduction, and continue
    // processing this version of the stack with the same lookahead symbol.
    if (last_reduction_version != STACK_VERSION_NONE) {
      ts_stack_renumber_version(self->stack, last_reduction_version, version);
      LOG_STACK();
      state = ts_stack_state(self->stack, version);

      // At the end of a non-terminal extra rule, the lexer will return a
      // null subtree, because the parser needs to perform a fixed reduction
      // regardless of the lookahead node. After performing that reduction,
      // (and completing the non-terminal extra rule) run the lexer again based
      // on the current parse state.
      if (!lookahead.ptr) {
        needs_lex = true;
      } else {
        ts_language_table_entry(
          self->language,
          state,
          ts_subtree_leaf_symbol(lookahead),
          &table_entry
        );
      }

      continue;
    }

    // (case 1) reduce 결과물이 기존 파싱 경로와 동일한 경우 병합
    // A reduction was performed, but was merged into an existing stack version.
    // This version can be discarded.
    if (did_reduce) {
      if (lookahead.ptr) {
        ts_subtree_release(&self->tree_pool, lookahead);
      }
      ts_stack_halt(self->stack, version);
      return true;
    }

    // (case 2) 키워드를 일반 식별자로 처리 시도
    // If the current lookahead token is a keyword that is not valid, but the
    // default word token *is* valid, then treat the lookahead token as the word
    // token instead.
    if (
      ts_subtree_is_keyword(lookahead) &&
      ts_subtree_symbol(lookahead) != self->language->keyword_capture_token &&
      !ts_language_is_reserved_word(self->language, state, ts_subtree_symbol(lookahead))
    ) {
      ts_language_table_entry(
        self->language,
        state,
        self->language->keyword_capture_token,
        &table_entry
      );
      if (table_entry.action_count > 0) {
        LOG(
          "switch from_keyword:%s, to_word_token:%s",
          TREE_NAME(lookahead),
          SYM_NAME(self->language->keyword_capture_token)
        );

        MutableSubtree mutable_lookahead = ts_subtree_make_mut(&self->tree_pool, lookahead);
        ts_subtree_set_symbol(&mutable_lookahead, self->language->keyword_capture_token, self->language);
        lookahead = ts_subtree_from_mut(mutable_lookahead);
        continue;
      }
    }

    // (case 2) 증분 파싱의 경우 재사용 노드 분해
    // If the current lookahead token is not valid and the previous subtree on
    // the stack was reused from an old tree, then it wasn't actually valid to
    // reuse that previous subtree. Remove it from the stack, and in its place,
    // push each of its children. Then try again to process the current lookahead.
    if (ts_parser__breakdown_top_of_stack(self, version)) {
      state = ts_stack_state(self->stack, version);
      ts_subtree_release(&self->tree_pool, lookahead);
      needs_lex = true;
      continue;
    }

    // (case 2) 모든 처리가 통하지 않는 진짜 구문 오류
    // 우선 해당 스택 버전을 멈춤, 이후 다른 버전들도 모두 멈추면 그때 에러 복구 시작
    // Otherwise, there is definitely an error in this version of the parse stack.
    // Mark this version as paused and continue processing any other stack
    // versions that exist. If some other version advances successfully, then
    // this version can simply be removed. But if all versions end up paused,
    // then error recovery is needed.
    LOG("detect_error lookahead:%s", TREE_NAME(lookahead));
    ts_stack_pause(self->stack, version, lookahead);
    return true;
  }
}

// [custom]
static bool ts_parser__advance_for_conversion(
  TSParser *self,
  StackVersion version,
  bool allow_node_reuse,
  uint32_t target_length
) {
  // 1. 스택에서 현재 문맥 읽기
  // 현재 문맥:
  //    스택 top에서 현재 버전의 state (ID),
  //    position (바이트 위치),
  //    외부 스캐너가 마지막으로 반환한 토큰 (external scanner 상태 복원용)
  TSStateId state = ts_stack_state(self->stack, version);
  uint32_t position = ts_stack_position(self->stack, version).bytes;
  Subtree last_external_token = ts_stack_last_external_token(self->stack, version);
  fprintf(stderr, "[ADV] state=%u pos=%u target=%u\n", state, position, target_length);

  // 재사용 여부, lookahead 토큰, table_entry(파싱 테이블에서 꺼낸 액션 목록) 초기화
  bool did_reuse = true;
  Subtree lookahead = NULL_SUBTREE;
  TableEntry table_entry = {.action_count = 0};

  // 2. 토큰 확보 (재사용 노드 시도)
  // 렉서 실행을 건너뛰고 old_tree에서 토큰을 꺼내 씀
  // If possible, reuse a node from the previous syntax tree.
  if (allow_node_reuse) {
      // allow_node_reuse = true  조건:
      //  1) old_tree가 존재 (증분 파싱)
      //  2) version_count == 1 (GLR 분기 없음, 단일 경로)
    lookahead = ts_parser__reuse_node(
      self, version, &state, position, last_external_token, &table_entry
    );
  }

  // 2. 토큰 확보 (캐시된 토큰 시도)
  // GLR에서 동일 position을 여러 version이 처리할 때 캐시 적중
  // 렉서 실행을 건너뛰고 재사용
  // If no node from the previous syntax tree could be reused, then try to
  // reuse the token previously returned by the lexer.
  if (!lookahead.ptr) {
    did_reuse = false;
    lookahead = ts_parser__get_cached_token(
      self, state, position, last_external_token, &table_entry
    );
  }

  bool needs_lex = !lookahead.ptr;
  for (;;) {
    // 3. Lexing (새로운 토큰 읽기)
    // Otherwise, re-run the lexer.
    if (needs_lex) {
      needs_lex = false;
      self->ext_scan_fail_max_position = 0;  // 초기화
      lookahead = ts_parser__lex(self, version, state);  // Lexer 실행
      if (self->has_scanner_error) return false;

      // 외부 스캐너가 커서 위치까지 읽었지만 실패 → 내부 렉서 결과 무시 → freeze
      // 예) state:1830에서 `_string_content` 렉싱 시도 → 잘린 소스에서 """ 없음 →
      //     외부 스캐너가 pos=210(커서)까지 읽고 실패 → 내부 렉서가 identifier 반환
      //     → state:1830은 identifier를 처리할 수 없어 에러 복구로 가야 하는 상황
      //     → conversion에서는 에러 복구 대신 state:1830을 freeze
      //
      // 단, 외부 스캐너가 context 판단을 위해 target 너머를 read-ahead한 후 실패하더라도
      // 내부 렉서 토큰이 현재 state에서 유효하면 계속 진행해야 한다.
      // 예) Haskell state:36이 `IO ()\n` 전체를 읽고 실패했지만
      //     내부 렉서의 name(IO)는 state:1462에서 유효한 SHIFT → 계속
      if (lookahead.ptr
          && !ts_subtree_has_external_tokens(lookahead)
          && self->ext_scan_fail_max_position >= target_length) {
        TableEntry validity = {.action_count = 0};
        ts_language_table_entry(self->language, state,
                                ts_subtree_symbol(lookahead), &validity);
        if (validity.action_count == 0) {
          return false;  // 내부 토큰도 유효하지 않음 → 진짜 cut source
        }
        // 유효하면 계속 (외부 스캐너의 context read-ahead였음)
      }

      if (position >= target_length) {
        // [커서 위치 도달] 렉서 결과에 따라 엄격히 분기:
        //
        // ① NULL → non-terminal extra reduce가 발생해 상태가 바뀔 수 있으므로 중단.
        //      예) `def foo(` 커서 직후: NULL 반환 → non-terminal extra reduce →
        //         올바른 상태가 이미 사라진 뒤 sym:end 감지.
        // ② sym:end / sym:error → EOF. 중단.
        // ③ 크기 > 0인 실제 토큰 → 커서 너머의 토큰. 중단.
        // ④ 크기 == 0, 해당 state에서 액션 없음 → 유효하지 않은 가상 토큰
        //      예) Python DEDENT: 해당 state에서 REJECT → 에러 복구 → 올바른 상태 폐기.
        //         중단해서 현재 상태(예: state:601)를 캡처.
        // ⑤ 크기 == 0, 해당 state에서 SHIFT 가능 → 유효한 외부 토큰
        //      예) Haskell _cmd_texp_start: SHIFT → state:8876 →
        //         다음 호출에서 state:8876을 캡처, 시뮬레이션이 state:7779 도출.
        if (!lookahead.ptr) return false;  // ①
        TSSymbol sym = ts_subtree_symbol(lookahead);
        if (sym == ts_builtin_sym_end) return false;   // ②
        if (sym == ts_builtin_sym_error) return false; // ②
        if (ts_subtree_total_size(lookahead).bytes > 0) return false;  // ③
        // ④ vs ⑤: 0-size 토큰의 유효성 검사
        TableEntry ze = {.action_count = 0};
        ts_language_table_entry(self->language, state, sym, &ze);
        if (ze.action_count == 0) return false;  // ④
        // ⑤: 유효한 SHIFT → 삽입 전/후 state 모두 캡처
        //   - 복사본을 halted로 고정: 삽입 전 state에서 시뮬레이션
        //   - 원본은 SHIFT 진행: 다음 호출에서 삽입 후 state 캡처
        //   - phase_3_conversion이 전체 버전(halted 포함)을 순회하며 합집합
        StackVersion pre_shift_copy = ts_stack_copy_version(self->stack, version);
        if (pre_shift_copy != STACK_VERSION_NONE) {
          ts_stack_halt(self->stack, pre_shift_copy);
        }
        ts_parser__set_cached_token(self, position, last_external_token, lookahead);
        ts_language_table_entry(self->language, state, sym, &table_entry);
      } else {
        // [커서 미도달] 기존 post-lex 체크 유지
        // sym:end 또는 커서 이후에서 sym:error → 중단
        if ((lookahead.ptr && ts_subtree_symbol(lookahead) == ts_builtin_sym_end)
            || ((lookahead.ptr && ts_subtree_symbol(lookahead) == ts_builtin_sym_error)
                && self->lexer.current_position.bytes >= target_length)) {
          return false;
        }

        // NULL + 렉서가 커서까지 전진: 커서 도달로 처리
        //   - non-terminal extra reduce(정상): NULL이지만 current_position < target_length
        //   - 커서 직전 토큰 불완전(예: Haskell `main ` 뒤 `::` 미도달):
        //       공백을 스킵하면 current_position == target_length에 도달하지만
        //       다음 문자(`::`)를 읽지 못해 NULL 반환
        //       → non-terminal extra reduce가 발동되면 state:2263이 사라짐
        if (!lookahead.ptr && self->lexer.current_position.bytes >= target_length) {
          return false;
        }

        // 커서 위치에서 0-size 가상 토큰: 유효하지 않으면 중단 (예: Python DEDENT)
        if (self->lexer.current_position.bytes >= target_length
            && lookahead.ptr
            && ts_subtree_total_size(lookahead).bytes == 0) {
          TableEntry zero_size_entry = {.action_count = 0};
          ts_language_table_entry(self->language, state, ts_subtree_symbol(lookahead), &zero_size_entry);
          if (zero_size_entry.action_count == 0) {
            return false;
          }
          // ⑤ (else-branch): 유효한 0-size SHIFT가 렉서를 커서 경계까지 전진시킨 경우
          //   position < target_length 이지만 렉서가 target_length까지 읽어버림
          //   → SHIFT를 진행시킨다. 0-size이므로 position은 그대로.
          //   → 다음 advance에서 계속 파싱하다가 실제 position >= target_length
          //      분기에 진입하여 올바르게 캡처됨 (예: Haskell _cmd_texp_start)
          //   → 단, SHIFT 전 상태(현재 state)도 캡처해야 한다.
          //     예) Python state:92에서 _indent SHIFT → state:752 →
          //         다음 advance에서 실패 → state:752만 캡처됨, state:92 누락.
          //     → 복사본을 halted로 고정하여 삽입 전 state를 시뮬레이션에 포함.
          {
            StackVersion pre_shift_copy = ts_stack_copy_version(self->stack, version);
            if (pre_shift_copy != STACK_VERSION_NONE) {
              ts_stack_halt(self->stack, pre_shift_copy);
            }
          }
          // fall-through
        }

        // ③ (else-branch): 크기>0 외부 토큰이 커서 경계에 걸치는 경우
        //   → token_end > target: 커서를 실제로 초과 → 현재 state 보존 후 중단
        //   → token_end == target: ⑤ 방식으로 전/후 상태 모두 탐색 (halted copy + fall-through)
        //   → token_end < target: read-ahead가 target을 넘었을 뿐, 토큰 자체는 경계 안 → 진행
        //   내부 스캐너 토큰은 항상 fall-through (SHIFT 허용, 이후 ⑤에서 state 캡처)
        //   예) Haskell sym=117(space, 외부, token_end>target): return false → state:2263 캡처
        //       Haskell _cmd_layout_start (외부, token_end==target): halted copy + SHIFT → state:2 캡처
        //       Haskell `(` (내부, size=2): 진행 → SHIFT → _cmd_texp_start ⑤ → state:7779
        if (lookahead.ptr
            && ts_subtree_total_size(lookahead).bytes > 0
            && ts_subtree_has_external_tokens(lookahead)) {
          uint32_t token_end = position + ts_subtree_total_size(lookahead).bytes;
          if (token_end > target_length) {
            return false;  // 실제 경계 초과
          } else if (token_end == target_length) {
            // ⑤: 삽입 전/후 상태 모두 탐색
            StackVersion copy = ts_stack_copy_version(self->stack, version);
            if (copy != STACK_VERSION_NONE) ts_stack_halt(self->stack, copy);
            // 현재 state에서 이 token에 유효한 action이 없으면
            // fall-through하면 ts_stack_pause → 에러 리커버리로 오염되므로 즉시 freeze
            TableEntry validity_check = {.action_count = 0};
            ts_language_table_entry(self->language, state,
                                    ts_subtree_symbol(lookahead), &validity_check);
            if (validity_check.action_count == 0) return false;
            // fall-through → SHIFT 진행
          }
          // token_end < target: read-ahead 무관, 계속 진행
        }

        // 토큰이 발견되면
        if (lookahead.ptr) {
          ts_parser__set_cached_token(self, position, last_external_token, lookahead);
          ts_language_table_entry(self->language, state, ts_subtree_symbol(lookahead), &table_entry);
        }
        // When parsing a non-terminal extra, a null lookahead indicates the
        // end of the rule. The reduction is stored in the EOF table entry.
        else {
          ts_language_table_entry(self->language, state, ts_builtin_sym_end, &table_entry);
        }
      }
    }

    // ③ 캐시 경로 경계 체크:
    // 캐시에서 가져온 토큰(needs_lex=false 경로)은 위의 if (needs_lex) 블록을 건너뛰므로
    // 커서 경계 체크가 적용되지 않는다. 여기서 동일한 조건을 적용한다.
    //
    // 경우 A: position이 이미 target에 도달(==) 또는 초과(>) → size>0 토큰이면 중단
    //   (lexed path의 ③과 동일 조건)
    //   예) Python state:1830(pos==target)에서 cached string_end(size:3)
    //
    // 경우 B: position < target이지만 외부 토큰이 경계를 가로지르는 경우
    //   → token_end > target: 실제 경계 초과 → 중단
    //   → token_end == target: ⑤ 방식으로 전/후 상태 모두 탐색 (halted copy + fall-through)
    //   (position < target이므로 lexed path에서는 else-branch ③이 담당했던 경우)
    if (lookahead.ptr && ts_subtree_total_size(lookahead).bytes > 0) {
      uint32_t sz = ts_subtree_total_size(lookahead).bytes;
      bool ext = ts_subtree_has_external_tokens(lookahead);
      fprintf(stderr, "[CACHE_CHK] state=%u pos=%u target=%u sym=%u sz=%u ext=%d\n",
              state, position, target_length, ts_subtree_symbol(lookahead), sz, ext);
      if (position >= target_length) {
        fprintf(stderr, "[CACHE_CHK] -> return false (A)\n");
        return false;  // 경우 A
      }
      if (ext) {
        uint32_t token_end = position + sz;
        if (token_end > target_length) {
          fprintf(stderr, "[CACHE_CHK] -> return false (B: token_end>target)\n");
          return false;  // 경우 B: 실제 경계 초과
        } else if (token_end == target_length) {
          fprintf(stderr, "[CACHE_CHK] -> halted copy (B: token_end==target)\n");
          // ⑤: 삽입 전/후 상태 모두 탐색
          StackVersion copy = ts_stack_copy_version(self->stack, version);
          if (copy != STACK_VERSION_NONE) ts_stack_halt(self->stack, copy);
          // 현재 state에서 이 token에 유효한 action이 없으면 즉시 freeze (에러 리커버리 방지)
          TableEntry validity_check2 = {.action_count = 0};
          ts_language_table_entry(self->language, state,
                                  ts_subtree_symbol(lookahead), &validity_check2);
          if (validity_check2.action_count == 0) return false;
          // fall-through → SHIFT 진행
        }
        // token_end < target: 계속 진행
      }
    }

    // 인터럽트 체크
    // If a cancellation flag, timeout, or progress callback was provided, then check every
    // time a fixed number of parse actions has been processed.
    if (!ts_parser__check_progress(self, &lookahead, &position, 1)) {
      return false;
    }

    // 4. 액션 실행 루프 (핵심 로직)
    // table_entry에 담긴 액션들을 순서대로 처리
    // Process each parse action for the current lookahead token in
    // the current state. If there are multiple actions, then this is
    // an ambiguous state. REDUCE actions always create a new stack
    // version, whereas SHIFT actions update the existing stack version
    // and terminate this loop.
    bool did_reduce = false;
    StackVersion last_reduction_version = STACK_VERSION_NONE;
    for (uint32_t i = 0; i < table_entry.action_count; i++) {
      TSParseAction action = table_entry.actions[i];

      switch (action.type) {
        case TSParseActionTypeShift: {
          if (action.shift.repetition) break;
          TSStateId next_state;
          if (action.shift.extra) {
            next_state = state;
            LOG("shift_extra");
          } else {
            next_state = action.shift.state;
            LOG("shift state:%u", next_state);
          }

          // 예전에 만들어둔 트리의 덩어리(Node)를 재활용하려고 가져온 경우 (증분 파싱)
          if (ts_subtree_child_count(lookahead) > 0) {
            ts_parser__breakdown_lookahead(self, &lookahead, state, &self->reusable_node);
            next_state = ts_language_next_state(self->language, state, ts_subtree_symbol(lookahead));
          } 

          // 스택에 lookahead push
          // 현재 version의 state -> next_state로 전환
          ts_parser__shift(self, version, next_state, lookahead, action.shift.extra);
          
          // 재사용 노드를 소비했으면
          // 재사용 노드 커서를 다음 노드로 이동
          if (did_reuse) reusable_node_advance(&self->reusable_node);
          return true;
        }

        case TSParseActionTypeReduce: {
          // 상황 판단
          bool is_fragile = table_entry.action_count > 1;           // 모호함
          bool end_of_non_terminal_extra = lookahead.ptr == NULL;   // Null이면 EOF
          // LOG("reduce sym:%s, child_count:%u", SYM_NAME(action.reduce.symbol), action.reduce.child_count);

          // ts_parser__reduce
          // 트리시터는 원본 프로세스(version)는 그대로 둔 채, 
          // 원본을 복제하여 Reduce 연산을 적용한 새로운 버전들을 heads 배열 끝에 추가(Push)

          // reduction_version : 이번 reduce 연산을 통해
          // heads 배열에서 새로 생긴 버전들의 시작 인덱스
          StackVersion reduction_version = ts_parser__reduce(
            self, version, action.reduce.symbol, action.reduce.child_count,
            action.reduce.dynamic_precedence, action.reduce.production_id,
            is_fragile, end_of_non_terminal_extra
          );

          did_reduce = true;
          if (reduction_version != STACK_VERSION_NONE) {
            last_reduction_version = reduction_version;
          }
          break;
        }

        case TSParseActionTypeAccept: {
          LOG("accept");
          ts_parser__accept(self, version, lookahead);
          return true;
        }

        case TSParseActionTypeRecover: {
          // 파싱 테이블을 조회했더니, 액션 목록에 RECVOER가 존재. 명시적 에러 처리
            // grammar.js에서 직접 에러 처리를 정의했거나
            // 파서 생성기가 테이블에 액션을 정의한 경우

          if (ts_subtree_child_count(lookahead) > 0) {
            ts_parser__breakdown_lookahead(self, &lookahead, ERROR_STATE, &self->reusable_node);
          }

          ts_parser__recover(self, version, lookahead);
          if (did_reuse) reusable_node_advance(&self->reusable_node);
          return true;
        }
      }
    }

    // 5. 뒷정리 및 재시도
    // If a reduction was performed, then replace the current stack version
    // with one of the stack versions created by a reduction, and continue
    // processing this version of the stack with the same lookahead symbol.
    if (last_reduction_version != STACK_VERSION_NONE) {
      ts_stack_renumber_version(self->stack, last_reduction_version, version);
      LOG_STACK();
      state = ts_stack_state(self->stack, version);

      // At the end of a non-terminal extra rule, the lexer will return a
      // null subtree, because the parser needs to perform a fixed reduction
      // regardless of the lookahead node. After performing that reduction,
      // (and completing the non-terminal extra rule) run the lexer again based
      // on the current parse state.
      if (!lookahead.ptr) {
        needs_lex = true;
      } else {
        ts_language_table_entry(
          self->language,
          state,
          ts_subtree_leaf_symbol(lookahead),
          &table_entry
        );
      }

      continue;
    }

    // A reduction was performed, but was merged into an existing stack version.
    // This version can be discarded.
    if (did_reduce) {
      if (lookahead.ptr) {
        ts_subtree_release(&self->tree_pool, lookahead);
      }
      ts_stack_halt(self->stack, version);
      return true;
    }

    // If the current lookahead token is a keyword that is not valid, but the
    // default word token *is* valid, then treat the lookahead token as the word
    // token instead.
    if (
      ts_subtree_is_keyword(lookahead) &&
      ts_subtree_symbol(lookahead) != self->language->keyword_capture_token &&
      !ts_language_is_reserved_word(self->language, state, ts_subtree_symbol(lookahead))
    ) {
      ts_language_table_entry(
        self->language,
        state,
        self->language->keyword_capture_token,
        &table_entry
      );
      if (table_entry.action_count > 0) {
        LOG(
          "switch from_keyword:%s, to_word_token:%s",
          TREE_NAME(lookahead),
          SYM_NAME(self->language->keyword_capture_token)
        );

        MutableSubtree mutable_lookahead = ts_subtree_make_mut(&self->tree_pool, lookahead);
        ts_subtree_set_symbol(&mutable_lookahead, self->language->keyword_capture_token, self->language);
        lookahead = ts_subtree_from_mut(mutable_lookahead);
        continue;
      }
    }

    // If the current lookahead token is not valid and the previous subtree on
    // the stack was reused from an old tree, then it wasn't actually valid to
    // reuse that previous subtree. Remove it from the stack, and in its place,
    // push each of its children. Then try again to process the current lookahead.
    if (ts_parser__breakdown_top_of_stack(self, version)) {
      state = ts_stack_state(self->stack, version);
      ts_subtree_release(&self->tree_pool, lookahead);
      needs_lex = true;
      continue;
    }

    // 파싱 테이블에 아무런 액션도 없는 경우
    // 해당 스택 버전을 멈춤 -> ts_parser_parse에서 ts_parser__condense_stack가 처리
    // Otherwise, there is definitely an error in this version of the parse stack.
    // Mark this version as paused and continue processing any other stack
    // versions that exist. If some other version advances successfully, then
    // this version can simply be removed. But if all versions end up paused,
    // then error recovery is needed.
    LOG("detect_error lookahead:%s", TREE_NAME(lookahead));
    ts_stack_pause(self->stack, version, lookahead);
    return true;
  }
}

// [info] 매 파싱 라운드 이후 살아있는 스택 버전들을 정리
// - 쓸모없는 버전 제거
// - 더 나은 버전 선택/병합/정렬
// - 에러 리커버리 트리거
static unsigned ts_parser__condense_stack(TSParser *self) {
  bool made_changes = false;
  unsigned min_error_cost = UINT_MAX;
  for (StackVersion i = 0; i < ts_stack_version_count(self->stack); i++) {
    // reduce 후 병합되어 더 이상 유효하지 않은 버전 제거
    // Prune any versions that have been marked for removal.
    if (ts_stack_is_halted(self->stack, i)) {
      ts_stack_remove_version(self->stack, i);
      i--;
      continue;
    }

    // min_error_cost 추적 (에러 없는 버전만)
    // Keep track of the minimum error cost of any stack version so
    // that it can be returned.
    ErrorStatus status_i = ts_parser__version_status(self, i);
    if (!status_i.is_in_error && status_i.cost < min_error_cost) {
      min_error_cost = status_i.cost;
    }

    // 살아있는 모든 스택 버전들을 두 개씩 짝지어 비교
    // 제거, 병합, 정렬
    // Examine each pair of stack versions, removing any versions that
    // are clearly worse than another version. Ensure that the versions
    // are ordered from most promising to least promising.
    for (StackVersion j = 0; j < i; j++) {
      ErrorStatus status_j = ts_parser__version_status(self, j);

      switch (ts_parser__compare_versions(self, status_j, status_i)) {
        case ErrorComparisonTakeLeft:
          made_changes = true;
          ts_stack_remove_version(self->stack, i);
          i--;
          j = i;
          break;

        // 비용이 비슷하거나(None) 
        // 한쪽을 약간 선호(PreferLeft/PreferRight)할 때 병합
        case ErrorComparisonPreferLeft:
        case ErrorComparisonNone:
          if (ts_stack_merge(self->stack, j, i)) {
            made_changes = true;
            i--;
            j = i;
          }
          break;

        case ErrorComparisonPreferRight:
          made_changes = true;
          if (ts_stack_merge(self->stack, j, i)) {
            i--;
            j = i;
          } else {
            ts_stack_swap_versions(self->stack, i, j);
          }
          break;

        case ErrorComparisonTakeRight:
          made_changes = true;
          ts_stack_remove_version(self->stack, j);
          i--;
          j--;
          break;
      }
    }
  } // 이 루프가 끝나면 배열은 비용이 낮은 버전이 앞쪽으로 정렬

  // 스택 개수가 시스템 제한 초과시, 맨 뒤쪽(가장 상태 안좋은 경로들)부터 제거
  // Enforce a hard upper bound on the number of stack versions by
  // discarding the least promising versions.
  while (ts_stack_version_count(self->stack) > MAX_VERSION_COUNT) {
    ts_stack_remove_version(self->stack, MAX_VERSION_COUNT);
    made_changes = true;
  }

  // 에러 리커버리 트리거
  // If the best-performing stack version is currently paused, or all
  // versions are paused, then resume the best paused version and begin
  // the error recovery process. Otherwise, remove the paused versions.
  if (ts_stack_version_count(self->stack) > 0) {
    bool has_unpaused_version = false;

    // 배열은 가장 상태가 좋은 순서로 정렬됨
    for (StackVersion i = 0, n = ts_stack_version_count(self->stack); i < n; i++) {
      // advance에서 멈춘 스택을 발견
      if (ts_stack_is_paused(self->stack, i)) {

        // 앞서 정상적인 스택이 단 하나도 없었다면
        // 즉, 모든 버전이 pause됐을 때
        if (!has_unpaused_version && self->accept_count < MAX_VERSION_COUNT) {
          LOG("resume version:%u", i);
          min_error_cost = ts_stack_error_cost(self->stack, i);

          // 스택을 깨우고 에러 처리 시작
          // 에러 상황에서 가능한 파싱 경로를 최대한 확장
          Subtree lookahead = ts_stack_resume(self->stack, i);
          ts_parser__handle_error(self, i, lookahead);

          // 복구를 시작했으므로 이제 유효한 경로로 취급
          has_unpaused_version = true;
        } else {
          // 정상 스택이 있거나, 더 나은 스택이 에러 복구에 들어간 상태면 
          // 이 paused 버전은 제거
          ts_stack_remove_version(self->stack, i);
          made_changes = true;
          i--;
          n--;
        }
      } else {
        has_unpaused_version = true;
      }
    }
  }

  if (made_changes) {
    LOG("condense");
    LOG_STACK();
  }

  return min_error_cost;
}

static bool ts_parser__balance_subtree(TSParser *self) {
  Subtree finished_tree = self->finished_tree;

  // If we haven't canceled balancing in progress before, then we want to clear the tree stack and
  // push the initial finished tree onto it. Otherwise, if we're resuming balancing after a
  // cancellation, we don't want to clear the tree stack.
  if (!self->canceled_balancing) {
    array_clear(&self->tree_pool.tree_stack);
    if (ts_subtree_child_count(finished_tree) > 0 && finished_tree.ptr->ref_count == 1) {
      array_push(&self->tree_pool.tree_stack, ts_subtree_to_mut_unsafe(finished_tree));
    }
  }

  while (self->tree_pool.tree_stack.size > 0) {
    if (!ts_parser__check_progress(self, NULL, NULL, 1)) {
      return false;
    }

    MutableSubtree tree = *array_get(&self->tree_pool.tree_stack, 
      self->tree_pool.tree_stack.size - 1
    );

    if (tree.ptr->repeat_depth > 0) {
      Subtree child1 = ts_subtree_children(tree)[0];
      Subtree child2 = ts_subtree_children(tree)[tree.ptr->child_count - 1];
      long repeat_delta = (long)ts_subtree_repeat_depth(child1) - (long)ts_subtree_repeat_depth(child2);
      if (repeat_delta > 0) {
        unsigned n = (unsigned)repeat_delta;

        for (unsigned i = n / 2; i > 0; i /= 2) {
          ts_subtree_compress(tree, i, self->language, &self->tree_pool.tree_stack);
          n -= i;

          // We scale the operation count increment in `ts_parser__check_progress` proportionately to the compression
          // size since larger values of i take longer to process. Shifting by 4 empirically provides good check
          // intervals (e.g. 193 operations when i=3100) to prevent blocking during large compressions.
          uint8_t operations = i >> 4 > 0 ? i >> 4 : 1;
          if (!ts_parser__check_progress(self, NULL, NULL, operations)) {
            return false;
          }
        }
      }
    }

    (void)array_pop(&self->tree_pool.tree_stack);

    for (uint32_t i = 0; i < tree.ptr->child_count; i++) {
      Subtree child = ts_subtree_children(tree)[i];
      if (ts_subtree_child_count(child) > 0 && child.ptr->ref_count == 1) {
        array_push(&self->tree_pool.tree_stack, ts_subtree_to_mut_unsafe(child));
      }
    }
  }

  return true;
}

static bool ts_parser_has_outstanding_parse(TSParser *self) {
  return (
    self->canceled_balancing ||             // balance 중 취소됨
    self->external_scanner_payload ||       // 외부 스캐너가 활성화되어 있음
    ts_stack_state(self->stack, 0) != 1 ||  // 스택이 초기 상태가 아님
    ts_stack_node_count_since_error(self->stack, 0) != 0    // 에러 복구 중
  );
}

// [new] 줄바꿈 인코딩
static void print_escaped_string(FILE *file, const char *input) {
  if (!input) {
    fprintf(file, "(null)");
    return;
  }
  for (const char *c = input; *c != '\0'; c++) {
    // Windows 스타일 개행 (\r\n) 처리
    if (*c == '\r' && *(c + 1) == '\n') {
      fprintf(file, "\\r\\n");
      c++; // 다음 글자(\n) 건너뜀
    }
    // Unix 스타일 개행 (\n)
    else if (*c == '\n') {
      fprintf(file, "\\n");
    }
    else {
      fputc(*c, file);
    }
  }
}

// Parser - Public

// [custom] TSParser 생성자
TSParser *ts_parser_new(void) {
  TSParser *self = ts_calloc(1, sizeof(TSParser));
  ts_lexer_init(&self->lexer);
  array_init(&self->reduce_actions);
  array_reserve(&self->reduce_actions, 4);
  
  // -----------------------------------------------------
  // 커서 위치 초기화
  self->cursor_row = UINT32_MAX;
  self->cursor_col = UINT32_MAX;

  array_init(&self->logged_actions);
  array_reserve(&self->logged_actions, 2048);

  // 동작 모드 설정 (default: 컨버전)
  self->bIsCollectionOrParseStateID = false; 
  // -----------------------------------------------------

  self->tree_pool = ts_subtree_pool_new(32);
  self->stack = ts_stack_new(&self->tree_pool);
  self->finished_tree = NULL_SUBTREE;
  self->reusable_node = reusable_node_new();
  self->dot_graph_file = NULL;
  self->cancellation_flag = NULL;
  self->timeout_duration = 0;
  self->language = NULL;
  self->has_scanner_error = false;
  self->has_error = false;
  self->canceled_balancing = false;
  self->external_scanner_payload = NULL;
  self->end_clock = clock_null();
  self->operation_count = 0;
  self->old_tree = NULL_SUBTREE;
  self->included_range_differences = (TSRangeArray) array_new();
  self->included_range_difference_index = 0;
  ts_parser__set_cached_token(self, 0, NULL_SUBTREE, NULL_SUBTREE);
  return self;
}

// [custom] TSParser 소멸자
void ts_parser_delete(TSParser *self) {
  if (!self) return;

  ts_parser_set_language(self, NULL);
  ts_stack_delete(self->stack);
  if (self->reduce_actions.contents) {
    array_delete(&self->reduce_actions);
  }
  // -----------------------------------------------------
  if (self->logged_actions.contents) {
    array_delete(&self->logged_actions);
  }
  // -----------------------------------------------------
  if (self->included_range_differences.contents) {
    array_delete(&self->included_range_differences);
  }
  if (self->old_tree.ptr) {
    ts_subtree_release(&self->tree_pool, self->old_tree);
    self->old_tree = NULL_SUBTREE;
  }
  ts_wasm_store_delete(self->wasm_store);
  ts_lexer_delete(&self->lexer);
  ts_parser__set_cached_token(self, 0, NULL_SUBTREE, NULL_SUBTREE);
  ts_subtree_pool_delete(&self->tree_pool);
  reusable_node_delete(&self->reusable_node);
  array_delete(&self->trailing_extras);
  array_delete(&self->trailing_extras2);
  array_delete(&self->scratch_trees);
  ts_free(self);
}

const TSLanguage *ts_parser_language(const TSParser *self) {
  return self->language;
}

bool ts_parser_set_language(TSParser *self, const TSLanguage *language) {
  ts_parser_reset(self);
  ts_language_delete(self->language);
  self->language = NULL;

  if (language) {
    if (
      language->abi_version > TREE_SITTER_LANGUAGE_VERSION ||
      language->abi_version < TREE_SITTER_MIN_COMPATIBLE_LANGUAGE_VERSION
    ) return false;

    if (ts_language_is_wasm(language)) {
      if (
        !self->wasm_store ||
        !ts_wasm_store_start(self->wasm_store, &self->lexer.data, language)
      ) return false;
    }
  }

  self->language = ts_language_copy(language);
  return true;
}

TSLogger ts_parser_logger(const TSParser *self) {
  return self->lexer.logger;
}

void ts_parser_set_logger(TSParser *self, TSLogger logger) {
  self->lexer.logger = logger;
}

void ts_parser_print_dot_graphs(TSParser *self, int fd) {
  if (self->dot_graph_file) {
    fclose(self->dot_graph_file);
  }

  if (fd >= 0) {
    #ifdef _WIN32
    self->dot_graph_file = _fdopen(fd, "a");
    #else
    self->dot_graph_file = fdopen(fd, "a");
    #endif
  } else {
    self->dot_graph_file = NULL;
  }
}

const size_t *ts_parser_cancellation_flag(const TSParser *self) {
  return (const size_t *)self->cancellation_flag;
}

void ts_parser_set_cancellation_flag(TSParser *self, const size_t *flag) {
  self->cancellation_flag = (const volatile size_t *)flag;
}

uint64_t ts_parser_timeout_micros(const TSParser *self) {
  return duration_to_micros(self->timeout_duration);
}

void ts_parser_set_timeout_micros(TSParser *self, uint64_t timeout_micros) {
  self->timeout_duration = duration_from_micros(timeout_micros);
}

bool ts_parser_set_included_ranges(
  TSParser *self,
  const TSRange *ranges,
  uint32_t count
) {
  return ts_lexer_set_included_ranges(&self->lexer, ranges, count);
}

const TSRange *ts_parser_included_ranges(const TSParser *self, uint32_t *count) {
  return ts_lexer_included_ranges(&self->lexer, count);
}

// [custom] TSParser 초기화 함수
void ts_parser_reset(TSParser *self) {
  // -----------------------------------------------------
  // 커서 위치 초기화
  self->cursor_row = UINT32_MAX;
  self->cursor_col = UINT32_MAX;
  // -----------------------------------------------------

  ts_parser__external_scanner_destroy(self);
  if (self->wasm_store) {
    ts_wasm_store_reset(self->wasm_store);
  }

  if (self->old_tree.ptr) {
    ts_subtree_release(&self->tree_pool, self->old_tree);
    self->old_tree = NULL_SUBTREE;
  }

  reusable_node_clear(&self->reusable_node);
  ts_lexer_reset(&self->lexer, length_zero());
  ts_stack_clear(self->stack);
  ts_parser__set_cached_token(self, 0, NULL_SUBTREE, NULL_SUBTREE);
  if (self->finished_tree.ptr) {
    ts_subtree_release(&self->tree_pool, self->finished_tree);
    self->finished_tree = NULL_SUBTREE;
  }
  self->accept_count = 0;
  self->has_scanner_error = false;
  self->has_error = false;
  self->canceled_balancing = false;
  self->parse_options = (TSParseOptions) {0};
  self->parse_state = (TSParseState) {0};
}

// [new] 커서 위치 설정 함수
void ts_parser_set_cursor_position(TSParser *self, TSPoint cursor_point) {
  if (self) {
    self->cursor_row = cursor_point.row;
    self->cursor_col = cursor_point.column;
  }
}

// [new] 파싱 중에 수집된 모든 액션을 파일로 덤프하는 함수 (디버깅용)
// note: 문법적 모호성 발생 시 다른 스택 버전도 포함됨
void ts_parser_write_logged_actions(
  TSParser *self, 
  const char *filename
) {
  FILE *ActionFile = fopen(filename, "w");
  if (!ActionFile) return;

  // 로그 출력용 임시 이름 스택
  Array(char *) DebugLogStack = array_new();

  for (uint32_t I = 0; I < self->logged_actions.size; ++I) {
    TSLoggedAction *Action = &self->logged_actions.contents[I];
    
    // fprintf(ActionFile, "[v%u] ", Action->version_id);

    switch (Action->type) {
      case TSParseActionTypeShift: {
        TSSymbol SymbolNum = Action->symbol;
        const char *SymbolName = ts_language_symbol_name(self->language, Action->symbol);
        const char *lexeme = Action->lexeme;
        if (!SymbolName) { SymbolName = "UNKNOWN_SYM"; }
        if (!lexeme) { lexeme = "UNKNOWN"; }

        // 가짜(Virtual) Shift 여부 표시
        // 출력 시 [SHIFT] 대신 [V-SHIFT]을 사용하여 구분
        const char* ActionLabel = Action->is_virtual ? "[V-SHIFT]" : "[SHIFT]";
        bool bIsSame = (strcmp(SymbolName, lexeme) == 0);
          
        if (bIsSame) {
          // 같으면: Lexeme 생략하고 출력
          // 출력 예: [SHIFT] State: 0 -> 5, symbol: if (25)
          fprintf(ActionFile, "%s State: %u -> %u, symbol: %s (%u)\n",
                    ActionLabel,Action->current_state,Action->next_state,SymbolName,SymbolNum);

          // 스택 저장용 문자열 생성 (간단하게 이름만)
            size_t StrLen = strlen(SymbolName) + 1;
            char *FormattedStr = (char *)ts_malloc(StrLen);
            snprintf(FormattedStr, StrLen, "%s", SymbolName);
            array_push(&DebugLogStack, FormattedStr);
        }
        else {
          // 다르면: Lexeme 포함하여 출력
          // 출력 예: [SHIFT] State: 5 -> 12, symbol: identifier (26, myVar)
          // fprintf(ActionFile, "%s State %u -> %u, symbol: %s (%u, %s)\n",
          //           ActionLabel,Action->current_state,Action->next_state,SymbolName,SymbolNum,lexeme);
          fprintf(ActionFile, "%s State %u -> %u, symbol: %s (%u, ",
                    ActionLabel, Action->current_state, Action->next_state, SymbolName, SymbolNum);
          // lexeme을 이스케이프 처리하여 출력
          print_escaped_string(ActionFile, lexeme);
          fprintf(ActionFile, ")\n");

          // 스택 저장용 문자열 생성 (이름(값) 형태)
          size_t StrLen = strlen(SymbolName) + strlen(lexeme) + 4; // '(',')', '\0', 여유분
          char *FormattedStr = (char *)ts_malloc(StrLen);
          snprintf(FormattedStr, StrLen, "%s(%s)", SymbolName, lexeme);
          array_push(&DebugLogStack, FormattedStr);
        } 
        break;
      }

      case TSParseActionTypeReduce: {
        const char *SymbolName = ts_language_symbol_name(self->language, Action->symbol);
        if (!SymbolName) { SymbolName = "UNKNOWN_SYMBOL"; }
          
        // 가짜(Virtual) Reduce 여부 표시
        // 출력 시 [REDUCE] 대신 [V-REDUCE] 등을 사용하여 구분
        const char* ActionLabel = Action->is_virtual ? "[V-REDUCE]" : "[REDUCE]";
        fprintf(ActionFile, "%s State %u -> GOTO %u, symbol: %s, child %u",
                ActionLabel,Action->current_state,Action->next_state,SymbolName,Action->child_count);
        
        // 자식 노드 정보 출력
        if (Action->child_count > 0) {
          fprintf(ActionFile, " { " );
          uint32_t StartIndex = DebugLogStack.size - Action->child_count;
          
          for (uint32_t k = 0; k < Action->child_count; ++k) {
            if (StartIndex + k < DebugLogStack.size) {
              // 스택에 저장된 "Symbol(Lexeme)" 문자열을 꺼냄
              char *ChildStr = *array_get(&DebugLogStack, StartIndex + k);
              // fprintf(ActionFile, "'%s' ", ChildStr);
              fprintf(ActionFile, "'");
              print_escaped_string(ActionFile, ChildStr);
              fprintf(ActionFile, "' ");
              // 사용한 자식 문자열 메모리 해제! (Pop 대신 여기서 해제)
              ts_free(ChildStr); 
            }
          }
          fprintf(ActionFile, "}\n");
        }
        // 스택 포인터만 줄임 (실제 데이터는 위에서 free 했음)
        for (uint32_t k = 0; k < Action->child_count; ++k) {
          if (DebugLogStack.size > 0) array_pop(&DebugLogStack);
        }

        // 부모 노드(Reduce 결과)도 동적 할당해서 넣어야 규칙이 유지됨
        // 부모는 Lexeme이 없으므로 SymbolName만 복사해서 넣음
        size_t ParentLen = strlen(SymbolName) + 1;
        char *ParentStr = (char *)ts_malloc(ParentLen);
        strcpy(ParentStr, SymbolName);
        array_push(&DebugLogStack, ParentStr);

        break;
      }

      case TSParseActionTypeRecover: {
        const char *SymbolName = ts_language_symbol_name(self->language, Action->symbol);
        if (!SymbolName) { SymbolName = "UNKNOWN_SYMBOL"; }
        
        // 에러 복구 발생 위치 출력
        fprintf(ActionFile, "[RECOVER] State %u, symbol: %s, Row: %u, Column:%u\n",
            Action->current_state,SymbolName,
            Action->start_point.row + 1,
            Action->start_point.column + 1
        );
        break;
      }

      case TSParseActionTypeAccept: {
        fprintf(ActionFile, "[ACCEPT] State %u\n", Action->current_state);
        break;
      }

      default: {
        fprintf(ActionFile, "[OTHER]\n");
        break;
        }
      }
  }
  for (uint32_t i = 0; i < DebugLogStack.size; i++) {
      char *Str = *array_get(&DebugLogStack, i);
      ts_free(Str);
  }
  array_delete(&DebugLogStack);
  fclose(ActionFile);
}

// [new] 컨버전 결과 출력 함수
void ts_parser_write_conversion_result(
  TSParser *self,
  TSStatePath *path,
  FILE *fp
) {
  if (!fp) fp = stdout;   // Null이면 터미널(stdout)로 출력
  if (path->count > 0) {
    fprintf(fp, "[conversion] Found States (%u)\n", path->count);
    fprintf(fp, "Path: ");
    for (uint32_t i = 0; i < path->count; i++) {
      fprintf(fp, "%u", path->states[i]);
      if (i < path->count - 1) fprintf(fp, ", ");
    }
    fprintf(fp, "\n");
  }
  else {
    fprintf(fp, "[conversion] Not Found\n");
  }
  if (fp == stdout) fflush(stdout);
}

typedef struct {
    FILE *file;
    const char *source;
    uint32_t source_len;
    const TSLanguage *lang;
    uint32_t byte_offset;   // 현재 커서 위치 (Bytes)
    TSPoint point_offset;   // 현재 커서 위치 (Row, Col)
} CollectionContext;

// [Helper] 바이트 오프셋 → 시각적 행/열 좌표 변환 (collection2에서 사용)
static void get_visual_position_from_offset(const char *text, uint32_t target_offset, uint32_t *out_row, uint32_t *out_col) {
    uint32_t current_offset = 0;
    uint32_t current_row = 0;
    uint32_t current_col = 0;
    const uint32_t tab_width = 4;

    if (!text) { *out_row = 0; *out_col = 0; return; }

    while (text[current_offset] != '\0' && current_offset < target_offset) {
        unsigned char current_char = (unsigned char)text[current_offset];
        if (current_char == '\n') {
            current_row++; current_col = 0; current_offset++;
        } else if (current_char == '\r' && text[current_offset + 1] == '\n') {
            current_row++; current_col = 0; current_offset += 2;
        } else if (current_char == '\t') {
            current_col = ((current_col / tab_width) + 1) * tab_width; current_offset++;
        } else {
            current_col++; current_offset++;
            if (current_char >= 0xC0) {
                while (text[current_offset] != '\0' && current_offset < target_offset &&
                      ((unsigned char)text[current_offset] & 0xC0) == 0x80) {
                    current_offset++;
                }
            }
        }
    }
    *out_row = current_row;
    *out_col = current_col;
}

// [new]
void dump_lexemes(CollectionContext *ctx, Subtree node) {
  // 1. 노드의 크기 정보 가져오기
  Length padding = ts_subtree_padding(node);
  Length size = ts_subtree_size(node);

  // 2. 텍스트 시작 위치 계산
  // 현재 커서(ctx->byte_offset)에서 패딩(앞쪽 공백)만큼 건너뛴 곳이 실제 텍스트 시작점(절대 바이트 오프셋)
  uint32_t start_byte = ctx->byte_offset + padding.bytes;
  uint32_t length_byte = size.bytes;

  // 3. 출력 형식: "  행,열: "
  if (length_byte > 0 && start_byte < ctx->source_len) {
    uint32_t vis_row = 0;
    uint32_t vis_col = 0;

    // [핵심 수정] 절대 바이트 오프셋을 역함수에 넣어 에디터 기준(Visual) 좌표로 변환
    get_visual_position_from_offset(ctx->source, start_byte, &vis_row, &vis_col);

    // 행과 열은 보통 1부터 시작하므로 각각 +1
    fprintf(ctx->file, "  %u,%u: \n", vis_row + 1, vis_col + 1);
  }

  // 4. 다음 형제를 위해 임시 컨텍스트의 커서를 이동시킴
  ctx->byte_offset += (padding.bytes + size.bytes);
  ctx->point_offset = point_add(ctx->point_offset, (padding.extent.row > 0 || size.extent.row > 0) 
        ? point_add(padding.extent, size.extent) 
        : (TSPoint){0, padding.extent.column + size.extent.column});
}

// [new]
void collect_recursive(
  CollectionContext *ctx, 
  Subtree tree,
  TSStateId state_from_parent
) {
  uint32_t count = ts_subtree_child_count(tree);

  // [Leaf 노드]
  if (count == 0) {
    // 커서 이동
    Length padding = ts_subtree_padding(tree);
    Length size = ts_subtree_size(tree);
    Length total = length_add(padding, size);
    ctx->byte_offset += total.bytes;
    ctx->point_offset = point_add(ctx->point_offset, total.extent);
    return;
  }

  // [Internal 노드]
  Subtree *children = ts_subtree_children(tree);
  if (!children) return;

  // ERROR 노드 확인
  bool current_is_error = ts_subtree_is_error(tree) ||
                          ts_subtree_symbol(tree) == ts_builtin_sym_error_repeat;

  TSStateId current_node_state = ts_subtree_parse_state(tree);
  // Fragile 노드(TS_TREE_STATE_NONE = USHRT_MAX)는 parse_state를 신뢰할 수 없음.
  // 이 경우 첫 번째 리프의 실제 parse_state를 fallback으로 사용한다.
  // (state_from_parent는 부모도 fragile일 수 있어 부적절)
  TSStateId running_state = (current_node_state < ctx->lang->state_count)
    ? current_node_state
    : ts_subtree_leaf_parse_state(tree);

  // 자식 순회
  for (uint32_t i = 0; i < count; i++) {
    Subtree child = children[i];
    TSSymbol child_sym = ts_subtree_symbol(child);
    uint32_t child_count = ts_subtree_child_count(child);
    bool is_leaf = (child_count == 0);
    bool is_valid_sym = (child_sym != ts_builtin_sym_end);
    bool is_extra = ts_subtree_extra(child);

    // 자식이 Leaf 노드이면 구조 후보 출력
    if (is_leaf && is_valid_sym && !current_is_error &&
      running_state > 0 && running_state < ctx->lang->state_count) {

      bool contaminated = false;
        for (uint32_t j = i; j < count; j++) {
          if (ts_subtree_extra(children[j])) continue;
          if (ts_subtree_error_cost(children[j]) > 0 || ts_subtree_missing(children[j])) {
            contaminated = true;
            break;
          }
      }

      if (!contaminated) {
        // line 1: state + symbols
        fprintf(ctx->file, "%u", running_state);
        
        for (uint32_t j = i; j < count; j++) {
          if (ts_subtree_extra(children[j])) continue;
          TSSymbol sym = ts_subtree_symbol(children[j]);
          const char *name = ts_language_symbol_name(ctx->lang, sym);
          fprintf(ctx->file, " %s", name ? name : "UNKNOWN");
        }
        fprintf(ctx->file, "\n");

        // line 2: lexemes
        CollectionContext temp_ctx = *ctx;
        for (uint32_t j = i; j < count; j++) {
          if (ts_subtree_extra(children[j])) continue;
          dump_lexemes(&temp_ctx, children[j]);
        }
        fprintf(ctx->file, "\n");
      }
    }

    // 자식이 또 Internal 노드이면 재귀
    collect_recursive(ctx, child, running_state);

    if (!is_extra && running_state > 0 && running_state < ctx->lang->state_count) {
      TSStateId next = ts_language_next_state(ctx->lang, running_state, child_sym);
      if (next != 0) {
        running_state = next;
      }
    }
  }
}

// [new] 컬렉션 ver.2
bool ts_parser_run_collection2 (
  TSTree *tree,
  const char *source_code,
  uint32_t length,
  FILE *file
) {

  if (!tree) { fprintf(stderr, "[ERROR] Tree is NULL\n"); return false; }
  
  if (!file) return false;

  Subtree root = tree->root;
  if (!root.ptr) return false;

  // 컨텍스트 설정
  CollectionContext ctx = {
      .file = file,
      .source = source_code,
      .source_len = length,
      .lang = ts_tree_language(tree),
      .byte_offset = 0,
      .point_offset = {0, 0}
  };

  collect_recursive(&ctx, root, 1);
  return true;
}

// [new] (Helper)
static void add_state_to_union(TSStatePath *union_path, TSStateId state) {
  for (uint32_t i = 0; i < union_path->count; i++) {
    if (union_path->states[i] == state) return; // 이미 존재하면 무시
  }
  if (union_path->count < 256) { // TSStatePath 최대 크기에 맞춰 안전하게 추가
    union_path->states[union_path->count++] = state;
  }
}

// [new]
TSStatePath ts_parser_parse_for_conversion(
  TSParser *self,
  const TSTree *old_tree,
  TSInput input,
  uint32_t length
) {
  // ----------------------------------------------
  // 1단계 : 전처리/초기화
  // ----------------------------------------------
  TSStatePath empty_result = {0};
  TSStatePath final_union = {0};

  TSTree *result = NULL;
  if (!self->language || !input.read) return empty_result;

  if (ts_language_is_wasm(self->language)) {
    if (!self->wasm_store) return empty_result;
    ts_wasm_store_start(self->wasm_store, &self->lexer.data, self->language);
  }
  
  ts_lexer_set_input(&self->lexer, input);
  array_clear(&self->included_range_differences);
  self->included_range_difference_index = 0;

  // normal parse의 에러 복구 토큰이 캐시에 남아 conversion parse를 오염시키므로 클리어
  ts_parser__set_cached_token(self, 0, NULL_SUBTREE, NULL_SUBTREE);

  self->operation_count = 0;
  if (self->timeout_duration) {
    self->end_clock = clock_after(clock_now(), self->timeout_duration);
  } else {
    self->end_clock = clock_null();
  }

  ts_parser__external_scanner_create(self);
  if (self->has_scanner_error) goto exit;

  // ----------------------------------------------
  // 2단계 : 파싱 재개 vs 새 파싱 시작 분기
  // ----------------------------------------------
  if (old_tree) {   // 이전버전의 트리가 있을 때 (증분 파싱)
    ts_subtree_retain(old_tree->root);
    self->old_tree = old_tree->root;
    ts_range_array_get_changed_ranges(
      old_tree->included_ranges, old_tree->included_range_count,
      self->lexer.included_ranges, self->lexer.included_range_count,
      &self->included_range_differences
    );
    reusable_node_reset(&self->reusable_node, old_tree->root);
    LOG("parse_after_edit");
    LOG_TREE(self->old_tree);
    for (unsigned i = 0; i < self->included_range_differences.size; i++) {
      TSRange *range = array_get(&self->included_range_differences, i);
      LOG("different_included_range %u - %u", range->start_byte, range->end_byte);
    }
  } else {    // 신규 파싱
    reusable_node_clear(&self->reusable_node);
    LOG("new_parse");
  }

  // 파싱 루프
  uint32_t position = 0, last_position = 0, version_count = 0;
  bool reached_cursor_target = false; // 루프 전체를 탈출할 플래그

  // do {...} while (version_count != 0) 
  // 파싱할 수 있는 경로가 남아있는 한 계속 진행
  do {
    version_count = ts_stack_version_count(self->stack);

    // for (version = 0; version < version_count; version++)
    // 현재 살아있는 모든 스택 버전을 한 번씩 순회
    for (
      StackVersion version = 0;
      version_count = ts_stack_version_count(self->stack),  // 매 루프마다 버전 수 다시 확인
      version < version_count;
      version++
    ) {
      bool allow_node_reuse = version_count == 1;
      while (ts_stack_is_active(self->stack, version)) {  // 한 버전이 토큰을 하나 먹을 때까지 굴림
        LOG(                                              // (토큰 하나 읽기 위해 여러번 reduce가 필요할 수도 있기에)
          "process version:%u, version_count:%u, state:%d, row:%u, col:%u",
          version,
          ts_stack_version_count(self->stack),
          ts_stack_state(self->stack, version),
          ts_stack_position(self->stack, version).extent.row,
          ts_stack_position(self->stack, version).extent.column
        );

        // 커서(length)에 도달하면 false를 반환하도록 설계
        if (!ts_parser__advance_for_conversion(self, version, allow_node_reuse, length)) {
          if (self->has_scanner_error) goto exit;
            
          // advance가 false를 반환했는데 스캐너 에러가 아니다
          // -> 우리의 설계대로 커서(length)에 도달하여 Freeze된 것
          reached_cursor_target = true;
          break; // 해당 버전의 처리를 멈춤
        }

        LOG_STACK();

        // GLR 동기화
        position = ts_stack_position(self->stack, version).bytes;
        if (position > last_position || (version > 0 && position == last_position)) {
          last_position = position;
          break;
        }
      }
    }

    // 누군가 커서에 도달했다면, 즉시 컨버전
    if (reached_cursor_target) {
      goto phase_3_conversion;
    }

    // condense 전에 halted 버전들의 상태를 final_union에 미리 저장
    // ts_parser__condense_stack은 halted 버전을 무조건 제거(line 2468-2471)하므로
    // advance_for_conversion에서 token_end==target 경우로 만든 halted copy가
    // condense 후 소멸되기 전에 시뮬레이션 결과를 보존해야 한다.
    // 예) "3,6": state:2263에서 _cond_layout_end(size:1, token_end=31=target) →
    //     halted copy at 2263 → SHIFT → position 변화로 break → condense → 2263 소멸
    {
      uint32_t vc = ts_stack_version_count(self->stack);
      for (StackVersion i = 0; i < vc; i++) {
        if (ts_stack_is_halted(self->stack, i)) {
          TSStatePath sim = ts_stack_simulate_conversion(self->stack, i, self->language, self->zero_byte_ext_mask);
          for (uint32_t j = 0; j < sim.count; j++) {
            add_state_to_union(&final_union, sim.states[j]);
          }
        }
      }
    }

    // 상태가 같은 버전을 병합
    // After advancing each version of the stack, re-sort the versions by their cost,
    // removing any versions that are no longer worth pursuing.
    unsigned min_error_cost = ts_parser__condense_stack(self);

    // If there's already a finished parse tree that's better than any in-progress version,
    // then terminate parsing. Clear the parse stack to remove any extra references to subtrees
    // within the finished tree, ensuring that these subtrees can be safely mutated in-place
    // for rebalancing.
    if (self->finished_tree.ptr && ts_subtree_error_cost(self->finished_tree) < min_error_cost) {
      ts_stack_clear(self->stack);
      break;
    }

    while (self->included_range_difference_index < self->included_range_differences.size) {
      TSRange *range = array_get(&self->included_range_differences, self->included_range_difference_index);
      if (range->end_byte <= position) {
        self->included_range_difference_index++;
      } else {
        break;
      }
    }
  } while (version_count != 0);

  // ----------------------------------------------
  // 3단계 : 컨버전
  // ----------------------------------------------
  phase_3_conversion:
    uint32_t final_version_count = ts_stack_version_count(self->stack);
    if (final_version_count == 0) {
      return final_union;
    }
    for (StackVersion v = 0; v < final_version_count; v++) {
      // stack.c에 구현된 함수 호출
      TSStatePath conversion_result = ts_stack_simulate_conversion(self->stack, v, self->language, self->zero_byte_ext_mask);
    
      // 결과 병합 (합집합)
      for (uint32_t j = 0; j < conversion_result.count; j++) {
        add_state_to_union(&final_union, conversion_result.states[j]);
      }
    }
    LOG("done");

exit:
  ts_parser_reset(self);
  return final_union;
}

// [custom]
TSTree *ts_parser_parse(
  TSParser *self,
  const TSTree *old_tree,
  TSInput input
) {
  // ----------------------------------------------
  // 1단계 : 전처리/초기화
  // ----------------------------------------------
  TSTree *result = NULL;
  if (!self->language || !input.read) return NULL;    // 언어/입력 유효성 검사

  if (self->logged_actions.contents) {
      array_clear(&self->logged_actions);
  }

  if (ts_language_is_wasm(self->language)) {    // 언어가 WASM 기반이면 별도 스토어 초기화
    if (!self->wasm_store) return NULL;
    ts_wasm_store_start(self->wasm_store, &self->lexer.data, self->language);
  }
  
  ts_lexer_set_input(&self->lexer, input);    // 입력 스트림을 Lexer에 연결
  array_clear(&self->included_range_differences);   // 증분 파싱을 위한 변경 범위 배열 초기화
  self->included_range_difference_index = 0;

  self->operation_count = 0;    // timeout_duration이 있으면 종료 시각 계산
  if (self->timeout_duration) {
    self->end_clock = clock_after(clock_now(), self->timeout_duration);
  } else {
    self->end_clock = clock_null();
  }

  // ----------------------------------------------
  // 2단계 : 파싱 재개 vs 새 파싱 시작 분기
  // ----------------------------------------------
  if (ts_parser_has_outstanding_parse(self)) {  // 이전 파싱이 타임아웃/취소로 중단된 경우
    
    // 재개 위치만 분기
    // - balance: 레이블로 점프 (파싱 완료, 균형만 재개)
    // - 파싱 루프부터 (파싱 자체를 재개)
    LOG("resume_parsing");
    if (self->canceled_balancing) goto balance;

  } else {

    // 새 파싱 초기화

    ts_parser__external_scanner_create(self);
    if (self->has_scanner_error) goto exit;

    // old tree 있음 -> 증분 파싱 준비
    // 이전 트리의 노드 최대한 재사용할 수 있도록 세팅
    if (old_tree) {
      ts_subtree_retain(old_tree->root);    // 공동 소유권 획득 및 파서에 저장
      self->old_tree = old_tree->root;
      ts_range_array_get_changed_ranges(    // 재사용 불가 구간 목록 계산
        old_tree->included_ranges, old_tree->included_range_count,
        self->lexer.included_ranges, self->lexer.included_range_count,
        &self->included_range_differences
      );
      reusable_node_reset(&self->reusable_node, old_tree->root);    // 재사용 커서를 old_tree의 첫 자식에 위치시킴
      LOG("parse_after_edit");
      LOG_TREE(self->old_tree);
      for (unsigned i = 0; i < self->included_range_differences.size; i++) {
        TSRange *range = array_get(&self->included_range_differences, i);
        LOG("different_included_range %u - %u", range->start_byte, range->end_byte);
      }
    } else {
      // old tree 없음 -> 완전 새 파싱
      reusable_node_clear(&self->reusable_node);
      LOG("new_parse");
    }
  }

  // ----------------------------------------------
  // 3단계 : 메인 파싱 루프 (GLR 알고리즘)
  // ----------------------------------------------
  uint32_t position = 0, last_position = 0, version_count = 0;

  // do {...} while (version_count != 0) 
  // 파싱할 수 있는 경로가 남아있는 한 계속 진행
  do {

    // for (version = 0; version < version_count; version++)
    // 현재 살아있는 모든 스택 버전을 한 번씩 순회
    for (
      StackVersion version = 0;
      version_count = ts_stack_version_count(self->stack),  // 매 루프마다 버전 수 다시 확인
      version < version_count;
      version++
    ) {
      bool allow_node_reuse = version_count == 1;

      // while (ts_stack_is_active)
      // 한 스택 버전이 토큰을 하나 먹을 때까지 굴림
      // (토큰 하나 읽기 위해 여러번 reduce가 필요할 수도 있기에)
      while (ts_stack_is_active(self->stack, version)) {
        LOG(
          "process version:%u, version_count:%u, state:%d, row:%u, col:%u",
          version,
          ts_stack_version_count(self->stack),
          ts_stack_state(self->stack, version),
          ts_stack_position(self->stack, version).extent.row,
          ts_stack_position(self->stack, version).extent.column
        );

        // ts_parser__advance: 하나의 액션 수행 (Shift/Reduce/Accept/Recover)
        // SHIFT 액션 → advance()가 return true 
        //           → 진행 위치 업데이트 
        //           → while break
        //           → 다음 version으로 넘어감
        //           → 모든 version이 한 번씩 Shift할 때까지 for 루프 반복

        if (!ts_parser__advance(self, version, allow_node_reuse)) {
          // false 반환 케이스 1: 외부 스캐너 에러
          // ts_parser__lex() → has_scanner_error = true → return false
          if (self->has_scanner_error) goto exit;

          // false 반환 케이스 2: 취소/타임아웃
          // ts_parser__check_progress() → 취소 신호 감지 → return false
          // 파서 상태는 보존됨 → 다음 호출 시 재개 가능
          return NULL;
        }

        LOG_STACK();

        // 진행 위치 업데이트
        position = ts_stack_position(self->stack, version).bytes; 
        if (position > last_position || (version > 0 && position == last_position)) {
          last_position = position;
          break;  // 이 버전은 충분히 전진했으므로 다음 버전으로
        }
      }
    }

    // 매 파싱 라운드 이후 살아있는 스택 버전들을 정리
    // 주로 모든 version이 한 번씩 Shift한 후 (for문 종료)
    // 같은 상태에 도달한 프로세스들을 하나로 병합
    // After advancing each version of the stack, re-sort the versions by their cost,
    // removing any versions that are no longer worth pursuing.
    unsigned min_error_cost = ts_parser__condense_stack(self);

    // finished_tree 조기 종료 판단
    // If there's already a finished parse tree that's better than any in-progress version,
    // then terminate parsing. Clear the parse stack to remove any extra references to subtrees
    // within the finished tree, ensuring that these subtrees can be safely mutated in-place
    // for rebalancing.
    if (self->finished_tree.ptr && ts_subtree_error_cost(self->finished_tree) < min_error_cost) {
      ts_stack_clear(self->stack);
      break;
    }

    while (self->included_range_difference_index < self->included_range_differences.size) {
      TSRange *range = array_get(&self->included_range_differences, self->included_range_difference_index);
      if (range->end_byte <= position) {
        self->included_range_difference_index++;
      } else {
        break;
      }
    }
  } while (version_count != 0);


// 3단계: 트리의 균형 맞추기 및 반환
balance:
  ts_assert(self->finished_tree.ptr);
  if (!ts_parser__balance_subtree(self)) {
    self->canceled_balancing = true;
    return false;
  }
  self->canceled_balancing = false;
  LOG("done");
  LOG_TREE(self->finished_tree);

  result = ts_tree_new(
    self->finished_tree,
    self->language,
    self->lexer.included_ranges,
    self->lexer.included_range_count
  );
  self->finished_tree = NULL_SUBTREE;

exit:
  ts_parser_reset(self);
  return result;
}

TSTree *ts_parser_parse_with_options(
  TSParser *self,
  const TSTree *old_tree,
  TSInput input,
  TSParseOptions parse_options
) {
  self->parse_options = parse_options;
  self->parse_state.payload = parse_options.payload;
  TSTree *result = ts_parser_parse(self, old_tree, input);
  // Reset parser options before further parse calls.
  self->parse_options = (TSParseOptions) {0};
  return result;
}

TSTree *ts_parser_parse_string(
  TSParser *self,
  const TSTree *old_tree,
  const char *string,
  uint32_t length
) {
  return ts_parser_parse_string_encoding(self, old_tree, string, length, TSInputEncodingUTF8);
}

TSTree *ts_parser_parse_string_encoding(
  TSParser *self,
  const TSTree *old_tree,
  const char *string,
  uint32_t length,
  TSInputEncoding encoding
) {
  TSStringInput input = {string, length};
  return ts_parser_parse(self, old_tree, (TSInput) {
    &input,
    ts_string_input_read,
    encoding,
    NULL,
  });
}

// [New Wrapper] 문자열을 받아 스택을 반환하는 편의 함수
TSStatePath ts_parser_parse_string_for_conversion(
  TSParser *self,
  const TSTree *old_tree,
  const char *string,
  uint32_t length
) {
  // 1. 문자열 입력 구조체 설정 (ts_parser_parse_string_encoding 로직 참조)
  TSStringInput input_data = {string, length};
  TSInput input = {
    &input_data,
    ts_string_input_read, // 기존에 정의된 함수 사용 (없으면 복사 필요)
    TSInputEncodingUTF8,
    NULL,
  };

  // 2. 커스텀 파싱 함수 호출
  return ts_parser_parse_for_conversion(self, old_tree, input, length);
}

void ts_parser_set_wasm_store(TSParser *self, TSWasmStore *store) {
  if (self->language && ts_language_is_wasm(self->language)) {
    // Copy the assigned language into the new store.
    const TSLanguage *copy = ts_language_copy(self->language);
    ts_parser_set_language(self, copy);
    ts_language_delete(copy);
  }

  ts_wasm_store_delete(self->wasm_store);
  self->wasm_store = store;
}

TSWasmStore *ts_parser_take_wasm_store(TSParser *self) {
  if (self->language && ts_language_is_wasm(self->language)) {
    ts_parser_set_language(self, NULL);
  }

  TSWasmStore *result = self->wasm_store;
  self->wasm_store = NULL;
  return result;
}

#undef LOG
