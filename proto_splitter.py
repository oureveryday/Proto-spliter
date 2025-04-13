import os
import re
import sys
from collections import defaultdict

def find_matching_brace(content, start_index):
    stack = 0
    for i in range(start_index, len(content)):
        if content[i] == '{':
            stack += 1
        elif content[i] == '}':
            stack -= 1
            if stack == 0:
                return i
    return -1

def parse_proto_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        content = file.read()

    messages = []
    for match in re.finditer(r'message\s+(\w+)\s*{', content):
        msg_name = match.group(1)
        start = match.start()
        end = find_matching_brace(content, start)
        if end != -1:
            messages.append((msg_name, start, end))

    field_pattern = r'(?:repeated|optional|required)?\s*([A-Z][A-Za-z0-9_]*)\s+[a-zA-Z0-9_]+\s*='

    message_dict = {}
    enum_dict = {}
    dependencies = defaultdict(set)

    # 构建message和enum字典
    for msg_name, start, end in messages:
        message_content = content[start:end+1]
        message_dict[msg_name] = message_content

    # 提取所有enum定义
    for enum in re.finditer(r'enum\s+(\w+)\s*{', content):
        enum_name = enum.group(1)
        start = enum.start()
        end = find_matching_brace(content, start)
        if end != -1:
            enum_dict[enum_name] = content[start:end+1]

    def extract_dependencies(msg_content):
        deps = set()
        
        # 标准字段类型匹配
        field_pattern = r'(?:repeated|optional|required)?\s*([A-Z][A-Za-z0-9_]*)\s+[a-zA-Z0-9_]+\s*='
        for match in re.finditer(field_pattern, msg_content):
            field_type = match.group(1)
            if field_type in message_dict or field_type in enum_dict:
                deps.add(field_type)
                
        # oneof内字段类型匹配
        oneof_pattern = r'oneof\s+\w+\s*{([^}]*)}'
        for oneof_match in re.finditer(oneof_pattern, msg_content):
            oneof_content = oneof_match.group(1)
            # 匹配oneof块内的字段类型
            oneof_field_pattern = r'\s*([A-Z][A-Za-z0-9_]*)\s+[a-zA-Z0-9_]+\s*='
            for field_match in re.finditer(oneof_field_pattern, oneof_content):
                field_type = field_match.group(1)
                if field_type in message_dict or field_type in enum_dict:
                    deps.add(field_type)
        
        # 匹配map字段中的值类型
        map_pattern = r'map\s*<\s*\w+\s*,\s*([A-Z][A-Za-z0-9_]*)\s*>\s+[a-zA-Z0-9_]+\s*='
        for match in re.finditer(map_pattern, msg_content):
            value_type = match.group(1)
            if value_type in message_dict or value_type in enum_dict:
                deps.add(value_type)
        
        return deps

    # 为每个message构建依赖关系
    for msg_name, msg_content in message_dict.items():
        dependencies[msg_name] = extract_dependencies(msg_content)
        
    # 为每个enum添加空依赖集合（enum不依赖其他类型）
    for enum_name in enum_dict:
        dependencies[enum_name] = set()

    # 检测循环依赖
    def detect_cycles(graph):
        visited = set()
        path = set()
        cycles = []
        
        def dfs(node):
            if node in path:
                # 找到循环
                cycle = []
                for n in path:
                    cycle.append(n)
                cycles.append(cycle)
                return True
                
            if node in visited:
                return False

            visited.add(node)
            path.add(node)

            # 使用 graph.get(node, []) 避免键不存在的情况
            for neighbor in graph.get(node, []):
                if dfs(neighbor):
                    return True

            path.remove(node)
            return False

        # 对图中所有节点的副本进行遍历
        nodes = list(graph.keys())
        for node in nodes:
            if node not in visited:
                dfs(node)

        return cycles

    # 构建依赖关系
    message_dict_copy = message_dict.copy()
    for msg_name in message_dict_copy:
        dependencies[msg_name] = extract_dependencies(message_dict[msg_name])

    # 检测循环依赖
    cycles = detect_cycles(dependencies)
    if cycles:
        print("检测到循环依赖:", cycles)
        # 打破循环依赖
        for cycle in cycles:
            # 移除最后一个节点到第一个节点的依赖
            if cycle[0] in dependencies[cycle[-1]]:
                dependencies[cycle[-1]].remove(cycle[0])

    return message_dict, enum_dict, dependencies

def write_proto_files(message_dict, enum_dict, dependencies, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    written_files = set()
    import_graph = {}  # 用于检测循环导入
    merged_files = {}  # 记录已合并的文件

    # 构建完整的导入图
    for name, deps in dependencies.items():
        import_graph[name] = set(deps)

    # 预先处理依赖图，解决循环导入
    def find_cycles():
        cycles = []
        visited = set()
        path = []
        path_set = set()

        def dfs(node):
            if node in path_set:
                # 找到循环
                idx = path.index(node)
                cycles.append(path[idx:] + [node])
                return
            if node in visited:
                return
            visited.add(node)
            path.append(node)
            path_set.add(node)
            for neighbor in import_graph.get(node, []):
                dfs(neighbor)
            path.pop()
            path_set.remove(node)

        for node in import_graph:
            if node not in visited:
                dfs(node)
        return cycles

    # 合并循环依赖的文件
    def merge_cycle_files():
        cycles = find_cycles()
        if not cycles:
            return
        print(f"检测到 {len(cycles)} 个循环导入:")
        for cycle in cycles:
            if len(cycle) <= 1:  # 跳过自循环
                continue
            print(f"  循环: {' -> '.join(cycle)}")
            # 移除末尾的重复节点
            if cycle[0] == cycle[-1]:
                cycle = cycle[:-1]
            merge_name = cycle[0]
            print(f"  解决方案: 将 {', '.join(cycle)} 合并到 {merge_name}.proto")
            for node in cycle:
                merged_files[node] = merge_name
            # 更新导入图：移除循环中内部相互依赖，并将其他文件对循环中任一文件的依赖重定向为合并文件
            for node in cycle:
                for other in cycle:
                    if other in import_graph[node]:
                        import_graph[node].remove(other)
            for src, targets in import_graph.items():
                if src not in cycle:
                    cycle_deps = set(target for target in targets if target in cycle)
                    if cycle_deps:
                        targets.difference_update(cycle_deps)
                        targets.add(merge_name)

    merge_cycle_files()

    # 获取文件中引用的所有类型（包括字段、参数等）
    def get_all_referenced_types(content):
        types = set()
        # 1. 常规字段
        field_pattern = r'(?:repeated|optional|required)?\s+([A-Z][A-Za-z0-9_]*)\s+[a-zA-Z0-9_]+\s*='
        for match in re.finditer(field_pattern, content):
            types.add(match.group(1))
        # 2. 无修饰符字段
        simple_field_pattern = r'(?<![a-zA-Z0-9_])([A-Z][A-Za-z0-9_]*)\s+[a-zA-Z0-9_]+\s*='
        for match in re.finditer(simple_field_pattern, content):
            fld = match.group(1)
            if fld not in {'OPTIONAL','REQUIRED','REPEATED'}:
                types.add(fld)
        # 3. oneof字段
        oneof_pattern = r'oneof\s+\w+\s*{([^}]*)}'
        for oneof_match in re.finditer(oneof_pattern, content):
            oneof_content = oneof_match.group(1)
            for field_match in re.finditer(r'\s*([A-Z][A-Za-z0-9_]*)\s+[a-zA-Z0-9_]+\s*=', oneof_content):
                types.add(field_match.group(1))
        # 4. map字段值类型
        map_pattern = r'map\s*<\s*\w+\s*,\s*([A-Z][A-Za-z0-9_]*)\s*>'
        for match in re.finditer(map_pattern, content):
            types.add(match.group(1))
        # 5. rpc或method中的参数和返回类型
        method_pattern = r'(?:rpc|method)\s+\w+\s*\(\s*([A-Z][A-Za-z0-9_]*)\s*\)\s*returns\s*\(\s*([A-Z][A-Za-z0-9_]*)\s*\)'
        for match in re.finditer(method_pattern, content):
            types.add(match.group(1))
            types.add(match.group(2))
        return types

    # 修改后的导入生成函数
    # 参数 merged_group 为当前写入的合并组（合并文件时所有被合并的类型列表）
    def generate_imports(file_name, file_content, merged_group=None):
        imports = set()
        referenced = get_all_referenced_types(file_content)
        # 如果是合并文件，则额外添加每个被合并类型的全局依赖
        if merged_group:
            for t in merged_group:
                referenced.update(dependencies.get(t, set()))
        for ref_type in referenced:
            if ref_type == file_name:
                continue
            # 如果该类型定义在本工程中（来自message_dict或enum_dict）
            if ref_type in message_dict or ref_type in enum_dict:
                # 如果ref_type属于合并组内部则跳过
                if merged_group and ref_type in merged_group:
                    continue
                # 如果该类型已经合并到其他文件，则引入合并文件名
                if ref_type in merged_files:
                    target_file = merged_files[ref_type]
                    if target_file != file_name:
                        imports.add(target_file)
                else:
                    imports.add(ref_type)
        return imports

    def write_file(name, content=None):
        if name in written_files:
            return
        # 已经被合并到其他文件则不独立生成
        if name in merged_files and name != merged_files[name]:
            return
        file_path = os.path.join(output_dir, f'{name}.proto')
        with open(file_path, 'w', encoding='utf-8') as file:
            full_content = 'syntax = "proto3";\n\n'
            # 处理合并文件
            if name in merged_files and name == merged_files[name]:
                # 取出所有被合并到该文件的类型
                merged_group = [t for t, m in merged_files.items() if m == name]
                file_content = ""
                # 添加枚举定义
                for type_name in merged_group:
                    if type_name in enum_dict:
                        file_content += enum_dict[type_name] + "\n\n"
                # 添加消息定义
                for type_name in merged_group:
                    if type_name in message_dict:
                        file_content += message_dict[type_name] + "\n\n"
                imports = generate_imports(name, file_content, merged_group)
                for imp in sorted(imports):
                    full_content += f'import "{imp}.proto";\n'
                if imports:
                    full_content += '\n'
                full_content += file_content
            else:
                # 普通文件处理
                if name in enum_dict:
                    file_content = enum_dict[name]
                elif content:
                    file_content = content
                elif name in message_dict:
                    file_content = message_dict[name]
                else:
                    file_content = ""
                imports = generate_imports(name, file_content)
                for imp in sorted(imports):
                    full_content += f'import "{imp}.proto";\n'
                if imports:
                    full_content += '\n'
                full_content += file_content
            file.write(full_content)
            written_files.add(name)

    # 先写入所有合并组目标文件
    for name in merged_files:
        if merged_files[name] == name:
            write_file(name)
    # 再写入所有未生成的枚举和消息文件
    for name in enum_dict:
        if name not in written_files:
            write_file(name, enum_dict[name])
    for name in message_dict:
        if name not in written_files:
            write_file(name, message_dict[name])
def main():
    input_file = 'input.proto'
    output_dir = 'output_protos'

    message_dict, enum_dict, dependencies = parse_proto_file(input_file)
    write_proto_files(message_dict, enum_dict, dependencies, output_dir)

if __name__ == '__main__':
    main()