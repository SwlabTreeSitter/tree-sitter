#ifndef TREE_SITTER_TREE_H_
#define TREE_SITTER_TREE_H_

#include "./subtree.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
  const Subtree *child;
  const Subtree *parent;
  Length position;
  TSSymbol alias_symbol;
} ParentCacheEntry;

struct TSTree {
  Subtree root;                   // Syntax Tree의 진입점
  const TSLanguage *language;     // 파싱에 사용된 언어
  TSRange *included_ranges;       // 분석 범위
  unsigned included_range_count;  // 범위 개수
};

TSTree *ts_tree_new(Subtree root, const TSLanguage *language, const TSRange *included_ranges, unsigned included_range_count);
TSNode ts_node_new(const TSTree *tree, const Subtree *subtree, Length position, TSSymbol alias);

#ifdef __cplusplus
}
#endif

#endif  // TREE_SITTER_TREE_H_
