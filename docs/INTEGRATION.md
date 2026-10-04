# SEIKCHA 信息层 · 前端对接指南（INTEGRATION）

> 读者：网站前端工程师。读完这一篇即可完成信息因子接入，无需了解爬虫实现。
> 维护方：info-pipeline 管道负责人。更新时间：2026-10-03（管线 v1.0）。

---

## 1. 你会拿到什么（一句话）

**一个每日更新的 JSON 快照文件**，放在 GitHub 仓库 `seikcha-info-pipeline` 里，通过 jsDelivr CDN 分发——
它就是一个**免服务器、免鉴权的"静态 API"**：前端 `fetch` 一个 URL 即可，没有后端、没有 token、没有跨域问题（CDN 已带 CORS 头）。

> 为什么不是动态 API：数据每天只更新一次，静态文件 + CDN 边缘节点比任何动态服务更快、更稳、免费，且天然防宕机。

>

> 数据从哪来（前端只需了解，不影响对接）：天气=Open-Meteo；治安=ACLED 官方公开月度表（联合国 HDX 分发）；
> 冲突波动/节点/口岸=GDELT 新闻检索 + Google News RSS 备源——全链路免账号，多级降级，每级在快照 evidence 里留痕。

## 2. 30 秒接入（原生 JS）

```js
const BASE = 'https://cdn.jsdelivr.net/gh/stone-users/seikcha-info-pipeline@main/snapshots';
const today = new Date().toISOString().slice(0, 10); // 业务日期按北京时间，见 §4

async function loadInfoDay(date) {
  for (const file of [`${date}.json`, 'latest.json']) {   // 日期寻址 → latest 兜底
    try {
      const r = await fetch(`${BASE}/${file}`);
      if (r.ok) return await r.json();
    } catch { /* 试下一个 */ }
  }
  return null; // → 前端回退默认档，界面给弱提示（见 §6）
}
```

**TypeScript 项目直接用现成模块**：拷贝网站引擎里的 `src/engine/infoSnapshot.ts`（零依赖、单文件、已测试），
然后一行调用：

```ts
import { fetchInfoSnapshot, todayStr, INFO_DEFAULTS } from './engine/infoSnapshot';

const info = await fetchInfoSnapshot('A', todayStr());  // 走廊 'A'~'H'
// info = { fr03: '段基准', fr15: '平', ct04: 1, ct05: '常规', ct06: '正常' }
```

> 该模块已内置：校验（任一字段非法 → 整份作废）、按日期缓存（单页会话只发一次请求）、
> 8 秒超时、逐级回退。签名 `fetchInfoSnapshot(corr, date)` 是冻结契约，不要改动。
> 它依赖 `src/engine/types.ts` 里的 `InfoSnapshot` 类型（同样只读拷贝）。

## 3. 快照 JSON 结构（schema）

```jsonc
{
  "date": "2026-10-03",              // 业务日期（UTC+8）
  "generated_at": "2026-10-03T09:01:23+08:00",
  "pipeline_version": "1.0",
  "corridors": {                     // 8 条权威走廊 A~H，缺一不可
    "A": {
      "fr03": "段基准",              // 治安热度：'段基准'|'低'|'中'|'高'|'极高'
      "fr15": "平",                  // 天气预报：'好'|'平'|'暴雨'|'极端'
      "ct04": 1,                     // 冲突波动：0|1|2|3（数字）
      "ct05": "常规",                // 节点安全：'正常'|'常规'|'收紧'|'关闭'
      "ct06": "正常"                 // 口岸运行：'通畅'|'正常'|'拥堵'|'关闭'
    },
    "B": { "...": "同上" }, "C": {}, "D": {}, "E": {}, "F": {}, "G": {}, "H": {}
  },
  "evidence": {                      // 证据留痕（审计用，前端一般不用渲染）
    "fr15": [{ "source": "Open-Meteo", "url": "https://...", "note": "..." }],
    "fr03": [], "ct04": [], "ct05": [], "ct06": []
  },
  "st_suggestion": {                 // ST-01 态势建议（⚠ 见 §7，仅供参考，不得自动生效）
    "B": { "suggestion": "S2", "basis": "ct04=3, ct05=常规, ct06=正常" }
  }
}
```

**取值含义与评分阈值出处**（打分在管道端完成，前端只展示，不要自行改档）：

| 字段 | 评分卡 | 档位含义 |
|---|---|---|
| fr03 | rating_cards.FR03 | 月化非武装事件数：<5 低 / 5–15 中 / 15–30 高 / >30 极高；'段基准'=回退段档案 |
| fr15 | rating_cards.FR15 | 未来72h沿线最大累积降雨(mm)：<10 好 / 10–50 平 / 50–150 暴雨 / >150 极端 |
| ct04 | rating_cards.CT04 | 近7日与近90日武装事件之比 r：<0.7→0 / <1.5→1 / ≤3→2 / >3→3（冲突骤变捕捉） |
| ct05 | rating_cards.CT05 | 节点（桥/枢纽）安全：**'关闭'=该段暂停承保（禁售）** |
| ct06 | rating_cards.CT06 | 口岸运行：**'关闭'=该段暂停承保（禁售）** |

## 4. 取数规则与时序（重要）

- **更新时间**：每日 **01:00 UTC（≈北京 09:00 / 仰光 07:30）** 由 GitHub Actions 自动生成并提交。
- **首选按日期取** `<BASE>/YYYY-MM-DD.json`：文件一经写出**永不变更**，CDN 缓存永不失真。
- **`latest.json` 只是兜底**（当天管道未跑/失败时给昨天的数据）：jsDelivr 对 `@main` 分支引用的缓存约 12 小时，
  所以 latest 可能滞后——这就是为什么首选日期寻址。
- **业务日期按北京时间**（UTC+8），不要用 UTC 日期字符串，否则 UTC 0–8 点之间会取错日期文件。
- 三级回退：`日期文件 → latest.json → 代码内置默认档`。默认档必须精确等于：

  ```json
  { "fr03": "段基准", "fr15": "平", "ct04": 1, "ct05": "常规", "ct06": "正常" }
  ```

  （注意 ct05 默认是 **'常规'** 不是 '正常'——与评分卡基线一致。）

## 5. 跨走廊报价怎么取（最不利合并）

一条报价路径可能跨多条走廊。保守口径（与模型方法论 PRC3"准备金按路径最坏段"一致）：
**取路径涉及走廊的最不利档位**。现成函数：

```ts
import { mergeWorstCorridor } from './engine/infoSnapshot';
const info = mergeWorstCorridor(['A', 'B'], day);  // day = loadInfoDay(todayStr()) 的结果
```

规则：fr03/fr15/ct05/ct06 按档位序取最坏；ct04 取最大值；走廊 ID 只认权威 A~H（假设段 W/N/S 自动忽略）。

## 6. 失败弱提示规范

快照未连接（三级回退全命中默认档）时，界面给**弱提示**（不打断报价流程），例如：

> 报价副标题：`信息因子：基准档（快照未连接，已回退）`
> 正常时：`信息因子：2026-10-03 每日快照已生效`

**披露纪律：媒体沉默 ≠ 安全**——快照里无证据的走廊按基准档处理，界面不得表述为"安全"。

## 7. `st_suggestion` 的红线

`suggestion`（S0–S3）是管道对 ST-01 态势状态的**每日建议档**，依据 ct04/ct05/ct06 信号。
**ST-01 是人工定级流程**（月事件计数+准入+证实遇袭；承保区域转移须人工批准并留痕）：

- 前端可以把它展示为"态势建议"（标注"人工定级参考"）；
- **不得**根据它自动改承保状态/禁售/转移——那会违反团队的模型治理红线。

## 8. 状态页（排障/演示用）

`https://stone-users.github.io/seikcha-info-pipeline/status/`
——每日自动更新：各数据源链路状态灯（真实/降级/兜底）、今日评分、30 天历史、证据链接。
如果前端"取不到新数据"，先看状态页就知道是管道问题还是网络问题。

## 9. 备用源与本地演示

| 源 | URL | 用途 |
|---|---|---|
| jsDelivr（主） | `https://cdn.jsdelivr.net/gh/<user>/seikcha-info-pipeline@main/snapshots` | 生产 |
| GitHub Pages（备） | `https://<user>.github.io/seikcha-info-pipeline/snapshots` | jsDelivr 不可用时 |
| 本地 `/snapshots` | 网站仓库 `webapp/public/snapshots/`（每日复制一份） | 比赛现场断网兜底 |

三个源内容相同、都带 CORS；切换只改构建环境变量 `VITE_INFO_SNAPSHOT_BASE`（Vite 项目），无需改代码。

## 10. 对接检查清单

- [ ] fetch 走 `日期.json → latest.json → 默认档` 三级
- [ ] 业务日期用 UTC+8 计算
- [ ] 校验五字段枚举（任一走廊非法 → 整份作废回退，宁缺毋错）
- [ ] ct05/ct06='关闭' 时该段展示"暂停承保"（引擎已处理，前端确认 UI 有禁售态）
- [ ] st_suggestion 只展示不执行
- [ ] 弱提示与披露语按 §6 措辞
