# 单批原生收藏：预计文件影响清单

本清单基于当前 `upstream/main`，用于实施前定位，不替代正式规格。实际文件以技术验证和测试驱动结果为准。

## 已完成的理解与安全准备

- `.gitignore`：补充 SQLite 备份、UI 状态和轮转日志忽略规则。
- `CONTEXT.md`：记录 Candidate、Platform Identity、Native Favorite、Favorite Pool、Initial/Secondary Screening 等统一语言。
- `docs/adr/0001-use-native-favorites-as-candidate-buffer.md`：记录使用平台原生收藏作为候选人缓冲池。
- `docs/adr/0002-separate-platform-action-identity-from-legacy-deduplication.md`：记录平台写操作身份与旧文本去重隔离。

## 预计修改

- `core/models.py`
  - 为 Screening Profile 或其持久模型表达岗位收藏评级配置。
  - 为 Automation Flow 表达筛选后动作、间隔和单批上限。
  - 增加收藏批次、任务、结果等跨层数据对象。

- `storage/migrations.py`
  - 通过向前迁移增加 Platform Identity、收藏批次/任务/动作记录结构。
  - 保留历史候选人、批次和筛选数据。

- `storage/repository.py`
  - 保存和读取岗位 Favorite Eligibility Policy。
  - 管理身份观察、配置快照、收藏任务状态转换、幂等领取和结果回传。

- `core/local_api.py`
  - 增加扩展读取收藏任务、领取下一项、回传结果、停止和查询状态的受鉴权接口。
  - 拒绝陈旧批次、非法状态转换和绕过任务快照的任意写操作。

- `ui/pages/ai_screen.py`
  - 在岗位编辑区增加 UR、SSR、SR、R、N 收藏评级多选项。
  - 显示“未配置不能自动收藏”的状态。

- `ui/pages/automation_flow.py`
  - 增加“仅采集并筛选／筛选并收藏”。
  - 增加节流和单批上限设置，并显示收藏状态汇总。

- `ui/main_window.py`
  - 在自动化 Initial Screening 完成后创建单批收藏任务。
  - 协调停止、恢复、失败重试、状态刷新和错误呈现。

- `extension/collector.js`
  - 扩充 BOSS 卡片身份证据采集，但不把敏感参数写入普通日志。
  - 保持现有 BOSS/猎聘卡片采集兼容。

- `extension/popup.html`
  - 展示当前筛选后动作、岗位收藏评级和收藏进度入口。

- `extension/popup.js`
  - 启动前展示桌面端锁定配置。
  - 把原 Source Page Context 交给收藏执行模块并呈现状态。

- `extension/favorite_runner.js`（预计新增）
  - 在原 BOSS 标签页中保持 Source Page Context、领取任务、串行执行并回传结果。
  - 平台动作通过可替换适配器隔离，具体 DOM 或同源请求方式由技术验证确定。

- `extension/service_worker.js`（按验证结果决定）
  - 只有当页面执行器需要现有后台状态协调时才修改；不默认把长任务迁入容易休眠的 MV3 后台。

- `extension/manifest.json`（预期不修改）
  - 当前权限预计足够。只有技术验证证明缺少必要权限时才做最小调整。

- `README.md` 与 `extension/README.md`
  - 功能实现并验证后补充单批模式、配置、限制和人工验收说明。

## 预计新增或扩展的测试

- `tests/test_favorite_workflow.py`（预计新增）：桌面端最高层完整工作流接缝。
- `tests/test_migrations.py`：旧数据库向前迁移与历史数据兼容。
- `tests/test_local_api.py`：收藏任务接口、鉴权、幂等和非法转换。
- `tests/test_automation_pipeline.py`：Initial Screening 完成后按配置生成收藏任务。
- `tests/test_screening_profiles_structured.py`：岗位收藏评级保存、复制和读取。
- `tests/test_ai_screen_page.py`：岗位收藏评级前端行为。
- `tests/test_automation_pipeline.py` 或对应页面测试：筛选后动作、批次快照和汇总。
- `extension/tests/extension_regression.test.js`：身份解析、页面上下文、串行执行、停止和结果分类。
- BOSS 脱敏 HTML/JSON 夹具：仅保存完成身份解析测试所需的最小字段，不保存 Cookie、Token 或真实候选人资料。

## 明确不修改

- `ai/prompt_manager.py`：第一阶段不修改 Prompt。
- `ai/provider.py`：第一阶段不修改 UR、SSR、SR、R、N 输出合同。
- 现有文本指纹候选人去重逻辑：第一阶段不迁移或重写。
- 猎聘平台适配：第一阶段不增加原生收藏。

## 实施门槛

在编写批量收藏实现前，必须先完成以下受控验证：

1. 在真实 BOSS 推荐页确认候选人主体标识、Recruiting Relationship 标识和临时请求参数的来源及稳定性。
2. 对一名测试候选人执行 Native Favorite。
3. 在 BOSS 收藏管理页确认该候选人可见。
4. 确认操作没有发送打招呼消息或触发其他平台动作。
5. 若验证失败，停止批量实现并输出技术验证报告。
