# SEIKCHA 信息层每日抓取管道（info-pipeline）

每天自动抓取网络开源数据 → 按评分卡规则打档 → 产出当日"信息因子快照"（InfoSnapshot），
供 SEIKCHA 保费导航网站实时调价。本仓库只产出**聚合计数与档位**，不落任何原始事件行。

## 一句话架构

```
Open-Meteo(天气 fr15) ─┐
ACLED(治安 fr03/冲突 ct04) ─┼→ score.py 规则出分 → validate 校验 → snapshots/YYYY-MM-DD.json
新闻/口岸(ct05/ct06) ─┘         （阈值唯一权威 = factor_tables.json → rating_cards）
                                        ↓ 提交进本仓库（提交历史=审计留痕）
                                        ↓ jsDelivr / GitHub Pages（CORS）
                        网站 fetchInfoSnapshot(corr, date) 按日期拉取 → 引擎调价
```

## 数据源降级链（关键设计）

**fr15 / ct04 永远不需要你提供任何凭证**——Open-Meteo 与 GDELT 都免注册；ACLED 是可选增强：

| 因子 | ① 浏览器辅助缓存 | ② ACLED OAuth | ③ GDELT 代理 | 全失败 |
|---|---|---|---|---|
| fr15 天气 | — | — | Open-Meteo（免key真实） | 基准档 '平' |
| ct04 冲突波动 | ACLED 事件计数（浏览器导出缓存） | ACLED 事件计数（服务端直连，常被 CF 拦） | **GDELT 媒体覆盖比值（免key真实）** | 基准档 1 |
| fr03 治安热度 | ACLED 月化计数（同上） | 同上 | 段基准（引擎回退段档案档） | 段基准 |
| ct05 节点安全 | — | — | **GDELT 新闻检索+规则初判**（"关闭"须≥2独立域名） | 基准档 '常规' |
| ct06 口岸运行 | — | — | **GDELT 口岸新闻+规则初判**（同上） | 基准档 '正常' |
| ST-01 态势 | 人工定级（红线） | — | 每日出**建议档**+证据（快照 `st_suggestion`+审计表） | 维持段档案 |

**浏览器辅助缓存（本地演示级真实数据）**：登录 ACLED 后在站点页内 fetch 导出 90 天 slim 事件 →
`cache/acled_events_cache.json`（窗口覆盖近90天且非空即生效），管道自动读取聚合。
该文件与 `.env`、`.acled_session.json` 均已 gitignore（含原始事件行，不公开分发——ACLED 条款）。

**为什么 GDELT 只供 ct04 不供 fr03**：ct04 的评分输入是"近7日÷近90日基线"的**比值**，
对计量单位不敏感（事件数或媒体覆盖强度都成立），GDELT 的覆盖量序列可直接代入同一评分卡；
fr03 的阈值是**绝对事件数**（<5/15/30），媒体覆盖份额不可比，硬套=打擦边球，故只按段基准回退。
GDELT 口径：走廊沿线城市英文名×武装冲突关键词的英文报道 90 日覆盖量时间序列，
90 日内非零天数<5 视为"媒体沉默≠安全"→落基准档；限流严格（429），走廊间串行 20s+递增退避。

## 目录

```
pipeline/            抓取与评分（纯标准库，零 pip 依赖）
  corridors.py       走廊A~H ↔ 城市坐标/ACLED admin1 映射（来源=02_route_network.md + cities.ts）
  net.py             标准库 HTTP GET（带重试）
  score.py           评分卡规则引擎（唯一出分点；基准档=webapp INFO_DEFAULTS）
  validate.py        快照 schema 校验（非法取值=中止发布）
  fetch_openmeteo.py fr15：走廊沿线未来72h降雨（单次批量请求，走廊取最不利点）
  fetch_acled.py     fr03/ct04：ACLED 事件计数聚合（需 key；--mock-acled 仅离线联调）
  fetch_gdelt.py     ct04 无key备源：GDELT 媒体覆盖比值（免注册，限流退避）
  fetch_news.py      ct05/ct06：GDELT 新闻检索+规则初判；另产出 ST-01 每日建议档
  build_snapshot.py  入口：数据源降级链编排 + 合成快照 + audit/*.md
tests/               评分卡边界 + schema 校验 + GDELT 比值纯函数 + 状态报告（unittest，44 用例）
snapshots/           产物：每日快照 + latest.json
audit/               每日审计 MD（证据 URL + 告警 + 披露）
status/              每日状态页：index.html（静态壳）+ status.json/history.json（每日生成）
docs/INTEGRATION.md  前端对接指南（给网站前端工程师的一篇文档）
.github/workflows/   daily.yml（每日01:00UTC）+ keepalive.yml（防60天停摆）
```

## 本地运行

```bat
cd info-pipeline
python -m unittest discover -s tests -v        :: 单测（不绿不发布）
python pipeline/build_snapshot.py              :: 生成今日快照（fr15 真实 + ct04 GDELT 真实；无需任何 key）
python pipeline/build_snapshot.py --mock-acled --date 2026-10-03   :: 全 mock（离线联调）
python pipeline/build_snapshot.py --copy-to ..\the-seikcha\webapp\public\snapshots
```

ACLED 凭证（可选增强）：`copy .env.example .env` 后填 `ACLED_EMAIL` / `ACLED_PASSWORD`
（OAuth 账号密码，2024 后不再用 key）。本地运行时管道不读 `.env` 文件本身——
先 `set ACLED_EMAIL=...` / `set ACLED_PASSWORD=...`（或用 PowerShell `$env:`）再跑。
注意：即便配好凭证，Cloudflare 仍可能拦截服务端请求（403），管道会自动降级 GDELT 并在审计里留痕；
真实 ACLED 近期数据走"浏览器辅助缓存"（见上节）。

## 部署（GitHub 全托管）

1. 本仓库 push 到你的 GitHub（公开仓库）；
2. Settings → Secrets → Actions 添加 `ACLED_EMAIL`、`ACLED_PASSWORD`（可选但推荐：
   **Actions runner IP 实测可通过 Cloudflare 直连 OAuth**；当前免费档数据封存期间返回 0 事件，
   管道自动识别不采信并降级 GDELT，获批全量访问后自动恢复官方数据）；
3. Actions 启用 `daily-info-snapshot`（默认每日 01:00 UTC = 北京 09:00，可手动 workflow_dispatch）；
4. 网站拉取地址（二选一，均带 CORS）：
   - jsDelivr（主）：`https://cdn.jsdelivr.net/gh/<你的用户名>/seikcha-info-pipeline@main/snapshots/2026-10-03.json`
   - GitHub Pages（备）：仓库 Settings → Pages → Deploy from branch (main / root) 后
     `https://<你的用户名>.github.io/seikcha-info-pipeline/snapshots/latest.json`
5. 网站侧在 `webapp/.env.production` 设 `VITE_INFO_SNAPSHOT_BASE=<上述目录URL>` 重新 build。

**运维备忘（2026-10-03 首跑实测）**：
- 本机 git push 需走系统代理：`git -c http.proxy=http://127.0.0.1:7899 push`（gh api 直连可用）；
  推送凭证走 `gh auth setup-git`（fine-grained PAT 需 All repositories + Administration/Contents/Actions 读写）。
- jsDelivr 对 `@main` 分支引用缓存约 12h：**同日重写文件后需手动刷缓存**
  `curl https://purge.jsdelivr.net/gh/stone-users/seikcha-info-pipeline@main/snapshots/latest.json`；
  正常每日一写的日期寻址文件无需关心。
- 手动 workflow_dispatch 重跑同一业务日期会重写当日快照（latest wins），审计依赖 git 历史。

## 每日状态页（GitHub Pages）

仓库根 `index.html` 自动跳转 `status/index.html`——启用 Pages 后访问
`https://<你的用户名>.github.io/seikcha-info-pipeline/` 即可看到：

- **今日数据源链路**：5 因子各一盏状态灯（绿=真实数据源 / 琥珀=降级链仍真实 / 红=基准档兜底或联调）；
- **今日走廊评分**：8 走廊 × 5 参数彩色表 + ST-01 建议表（含"人工定级"红线披露）；
- **近 30 天运行历史**：由每日快照 evidence 派生的链路档时间线；
- **今日证据**：可折叠的证据链接列表（审计留痕）。

数据文件 `status/status.json` / `status/history.json` 由 `build_snapshot.py` 每日生成
（生成失败不阻塞快照发布），随 snapshots/audit 一起提交——git 提交历史即状态变更留痕。
前端对接文档见 `docs/INTEGRATION.md`。

## 口径与红线（写代码前必读）

- 阈值唯一权威 = `the-seikcha/database/model-core/factor_tables.json → rating_cards`；
  本仓库 `score.py` 是其代码化，改动阈值必须先改 JSON 权威并同步（详见该文件头注释）。
- 基准档必须逐字等于 webapp `INFO_DEFAULTS`（注意 ct05='常规' 而非 '正常'——无证据=中性，
  不得因缺数据降保费）；缺数因子落基准档并在 evidence 留痕。
- 媒体沉默≠安全；ST-01 态势状态属人工定级流程，不在本管道范围。
- ACLED 条款：快照只含聚合计数与档位；发布公开仓库前请核对 ACLED 使用条款对
  聚合数据公开的要求，如不允许公开则转私有仓库并改托管方案。
- 中国大陆访问 GitHub/jsDelivr 偶发不稳：网站端有基准档回退 + 界面弱提示，演示兜底 =
  本地跑管道后 `--copy-to` 进 webapp/public。
