#include "./alloc.h"
#include "./language.h"
#include "./subtree.h"
#include "./array.h"
#include "./stack.h"
#include "./length.h"
#include <assert.h>
#include <inttypes.h>
#include <stdio.h>

#define MAX_LINK_COUNT 8
#define MAX_NODE_POOL_SIZE 50
#define MAX_ITERATOR_COUNT 64

#if defined _WIN32 && !defined __GNUC__
#define forceinline __forceinline
#else
#define forceinline static inline __attribute__((always_inline))
#endif

typedef struct StackNode StackNode;

typedef struct {
  StackNode *node;
  Subtree subtree;
  bool is_pending;
} StackLink;

struct StackNode {
  TSStateId state;
  Length position;
  StackLink links[MAX_LINK_COUNT];
  short unsigned int link_count;
  uint32_t ref_count;
  unsigned error_cost;
  unsigned node_count;
  int dynamic_precedence;
};

typedef struct {
  StackNode *node;
  SubtreeArray subtrees;
  uint32_t subtree_count;
  bool is_pending;
} StackIterator;

typedef Array(StackNode *) StackNodeArray;

typedef enum {
  StackStatusActive,
  StackStatusPaused,
  StackStatusHalted,
} StackStatus;

typedef struct {
  StackNode *node;
  StackSummary *summary;
  unsigned node_count_at_last_error;
  Subtree last_external_token;
  Subtree lookahead_when_paused;
  StackStatus status;
} StackHead;

struct Stack {
  Array(StackHead) heads;
  StackSliceArray slices;
  Array(StackIterator) iterators;
  StackNodeArray node_pool;
  StackNode *base_node;
  SubtreePool *subtree_pool;
};

typedef unsigned StackAction;
enum {
  StackActionNone,
  StackActionStop = 1,
  StackActionPop = 2,
};

typedef StackAction (*StackCallback)(void *, const StackIterator *);

static void stack_node_retain(StackNode *self) {
  if (!self)
    return;
  ts_assert(self->ref_count > 0);
  self->ref_count++;
  ts_assert(self->ref_count != 0);
}

static void stack_node_release(
  StackNode *self,
  StackNodeArray *pool,
  SubtreePool *subtree_pool
) {
recur:
  ts_assert(self->ref_count != 0);
  self->ref_count--;
  if (self->ref_count > 0) return;

  StackNode *first_predecessor = NULL;
  if (self->link_count > 0) {
    for (unsigned i = self->link_count - 1; i > 0; i--) {
      StackLink link = self->links[i];
      if (link.subtree.ptr) ts_subtree_release(subtree_pool, link.subtree);
      stack_node_release(link.node, pool, subtree_pool);
    }
    StackLink link = self->links[0];
    if (link.subtree.ptr) ts_subtree_release(subtree_pool, link.subtree);
    first_predecessor = self->links[0].node;
  }

  if (pool->size < MAX_NODE_POOL_SIZE) {
    array_push(pool, self);
  } else {
    ts_free(self);
  }

  if (first_predecessor) {
    self = first_predecessor;
    goto recur;
  }
}

/// Get the number of nodes in the subtree, for the purpose of measuring
/// how much progress has been made by a given version of the stack.
static uint32_t stack__subtree_node_count(Subtree subtree) {
  uint32_t count = ts_subtree_visible_descendant_count(subtree);
  if (ts_subtree_visible(subtree)) count++;

  // Count intermediate error nodes even though they are not visible,
  // because a stack version's node count is used to check whether it
  // has made any progress since the last time it encountered an error.
  if (ts_subtree_symbol(subtree) == ts_builtin_sym_error_repeat) count++;

  return count;
}

static StackNode *stack_node_new(
  StackNode *previous_node,
  Subtree subtree,
  bool is_pending,
  TSStateId state,
  StackNodeArray *pool
) {
  StackNode *node = pool->size > 0
    ? array_pop(pool)
    : ts_malloc(sizeof(StackNode));
  *node = (StackNode) {
    .ref_count = 1,
    .link_count = 0,
    .state = state
  };

  if (previous_node) {
    node->link_count = 1;
    node->links[0] = (StackLink) {
      .node = previous_node,
      .subtree = subtree,
      .is_pending = is_pending,
    };

    node->position = previous_node->position;
    node->error_cost = previous_node->error_cost;
    node->dynamic_precedence = previous_node->dynamic_precedence;
    node->node_count = previous_node->node_count;

    if (subtree.ptr) {
      node->error_cost += ts_subtree_error_cost(subtree);
      node->position = length_add(node->position, ts_subtree_total_size(subtree));
      node->node_count += stack__subtree_node_count(subtree);
      node->dynamic_precedence += ts_subtree_dynamic_precedence(subtree);
    }
  } else {
    node->position = length_zero();
    node->error_cost = 0;
  }

  return node;
}

static bool stack__subtree_is_equivalent(Subtree left, Subtree right) {
  if (left.ptr == right.ptr) return true;
  if (!left.ptr || !right.ptr) return false;

  // Symbols must match
  if (ts_subtree_symbol(left) != ts_subtree_symbol(right)) return false;

  // If both have errors, don't bother keeping both.
  if (ts_subtree_error_cost(left) > 0 && ts_subtree_error_cost(right) > 0) return true;

  return (
    ts_subtree_padding(left).bytes == ts_subtree_padding(right).bytes &&
    ts_subtree_size(left).bytes == ts_subtree_size(right).bytes &&
    ts_subtree_child_count(left) == ts_subtree_child_count(right) &&
    ts_subtree_extra(left) == ts_subtree_extra(right) &&
    ts_subtree_external_scanner_state_eq(left, right)
  );
}

static void stack_node_add_link(
  StackNode *self,
  StackLink link,
  SubtreePool *subtree_pool
) {
  if (link.node == self) return;

  for (int i = 0; i < self->link_count; i++) {
    StackLink *existing_link = &self->links[i];
    if (stack__subtree_is_equivalent(existing_link->subtree, link.subtree)) {
      // In general, we preserve ambiguities until they are removed from the stack
      // during a pop operation where multiple paths lead to the same node. But in
      // the special case where two links directly connect the same pair of nodes,
      // we can safely remove the ambiguity ahead of time without changing behavior.
      if (existing_link->node == link.node) {
        if (
          ts_subtree_dynamic_precedence(link.subtree) >
          ts_subtree_dynamic_precedence(existing_link->subtree)
        ) {
          ts_subtree_retain(link.subtree);
          ts_subtree_release(subtree_pool, existing_link->subtree);
          existing_link->subtree = link.subtree;
          self->dynamic_precedence =
            link.node->dynamic_precedence + ts_subtree_dynamic_precedence(link.subtree);
        }
        return;
      }

      // If the previous nodes are mergeable, merge them recursively.
      if (
        existing_link->node->state == link.node->state &&
        existing_link->node->position.bytes == link.node->position.bytes &&
        existing_link->node->error_cost == link.node->error_cost
      ) {
        for (int j = 0; j < link.node->link_count; j++) {
          stack_node_add_link(existing_link->node, link.node->links[j], subtree_pool);
        }
        int32_t dynamic_precedence = link.node->dynamic_precedence;
        if (link.subtree.ptr) {
          dynamic_precedence += ts_subtree_dynamic_precedence(link.subtree);
        }
        if (dynamic_precedence > self->dynamic_precedence) {
          self->dynamic_precedence = dynamic_precedence;
        }
        return;
      }
    }
  }

  if (self->link_count == MAX_LINK_COUNT) return;

  stack_node_retain(link.node);
  unsigned node_count = link.node->node_count;
  int dynamic_precedence = link.node->dynamic_precedence;
  self->links[self->link_count++] = link;

  if (link.subtree.ptr) {
    ts_subtree_retain(link.subtree);
    node_count += stack__subtree_node_count(link.subtree);
    dynamic_precedence += ts_subtree_dynamic_precedence(link.subtree);
  }

  if (node_count > self->node_count) self->node_count = node_count;
  if (dynamic_precedence > self->dynamic_precedence) self->dynamic_precedence = dynamic_precedence;
}

static void stack_head_delete(
  StackHead *self,
  StackNodeArray *pool,
  SubtreePool *subtree_pool
) {
  if (self->node) {
    if (self->last_external_token.ptr) {
      ts_subtree_release(subtree_pool, self->last_external_token);
    }
    if (self->lookahead_when_paused.ptr) {
      ts_subtree_release(subtree_pool, self->lookahead_when_paused);
    }
    if (self->summary) {
      array_delete(self->summary);
      ts_free(self->summary);
    }
    stack_node_release(self->node, pool, subtree_pool);
  }
}

static StackVersion ts_stack__add_version(
  Stack *self,
  StackVersion original_version,
  StackNode *node
) {
  StackHead head = {
    .node = node,
    .node_count_at_last_error = array_get(&self->heads, original_version)->node_count_at_last_error,
    .last_external_token = array_get(&self->heads, original_version)->last_external_token,
    .status = StackStatusActive,
    .lookahead_when_paused = NULL_SUBTREE,
  };
  array_push(&self->heads, head);
  stack_node_retain(node);
  if (head.last_external_token.ptr) ts_subtree_retain(head.last_external_token);
  return (StackVersion)(self->heads.size - 1);
}

static void ts_stack__add_slice(
  Stack *self,
  StackVersion original_version,
  StackNode *node,
  SubtreeArray *subtrees
) {
  for (uint32_t i = self->slices.size - 1; i + 1 > 0; i--) {
    StackVersion version = array_get(&self->slices, i)->version;
    if (array_get(&self->heads, version)->node == node) {
      StackSlice slice = {*subtrees, version};
      array_insert(&self->slices, i + 1, slice);
      return;
    }
  }

  StackVersion version = ts_stack__add_version(self, original_version, node);
  StackSlice slice = { *subtrees, version };
  array_push(&self->slices, slice);
}

static StackSliceArray stack__iter(
  Stack *self,
  StackVersion version,
  StackCallback callback,
  void *payload,
  int goal_subtree_count
) {
  // 초기화
  array_clear(&self->slices);     // 결과 담을 배열
  array_clear(&self->iterators);  // 스택 탐색용 iterator 목록

  // 현재 스택의 꼭대기
  StackHead *head = array_get(&self->heads, version);
  // 첫 번째 iterator 생성
  StackIterator new_iterator = {
    .node = head->node,       // 시작점: 현재 헤드
    .subtrees = array_new(),  // 수집 결과: 비어있음
    .subtree_count = 0,       // 모은 개수: 0개
    .is_pending = true,
  };

  bool include_subtrees = false;
  if (goal_subtree_count >= 0) {
    include_subtrees = true;
    array_reserve(&new_iterator.subtrees, (uint32_t)ts_subtree_alloc_size(goal_subtree_count) / sizeof(Subtree));
  }

  // iterator를 목록에 추가
  array_push(&self->iterators, new_iterator);

  while (self->iterators.size > 0) {
    for (uint32_t i = 0, size = self->iterators.size; i < size; i++) {
      StackIterator *iterator = array_get(&self->iterators, i);
      StackNode *node = iterator->node;

      StackAction action = callback(payload, iterator);
      bool should_pop = action & StackActionPop;
      bool should_stop = action & StackActionStop || node->link_count == 0;

      if (should_pop) {
        SubtreeArray subtrees = iterator->subtrees;
        if (!should_stop) {
          ts_subtree_array_copy(subtrees, &subtrees);
        }
        ts_subtree_array_reverse(&subtrees);
        ts_stack__add_slice(
          self,
          version,
          node,
          &subtrees
        );
      }

      if (should_stop) {
        if (!should_pop) {
          ts_subtree_array_delete(self->subtree_pool, &iterator->subtrees);
        }
        array_erase(&self->iterators, i);
        i--, size--;
        continue;
      }

      // 현재 노드에 연결된 부모(링크)의 개수 만큼 반복
      for (uint32_t j = 1; j <= node->link_count; j++) {
        StackIterator *next_iterator;
        StackLink link;
        // 외길인 경우
        if (j == node->link_count) {
          link = node->links[0];
          next_iterator = array_get(&self->iterators, i);
        } else {
          // 갈림길인 경우 (Merge되었던 스택이 다시 Split)
          if (self->iterators.size >= MAX_ITERATOR_COUNT) continue;
          link = node->links[j];
          StackIterator current_iterator = *array_get(&self->iterators, i);
          array_push(&self->iterators, current_iterator);
          next_iterator = array_back(&self->iterators);
          ts_subtree_array_copy(next_iterator->subtrees, &next_iterator->subtrees);
        }

        next_iterator->node = link.node;
        if (link.subtree.ptr) {
          if (include_subtrees) {
            array_push(&next_iterator->subtrees, link.subtree);
            ts_subtree_retain(link.subtree);
          }

          if (!ts_subtree_extra(link.subtree)) {
            next_iterator->subtree_count++;
            if (!link.is_pending) {
              next_iterator->is_pending = false;
            }
          }
        } else {
          next_iterator->subtree_count++;
          next_iterator->is_pending = false;
        }
      }
    }
  }

  return self->slices;
}

Stack *ts_stack_new(SubtreePool *subtree_pool) {
  Stack *self = ts_calloc(1, sizeof(Stack));

  array_init(&self->heads);
  array_init(&self->slices);
  array_init(&self->iterators);
  array_init(&self->node_pool);
  array_reserve(&self->heads, 4);
  array_reserve(&self->slices, 4);
  array_reserve(&self->iterators, 4);
  array_reserve(&self->node_pool, MAX_NODE_POOL_SIZE);

  self->subtree_pool = subtree_pool;
  self->base_node = stack_node_new(NULL, NULL_SUBTREE, false, 1, &self->node_pool);
  ts_stack_clear(self);

  return self;
}

void ts_stack_delete(Stack *self) {
  if (self->slices.contents)
    array_delete(&self->slices);
  if (self->iterators.contents)
    array_delete(&self->iterators);
  stack_node_release(self->base_node, &self->node_pool, self->subtree_pool);
  for (uint32_t i = 0; i < self->heads.size; i++) {
    stack_head_delete(array_get(&self->heads, i), &self->node_pool, self->subtree_pool);
  }
  array_clear(&self->heads);
  if (self->node_pool.contents) {
    for (uint32_t i = 0; i < self->node_pool.size; i++)
      ts_free(*array_get(&self->node_pool, i));
    array_delete(&self->node_pool);
  }
  array_delete(&self->heads);
  ts_free(self);
}

uint32_t ts_stack_version_count(const Stack *self) {
  return self->heads.size;
}

uint32_t ts_stack_halted_version_count(Stack *self) {
  uint32_t count = 0;
  for (uint32_t i = 0; i < self->heads.size; i++) {
    StackHead *head = array_get(&self->heads, i);
    if (head->status == StackStatusHalted) {
      count++;
    }
  }
  return count;
}

TSStateId ts_stack_state(const Stack *self, StackVersion version) {
  return array_get(&self->heads, version)->node->state;
}

Length ts_stack_position(const Stack *self, StackVersion version) {
  return array_get(&self->heads, version)->node->position;
}

Subtree ts_stack_last_external_token(const Stack *self, StackVersion version) {
  return array_get(&self->heads, version)->last_external_token;
}

void ts_stack_set_last_external_token(Stack *self, StackVersion version, Subtree token) {
  StackHead *head = array_get(&self->heads, version);
  if (token.ptr) ts_subtree_retain(token);
  if (head->last_external_token.ptr) ts_subtree_release(self->subtree_pool, head->last_external_token);
  head->last_external_token = token;
}

unsigned ts_stack_error_cost(const Stack *self, StackVersion version) {
  StackHead *head = array_get(&self->heads, version);
  unsigned result = head->node->error_cost;
  if (
    head->status == StackStatusPaused ||
    (head->node->state == ERROR_STATE && !head->node->links[0].subtree.ptr)) {
    result += ERROR_COST_PER_RECOVERY;
  }
  return result;
}

unsigned ts_stack_node_count_since_error(const Stack *self, StackVersion version) {
  StackHead *head = array_get(&self->heads, version);
  if (head->node->node_count < head->node_count_at_last_error) {
    head->node_count_at_last_error = head->node->node_count;
  }
  return head->node->node_count - head->node_count_at_last_error;
}

void ts_stack_push(
  Stack *self,
  StackVersion version,
  Subtree subtree,
  bool pending,
  TSStateId state
) {
  StackHead *head = array_get(&self->heads, version);
  StackNode *new_node = stack_node_new(head->node, subtree, pending, state, &self->node_pool);
  if (!subtree.ptr) head->node_count_at_last_error = new_node->node_count;
  head->node = new_node;
}

forceinline StackAction pop_count_callback(void *payload, const StackIterator *iterator) {
  unsigned *goal_subtree_count = payload;
  if (iterator->subtree_count == *goal_subtree_count) {
    return StackActionPop | StackActionStop;
  } else {
    return StackActionNone;
  }
}

StackSliceArray ts_stack_pop_count(Stack *self, StackVersion version, uint32_t count) {
  return stack__iter(self, version, pop_count_callback, &count, (int)count);
}


forceinline StackAction pop_pending_callback(void *payload, const StackIterator *iterator) {
  (void)payload;
  if (iterator->subtree_count >= 1) {
    if (iterator->is_pending) {
      return StackActionPop | StackActionStop;
    } else {
      return StackActionStop;
    }
  } else {
    return StackActionNone;
  }
}

StackSliceArray ts_stack_pop_pending(Stack *self, StackVersion version) {
  StackSliceArray pop = stack__iter(self, version, pop_pending_callback, NULL, 0);
  if (pop.size > 0) {
    ts_stack_renumber_version(self, array_get(&pop, 0)->version, version);
    array_get(&pop, 0)->version = version;
  }
  return pop;
}

forceinline StackAction pop_error_callback(void *payload, const StackIterator *iterator) {
  if (iterator->subtrees.size > 0) {
    bool *found_error = payload;
    if (!*found_error && ts_subtree_is_error(*array_get(&iterator->subtrees, 0))) {
      *found_error = true;
      return StackActionPop | StackActionStop;
    } else {
      return StackActionStop;
    }
  } else {
    return StackActionNone;
  }
}

SubtreeArray ts_stack_pop_error(Stack *self, StackVersion version) {
  StackNode *node = array_get(&self->heads, version)->node;
  for (unsigned i = 0; i < node->link_count; i++) {
    if (node->links[i].subtree.ptr && ts_subtree_is_error(node->links[i].subtree)) {
      bool found_error = false;
      StackSliceArray pop = stack__iter(self, version, pop_error_callback, &found_error, 1);
      if (pop.size > 0) {
        ts_assert(pop.size == 1);
        ts_stack_renumber_version(self, array_get(&pop, 0)->version, version);
        return array_get(&pop, 0)->subtrees;
      }
      break;
    }
  }
  return (SubtreeArray) {.size = 0};
}

forceinline StackAction pop_all_callback(void *payload, const StackIterator *iterator) {
  (void)payload;
  return iterator->node->link_count == 0 ? StackActionPop : StackActionNone;
}

StackSliceArray ts_stack_pop_all(Stack *self, StackVersion version) {
  return stack__iter(self, version, pop_all_callback, NULL, 0);
}

typedef struct {
  StackSummary *summary;
  unsigned max_depth;
} SummarizeStackSession;

forceinline StackAction summarize_stack_callback(void *payload, const StackIterator *iterator) {
  SummarizeStackSession *session = payload;
  TSStateId state = iterator->node->state;
  unsigned depth = iterator->subtree_count;
  if (depth > session->max_depth) return StackActionStop;
  for (unsigned i = session->summary->size - 1; i + 1 > 0; i--) {
    StackSummaryEntry entry = *array_get(session->summary, i);
    if (entry.depth < depth) break;
    if (entry.depth == depth && entry.state == state) return StackActionNone;
  }
  array_push(session->summary, ((StackSummaryEntry) {
    .position = iterator->node->position,
    .depth = depth,
    .state = state,
  }));
  return StackActionNone;
}

void ts_stack_record_summary(Stack *self, StackVersion version, unsigned max_depth) {
  SummarizeStackSession session = {
    .summary = ts_malloc(sizeof(StackSummary)),
    .max_depth = max_depth
  };
  array_init(session.summary);
  stack__iter(self, version, summarize_stack_callback, &session, -1);
  StackHead *head = array_get(&self->heads, version);
  if (head->summary) {
    array_delete(head->summary);
    ts_free(head->summary);
  }
  head->summary = session.summary;
}

StackSummary *ts_stack_get_summary(Stack *self, StackVersion version) {
  return array_get(&self->heads, version)->summary;
}

int ts_stack_dynamic_precedence(Stack *self, StackVersion version) {
  return array_get(&self->heads, version)->node->dynamic_precedence;
}

bool ts_stack_has_advanced_since_error(const Stack *self, StackVersion version) {
  const StackHead *head = array_get(&self->heads, version);
  const StackNode *node = head->node;
  if (node->error_cost == 0) return true;
  while (node) {
    if (node->link_count > 0) {
      Subtree subtree = node->links[0].subtree;
      if (subtree.ptr) {
        if (ts_subtree_total_bytes(subtree) > 0) {
          return true;
        } else if (
          node->node_count > head->node_count_at_last_error &&
          ts_subtree_error_cost(subtree) == 0
        ) {
          node = node->links[0].node;
          continue;
        }
      }
    }
    break;
  }
  return false;
}

void ts_stack_remove_version(Stack *self, StackVersion version) {
  stack_head_delete(array_get(&self->heads, version), &self->node_pool, self->subtree_pool);
  array_erase(&self->heads, version);
}

void ts_stack_renumber_version(Stack *self, StackVersion v1, StackVersion v2) {
  if (v1 == v2) return;
  ts_assert(v2 < v1);
  ts_assert((uint32_t)v1 < self->heads.size);
  StackHead *source_head = array_get(&self->heads, v1);
  StackHead *target_head = array_get(&self->heads, v2);
  if (target_head->summary && !source_head->summary) {
    source_head->summary = target_head->summary;
    target_head->summary = NULL;
  }
  stack_head_delete(target_head, &self->node_pool, self->subtree_pool);
  *target_head = *source_head;
  array_erase(&self->heads, v1);
}

void ts_stack_swap_versions(Stack *self, StackVersion v1, StackVersion v2) {
  StackHead temporary_head = *array_get(&self->heads, v1);
  *array_get(&self->heads, v1) = *array_get(&self->heads, v2);
  *array_get(&self->heads, v2) = temporary_head;
}

StackVersion ts_stack_copy_version(Stack *self, StackVersion version) {
  ts_assert(version < self->heads.size);
  StackHead version_head = *array_get(&self->heads, version);
  array_push(&self->heads, version_head);
  StackHead *head = array_back(&self->heads);
  stack_node_retain(head->node);
  if (head->last_external_token.ptr) ts_subtree_retain(head->last_external_token);
  head->summary = NULL;
  return self->heads.size - 1;
}

bool ts_stack_merge(Stack *self, StackVersion version1, StackVersion version2) {
  if (!ts_stack_can_merge(self, version1, version2)) return false;
  StackHead *head1 = array_get(&self->heads, version1);
  StackHead *head2 = array_get(&self->heads, version2);
  for (uint32_t i = 0; i < head2->node->link_count; i++) {
    stack_node_add_link(head1->node, head2->node->links[i], self->subtree_pool);
  }
  if (head1->node->state == ERROR_STATE) {
    head1->node_count_at_last_error = head1->node->node_count;
  }
  ts_stack_remove_version(self, version2);
  return true;
}

bool ts_stack_can_merge(Stack *self, StackVersion version1, StackVersion version2) {
  StackHead *head1 = array_get(&self->heads, version1);
  StackHead *head2 = array_get(&self->heads, version2);
  return
    head1->status == StackStatusActive &&
    head2->status == StackStatusActive &&
    head1->node->state == head2->node->state &&
    head1->node->position.bytes == head2->node->position.bytes &&
    head1->node->error_cost == head2->node->error_cost &&
    ts_subtree_external_scanner_state_eq(head1->last_external_token, head2->last_external_token);
}

void ts_stack_halt(Stack *self, StackVersion version) {
  array_get(&self->heads, version)->status = StackStatusHalted;
}

void ts_stack_pause(Stack *self, StackVersion version, Subtree lookahead) {
  StackHead *head = array_get(&self->heads, version);
  head->status = StackStatusPaused;
  head->lookahead_when_paused = lookahead;
  head->node_count_at_last_error = head->node->node_count;
}

bool ts_stack_is_active(const Stack *self, StackVersion version) {
  return array_get(&self->heads, version)->status == StackStatusActive;
}

bool ts_stack_is_halted(const Stack *self, StackVersion version) {
  return array_get(&self->heads, version)->status == StackStatusHalted;
}

bool ts_stack_is_paused(const Stack *self, StackVersion version) {
  return array_get(&self->heads, version)->status == StackStatusPaused;
}

Subtree ts_stack_resume(Stack *self, StackVersion version) {
  StackHead *head = array_get(&self->heads, version);
  ts_assert(head->status == StackStatusPaused);
  Subtree result = head->lookahead_when_paused;
  head->status = StackStatusActive;
  head->lookahead_when_paused = NULL_SUBTREE;
  return result;
}

void ts_stack_clear(Stack *self) {
  stack_node_retain(self->base_node);
  for (uint32_t i = 0; i < self->heads.size; i++) {
    stack_head_delete(array_get(&self->heads, i), &self->node_pool, self->subtree_pool);
  }
  array_clear(&self->heads);
  array_push(&self->heads, ((StackHead) {
    .node = self->base_node,
    .status = StackStatusActive,
    .last_external_token = NULL_SUBTREE,
    .lookahead_when_paused = NULL_SUBTREE,
  }));
}

bool ts_stack_print_dot_graph(Stack *self, const TSLanguage *language, FILE *f) {
  array_reserve(&self->iterators, 32);
  if (!f) f = stderr;

  fprintf(f, "digraph stack {\n");
  fprintf(f, "rankdir=\"RL\";\n");
  fprintf(f, "edge [arrowhead=none]\n");

  Array(StackNode *) visited_nodes = array_new();

  array_clear(&self->iterators);
  for (uint32_t i = 0; i < self->heads.size; i++) {
    StackHead *head = array_get(&self->heads, i);
    if (head->status == StackStatusHalted) continue;

    fprintf(f, "node_head_%u [shape=none, label=\"\"]\n", i);
    fprintf(f, "node_head_%u -> node_%p [", i, (void *)head->node);

    if (head->status == StackStatusPaused) {
      fprintf(f, "color=red ");
    }
    fprintf(f,
      "label=%u, fontcolor=blue, weight=10000, labeltooltip=\"node_count: %u\nerror_cost: %u",
      i,
      ts_stack_node_count_since_error(self, i),
      ts_stack_error_cost(self, i)
    );

    if (head->summary) {
      fprintf(f, "\nsummary:");
      for (uint32_t j = 0; j < head->summary->size; j++) fprintf(f, " %u", array_get(head->summary, j)->state);
    }

    if (head->last_external_token.ptr) {
      const ExternalScannerState *state = &head->last_external_token.ptr->external_scanner_state;
      const char *data = ts_external_scanner_state_data(state);
      fprintf(f, "\nexternal_scanner_state:");
      for (uint32_t j = 0; j < state->length; j++) fprintf(f, " %2X", data[j]);
    }

    fprintf(f, "\"]\n");
    array_push(&self->iterators, ((StackIterator) {
      .node = head->node
    }));
  }

  bool all_iterators_done = false;
  while (!all_iterators_done) {
    all_iterators_done = true;

    for (uint32_t i = 0; i < self->iterators.size; i++) {
      StackIterator iterator = *array_get(&self->iterators, i);
      StackNode *node = iterator.node;

      for (uint32_t j = 0; j < visited_nodes.size; j++) {
        if (*array_get(&visited_nodes, j) == node) {
          node = NULL;
          break;
        }
      }

      if (!node) continue;
      all_iterators_done = false;

      fprintf(f, "node_%p [", (void *)node);
      if (node->state == ERROR_STATE) {
        fprintf(f, "label=\"?\"");
      } else if (
        node->link_count == 1 &&
        node->links[0].subtree.ptr &&
        ts_subtree_extra(node->links[0].subtree)
      ) {
        fprintf(f, "shape=point margin=0 label=\"\"");
      } else {
        fprintf(f, "label=\"%d\"", node->state);
      }

      fprintf(
        f,
        " tooltip=\"position: %u,%u\nnode_count:%u\nerror_cost: %u\ndynamic_precedence: %d\"];\n",
        node->position.extent.row + 1,
        node->position.extent.column,
        node->node_count,
        node->error_cost,
        node->dynamic_precedence
      );

      for (int j = 0; j < node->link_count; j++) {
        StackLink link = node->links[j];
        fprintf(f, "node_%p -> node_%p [", (void *)node, (void *)link.node);
        if (link.is_pending) fprintf(f, "style=dashed ");
        if (link.subtree.ptr && ts_subtree_extra(link.subtree)) fprintf(f, "fontcolor=gray ");

        if (!link.subtree.ptr) {
          fprintf(f, "color=red");
        } else {
          fprintf(f, "label=\"");
          bool quoted = ts_subtree_visible(link.subtree) && !ts_subtree_named(link.subtree);
          if (quoted) fprintf(f, "'");
          ts_language_write_symbol_as_dot_string(language, f, ts_subtree_symbol(link.subtree));
          if (quoted) fprintf(f, "'");
          fprintf(f, "\"");
          fprintf(
            f,
            "labeltooltip=\"error_cost: %u\ndynamic_precedence: %" PRId32 "\"",
            ts_subtree_error_cost(link.subtree),
            ts_subtree_dynamic_precedence(link.subtree)
          );
        }

        fprintf(f, "];\n");

        StackIterator *next_iterator;
        if (j == 0) {
          next_iterator = array_get(&self->iterators, i);
        } else {
          array_push(&self->iterators, iterator);
          next_iterator = array_back(&self->iterators);
        }
        next_iterator->node = link.node;
      }

      array_push(&visited_nodes, node);
    }
  }

  fprintf(f, "}\n");

  array_delete(&visited_nodes);
  return true;
}

// ========================================
//  GLR 파싱을 위한 컨버전 로직
// ========================================
typedef struct {
  TSStateId  state;
  StackNode *base_node;
} VisitedKey;

typedef struct {
  VisitedKey entries[1024];
  uint32_t   count;
} VisitedSet;

typedef struct {
  uint32_t child_count;
  TSSymbol symbol;  // non terminal
} ReduceProduction;

// (Helper) 중복 없이 상태 추가
static void add_state(TSStatePath *union_path, TSStateId state) {
  for (uint32_t i = 0; i < union_path->count; i++) {
    if (union_path->states[i] == state) return; 
  }
  if (union_path->count < 256) {
    union_path->states[union_path->count++] = state;
  }
}

// 전방 선언
static void simulate_reduce_pop_dfs(
  StackNode *node,
  uint32_t pop_count,
  TSSymbol reduce_symbol,
  const TSLanguage *language,
  TSStatePath *result,
  VisitedSet *visited
);

// (state, base_node) 쌍으로 방문 여부를 추적
// 동일한 GSS 컨텍스트에서 동일한 state 재진입만 차단
// → 다른 스택 문맥에서 같은 state 도달은 허용
static bool mark_visited(VisitedSet *visited, TSStateId state, StackNode *base_node) {
  for (uint32_t i = 0; i < visited->count; i++) {
    if (visited->entries[i].state     == state &&
        visited->entries[i].base_node == base_node) {
      return true;  // 이미 이 (state, 컨텍스트)로 탐색한 적 있음
    }
  }
  if (visited->count < 1024) {
    visited->entries[visited->count].state     = state;
    visited->entries[visited->count].base_node = base_node;
    visited->count++;
  } else {
    // 테이블 포화 → 방문한 것으로 처리
    return true;
  }
  return false;
}

// 현재 상태에서 가능한 reduce 액션들을 수집
static uint32_t collect_reduces(
  const TSLanguage  *language,
  TSStateId state,
  ReduceProduction *out,
  uint32_t out_cap
) {
  uint32_t count = 0;

  // terminal 심볼 범위만 조회
  uint32_t terminal_count = language->token_count + language->external_token_count;

  for (TSSymbol sym = 0; sym < terminal_count && count < out_cap; sym++) {
    uint32_t idx = ts_language_lookup(language, state, sym);
    if (idx == 0) continue;

    const TSParseActionEntry *entry = &language->parse_actions[idx];
    const TSParseAction *actions = (const TSParseAction *)(entry + 1);

    for (uint32_t a = 0; a < entry->entry.count && count < out_cap; a++) {
      if (actions[a].type != TSParseActionTypeReduce) continue;

      TSSymbol sym_r = actions[a].reduce.symbol;
      uint32_t count_r = actions[a].reduce.child_count;

      // (symbol, child_count) 중복 제거
      bool dup = false;
      for (uint32_t k = 0; k < count; k++) {
        if (out[k].symbol == sym_r && out[k].child_count == count_r) {
          dup = true;
          break;
        }
      }
      if (!dup) {
        out[count].symbol = sym_r;
        out[count].child_count = count_r;
        count++;
      }
    }
  }
  return count;
}

// current_state에 도달했음을 기록하고,
// 그 상태에서 가능한 모든 reduce를 시뮬레이션
static void simulate_current_states_dfs(
  TSStateId current_state,
  StackNode *real_node,    // 스택 top 노드
  bool is_virtual,
  const TSLanguage *language,
  TSStatePath *result,
  VisitedSet *visited
) {
  // 1. 도달한 상태는 무조건 결과 집합에 추가
  add_state(result, current_state);

  // 2. (state, base_node) 쌍으로 동일 컨텍스트에서 재실행 방지
  if (mark_visited(visited, current_state, real_node)) return;

  // 3. terminal 범위 내 reduce 수집
  ReduceProduction prd[256];
  uint32_t prd_count = collect_reduces(language, current_state, prd, 256);

  // 4. 각 reduce 시뮬레이션
  for (uint32_t i = 0; i < prd_count; i++) {
    uint32_t pop_count = prd[i].child_count;

    if (pop_count == 0) {
      // epsilon: 반드시 current_state 기준으로 GOTO
      TSStateId next_state = ts_language_lookup(language, current_state, prd[i].symbol);
      if (next_state != 0) {
        simulate_current_states_dfs(next_state, real_node, true, language, result, visited);
      }
      continue;
    }

    if (is_virtual) {
      // 이전 단계의 Reduce(GOTO)로 만들어진 비단말 심볼이 실제 스택에 Push되지 않고,
      // 스택 꼭대기에 있다고 상상만 하는 상태
      // 따라서 실제 스택 top → pop_count - 1 으로 reduce 수행
      simulate_reduce_pop_dfs(real_node, pop_count - 1, prd[i].symbol, language, result, visited);
    } else {
      // 실제 스택 top → pop_count 그대로 reduce 수행
      simulate_reduce_pop_dfs(real_node, pop_count, prd[i].symbol, language, result, visited);
    }
  }
}

// reduce 시뮬레이션
static void simulate_reduce_pop_dfs(
  StackNode *node,
  uint32_t pop_count,
  TSSymbol reduce_symbol,
  const TSLanguage *language,
  TSStatePath *result,
  VisitedSet *visited
) {
  if (!node) return;

  // pop 완료
  if (pop_count == 0) {
    // GOTO로 다음 상태 계산 후 재귀적으로 탐색
    TSStateId next_state = ts_language_lookup(language, node->state, reduce_symbol);
    if (next_state != 0) {
      simulate_current_states_dfs(next_state, node, true, language, result, visited);
    }
    return;
  }

  // link_count > 1이면 merge 흔적 → 각 링크에 대해 독립 재귀
  for (int i = 0; i < node->link_count; i++) {
    StackLink link = node->links[i];
    bool is_extra = link.subtree.ptr != NULL && ts_subtree_extra(link.subtree);

    // extra 링크는 pop_count 소모 없이 통과
    uint32_t next_pop = is_extra ? pop_count : pop_count - 1;
    simulate_reduce_pop_dfs(link.node, next_pop, reduce_symbol, language, result, visited);
  }
}

// ========================================
// 0-byte External SHIFT 체인 시뮬레이션 확장
// ========================================
// 소스 컷으로 인해 0-byte external token(예: TIGHT_DOT)이 정상 처리되지 못한 경우,
// 문법 테이블만으로 "가상 스택"을 구성하여 reduce 시뮬레이션을 확장한다.
//
// 예시 (Haskell TIGHT_DOT):
//   cursor state=8847
//   → (virtual) External#28(TIGHT_DOT) Shift → 12494
//   → (virtual) '.' Shift                    → 10081
//   → reduce _tight_dot(len=2) : GOTO(8847, _tight_dot) = 10878
//   → reduce _modid_prefix(len=2): GOTO(9625, _modid_prefix) = 10902  ✓

// 안전장치: vstack 배열 오버플로우 방지
// 실제 탐색 시작 깊이는 최대 2(ext-shift + any-shift),
// reduce 후 epsilon GOTO push 여유 포함해도 3이면 충분하나 1 여유를 둠
#define MAX_VDEPTH 4

typedef struct {
  TSStateId states[MAX_VDEPTH];  // 실제 스택 위에 가상으로 쌓인 state (bottom→top)
  uint32_t  depth;
} VStack;

// 전방 선언
static void simulate_reduce_with_vstack(
  StackNode *real_node,
  VStack vstack,
  uint32_t pop_count,
  TSSymbol symbol,
  const TSLanguage *language,
  TSStatePath *result,
  VisitedSet *visited
);

// 가상 스택 컨텍스트에서 현재 상태를 결과에 추가하고 reduce 체인 시뮬레이션
static void simulate_with_vstack(
  TSStateId current_state,
  StackNode *real_node,
  VStack vstack,
  const TSLanguage *language,
  TSStatePath *result,
  VisitedSet *visited
) {
  add_state(result, current_state);
  if (mark_visited(visited, current_state, real_node)) return;

  ReduceProduction prd[64];
  uint32_t prd_count = collect_reduces(language, current_state, prd, 64);
  for (uint32_t i = 0; i < prd_count; i++) {
    simulate_reduce_with_vstack(
      real_node, vstack,
      prd[i].child_count, prd[i].symbol,
      language, result, visited
    );
  }
}

// 가상 스택과 실제 스택을 혼합하여 pop_count개 팝 후 GOTO 수행
static void simulate_reduce_with_vstack(
  StackNode *real_node,
  VStack vstack,
  uint32_t pop_count,
  TSSymbol symbol,
  const TSLanguage *language,
  TSStatePath *result,
  VisitedSet *visited
) {
  if (!real_node) return;

  if (pop_count == 0) {
    // epsilon: 현재 가상 top(없으면 실제 top) 상태에서 GOTO
    TSStateId top = (vstack.depth > 0) ? vstack.states[vstack.depth - 1] : real_node->state;
    TSStateId next = ts_language_lookup(language, top, symbol);
    if (next != 0) {
      VStack nv = vstack;
      if (nv.depth < MAX_VDEPTH) nv.states[nv.depth++] = next;
      simulate_with_vstack(next, real_node, nv, language, result, visited);
    }
    return;
  }

  if (pop_count <= vstack.depth) {
    // 가상 스택에서만 팝 — 실제 스택 불변
    uint32_t remaining = vstack.depth - pop_count;
    TSStateId goto_base = (remaining > 0) ? vstack.states[remaining - 1] : real_node->state;
    TSStateId next = ts_language_lookup(language, goto_base, symbol);
    if (next != 0) {
      VStack nv;
      nv.depth = remaining;
      for (uint32_t k = 0; k < remaining; k++) nv.states[k] = vstack.states[k];
      if (nv.depth < MAX_VDEPTH) nv.states[nv.depth++] = next;
      simulate_with_vstack(next, real_node, nv, language, result, visited);
    }
    return;
  }

  // 가상 스택 소진 후 나머지는 실제 스택에서 팝
  // simulate_reduce_pop_dfs가 is_virtual=true로 GOTO 처리하므로 위임
  uint32_t real_pops = pop_count - vstack.depth;
  simulate_reduce_pop_dfs(real_node, real_pops, symbol, language, result, visited);
}

// state에서 external SHIFT 체인(깊이 1~2)을 가상으로 따라가며 simulate
static void simulate_ext_shift_chains(
  TSStateId state,
  StackNode *real_node,
  const TSLanguage *language,
  TSStatePath *result,
  VisitedSet *visited,
  uint64_t zero_byte_ext_mask   // 실제 파싱 중 size==0으로 관측된 external token 인덱스 bitmask
) {
  // depth-1: state에서 0-byte external token SHIFT → s1
  // zero_byte_ext_mask: 파싱 중 실제로 size==0으로 반환된 external token만 포함
  // mask가 0이면 fallback으로 visible==false 기준 사용 (파싱 데이터가 없는 경우 대비)
  bool use_mask = (zero_byte_ext_mask != 0);

  for (uint32_t ei = 0; ei < language->external_token_count; ei++) {
    // 0-byte 여부 판별
    if (use_mask) {
      // 실제 파싱에서 관측된 0-byte 토큰만 허용
      if (ei >= 64 || !(zero_byte_ext_mask & (1ULL << ei))) continue;
    } else {
      // fallback: visible=true는 확실히 byte-consuming
      TSSymbol ext_sym = language->external_scanner.symbol_map[ei];
      if (language->symbol_metadata[ext_sym].visible) continue;
    }

    TSSymbol ext = language->external_scanner.symbol_map[ei];

    uint32_t idx = ts_language_lookup(language, state, ext);
    if (idx == 0) continue;

    const TSParseActionEntry *entry = &language->parse_actions[idx];
    const TSParseAction *acts = (const TSParseAction *)(entry + 1);
    TSStateId s1 = 0;
    for (uint32_t a = 0; a < entry->entry.count; a++) {
      if (acts[a].type == TSParseActionTypeShift && !acts[a].shift.extra) {
        s1 = acts[a].shift.state;
        break;
      }
    }
    if (s1 == 0) continue;

    // depth-1: vstack=[s1]
    VStack v1 = { .depth = 1 };
    v1.states[0] = s1;
    simulate_with_vstack(s1, real_node, v1, language, result, visited);

    // depth-2: s1에 non-extra REDUCE가 없는 경우에만 (=반드시 SHIFT해야 진행 가능)
    // s1에서 가능한 terminal SHIFT → s2, vstack=[s1, s2]
    bool s1_has_reduce = false;
    for (TSSymbol sym = 0; sym < language->token_count; sym++) {
      uint32_t chk = ts_language_lookup(language, s1, sym);
      if (chk == 0) continue;
      const TSParseActionEntry *ce = &language->parse_actions[chk];
      const TSParseAction *ca = (const TSParseAction *)(ce + 1);
      for (uint32_t k = 0; k < ce->entry.count; k++) {
        if (ca[k].type == TSParseActionTypeReduce) { s1_has_reduce = true; break; }
      }
      if (s1_has_reduce) break;
    }
    if (s1_has_reduce) continue;

    for (TSSymbol sym2 = 0; sym2 < language->token_count; sym2++) {
      uint32_t idx2 = ts_language_lookup(language, s1, sym2);
      if (idx2 == 0) continue;
      const TSParseActionEntry *e2 = &language->parse_actions[idx2];
      const TSParseAction *acts2 = (const TSParseAction *)(e2 + 1);
      TSStateId s2 = 0;
      for (uint32_t b = 0; b < e2->entry.count; b++) {
        if (acts2[b].type == TSParseActionTypeShift && !acts2[b].shift.extra) {
          s2 = acts2[b].shift.state;
          break;
        }
      }
      if (s2 == 0) continue;
      VStack v2 = { .depth = 2 };
      v2.states[0] = s1;
      v2.states[1] = s2;
      simulate_with_vstack(s2, real_node, v2, language, result, visited);
    }
  }
}

// ts_stack_simulate_conversion  (공개 진입점)
// 하나의 스택 버전에 대해 시뮬레이션을 수행하고
// 도달 가능한 모든 current_state를 반환
TSStatePath ts_stack_simulate_conversion(
  Stack *self,
  StackVersion version,
  const TSLanguage *language,
  uint64_t zero_byte_ext_mask
) {
  TSStatePath current_states = {0};
  if (version >= self->heads.size) return current_states;
  StackHead *head = array_get(&self->heads, version);
  if (!head || !head->node) return current_states;

  VisitedSet visited = {0};

  simulate_current_states_dfs(
    head->node->state,    // 현재 상태
    head->node,           // 현재 노드
    false,                // 실제 스택 top
    language,
    &current_states,
    &visited
  );

  // 0-byte external SHIFT 체인 확장 시뮬레이션 (별도 visited set 사용)
  VisitedSet ext_visited = {0};
  simulate_ext_shift_chains(
    head->node->state,
    head->node,
    language,
    &current_states,
    &ext_visited,
    zero_byte_ext_mask
  );

  return current_states;
}

#undef forceinline
