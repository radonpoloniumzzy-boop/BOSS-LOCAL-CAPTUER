# 招聘人才工作台

当前默认主入口是网页工作台。

如果你是第一次在新电脑上使用这个项目，推荐路径就是：

下载 `main`
→ 运行 `setup_web_workbench.cmd`
→ 双击 `launch_web_workbench.cmd`
→ 首次确认人才库目录
→ 从网页“设置”复制一次性连接码
→ Chrome 加载 `extension/`
→ 插件配对
→ 采集当前内容或自动滚动采集
→ 网页查看候选人和批次
→ 导出批次 Markdown

## 当前产品边界

- 网页端是当前正式主入口。
- Chrome 插件负责招聘平台页面采集。
- 网页端负责本地入库、候选人列表、采集批次、连接和批次 Markdown 导出。
- 岗位、Mapping、AI、人工复核、简历和沟通流程仍属于后续阶段。
- 旧桌面端只保留兼容入口，不是新增功能主线。

## 新电脑快速开始

1. 安装官方 [CPython 3.12](https://www.python.org/downloads/windows/)。
2. 获取当前 `main` 分支源码。
3. 双击 `setup_web_workbench.cmd`。
4. 初始化完成后，双击 `launch_web_workbench.cmd`。
5. 首次打开时按提示确认人才库目录。
6. 在网页“设置”页复制一次性连接码。
7. 在 Chrome 的 `chrome://extensions` 中加载 `extension/` 目录。
8. 在插件中粘贴连接码完成配对。
9. 开始采集、查看候选人和批次，并导出 Markdown。

详细说明见：

- [网页工作台快速开始](docs/guides/web-workbench-quick-start.md)
- [备份与恢复](docs/guides/backup-and-recovery.md)
- [当前预览版本说明](docs/releases/current-preview.md)

## 初始化与启动

### 初始化

双击：

```text
setup_web_workbench.cmd
```

它会：

- 检查官方 CPython 3.12；
- 在缺少 `.venv` 时创建本地虚拟环境；
- 使用 `.venv\Scripts\python.exe` 安装 `requirements.txt`；
- 验证网页前端产物、插件目录和启动文件是否完整。

初始化过程不会：

- 创建或修改人才库；
- 写入 bootstrap；
- 启动桌面端；
- 覆盖已有配置；
- 修改真实候选人数据；
- 要求 Node/npm 作为最终用户启动依赖。

### 启动网页工作台

双击：

```text
launch_web_workbench.cmd
```

启动器会显示真实检查步骤：

- 读取本机配置
- 检查运行环境
- 检查网页资源
- 检查端口和已有服务
- 连接人才库
- 确认数据库状态
- 打开浏览器

如果网页工作台已在运行，它会直接打开正确端口，不会启动第二个实例。

如果看到“缺少网页工作台运行环境”，先运行 `setup_web_workbench.cmd`，不要改用系统 Python 直接启动 `web_app.py`。

## Chrome 插件连接

网页模式下不要求用户手工输入 API 地址或 Token。

标准流程是：

1. 打开网页工作台。
2. 进入“设置”页。
3. 点击复制一次性连接码。
4. 在插件里粘贴。
5. 配对成功后，插件会安全记忆连接。

桌面兼容模式里的 API 地址 / Token 高级设置仍保留，但只作为兼容说明，不是网页工作台默认流程。

## 数据位置、备份与互斥

- 人才库数据与项目源码分离。
- bootstrap 默认保存在：

```text
%LOCALAPPDATA%\RecruitingTalentWorkbench\bootstrap.json
```

- 实际人才库目录在首次设置时由用户确认。
- 网页端和旧桌面端不能同时占用同一人才库。
- 不要把项目里的 `data/` 目录当成可以随手删除的缓存。
- 数据库故障时不得创建空库替代旧库。

备份与恢复细则见：
[backup-and-recovery.md](docs/guides/backup-and-recovery.md)

## 版本来源

当前预览版由多个组件组成，版本来源彼此独立：

- 核心工作台版本：`core/version.py`
- Chrome 插件版本：`extension/manifest.json`
- 前端包版本：`web/frontend/package.json`

当前代码基线请以 `main` 分支和对应提交为准，不把这些组件版本硬凑成一个虚构的统一大版本。

## 仓库结构

```text
<项目目录>\
  app.py
  web_app.py
  setup_web_workbench.cmd
  setup_web_workbench.py
  launch_web_workbench.cmd
  launch_web_workbench.py
  extension/
  web/
  core/
  storage/
  tests/
  docs/
```

## 开发与验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q
node extension\tests\extension_regression.test.js
cd web\frontend
npm.cmd test -- --run
npm.cmd run build
```

## 兼容入口

旧桌面端入口仍保留在：

- `launch_boss_local_tool.cmd`
- `launch_boss_local_tool.vbs`

但它属于兼容模式，不是当前默认 onboarding 路线。
