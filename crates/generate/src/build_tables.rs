// 이름을 번호로 변경한 부분을 찾던가, GPT에게 물어봐보자.

mod build_lex_table;
mod build_parse_table;
mod coincident_tokens;
mod item;
mod item_set_builder;
mod minimize_parse_table;
mod token_conflicts;

use std::collections::{BTreeSet, HashMap};
use std::io::{self, Write};
use std::fs::File;

pub use build_lex_table::LARGE_CHARACTER_RANGE_COUNT;
use build_parse_table::BuildTableResult;
pub use build_parse_table::ParseTableBuilderError;
use log::info;

use self::{
    build_lex_table::build_lex_table,
    build_parse_table::{build_parse_table, ParseStateInfo},
    coincident_tokens::CoincidentTokenIndex,
    item_set_builder::ParseItemSetBuilder,
    minimize_parse_table::minimize_parse_table,
    token_conflicts::TokenConflictMap,
};
use crate::{
    grammars::{InlinedProductionMap, LexicalGrammar, SyntaxGrammar, InputGrammar},
    nfa::{CharacterSet, NfaCursor},
    node_types::VariableInfo,
    rules::{AliasMap, Symbol, SymbolType, TokenSet},
    tables::{LexTable, ParseAction, ParseTable, ParseTableEntry, GotoAction},
};

pub struct Tables {
    pub parse_table: ParseTable,
    pub main_lex_table: LexTable,
    pub keyword_lex_table: LexTable,
    pub large_character_sets: Vec<(Option<Symbol>, CharacterSet)>,
}

pub fn build_tables(
    syntax_grammar: &SyntaxGrammar,
    lexical_grammar: &LexicalGrammar,
    input_grammar: &InputGrammar,
    simple_aliases: &AliasMap,
    variable_info: &[VariableInfo],
    inlines: &InlinedProductionMap,
    report_symbol_name: Option<&str>,
) -> BuildTableResult<Tables> {
    let item_set_builder = ParseItemSetBuilder::new(syntax_grammar, lexical_grammar, inlines);
    let following_tokens =
        get_following_tokens(syntax_grammar, lexical_grammar, inlines, &item_set_builder);
    let (mut parse_table, parse_state_info) = build_parse_table(
        syntax_grammar,
        lexical_grammar,
        item_set_builder,
        variable_info,
    )?;
    let token_conflict_map = TokenConflictMap::new(lexical_grammar, following_tokens);
    let coincident_token_index = CoincidentTokenIndex::new(&parse_table, lexical_grammar);
    let keywords = identify_keywords(
        lexical_grammar,
        &parse_table,
        syntax_grammar.word_token,
        &token_conflict_map,
        &coincident_token_index,
    );
    populate_error_state(
        &mut parse_table,
        syntax_grammar,
        lexical_grammar,
        &coincident_token_index,
        &token_conflict_map,
        &keywords,
    );
    populate_used_symbols(&mut parse_table, syntax_grammar, lexical_grammar);
    minimize_parse_table(
        &mut parse_table,
        syntax_grammar,
        lexical_grammar,
        simple_aliases,
        &token_conflict_map,
        &keywords,
    );
    let lex_tables = build_lex_table(
        &mut parse_table,
        syntax_grammar,
        lexical_grammar,
        &keywords,
        &coincident_token_index,
        &token_conflict_map,
    );
    populate_external_lex_states(&mut parse_table, syntax_grammar);
    mark_fragile_tokens(&mut parse_table, lexical_grammar, &token_conflict_map);

    if let Some(report_symbol_name) = report_symbol_name {
        report_state_info(
            syntax_grammar,
            lexical_grammar,
            &parse_table,
            &parse_state_info,
            report_symbol_name,
        );
    }

    // let mut file_lexical_grammar = File::create("saved_lexical_grammar.txt").expect("Unable to create file");
    // writeln!(file_lexical_grammar, "{:?}", lexical_grammar).expect("Unable to write to file");
    
    // let mut file_syntax_grammar = File::create("saved_syntax_grammar.txt").expect("Unable to create file");
    // writeln!(file_syntax_grammar, "{:?}", syntax_grammar).expect("Unable to write to file");

    // let mut file_parse_state_info = File::create("saved_parse_state_info.txt").expect("Unable to create file");
    // writeln!(file_parse_state_info, "{:?}", parse_state_info).expect("Unable to write to file");

    // let mut file_parse_table = File::create("saved_parse_table.txt").expect("Unable to create file"); 
    // writeln!(file_parse_table, "{:?}", parse_table).expect("Unable to write to file");

    // let mut file_lexical_grammar = File::create("saved_lexical_grammar.txt").expect("Unable to create file");
    // writeln!(file_lexical_grammar, "{:#?}", lexical_grammar).expect("Unable to write to file");

    // let mut file_syntax_grammar = File::create("saved_syntax_grammar.txt").expect("Unable to create file");
    // writeln!(file_syntax_grammar, "{:#?}", syntax_grammar).expect("Unable to write to file");

    // let mut file_parse_state_info = File::create("saved_parse_state_info.txt").expect("Unable to create file");
    // writeln!(file_parse_state_info, "{:#?}", parse_state_info).expect("Unable to write to file");

    // let mut file_parse_table = File::create("saved_parse_table.txt").expect("Unable to create file");
    // writeln!(file_parse_table, "{:#?}", parse_table).expect("Unable to write to file");

    // 렉서의 정규식, 파서의 문법, 파서 상태(LR 아이템) 이런 정보들이 구조체에 저장되어 있다.     
    let mut file_lexical_grammar = File::create("saved_lexical_grammar.txt").expect("Unable to create file");
    writeln!(file_lexical_grammar, "{:#?}", lexical_grammar).expect("Unable to write to file");

    let mut file_syntax_grammar = File::create("saved_syntax_grammar.txt").expect("Unable to create file");
    writeln!(file_syntax_grammar, "{:#?}", syntax_grammar).expect("Unable to write to file");

    let mut file_parse_state_info = File::create("saved_parse_state_info.txt").expect("Unable to create file");

    let mut file_parse_state_info_name = File::create("saved_parse_state_info_name.txt")
        .expect("Unable to create file");

    let mut file_parse_state_info_pretty = File::create("saved_parse_state_info_pretty.txt")
        .expect("Unable to create file");

    // --- Pretty dump for lexical grammar ---
    let mut file_lexical_grammar_pretty = File::create("saved_lexical_grammar_pretty.txt")
        .expect("Unable to create file");
    dump_lexical_grammar_pretty(&mut file_lexical_grammar_pretty, lexical_grammar)
        .expect("Unable to write lexical grammar pretty dump");

    // --- Pretty dump for syntax grammar ---
    let mut file_syntax_grammar_pretty = File::create("saved_syntax_grammar_pretty.txt").expect("Unable to create file");
    dump_syntax_grammar_pretty( &mut file_syntax_grammar_pretty, syntax_grammar, lexical_grammar,)
        .expect("Unable to write syntax grammar pretty dump");

    // for (i, state_info) in parse_state_info.iter().enumerate() {
    //     writeln!(file_parse_state_info, "==============================").unwrap();
    //     writeln!(file_parse_state_info, "Parse State #{}", i).unwrap();
    //     writeln!(file_parse_state_info, "------------------------------").unwrap();
    //     writeln!(file_parse_state_info, "{:#?}", state_info).unwrap();
    //     writeln!(file_parse_state_info).unwrap();
    // }

    // for (i, state_info) in parse_state_info.iter().enumerate() {
    //     writeln!(file_parse_state_info, "==============================").unwrap();
    //     writeln!(file_parse_state_info, "Parse State #{}", i).unwrap();
    //     writeln!(file_parse_state_info, "------------------------------").unwrap();
    //     //writeln!(file_parse_state_info, "{:#?}", state_info).unwrap();
    //     /*
    //         1. state_info 에서 ParseItemSet을 가져오기
    //         2. foreach parseItemSetEntry in ParseItemSet
    //             2.1 variable index 숫자를 non-terminal 이름을 가져와 출력
    //             2.2 step에 있는 심볼들을 문자열로 바꿔 출력 (이름 가져오기)
    //             2.3 rhs에서 step_index 만큼 지난 다음 . 찍기
    //         3. 주변상황 확인하기
    //      */
    //     writeln!(file_parse_state_info).unwrap();
    // }

    // save_parse_state_info.txt
    for (i, state_info) in parse_state_info.iter().enumerate() 
    {
        writeln!(file_parse_state_info, "Parse State #{}", i).unwrap();

        // 1. state_info (튜플)에서 ParseItemSet을 가져옵니다.
        //    (Vec<Symbol>, ParseItemSet) 형태라고 가정합니다.
        let item_set = &state_info.1;

        // 2. foreach parseItemSetEntry in ParseItemSet
        for entry in &item_set.entries {
            let item = &entry.item;

            // 2.1 variable index 숫자를 non-terminal 이름 대신 출력
            //     (u32::MAX는 S' -> .S 와 같은 증강된 시작 규칙을 의미)
            let lhs_str = if item.variable_index == u32::MAX {
                "ACCEPT".to_string()
            } else {
                format!("Variable({})", item.variable_index)
            };

            let mut rhs_string = String::new();

            // 2.2 step에 있는 심볼들을 문자열(Debug 포맷)로 바꿔 출력
            for (step_index, step) in item.production.steps.iter().enumerate() {
                
                // 2.3 rhs에서 step_index 만큼 지난 다음 . 찍기
                if step_index == (item.step_index as usize) {
                    rhs_string.push_str(". ");
                }
                
                // 심볼의 kind와 index를 직접 포맷팅합니다.
                rhs_string.push_str(&format!(
                    "{:?}({})", 
                    step.symbol.kind, 
                    step.symbol.index
                ));
                rhs_string.push(' ');
            }

            // 만약 점(.)이 규칙의 맨 끝에 와야 한다면 (Reduce 아이템)
            if (item.step_index as usize) == item.production.steps.len() {
                rhs_string.push_str(". ");
            }

            // 최종 포맷으로 출력 (::= 대신 -> 사용)
            writeln!(
                file_parse_state_info,
                "    {} -> {}", // "::=" 에서 "->" 로 변경
                lhs_str,
                rhs_string.trim_end()
            ).unwrap();

            // --- [수정된 부분] ---
            // 3. Lookaheads 출력 로직 전체를 삭제(또는 주석 처리)합니다.
            /*
            let mut lookaheads_str = String::from("    Lookaheads: [");
            let mut first = true;
            for symbol in entry.lookaheads.iter() {
                if !first {
                    lookaheads_str.push_str(", ");
                }
                lookaheads_str.push_str(&format!(
                    "{:?}({})",
                    symbol.kind,
                    symbol.index
                ));
                first = false;
            }
            lookaheads_str.push(']');
            writeln!(file_parse_state_info, "{}", lookaheads_str).unwrap();
            */
            // --- [수정 끝] ---

        } // end for entry

        writeln!(file_parse_state_info).unwrap(); // ParseItemSetEntry 간의 줄바꿈 (이것은 유지)
    } // end for state_info
    // lhs -> rhs . rhs' 포멧

    // save_parse_state_info_name.txt
    for (i, state_info) in parse_state_info.iter().enumerate() {
        writeln!(file_parse_state_info_name, "Parse State #{}", i).unwrap();

        let item_set = &state_info.1;

        for entry in &item_set.entries {
            let item = &entry.item;

            // LHS: Non-terminal 이름 + 인덱스
            let lhs_str = if item.variable_index == u32::MAX {
                "ACCEPT".to_string()
            } else {
                let idx = item.variable_index as usize;
                if let Some(var) = syntax_grammar.variables.get(idx) {
                    // 예: Stmt(NT#4)
                    format!("{}(NT#{})", var.name, item.variable_index)
                } else {
                    format!("NonTerminal({})", item.variable_index)
                }
            };

            let mut rhs_string = String::new();

            for (step_index, step) in item.production.steps.iter().enumerate() {
                // 점(.) 위치
                if step_index == (item.step_index as usize) {
                    rhs_string.push_str(". ");
                }

                // 각 심볼을 “이름(인덱스)” 형태로 변환
                let sym_str = symbol_to_readable_string(step.symbol, syntax_grammar, lexical_grammar);
                rhs_string.push_str(&sym_str);
                rhs_string.push(' ');
            }

            // Reduce 아이템이면 끝에 점(.) 추가
            if (item.step_index as usize) == item.production.steps.len() {
                rhs_string.push_str(". ");
            }
            

            writeln!(
                file_parse_state_info_name,
                "    {} -> {}",
                lhs_str,
                rhs_string.trim_end()
            ).unwrap();
        }

        writeln!(file_parse_state_info_name).unwrap();
    }    

    // save_parse_state_info_pretty.txt
    for (i, state_info) in parse_state_info.iter().enumerate() {
        writeln!(file_parse_state_info_pretty, "Parse State #{}", i).unwrap();

        let item_set = &state_info.1;

        for entry in &item_set.entries {
            let item = &entry.item;

            // LHS: Non-terminal 이름 + 인덱스
            let lhs_str = if item.variable_index == u32::MAX {
                "ACCEPT".to_string()
            } else {
                let idx = item.variable_index as usize;
                if let Some(var) = syntax_grammar.variables.get(idx) {
                    format!("{}(NT#{})", var.name, item.variable_index)
                } else {
                    format!("NonTerminal({})", item.variable_index)
                }
            };

            let mut rhs_string = String::new();

            for (step_index, step) in item.production.steps.iter().enumerate() {
                // 점(.) 위치 표시
                if step_index == (item.step_index as usize) {
                    rhs_string.push_str(". ");
                }

                // ★ 수정된 부분: get_pretty_symbol_name 사용
                let mut sym_str = get_pretty_symbol_name(
                    step.symbol, 
                    syntax_grammar, 
                    lexical_grammar
                );

                rhs_string.push_str(&sym_str);
                rhs_string.push(' ');
            }

            // Reduce 아이템이면 끝에 점(.) 추가
            if (item.step_index as usize) == item.production.steps.len() {
                rhs_string.push_str(". ");
            }

            writeln!(
                file_parse_state_info_pretty,
                "    {} -> {}",
                lhs_str,
                rhs_string.trim_end()
            ).unwrap();
        }

        writeln!(file_parse_state_info_pretty).unwrap();
    }
    
    // parse table에 있는 shift, reduce 액션 분석
    let mut file_parse_table = File::create("saved_parse_table.txt")
        .expect("Unable to create file");
    writeln!(file_parse_table, "{:#?}", parse_table)
        .expect("Unable to write to file");

    // parse_table_pretty
    let mut file_parse_table_pretty = File::create("saved_parse_table_pretty.txt")
        .expect("Unable to create file");
    dump_parse_table_pretty(&mut file_parse_table_pretty,&parse_table,syntax_grammar,lexical_grammar,)
        .expect("Unable to write parse_table_pretty");

    // action_table.txt
    let mut f = File::create("saved_action_table.txt").expect("Unable to create action_table.txt");
    dump_action_table(&mut f, &parse_table, syntax_grammar, lexical_grammar)
        .expect("Unable to write action_table.txt");

    // goto_table.txt
    let mut f = File::create("saved_goto_table.txt").expect("Unable to create goto_table.txt");
    dump_goto_table(&mut f, &parse_table, syntax_grammar)
        .expect("Unable to write goto_table.txt");

    // prod_rules.txt
    let mut f = File::create("saved_prod_rules.txt").expect("Unable to create prod_rules.txt");
    dump_prod_rules(&mut f, syntax_grammar, lexical_grammar)
        .expect("Unable to write prod_rules.txt");

    Ok(Tables {
        parse_table,
        main_lex_table: lex_tables.main_lex_table,
        keyword_lex_table: lex_tables.keyword_lex_table,
        large_character_sets: lex_tables.large_character_sets,
    })
}

fn get_following_tokens(
    syntax_grammar: &SyntaxGrammar,
    lexical_grammar: &LexicalGrammar,
    inlines: &InlinedProductionMap,
    builder: &ParseItemSetBuilder,
) -> Vec<TokenSet> {
    let mut result = vec![TokenSet::new(); lexical_grammar.variables.len()];
    let productions = syntax_grammar
        .variables
        .iter()
        .flat_map(|v| &v.productions)
        .chain(&inlines.productions);
    let all_tokens = (0..result.len())
        .map(Symbol::terminal)
        .collect::<TokenSet>();
    for production in productions {
        for i in 1..production.steps.len() {
            let left_tokens = builder.last_set(&production.steps[i - 1].symbol);
            let right_tokens = builder.first_set(&production.steps[i].symbol);
            let right_reserved_tokens = builder.reserved_first_set(&production.steps[i].symbol);
            for left_token in left_tokens.iter() {
                if left_token.is_terminal() {
                    result[left_token.index].insert_all_terminals(right_tokens);
                    if let Some(reserved_tokens) = right_reserved_tokens {
                        result[left_token.index].insert_all_terminals(reserved_tokens);
                    }
                }
            }
        }
    }
    for extra in &syntax_grammar.extra_symbols {
        if extra.is_terminal() {
            for entry in &mut result {
                entry.insert(*extra);
            }
            result[extra.index] = all_tokens.clone();
        }
    }
    result
}

fn populate_error_state(
    parse_table: &mut ParseTable,
    syntax_grammar: &SyntaxGrammar,
    lexical_grammar: &LexicalGrammar,
    coincident_token_index: &CoincidentTokenIndex,
    token_conflict_map: &TokenConflictMap,
    keywords: &TokenSet,
) {
    let state = &mut parse_table.states[0];
    let n = lexical_grammar.variables.len();

    // First identify the *conflict-free tokens*: tokens that do not overlap with
    // any other token in any way, besides matching exactly the same string.
    let conflict_free_tokens = (0..n)
        .filter_map(|i| {
            let conflicts_with_other_tokens = (0..n).any(|j| {
                j != i
                    && !coincident_token_index.contains(Symbol::terminal(i), Symbol::terminal(j))
                    && token_conflict_map.does_match_shorter_or_longer(i, j)
            });
            if conflicts_with_other_tokens {
                None
            } else {
                info!(
                    "error recovery - token {} has no conflicts",
                    lexical_grammar.variables[i].name
                );
                Some(Symbol::terminal(i))
            }
        })
        .collect::<TokenSet>();

    let recover_entry = ParseTableEntry {
        reusable: false,
        actions: vec![ParseAction::Recover],
    };

    // Exclude from the error-recovery state any token that conflicts with one of
    // the *conflict-free tokens* identified above.
    for i in 0..n {
        let symbol = Symbol::terminal(i);
        if !conflict_free_tokens.contains(&symbol)
            && !keywords.contains(&symbol)
            && syntax_grammar.word_token != Some(symbol)
        {
            if let Some(t) = conflict_free_tokens.iter().find(|t| {
                !coincident_token_index.contains(symbol, *t)
                    && token_conflict_map.does_conflict(symbol.index, t.index)
            }) {
                info!(
                    "error recovery - exclude token {} because of conflict with {}",
                    lexical_grammar.variables[i].name, lexical_grammar.variables[t.index].name
                );
                continue;
            }
        }
        info!(
            "error recovery - include token {}",
            lexical_grammar.variables[i].name
        );
        state
            .terminal_entries
            .entry(symbol)
            .or_insert_with(|| recover_entry.clone());
    }

    for (i, external_token) in syntax_grammar.external_tokens.iter().enumerate() {
        if external_token.corresponding_internal_token.is_none() {
            state
                .terminal_entries
                .entry(Symbol::external(i))
                .or_insert_with(|| recover_entry.clone());
        }
    }

    state.terminal_entries.insert(Symbol::end(), recover_entry);
}

fn populate_used_symbols(
    parse_table: &mut ParseTable,
    syntax_grammar: &SyntaxGrammar,
    lexical_grammar: &LexicalGrammar,
) {
    let mut terminal_usages = vec![false; lexical_grammar.variables.len()];
    let mut non_terminal_usages = vec![false; syntax_grammar.variables.len()];
    let mut external_usages = vec![false; syntax_grammar.external_tokens.len()];
    for state in &parse_table.states {
        for symbol in state.terminal_entries.keys() {
            match symbol.kind {
                SymbolType::Terminal => terminal_usages[symbol.index] = true,
                SymbolType::External => external_usages[symbol.index] = true,
                _ => {}
            }
        }
        for symbol in state.nonterminal_entries.keys() {
            non_terminal_usages[symbol.index] = true;
        }
    }
    parse_table.symbols.push(Symbol::end());
    for (i, value) in terminal_usages.into_iter().enumerate() {
        if value {
            // Assign the grammar's word token a low numerical index. This ensures that
            // it can be stored in a subtree with no heap allocations, even for grammars with
            // very large numbers of tokens. This is an optimization, but it's also important to
            // ensure that a subtree's symbol can be successfully reassigned to the word token
            // without having to move the subtree to the heap.
            // See https://github.com/tree-sitter/tree-sitter/issues/258
            if syntax_grammar.word_token.is_some_and(|t| t.index == i) {
                parse_table.symbols.insert(1, Symbol::terminal(i));
            } else {
                parse_table.symbols.push(Symbol::terminal(i));
            }
        }
    }
    for (i, value) in external_usages.into_iter().enumerate() {
        if value {
            parse_table.symbols.push(Symbol::external(i));
        }
    }
    for (i, value) in non_terminal_usages.into_iter().enumerate() {
        if value {
            parse_table.symbols.push(Symbol::non_terminal(i));
        }
    }
}

fn populate_external_lex_states(parse_table: &mut ParseTable, syntax_grammar: &SyntaxGrammar) {
    let mut external_tokens_by_corresponding_internal_token = HashMap::new();
    for (i, external_token) in syntax_grammar.external_tokens.iter().enumerate() {
        if let Some(symbol) = external_token.corresponding_internal_token {
            external_tokens_by_corresponding_internal_token.insert(symbol.index, i);
        }
    }

    // Ensure that external lex state 0 represents the absence of any
    // external tokens.
    parse_table.external_lex_states.push(TokenSet::new());

    for i in 0..parse_table.states.len() {
        let mut external_tokens = TokenSet::new();
        for token in parse_table.states[i].terminal_entries.keys() {
            if token.is_external() {
                external_tokens.insert(*token);
            } else if token.is_terminal() {
                if let Some(index) =
                    external_tokens_by_corresponding_internal_token.get(&token.index)
                {
                    external_tokens.insert(Symbol::external(*index));
                }
            }
        }

        parse_table.states[i].external_lex_state_id = parse_table
            .external_lex_states
            .iter()
            .position(|tokens| *tokens == external_tokens)
            .unwrap_or_else(|| {
                parse_table.external_lex_states.push(external_tokens);
                parse_table.external_lex_states.len() - 1
            });
    }
}

fn identify_keywords(
    lexical_grammar: &LexicalGrammar,
    parse_table: &ParseTable,
    word_token: Option<Symbol>,
    token_conflict_map: &TokenConflictMap,
    coincident_token_index: &CoincidentTokenIndex,
) -> TokenSet {
    if word_token.is_none() {
        return TokenSet::new();
    }

    let word_token = word_token.unwrap();
    let mut cursor = NfaCursor::new(&lexical_grammar.nfa, Vec::new());

    // First find all of the candidate keyword tokens: tokens that start with
    // letters or underscore and can match the same string as a word token.
    let keyword_candidates = lexical_grammar
        .variables
        .iter()
        .enumerate()
        .filter_map(|(i, variable)| {
            cursor.reset(vec![variable.start_state]);
            if all_chars_are_alphabetical(&cursor)
                && token_conflict_map.does_match_same_string(i, word_token.index)
                && !token_conflict_map.does_match_different_string(i, word_token.index)
            {
                info!(
                    "Keywords - add candidate {}",
                    lexical_grammar.variables[i].name
                );
                Some(Symbol::terminal(i))
            } else {
                None
            }
        })
        .collect::<TokenSet>();

    // Exclude keyword candidates that shadow another keyword candidate.
    let keywords = keyword_candidates
        .iter()
        .filter(|token| {
            for other_token in keyword_candidates.iter() {
                if other_token != *token
                    && token_conflict_map.does_match_same_string(other_token.index, token.index)
                {
                    info!(
                        "Keywords - exclude {} because it matches the same string as {}",
                        lexical_grammar.variables[token.index].name,
                        lexical_grammar.variables[other_token.index].name
                    );
                    return false;
                }
            }
            true
        })
        .collect::<TokenSet>();

    // Exclude keyword candidates for which substituting the keyword capture
    // token would introduce new lexical conflicts with other tokens.
    let keywords = keywords
        .iter()
        .filter(|token| {
            for other_index in 0..lexical_grammar.variables.len() {
                if keyword_candidates.contains(&Symbol::terminal(other_index)) {
                    continue;
                }

                // If the word token was already valid in every state containing
                // this keyword candidate, then substituting the word token won't
                // introduce any new lexical conflicts.
                if coincident_token_index
                    .states_with(*token, Symbol::terminal(other_index))
                    .iter()
                    .all(|state_id| {
                        parse_table.states[*state_id]
                            .terminal_entries
                            .contains_key(&word_token)
                    })
                {
                    continue;
                }

                if !token_conflict_map.has_same_conflict_status(
                    token.index,
                    word_token.index,
                    other_index,
                ) {
                    info!(
                        "Keywords - exclude {} because of conflict with {}",
                        lexical_grammar.variables[token.index].name,
                        lexical_grammar.variables[other_index].name
                    );
                    return false;
                }
            }

            info!(
                "Keywords - include {}",
                lexical_grammar.variables[token.index].name,
            );
            true
        })
        .collect();

    keywords
}

fn mark_fragile_tokens(
    parse_table: &mut ParseTable,
    lexical_grammar: &LexicalGrammar,
    token_conflict_map: &TokenConflictMap,
) {
    let n = lexical_grammar.variables.len();
    let mut valid_tokens_mask = Vec::with_capacity(n);
    for state in &mut parse_table.states {
        valid_tokens_mask.clear();
        valid_tokens_mask.resize(n, false);
        for token in state.terminal_entries.keys() {
            if token.is_terminal() {
                valid_tokens_mask[token.index] = true;
            }
        }
        for (token, entry) in &mut state.terminal_entries {
            if token.is_terminal() {
                for (i, is_valid) in valid_tokens_mask.iter().enumerate() {
                    if *is_valid && token_conflict_map.does_overlap(i, token.index) {
                        entry.reusable = false;
                        break;
                    }
                }
            }
        }
    }
}

fn report_state_info<'a>(
    syntax_grammar: &SyntaxGrammar,
    lexical_grammar: &LexicalGrammar,
    parse_table: &ParseTable,
    parse_state_info: &[ParseStateInfo<'a>],
    report_symbol_name: &'a str,
) {
    let mut all_state_indices = BTreeSet::new();
    let mut symbols_with_state_indices = (0..syntax_grammar.variables.len())
        .map(|i| (Symbol::non_terminal(i), BTreeSet::new()))
        .collect::<Vec<_>>();

    for (i, state) in parse_table.states.iter().enumerate() {
        all_state_indices.insert(i);
        let item_set = &parse_state_info[state.id];
        for entry in &item_set.1.entries {
            if !entry.item.is_augmented() {
                symbols_with_state_indices[entry.item.variable_index as usize]
                    .1
                    .insert(i);
            }
        }
    }

    symbols_with_state_indices.sort_unstable_by_key(|(_, states)| -(states.len() as i32));

    let max_symbol_name_length = syntax_grammar
        .variables
        .iter()
        .map(|v| v.name.len())
        .max()
        .unwrap();
    for (symbol, states) in &symbols_with_state_indices {
        eprintln!(
            "{:width$}\t{}",
            syntax_grammar.variables[symbol.index].name,
            states.len(),
            width = max_symbol_name_length
        );
    }
    eprintln!();

    let state_indices = if report_symbol_name == "*" {
        Some(&all_state_indices)
    } else {
        symbols_with_state_indices
            .iter()
            .find_map(|(symbol, state_indices)| {
                if syntax_grammar.variables[symbol.index].name == report_symbol_name {
                    Some(state_indices)
                } else {
                    None
                }
            })
    };

    if let Some(state_indices) = state_indices {
        let mut state_indices = state_indices.iter().copied().collect::<Vec<_>>();
        state_indices.sort_unstable_by_key(|i| (parse_table.states[*i].core_id, *i));

        for state_index in state_indices {
            let id = parse_table.states[state_index].id;
            let (preceding_symbols, item_set) = &parse_state_info[id];
            eprintln!("state index: {state_index}");
            eprintln!("state id: {id}");
            eprint!("symbol sequence:");
            for symbol in preceding_symbols {
                let name = if symbol.is_terminal() {
                    &lexical_grammar.variables[symbol.index].name
                } else if symbol.is_external() {
                    &syntax_grammar.external_tokens[symbol.index].name
                } else {
                    &syntax_grammar.variables[symbol.index].name
                };
                eprint!(" {name}");
            }
            eprintln!(
                "\nitems:\n{}",
                item::ParseItemSetDisplay(item_set, syntax_grammar, lexical_grammar),
            );
        }
    }
}

fn all_chars_are_alphabetical(cursor: &NfaCursor) -> bool {
    cursor.transition_chars().all(|(chars, is_sep)| {
        if is_sep {
            true
        } else {
            chars.chars().all(|c| c.is_alphabetic() || c == '_')
        }
    })
}

// save_parse_state_name.txt 유틸 함수
fn symbol_to_readable_string(
    symbol: Symbol,
    syntax_grammar: &SyntaxGrammar,
    lexical_grammar: &LexicalGrammar,
) -> String {
    match symbol.kind {
        SymbolType::NonTerminal => {
            // 논터미널: syntax_grammar.variables[index].name 을 사용
            if let Some(var) = syntax_grammar.variables.get(symbol.index) {
                format!("{}(NT#{})", var.name, symbol.index)
            } else {
                format!("NonTerminal({})", symbol.index)
            }
        }
        SymbolType::Terminal => {
            // 터미널: lexical_grammar.variables[index].name 을 우선 사용
            if let Some(var) = lexical_grammar.variables.get(symbol.index) {
                if !var.name.is_empty() {
                    // grammar.js 에서 이름 붙은 토큰인 경우
                    format!("{}(T#{})", var.name, symbol.index)
                } else {
                    // 이름이 없는(정규식 기반) 토큰
                    format!("Terminal({})", symbol.index)
                }
            } else {
                format!("Terminal({})", symbol.index)
            }
        }
        SymbolType::External => {
            // external scanner 토큰
            if let Some(ext) = syntax_grammar.external_tokens.get(symbol.index) {
                format!("{}[ext#{}]", ext.name, symbol.index)
            } else {
                format!("External({})", symbol.index)
            }
        }
        SymbolType::End => {
            "END".to_string()
        }
        SymbolType::EndOfNonTerminalExtra => {
            "END_OF_NON_TERMINAL_EXTRA".to_string()
        }
    }
}


// save_parse_state_pretty.txt 유틸 함수
// 심볼을 출력용 문자열로 변환 (예: "#include(T#0)" 또는 "/regex/(T#1)")
fn get_pretty_symbol_name(
    symbol: Symbol,
    syntax_grammar: &SyntaxGrammar,
    lexical_grammar: &LexicalGrammar,
) -> String {
    use crate::rules::SymbolType;

    match symbol.kind {
        SymbolType::NonTerminal => {
            // 논터미널: syntax_grammar.variables[index].name
            if let Some(var) = syntax_grammar.variables.get(symbol.index) {
                format!("{}(NT#{})", var.name, symbol.index)
            } else {
                format!("NonTerminal({})", symbol.index)
            }
        }

        SymbolType::Terminal => {
            // 터미널: lexical_grammar.variables[index]에서
            // 1순위: source_content (정규식 / 리터럴)
            // 2순위: name (예: identifier, Stmt_token3 등)
            if let Some(lex) = lexical_grammar.variables.get(symbol.index) {
                if let Some(ref text) = lex.source_content {
                    // get_rule_content에서 "'if'" 또는 "/[Ff][Oo][Rr]/" 형태로 넣어둠
                    format!("{}(T#{})", text, symbol.index)
                } else {
                    // 원본 Rule 정보를 못 구하는 경우: 내부 이름이라도 출력
                    format!("{}(T#{})", lex.name, symbol.index)
                }
            } else {
                format!("Terminal({})", symbol.index)
            }
        }

        SymbolType::External => {
            // external scanner 토큰: 이름만 출력
            if let Some(ext) = syntax_grammar.external_tokens.get(symbol.index) {
                format!("{}[ext#{}]", ext.name, symbol.index)
            } else {
                format!("External({})", symbol.index)
            }
        }

        SymbolType::End => "END".to_string(),

        SymbolType::EndOfNonTerminalExtra => "END_OF_NON_TERMINAL_EXTRA".to_string(),
    }
}

fn dump_parse_table_pretty(
    w: &mut dyn Write,
    parse_table: &ParseTable,
    syntax_grammar: &SyntaxGrammar,
    lexical_grammar: &LexicalGrammar,
) -> io::Result<()> {
    for (state_id, state) in parse_table.states.iter().enumerate() {
        writeln!(w, "State #{}", state_id)?;
        writeln!(w, "  core_id: {}", state.core_id)?;
        writeln!(
            w,
            "  lex_state_id: {}, external_lex_state_id: {}",
            state.lex_state_id, state.external_lex_state_id
        )?;

        // --- 1) 터미널 액션들 ---
        writeln!(w, "  [Terminal actions]")?;
        for (sym, entry) in &state.terminal_entries {
            let sym_str = get_pretty_symbol_name(*sym, syntax_grammar, lexical_grammar);

            for action in &entry.actions {
                let action_str = match action {
                    ParseAction::Accept => "Accept".to_string(),

                    ParseAction::Shift { state, is_repetition } => {
                        if *is_repetition {
                            format!("Shift -> state {} (repetition)", state)
                        } else {
                            format!("Shift -> state {}", state)
                        }
                    }

                    ParseAction::ShiftExtra => "ShiftExtra".to_string(),

                    ParseAction::Recover => "Recover".to_string(),

                    ParseAction::Reduce {
                        symbol,
                        child_count,
                        dynamic_precedence,
                        production_id,
                    } => {
                        let lhs_name = if symbol.is_non_terminal() {
                            if let Some(var) = syntax_grammar.variables.get(symbol.index) {
                                format!("{}(NT#{})", var.name, symbol.index)
                            } else {
                                format!("NT#{}", symbol.index)
                            }
                        } else {
                            // 이 경우는 거의 안 나오지만 방어적으로
                            format!("{:?}#{}", symbol.kind, symbol.index)
                        };

                        format!(
                            "Reduce -> {} (children={})",   // dyn_prec={}, prod_id={}
                            lhs_name, child_count   // , dynamic_precedence, production_id
                        )
                    }
                };

                writeln!(w, "    on {} => {}", sym_str, action_str)?;
            }
        }

        // --- 2) Non-terminal goto ---
        writeln!(w, "  [Nonterminal gotos]")?;
        for (sym, goto) in &state.nonterminal_entries {
            let sym_str = get_pretty_symbol_name(*sym, syntax_grammar, lexical_grammar);
            match goto {
                GotoAction::Goto(next_state) => {
                    writeln!(w, "    goto {} => state {}", sym_str, next_state)?;
                }
                GotoAction::ShiftExtra => {
                    writeln!(w, "    goto {} => ShiftExtra", sym_str)?;
                }
            }
        }

        writeln!(w)?; // 상태 간 공백 줄
    }

    Ok(())
}

/// LexicalGrammar를 사람이 읽기 좋게 저장
fn dump_lexical_grammar_pretty(
    w: &mut dyn Write,
    lexical_grammar: &LexicalGrammar,
) -> io::Result<()> {
    writeln!(w, "Lexical tokens (terminals):")?;
    writeln!(w, "==========================")?;

    for (i, var) in lexical_grammar.variables.iter().enumerate() {
        // 1순위: 우리가 저장한 source_content (/'STEP'/, /[Ss][Tt][Ee][Pp]/ 등)
        // 2순위: 이름(name) – 예: identifier, OptStep_token1 등
        let text = if let Some(ref s) = var.source_content {
            s.as_str()
        } else {
            &var.name
        };

        writeln!(
            w,
            "T#{:<3}  {:<30}  kind={:?}, start_state={}",
            i,
            text,
            var.kind,
            var.start_state
        )?;
    }

    writeln!(w)?;
    writeln!(w, "NFA (states + transitions):")?;
    writeln!(w, "==========================")?;
    writeln!(w, "{:#?}", lexical_grammar.nfa)?;

    Ok(())
}

/// SyntaxGrammar를 BNF 스타일로 예쁘게 저장
fn dump_syntax_grammar_pretty(
    w: &mut dyn Write,
    syntax_grammar: &SyntaxGrammar,
    lexical_grammar: &LexicalGrammar,
) -> io::Result<()> {
    writeln!(w, "Syntax grammar (nonterminals & productions):")?;
    writeln!(w, "=========================================")?;

    for (nt_idx, var) in syntax_grammar.variables.iter().enumerate() {
        writeln!(w)?;
        writeln!(w, "{}(NT#{})", var.name, nt_idx)?;
        writeln!(w, "-----------------------------------------")?;

        for (prod_idx, prod) in var.productions.iter().enumerate() {
            // LHS
            write!(w, "  [{}] {} ->", prod_idx, var.name)?;

            if prod.steps.is_empty() {
                writeln!(w, " /* empty */")?;
                continue;
            }

            // RHS
            for step in &prod.steps {
                let sym_str = get_pretty_symbol_name(step.symbol, syntax_grammar, lexical_grammar);
                write!(w, " {}", sym_str)?;
            }

            writeln!(w)?;
        }
    }

    Ok(())
}


// fn step_reserved_sets(steps: &[crate::grammars::ProductionStep]) -> String {
//     let mut sets = steps
//         .iter()
//         .map(|s| s.reserved_word_set_id.0)
//         .collect::<Vec<_>>();
//     sets.sort();
//     sets.dedup();
//     if sets.is_empty() {
//         "-".to_string()
//     } else {
//         format!("{:?}", sets)
//     }
// }

/// action_table용 심볼 이름 (짧게)
fn terminal_display_name(sym: Symbol, lexical_grammar: &LexicalGrammar) -> String {
    match sym.kind {
        SymbolType::End => "$".to_string(), // EOF 심볼

        SymbolType::Terminal => {
            if let Some(var) = lexical_grammar.variables.get(sym.index) {
                // 1순위: 정규식 source_content가 있으면 그대로 출력
                if let Some(p) = &var.source_content {
                    return p.clone();  // "/regex/" 형태
                }

                // 2순위: 이름이 있으면 출력
                if !var.name.is_empty() {
                    return var.name.clone();
                }

                // 3순위: fallback
                format!("T#{}", sym.index)
            } else {
                format!("T#{}", sym.index)
            }
        }

        SymbolType::External => format!("External#{}", sym.index),

        // NonTerminal이 올 일은 없지만 방어 코드
        _ => format!("{:?}#{}", sym.kind, sym.index),
    }
}

fn dump_action_table(
    w: &mut dyn Write,
    parse_table: &ParseTable,
    syntax_grammar: &SyntaxGrammar,
    lexical_grammar: &LexicalGrammar,
) -> io::Result<()> {
    for (state_id, state) in parse_table.states.iter().enumerate() {
        for (sym, entry) in &state.terminal_entries {
            let term_name = terminal_display_name(*sym, lexical_grammar);

            // 한 (state, terminal)에 여러 액션이 있을 수 있어서 모두 출력
            for action in &entry.actions {
                let act_str = match action {
                    ParseAction::Accept => "Accept".to_string(),
                    ParseAction::Shift { state, .. } => format!("Shift {}", state),
                    ParseAction::ShiftExtra => "ShiftExtra".to_string(),
                    ParseAction::Recover => "Recover".to_string(),
                    ParseAction::Reduce {
                        symbol,
                        child_count,
                        dynamic_precedence,
                        production_id,
                    } => {
                        // 여기서는 간단하게 production_id도 같이 찍어두면 좋음
                        let lhs_name = if symbol.is_non_terminal() {
                            if let Some(var) = syntax_grammar.variables.get(symbol.index) {
                                var.name.clone()
                            } else {
                                format!("NT#{}", symbol.index)
                            }
                        } else {
                            format!("{:?}#{}", symbol.kind, symbol.index)
                        };
                        // 예: "Reduce Expression [prod=5,len=2]"
                        format!(
                            "Reduce {} [prod={}, len={}, dyn_prec={}]",
                            lhs_name, production_id, child_count, dynamic_precedence
                        )
                    }
                };

                // 탭 구분: state_id \t terminal_name \t Action...
                writeln!(w, "{}\t{}\t{}", state_id, term_name, act_str)?;
            }
        }
    }
    Ok(())
}

fn dump_goto_table(
    w: &mut dyn Write,
    parse_table: &ParseTable,
    syntax_grammar: &SyntaxGrammar,
) -> io::Result<()> {
    for (state_id, state) in parse_table.states.iter().enumerate() {
        for (sym, goto) in &state.nonterminal_entries {
            // sym은 NonTerminal이어야 함
            let nt_name = if sym.is_non_terminal() {
                if let Some(var) = syntax_grammar.variables.get(sym.index) {
                    var.name.clone()
                } else {
                    format!("NT#{}", sym.index)
                }
            } else {
                // 방어적 코드
                format!("{:?}#{}", sym.kind, sym.index)
            };

            if let GotoAction::Goto(next_state) = goto {
                writeln!(w, "{}\t{}\t{}", state_id, nt_name, next_state)?;
            } else {
            }
        }
    }
    Ok(())
}

fn dump_prod_rules(
    w: &mut dyn Write,
    syntax_grammar: &SyntaxGrammar,
    lexical_grammar: &LexicalGrammar,
) -> io::Result<()> {

    let mut global_idx = 0;

    for (nt_idx, var) in syntax_grammar.variables.iter().enumerate() {
        for (prod_idx, prod) in var.productions.iter().enumerate() {
            // "0: Expr -> ..." 이런 헤더
            write!(w, "{}: {} ->", global_idx, var.name)?;

            if prod.steps.is_empty() {
                writeln!(w, " /* empty */")?;
            } else {
                for step in &prod.steps {
                    let sym_str = get_pretty_symbol_name(step.symbol, syntax_grammar, lexical_grammar);
                    write!(w, " {}", sym_str)?;
                }
                writeln!(w)?;
            }
            writeln!(w)?;

            // // 디버깅용 주석, NT index / prod index
            // writeln!(
            //     w,
            //     "    ;; [nt_idx={}, nt_name={}, local_prod_idx={}]",
            //     nt_idx, var.name, prod_idx
            // )?;

            global_idx += 1;
        }
    }

    Ok(())
}
