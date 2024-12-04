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

    def collect_all_dependencies(name, visited=None):
        """递归收集所有依赖，包括传递依赖"""
        if visited is None:
            visited = set()
        
        if name in visited:
            return set()
            
        visited.add(name)
        all_deps = set()
        
        # 直接依赖
        direct_deps = dependencies.get(name, set())
        all_deps.update(direct_deps)
        
        # 递归收集依赖的依赖
        for dep in direct_deps:
            all_deps.update(collect_all_dependencies(dep, visited))
            
        return all_deps

    def get_all_field_types(content):
        """收集所有字段类型，包括oneof内的"""
        types = set()
        
        # 收集常规字段类型
        field_pattern = r'(?:repeated|optional|required)?\s*([A-Z][A-Za-z0-9_]*)\s+[a-zA-Z0-9_]+\s*='
        for match in re.finditer(field_pattern, content):
            field_type = match.group(1)
            types.add(field_type)
        
        # 收集oneof中的字段类型
        oneof_pattern = r'oneof\s+\w+\s*{([^}]*)}'
        for oneof_match in re.finditer(oneof_pattern, content):
            oneof_content = oneof_match.group(1)
            for field_match in re.finditer(r'\s*([A-Z][A-Za-z0-9_]*)\s+[a-zA-Z0-9_]+\s*=', oneof_content):
                field_type = field_match.group(1)
                types.add(field_type)
        
        return types

    def write_file(name, content):
        if name in written_files:
            return
            
        file_path = os.path.join(output_dir, f'{name}.proto')
        with open(file_path, 'w', encoding='utf-8') as file:
            full_content = 'syntax = "proto3";\n\n'
            
            # 收集所有依赖
            all_deps = collect_all_dependencies(name)
            written_types = set()
            
            # 首先写入所有enum依赖
            for dep in sorted(all_deps):
                if dep in enum_dict and dep not in written_types:
                    full_content += enum_dict[dep] + '\n\n'
                    written_types.add(dep)
            
            # 再写入所有message依赖
            for dep in sorted(all_deps):
                if dep in message_dict and dep != name:
                    # 获取依赖message中的所有类型
                    dep_types = get_all_field_types(message_dict[dep])
                    # 写入依赖message中未写入的enum
                    for dep_type in sorted(dep_types):
                        if dep_type in enum_dict and dep_type not in written_types:
                            full_content += enum_dict[dep_type] + '\n\n'
                            written_types.add(dep_type)
                    full_content += message_dict[dep] + '\n\n'
            
            # 写入当前内容
            if name in enum_dict:
                full_content += enum_dict[name]
            else:
                # 当前message的enum依赖
                current_types = get_all_field_types(content)
                for current_type in sorted(current_types):
                    if current_type in enum_dict and current_type not in written_types:
                        full_content += enum_dict[current_type] + '\n\n'
                        written_types.add(current_type)
                full_content += content
                
            file.write(full_content)
            written_files.add(name)

    # 处理所有message和enum
    for name in list(message_dict.keys()) + list(enum_dict.keys()):
        if name not in written_files:
            write_file(name, message_dict.get(name, enum_dict.get(name)))
def main():
    input_file = 'input.proto'
    output_dir = 'output_protos'

    message_dict, enum_dict, dependencies = parse_proto_file(input_file)
    write_proto_files(message_dict, enum_dict, dependencies, output_dir)

if __name__ == '__main__':
    main()