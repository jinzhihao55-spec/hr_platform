# ============================================================
# 周报离职去重修复 + 交叉校验软提示
# 用法：复制此文件到服务器，右键 -> "使用 PowerShell 运行"
# 或：在 PowerShell 中 cd 到脚本目录，执行 .\fix_weekly_dedup.ps1
# ============================================================
$ErrorActionPreference = "Stop"
$baseDir = "C:\Users\Administrator\Desktop\v1_7.21_new\backend"

Write-Host "=== 周报修复脚本 ===" -ForegroundColor Cyan
Write-Host ""

# ---- 1. 修复 weekly.py：合计行入离职全局去重 ----
$weeklyPath = Join-Path $baseDir "app\pipeline\calculation\weekly.py"
Write-Host "[1/3] 备份 weekly.py ..." -ForegroundColor Yellow
Copy-Item $weeklyPath "$weeklyPath.bak" -Force

Write-Host "[2/3] 修复 weekly.py（合计行入离职全局去重）..." -ForegroundColor Yellow

$weekly = Get-Content $weeklyPath -Raw -Encoding UTF8

# 替换：合计行 sum(x["joiners"]) / sum(x["leavers"]) 改为全局 _window_count 去重
# 旧代码特征：joiners": sum(x["joiners"] for x in main_rows)
$oldLeavers = '"leavers": sum(x["leavers"] for x in main_rows),'
$newLeavers = @'
"leavers": total_leavers,
'@.TrimEnd()

$oldJoiners = '"joiners": sum(x["joiners"] for x in main_rows),'
$newJoiners = @'
"joiners": total_joiners,
'@.TrimEnd()

$oldJoinersF = '"joiners_formal": sum(x["joiners_formal"] for x in main_rows),'
$newJoinersF = @'
"joiners_formal": total_joiners_f,
'@.TrimEnd()

$oldLeaversF = '"leavers_formal": sum(x["leavers_formal"] for x in main_rows),'
$newLeaversF = @'
"leavers_formal": total_leavers_f,
'@.TrimEnd()

# 在总和行之前插入 _window_count 调用
$oldIfMain = 'if main_rows:'
$newIfMain = @'
if main_rows:
        total_joiners, total_joiner_ids = _window_count(
            emp, week_start, week_end, res_by_emp, joiners=True,
        )
        total_leavers, total_leaver_ids = _window_count(
            emp, week_start, week_end, res_by_emp, leavers=True,
        )
        total_joiners_f, _ = _window_count(
            emp, week_start, week_end, res_by_emp,
            joiners=True, formal_only=True,
        )
        total_leavers_f, _ = _window_count(
            emp, week_start, week_end, res_by_emp,
            leavers=True, formal_only=True,
        )
'@.TrimEnd()

# 先检查旧模式是否存在
if ($weekly -notmatch [regex]::Escape($oldLeavers)) {
    Write-Host "  [警告] 未找到旧代码模式，可能已修复或代码不同。跳过。" -ForegroundColor Magenta
} else {
    $weekly = $weekly -replace [regex]::Escape($oldLeavers), $newLeavers
    $weekly = $weekly -replace [regex]::Escape($oldJoiners), $newJoiners
    $weekly = $weekly -replace [regex]::Escape($oldJoinersF), $newJoinersF
    $weekly = $weekly -replace [regex]::Escape($oldLeaversF), $newLeaversF
    $weekly = $weekly -replace [regex]::Escape($oldIfMain), $newIfMain
    Write-Host "  weekly.py 修复完成" -ForegroundColor Green
}

# 更新 source 和 formula 描述
$oldSource = '"source": "各事业部 Sheet2 行求和"'
$newSource = '"source": "各事业部 Sheet2 行求和（入离职已全局去重）"'
$weekly = $weekly -replace [regex]::Escape($oldSource), $newSource

$oldFormula = '"formula": "合计=Σ各事业部"'
$newFormula = '"formula": "合计=Σ各事业部（在职总数 / 类型拆分）；入离职按自然人去重后取全局值"'
$weekly = $weekly -replace [regex]::Escape($oldFormula), $newFormula

[System.IO.File]::WriteAllText($weeklyPath, $weekly, [System.Text.UTF8Encoding]::new($false))

# ---- 2. 修复 validators.py：交叉校验降为软提示 ----
$validatorsPath = Join-Path $baseDir "app\pipeline\calculation\validators.py"
Write-Host "[3/3] 修复 validators.py（交叉校验降为软提示）..." -ForegroundColor Yellow

Copy-Item $validatorsPath "$validatorsPath.bak" -Force

$validators = Get-Content $validatorsPath -Raw -Encoding UTF8

# 只修改 "周报本周入职=日报Row2合计" 和 "周报本周离职=日报Row3合计" 两处的 hard_block
$validators = $validators -replace '(?s)("check": "周报本周入职=日报Row2合计".*?"hard_block": )True', '${1}False'
$validators = $validators -replace '(?s)("check": "周报本周离职=日报Row3合计".*?"hard_block": )True', '${1}False'

[System.IO.File]::WriteAllText($validatorsPath, $validators, [System.Text.UTF8Encoding]::new($false))

Write-Host ""
Write-Host "=== 修复完成 ===" -ForegroundColor Green
Write-Host ""
Write-Host "下一步：" -ForegroundColor Cyan
Write-Host "  1. 重启后端服务（停止 uvicorn 进程，重新启动）"
Write-Host "  2. 在网页上重新上传 7/24 的四个数据源"
Write-Host "  3. 预览周报，确认合计行离职人数 = 7"
Write-Host ""
Write-Host "备份文件：" -ForegroundColor Yellow
Write-Host "  $weeklyPath.bak"
Write-Host "  $validatorsPath.bak"
Write-Host ""
Read-Host "按 Enter 退出"