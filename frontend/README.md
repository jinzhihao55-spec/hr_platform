# 人事报表智能体（React 版）

> 从 HTML 静态模板完整迁移至 React 19 + Vite 架构，保持原 UI 和交互逻辑一致。

## 项目简介

人事报表智能体前端，覆盖 **工作台、日报、周报、计算日志、归档、口径与设置** 6 个核心页面。采用 SPA 单页路由，左侧深色导航栏 + 右侧内容区布局。

## 运行条件

- **Node.js** >= 18
- **npm** >= 9（推荐 `pnpm` 或 `yarn`）

## 运行说明

### 1. 安装依赖

```bash
cd frontend_react
npm install
```

### 2. 启动开发服务器

```bash
npm run dev
```

浏览器打开 `http://localhost:5173` 即可访问。

### 3. 生产构建

```bash
npm run build      # 输出到 dist/
npm run preview    # 本地预览产物
```

## 技术架构

| 层级 | 技术选型 |
|------|---------|
| 框架 | React 19.2 |
| 构建 | Vite 8.1 |
| 样式 | 原生 CSS（CSS 变量驱动） |
| 路由 | 自研轻量路由（`useState` 切换组件） |
| 数据 | 6 个独立模拟数据模块，纯 JS 导出 |
| 检查 | oxlint |

### 架构决策

- **无第三方路由库**（React Router 等）：6 个页面用 `useState` + 组件条件渲染，足够轻量，避免额外依赖。
- **无状态管理库**（Redux / Zustand 等）：每个页面内聚自身状态，跨页面无需共享数据。
- **无 UI 组件库**（Ant Design / TDesign 等）：完全还原 `app.css` 的设计风格。
- **CSS 变量**统一在 `index.css` 中定义（`--brand` / `--panel` / `--line` 等），各页面 CSS 复用。

## 项目结构

```
frontend_react/
├── index.html                  # 入口 HTML
├── package.json                # 依赖与脚本
├── vite.config.js              # Vite 配置
├── public/
│   └── favicon.svg             # 网站图标
└── src/
    ├── main.jsx                # React 入口（createRoot）
    ├── App.jsx                 # 根组件 + 页面路由表
    ├── index.css               # 全局 CSS 变量 + 重置 + 布局
    │
    ├── pages/                  # 6 个页面（每个 .jsx + .css）
    │   ├── Workbench.jsx       # 工作台（文件 + 对话 + 最近输出）
    │   ├── DailyReport.jsx     # 日报（KPI / 主表 / 在岗时长 / 校验）
    │   ├── WeeklyReport.jsx    # 周报（Sheet2 / Sheet1 双表）
    │   ├── ComputeLog.jsx      # 计算日志（trace 追踪 + 校验清单）
    │   ├── Archive.jsx         # 归档（文件夹折叠）
    │   └── Settings.jsx        # 口径与设置（8 张配置卡片）
    │
    ├── components/             # 11 个可复用组件
    │   ├── ArchiveFold/        # 归档文件夹（details/summary）
    │   ├── ChatPanel/          # 对话面板（消息列表 + 输入）
    │   ├── CheckItem/          # 校验清单项（✓ + ★ 硬标记）
    │   ├── DropZone/           # 文件拖拽上传区
    │   ├── FileRow/            # 文件行（上传状态展示）
    │   ├── GenerateCard/       # 生成按钮卡片
    │   ├── InputCard/          # 输入卡片（DropZone + FileRow）
    │   ├── MessageBubble/      # 对话气泡
    │   ├── RecentOutput/       # 最近输出列表
    │   ├── Sidebar/            # 左侧导航栏
    │   └── TraceItem/          # 计算追踪项（details/summary）
    │
    └── data/                   # 6 个模拟数据模块
        ├── mockData.js         # 工作台数据
        ├── dailyReportData.js  # 日报数据
        ├── weeklyReportData.js # 周报数据
        ├── archiveData.js      # 归档数据
        ├── computeLogData.js   # 计算日志数据
        └── settingsData.js     # 口径与设置数据
```

## 页面路由

| 侧边栏 Key | 路由 Key | 组件 | 说明 |
|-----------|---------|------|------|
| ▣ 工作台 | `workbench` | `Workbench` | 默认首页，文件上传 + 对话 + 输出 |
| ▤ 日报 | `daily` | `DailyReport` | KPI / 40 行主表 / 在校时长 / 12 项校验 |
| ▦ 周报 | `weekly` | `WeeklyReport` | 主体×事业部 / 成本中心×项目 |
| ✓ 计算日志 | `log` | `ComputeLog` | 5 条 trace 追踪 / 12 项校验 |
| ▢ 归档 | `archive` | `Archive` | 4 个日期文件夹折叠 |
| ⚙ 口径与设置 | `settings` | `Settings` | 8 张配置卡片（公式 / 字典 / LLM 等） |

## 设计说明

### 数据驱动渲染

所有表格、列表、配置卡片的渲染均由纯 JS 数据驱动，无硬编码 UI：

```js
// 示例：周报 Sheet2 表格
{sheet2Rows.map((row, i) => (
  <tr key={i} className={row._derive ? 'derive' : ''}>
    {sheet2Columns.map(col => (
      <td key={col.key} className={col.align}>{row[col.key]}</td>
    ))}
  </tr>
))}
```

新增一行数据只需在数组中追加对象，无需碰 JSX。

### 原生 HTML 行为还原

- **TraceItem / ArchiveFold**：使用原生 `<details>` + `<summary>` 实现折叠展开
- **Seg 分段器**：纯 `<a>` 标签 + `onClick` 阻止默认跳转
- **表格样式**：`align: 'r'` / `fx` / `derive` / `nm` 等 CSS class 精确还原原版

### CSS 变量体系

```css
:root {
  --bg: #f5f7fa;        /* 页面底色 */
  --panel: #fff;        /* 卡片 / 面板底色 */
  --ink: #1d2533;       /* 主文字 */
  --muted: #7b8696;     /* 次要文字 */
  --faint: #9aa4b2;     /* 更弱文字 */
  --line: #eaeef3;      /* 边框 / 分割线 */
  --brand: #2f6bb0;     /* 主色 / 强调 */
  --brand-soft: #eaf1f9;/* 浅主色 */
  --ok: #39a06e;        /* 通过 / 正向 */
  --pend: #c08a2e;      /* 待处理 */
  --bad: #c8554b;       /* 错误 / 硬阻断 */
  --r: 12px;            /* 统一圆角 */
  --shadow: ...;        /* 卡片阴影 */
}
```

## 测试说明

- `npm run lint`：运行 oxlint 静态检查
- `npm run build`：验证构建通过（当前：56 modules，零错误）
- `npm run dev` 后浏览器访问各页面手动测试


