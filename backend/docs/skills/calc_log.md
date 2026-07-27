# 计算日志规范（交付物 C）

> **类型**：Skill · **读者**：AI · **模式**：A + B  
> 主 Skill：[`SKILL_CALC.md`](SKILL_CALC.md) · 生成：Prompt 7 · 校验引用：[`validation.md`](validation.md)

每次出日报/周报必须同步产出。

---

## 必须覆盖

- **运行元信息**：报告日、基线日、星期、是否周报、节假日依据
- **输入清单**：四文件名称/行数/字段、截图 vs Excel（Q6）
- **日报 trace**：Row2–40；空白行标「空白行-不填」
- **在岗时长 trace** + B10 vs Row14
- **周报 trace**（出周报时）：Sheet2 主体×事业部 + Sheet1 成本中心×项目 + 周报校验
- **校验 12 项**逐项 passed/failed
- **人工决策**：补 LWD、招聘取数选择等

---

## 单行 trace 模板

```
行号 / 字段：Row3 今日离职
输入源：人员表
命中筛选：纳入口径 且 离职日期=2026-06-25 或 今日首次可见
命中明细：工号 EMP_*** → 计入；EMP_*** 昨日已可见 → 剔除
公式：COUNT = 1
中间值：候选 2 条，去重剔除 1 条
最终值：1
链式：Row9 = 昨日5 + 今日1 = 6
校验：Row7 = Row2 - Row3 自检
备注：无
```

派生行（6/7/12/17/18/19/22/33/37/40）须写左值、右值、公式、是否相等。  
例：`Row40=37(3)+38(2)+39(4)=9；Row18(9)==Row40(9) → True`

---

## 在岗时长 trace 模板

固定输出 8 行 BU trace，即使该 BU 为 0 也要写：

```
BU_A：YTD离职=1；有效平均样本=1；平均在职(年)=1.42；invalid_dates=0
BU_B：YTD离职=0；有效平均样本=0；平均在职(年)=null；invalid_dates=0
...
BU_H：YTD离职=0；有效平均样本=0；平均在职(年)=null；invalid_dates=0
合计：Σ(BU YTD)=1；B10=1；Sheet1 Row14=1；passed=true
```

若 `invalid_dates > 0`，在日志中列出脱敏记录数与字段类型（缺入职日期 / 离职早于入职），作为软提示。

---

## 周报 trace 模板（Sheet2 · 主体×事业部）

出周报时，每个事业部一行（口径见 [`weekly_report.md`](weekly_report.md)）：

```
事业部：{business_unit}
输入源：人员表（窗口结束日在职快照）
在职总数：{headcount}（正式={cnt_formal} / 实习={cnt_intern} / 劳务={cnt_labor}）
本周入职：{joiners}（归属日 ∈ 周一~窗口结束日）
本周离职：{leavers}（离职事实已生效）
前三项目：{name}({count})、{name}({count})、{name}({count})
校验：类型拆分=在职总数 → passed/failed
```

## 周报 trace 模板（Sheet1 · 成本中心×项目）

```
成本中心：CC_{project}
项目：{project}
在职人数：{headcount}
本周入职：{joiners}
本周离职：{leavers}
```

## 周报校验

- 各事业部：`正式+实习+劳务 = 在职总数`（硬阻断）
- 失败时写期望/实际，话术见 [`question_templates.md`](question_templates.md)

---

## 错误追溯

- 命中明细定位到**具体输入行**（脱敏 + 日期/单号）
- 链式行写「昨日值 + 增量 = 今日值」
- 校验失败写期望/实际/阻断动作（话术见 [`question_templates.md`](question_templates.md)）
