# 设置 conda 根目录
$condaRoot = "C:\Users\14649\anaconda3"

# 加载 conda PowerShell 支持
& "$condaRoot\shell\condabin\conda-hook.ps1"

# 强制切换到 dbd（不管当前是不是 base）
conda deactivate
conda activate dbd

# （可选）进入你的项目目录
Set-Location "C:\Users\14649\Desktop\English Vocabulary Learning Tool\Vocabulary Intelligence and Training for Adaptive Learning"

python main.py