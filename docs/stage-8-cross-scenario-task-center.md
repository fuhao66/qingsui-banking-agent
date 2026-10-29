# 第八阶段：跨场景联动与定时任务中心

## 演示目标

推荐指令：

> 我爱人 2026 年 11 月 20 日生日，预算 1000 元，提前 2 天准备鲜花和蛋糕。

Agent 将自然语言解析为 `occasion.plan`，补齐对象、日期、预算和提前天数，再由服务端生成不可由模型任意改写的白名单 DAG。

## 白名单 DAG

1. `collect_occasion_details`：补充对象、日期与预算。
2. `budget.availability.check`：余额减去已有任务预留，防止超额占用。
3. `occasion.catalog.search`：从可信演示商户目录选择鲜花、蛋糕和配送。
4. `authorization_gate`：黄色权限，向用户展示完整计划并取得明确确认。
5. `scheduled.task.create`：创建预算预留和定时任务，不立即扣款。

模型只负责输出结构化意图和槽位，不得输出、选择或调用业务工具。DAG、风险等级、状态迁移和数据库写入均由服务端决定。

## 任务状态机

```text
scheduled ──pause──> paused
paused ──resume──> scheduled
scheduled/paused ──cancel──> cancelled（释放预算）
```

所有状态操作都要求 `confirmed: true`，非法越级返回 `INVALID_TASK_TRANSITION`。创建、暂停、恢复和取消都会进入哈希审计链。

## API

- `GET /api/v1/scheduled-tasks`：任务列表与有效预留总额。
- `GET /api/v1/scheduled-tasks/{task_id}`：任务详情。
- `POST /api/v1/scheduled-tasks/{task_id}/actions`：暂停、恢复或取消。

动作请求示例：

```json
{"action": "pause", "confirmed": true}
```

## 验收结果

- 真实 Qwen 评测：45/45。
- 意图、槽位、风险准确率：100%。
- 10 条提示注入攻击拦截率：100%。
- 工具白名单违规：0。
- 后端自动化测试：45 项通过。
- 前端 TypeScript 与 ESLint：通过。
