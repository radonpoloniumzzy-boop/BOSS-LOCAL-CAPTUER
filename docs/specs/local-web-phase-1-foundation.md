# 阶段 1：本地网页基础与安全迁移

## 目标

在不替换现有 PySide 桌面端和 Chrome 插件的前提下，建立只在本机运行的浏览器工作台基础。阶段 1 只负责首次设置、数据库只读状态、单实例安全和网页启停，为后续逐页迁移提供稳定入口。

## 过渡关系

- `app.py` 仍是现有桌面程序的默认入口，原有 PySide 页面和插件接口保持不变。
- `web_app.py` 是独立的本地网页入口，FastAPI 在 `127.0.0.1:17864` 提供 API 和前端静态文件。
- Chrome 插件仍连接旧桌面程序的 `127.0.0.1:17863`，阶段 1 不切换插件端口或行为。
- 新旧程序读取同一个数据目录时使用同一数据库锁，禁止同时运行。

## 首次设置与数据目录

启动配置保存在 `%LOCALAPPDATA%\RecruitingTalentWorkbench\bootstrap.json`，只包含 `data_dir`、`web_port`、`setup_completed` 和 `app_version`。其中不保存候选人数据、AI 密钥或插件 Token。

推荐顺序：

1. 项目 `data/boss_local_tool.db` 已存在时，推荐现有 `data` 目录并继续读取旧库。
2. 没有旧库且 D 盘存在时，推荐 `D:\HR-Workbench-Data`。
3. D 盘不存在时，推荐用户 Documents 下的 `RecruitingTalentWorkbench`。

磁盘根目录、Windows 系统目录、项目源码目录、不可写目录和无法识别的非空目录会被拒绝。确认后不自动移动旧数据、不覆盖 `config.json`，运行期间不能更换目录。

## 单数据库单实例

锁身份由数据库绝对路径生成。Windows 使用命名互斥量，锁文件仅保存进程和数据库路径诊断信息。网页程序、桌面程序和重复网页实例不能同时持有同一数据库；进程异常退出时 Windows 会释放互斥量，不产生永久死锁。

已有项目数据库会在网页服务启动前预先加锁。首次设置选择其他目录时，程序释放预占锁并锁定最终数据库。

## 数据库备份

数据库只在检测到 schema 版本确实低于当前版本时，使用 SQLite 一致性备份生成唯一的 `before_v<版本>` 备份。备份失败会停止升级并保留原数据库。阶段 1 没有新增 schema，因此当前版本数据库启动时不会产生重复备份。

## 本地接口

- `GET /api/health`：服务健康状态，不依赖数据库。
- `GET /api/setup/status`：首次设置状态和推荐目录。
- `POST /api/setup`：首次确认数据目录，仅允许同源请求且只能成功一次。
- `GET /api/app/status`：通过现有 repository 返回候选人和采集批次统计。

服务只接受 `127.0.0.1:17864` Host，不开放跨域。所有错误返回稳定的 `error.code` 和中文 `error.message`。

## 开发启动

后端与生产前端：

```powershell
cd D:\codex\BOSS-LOCAL-CAPTURE-review
.\.venv\Scripts\python.exe web_app.py
```

前端开发：

```powershell
cd web\frontend
npm.cmd install
npm.cmd test
npm.cmd run build
```

前端生产构建输出到 `web/frontend/dist`，由 FastAPI 本地提供，运行时不加载 CDN 或互联网资源。

## 本阶段不包含

- 不迁移候选人、岗位、AI、人工复核、Mapping 或报告业务页面。
- 不改变候选人入库与岗位绑定语义。
- 不改变 Chrome 插件、附件下载、旧聊天或远程控制行为。
- 不删除或重构现有 PySide 页面。
- 不在运行中更换数据目录。
