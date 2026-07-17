# DESIGN.md 使用说明

本项目已安装 `VoltAgent/awesome-design-md` 的设计提示词库。

## 当前启用的设计规范

项目根目录的 `DESIGN.md` 是 AI 默认会读取的设计规范。当前启用的是：

```text
docs/awesome-design-md/design-md/linear.app/DESIGN.md
```

选择 Linear 风格是因为它更简洁、克制、现代，适合把 BI 后台做得更轻、更好看，同时保留高频看数需要的信息密度。

## 怎么使用

在让 AI 改页面或新增页面时，直接说明：

```text
请参考项目根目录 DESIGN.md 的视觉规范，保持当前 BI 后台的信息密度和组件一致性。
```

如果要更明确，可以这样说：

```text
请按 DESIGN.md 改造销售概览页：统一颜色、字号、卡片、表格、筛选栏和图表容器样式。
```

## 怎么切换风格

完整设计库在：

```text
docs/awesome-design-md/design-md
```

每个子目录都有一个 `DESIGN.md`。想换风格时，把对应文件复制到项目根目录覆盖当前的 `DESIGN.md` 即可。

例如切换为 Linear 风格：

```powershell
Copy-Item -Force docs\awesome-design-md\design-md\linear.app\DESIGN.md DESIGN.md
```

例如切换为 Vercel 风格：

```powershell
Copy-Item -Force docs\awesome-design-md\design-md\vercel\DESIGN.md DESIGN.md
```

## 推荐给本项目的备选风格

- `ibm`：企业后台、数据平台、BI 报表，稳重清晰。
- `linear.app`：现代 SaaS 后台，克制、精密、轻量。
- `vercel`：开发者平台感强，黑白清晰，适合技术型产品。
- `sentry`：监控、日志、异常分析类界面，适合数据密集页面。
- `mintlify`：文档和阅读体验好，适合帮助中心或说明页。

## 注意

这个库不是 npm 依赖，也不需要运行安装命令。它的“安装”就是把 `DESIGN.md` 放进项目，让 AI 工具读取它作为视觉设计约束。
