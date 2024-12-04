@echo off
setlocal enabledelayedexpansion

REM 设置输出目录
set OUTPUT_DIR=csharp_out
if not exist %OUTPUT_DIR% mkdir %OUTPUT_DIR%

REM 遍历所有proto文件
for %%f in (output_protos\*.proto) do (
    echo Processing %%f...
    
    REM 使用protoc生成C#代码
    protoc --proto_path=output_protos --csharp_out=%OUTPUT_DIR% %%f
    
    if errorlevel 1 (
        echo Error processing %%f
    ) else (
        echo Successfully processed %%f
    )
)

echo Done.
pause