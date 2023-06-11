from typing import List


def build_infill_prompt_for_funcs(changed_file, func_nodes: List, placeholder: str):
    """
    Infill prompt building of changed functions/methods (extracted from diff) for InCoder model.

    Params:
        - changed_file: PatchSet.File, where func_nodes are extracted from.
        - func_nodes: List[ASTNode], which are ast nodes of changed function.
        - placeholder: Infill placeholder (mask) to indicate changed place.
    """
    func_prompts = []
    for func_node in func_nodes:
        start_line, start_col = func_node.start_point
        end_line, end_col = func_node.end_point
        func_prompt = ''
        before_code_line = -1
        on_buggy_hunk = False
        for hunk in changed_file:
            for line in hunk:
                if line.is_context or line.is_removed:
                    before_code_line += 1
                # Entering func lines
                if start_line <= before_code_line <= end_line:
                    if line.value.strip() == '':
                        continue
                    if line.is_context:
                        if on_buggy_hunk:
                            func_prompt += f'{placeholder}\n'
                            on_buggy_hunk = False
                        func_prompt += line.value
                    else:
                        on_buggy_hunk = True
            # Clean tail
            if on_buggy_hunk:
                func_prompt += f'{placeholder}\n'
                on_buggy_hunk = False

        func_prompts.append({
            'line_range': (start_line, end_line),
            'func_prompt': func_prompt,
            'buggy_func': func_node.text,
        })
    return func_prompts