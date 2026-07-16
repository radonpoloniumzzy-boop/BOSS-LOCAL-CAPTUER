# BOSS 原生收藏与页面内扩展参考调查

调查日期：2026-07-16

## 结论

本次没有找到一个已经公开验证、可直接复用的“招聘方在推荐牛人页筛选后调用 BOSS 原生收藏，并在收藏管理页确认”的开源项目或 Codex skill。

现有项目主要集中在求职者侧的岗位搜索、投递和打招呼。它们可以提供 Chrome 扩展结构、页面内 DOM 适配和任务节流方面的参考，但不能证明招聘方推荐页的未沟通候选人能够被原生收藏。

当前最合适的下一步不是安装外部 skill 或更换自动化浏览器，而是在现有 Manifest V3 扩展中做一个一次性的“被动收藏诊断原型”：扩展不接管标签、不自动点击，由用户手动收藏一名测试候选人，扩展只记录脱敏后的控件结构和收藏前后状态。

## 候选项目

### Ocyss/boss-helper

- 仓库：[Ocyss/boss-helper](https://github.com/Ocyss/boss-helper)
- 定位：求职者侧 BOSS 助手，提供页面 UI 调整、筛选、批量投递和自动打招呼；不是招聘方候选人收藏工具。
- 维护状态：仓库首页显示持续维护，2026-07 仍有 release。
- 可借鉴：WXT/Manifest V3、content script、background、页面内 UI 与消息通信的目录分层。
- 不可直接证明：没有证据显示它实现了招聘方“推荐牛人 → 原生收藏 → 收藏管理页”的流程。
- 许可注意：仓库包含 MIT LICENSE，但 README 同时写有“禁止商业用途”的额外说明；复制代码前需要单独澄清许可，当前只参考架构和测试思路。

### loks666/get_jobs

- 仓库：[loks666/get_jobs](https://github.com/loks666/get_jobs)
- 当前问题：[关于 Boss 防检测的 Discussion #250](https://github.com/loks666/get_jobs/discussions/250)
- 定位：求职者侧多平台自动投递，不是招聘方收藏。
- 关键证据：维护者在 README 中明确记录 BOSS 新检测会造成网页回退，并在自动投递过程中不断刷新；Discussion #250 中也报告了登录后刷新、闪退以及 CDP/DevTools 控制相关现象。
- 对本项目的意义：这与本次“标签被接管后刷新或退出 BOSS”的现场结果一致，说明外部浏览器接管不是可靠验证接缝。
- 不建议采用：Discussion 中的反检测补丁、环境伪装和私有检测绕过建议缺乏稳定验收，也会扩大账号与维护风险。本项目不走绕过平台限制的路线。

### Wafaamu3113/boss-cli 与其 SKILL.md

- 仓库：[Wafaamu3113/boss-cli](https://github.com/Wafaamu3113/boss-cli)
- Skill：[boss-cli/SKILL.md](https://github.com/Wafaamu3113/boss-cli/blob/main/SKILL.md)
- 定位：求职者侧岗位搜索、推荐、申请、打招呼和聊天查询，依赖逆向接口及本地浏览器凭据。
- 不适用原因：命令集中没有招聘方候选人收藏；其 `recommend` 是求职者岗位推荐，`greet` 是求职者投递/打招呼，领域对象与本项目相反。
- 决策：不安装该 skill，不向它提供账号凭据，也不把其逆向接口当作招聘方收藏验证。

## 官方扩展能力

Chrome 官方文档说明，content script 可以在匹配页面中读取和修改 DOM，并通过消息机制与扩展其他部分通信；默认运行在与页面 JavaScript 隔离的执行环境中：[Chrome Content Scripts](https://developer.chrome.com/docs/extensions/develop/concepts/content-scripts)。程序化注入需要 `scripting` 与页面权限：[chrome.scripting](https://developer.chrome.com/docs/extensions/reference/api/scripting)。

现有项目已经有固定匹配 BOSS 域名的 content script，因此原型可以完全留在扩展内部，不需要 Codex/Playwright/CDP 认领标签。

## 推荐原型

1. 在扩展中增加默认关闭的“收藏诊断模式”。
2. 仅在 `/web/chat/recommend` 且用户主动开启时工作。
3. 使用 `MutationObserver` 被动观察可见候选卡和疑似收藏控件，不点击、不发请求。
4. 用户手动收藏一名测试候选人。
5. 只记录：页面路径、控件标签与 class/aria/title 的脱敏签名、可信 action identity 字段名称、收藏前后状态、时间。
6. 不记录：姓名、简历正文、Cookie、Token、完整请求头或未知查询参数。
7. 用户在 BOSS 收藏管理页手工确认结果后，再决定是否开发扩展内部的单次点击验证。

## 适用 skills

- `research`：本次用于一手来源调查。
- `prototype`：下一阶段用于构建可随时删除的被动诊断原型，回答“页面内扩展是否稳定观察到收藏状态”这一单一问题。
- `tdd`：在原型证明可行后，为脱敏、状态识别和禁写保护建立测试。
- `codebase-design`：将 BOSS 页面适配器与收藏任务状态机隔离。
- `implement`：只有真实单人手工验证成功后才进入正式实现。

不建议当前使用 `chrome:control-chrome`、`browser:control-in-app-browser` 或外部 `boss-cli` skill 来执行真实收藏。
