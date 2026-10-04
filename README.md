# SEIKCHA 信息层每日抓取管道（info-pipeline）

每天自动抓取网络开源数据 → 按评分卡规则打档 → 产出当日"信息因子快照"（InfoSnapshot），
供 SEIKCHA 保费导航网站实时调价。本仓库只产出**聚合计数与档位**，不落任何原始事件行。

## 一句话架构

```
Open-Meteo(天气 fr15) ──────────┐
ACLED 公开月度表·HDX(治安 fr03) ─┼→ score.py 规则出分 → validate 校验 → snapshots/YYYY-MM-DD.json
GDELT / Google News RSS(其余) ──┘      （阈值唯一权威 = factor_tables.json → rating_cards）
                                        ↓ 提交进本仓库（提交历史=审计留痕）
                                        ↓ jsDelivr / GitHub Pages（CORS）
                        网站 fetchInfoSnapshot(corr, date) 按日期拉取 → 引擎调价
```

**全链路免账号**：所有数据源（Open-Meteo / 联合国 HDX 分发的 ACLED 公开月度表 / GDELT /
Google News RSS）均无需注册或凭证——GitHub Actions 克隆即跑，零密钥管理负担。

## 数据源降级链（关键设计）

| 因子 | 主源（真实数据） | 备源 | 全失败 |
|---|---|---|---|
| fr15 天气 | Open-Meteo（免key，未来72h降雨） | — | 基准档 '平' |
| ct04 冲突波动 | **GDELT 媒体覆盖比值**（免key，近7日/近90日比） | — | 基准档 1 |
| fr03 治安热度 | **ACLED 官方公开月度表**（联合国 HDX 分发，免账号；月度 admin1 聚合，滞后约1个月——与 FR03 评分卡"月化计数"口径一致） | — | 段基准（回退段档案历史画像） |
| ct05 节点安全 | **GDELT 新闻检索**（全走廊合并单查） | **Google News RSS**（GDELT 429 时兜底） | 基准档 '常规' |
| ct06 口岸运行 | **GDELT 口岸新闻**（全口岸单查） | **Google News RSS** | 基准档 '正常' |
| ST-01 态势 | 人工定级（红线） | — | 每日出**建议档**+证据（快照 `st_suggestion`+审计表） | 维持段档案 |

新闻双源共用同一套关键词规则引擎与保守口径（媒体沉默≠安全；"关闭"须≥2独立信源佐证——
GDELT 用域名、RSS 用出版方名作为独立信源单位）。查询预算：每日仅 2 次 GDELT + 至多 2 次 RSS。

**fr03 数据源说明（2026-10 实测）**：HDX 的 "Myanmar - Conflict Events" 由 ACLED 官方维护、
平台级持续更新（实测 as-of 滞后 2 天）——"12 个月数据封存"仅针对 ACLED 免费 API 账号，
公开分发渠道数据是新鲜的。管道经 HDX API 动态解析当月文件下载地址（as-of 日期会变，不写死），
下载失败时回退本地缓存 `cache/hdx_demo.xlsx`（gitignored）。粒度披露：月度 admin1 聚合、
滞后约 1 个月，与 FR03 评分卡的"月化非武装事件数"输入口径天然一致。
fetch_acled.py（OAuth 直连）保留为休眠代码：无凭证时自动跳过，未来获批官方 API 可零成本复用。

**为什么 GDELT 只供 ct04 不供 fr03 的"每日"口径**：fr03 阈值是绝对事件数（<5/15/30），
HDX 月度表恰好提供同口径月化计数；ct04 评分输入是"近7日÷近90日基线"的**比值**，
对计量单位不敏感，GDELT 覆盖量序列可直接代入同一评分卡。
GDELT 口径：走廊沿线城市英文名×武装冲突关键词的英文报道 90 日覆盖量时间序列，
90 日内非零天数<5 视为"媒体沉默≠安全"→落基准档；限流严格（429），串行+退避。

## 目录

```
pipeline/            抓取与评分（纯标准库，零 pip 依赖）
  corridors.py       走廊A~H ↔ 城市坐标/ACLED admin1 映射（来源=02_route_network.md + cities.ts）
  net.py             标准库 HTTP GET（带重试）
  score.py           评分卡规则引擎（唯一出分点；基准档=webapp INFO_DEFAULTS）
  validate.py        快照 schema 校验（非法取值=中止发布）
  fetch_openmeteo.py fr15：走廊沿线未来72h降雨（单次批量请求，走廊取最不利点）
  fetch_hdx.py       fr03：ACLED 官方公开月度表（HDX 分发，标准库解析 XLSX，免账号）
  fetch_acled.py     （休眠）ACLED OAuth 直连：无凭证自动跳过，获批官方 API 后可复用
  fetch_gdelt.py     ct04 无key备源：GDELT 媒体覆盖比值（免注册，限流退避）
  fetch_news.py      ct05/ct06：GDELT 主源 + Google News RSS 备源；另产出 ST-01 每日建议档
  build_snapshot.py  入口：数据源降级链编排 + 合成快照 + audit/*.md
tests/               评分卡边界 + schema 校验 + 新闻规则 + HDX/RSS 纯函数 + 状态报告（unittest，60 用例）
snapshots/           产物：每日快照 + latest.json
audit/               每日审计 MD（证据 URL + 告警 + 披露）
status/              每日状态页：index.html（静态壳）+ status.json/history.json（每日生成）
docs/INTEGRATION.md  前端对接指南（给网站前端工程师的一篇文档）
.github/workflows/   daily.yml（每日00:40UTC=北京08:40，错峰防跳班）+ keepalive.yml
```

## 本地运行

```bat
cd info-pipeline
python -m unittest discover -s tests -v        :: 单测（不绿不发布）
python pipeline/build_snapshot.py              :: 生成今日快照（fr15 真实 + ct04 GDELT 真实；无需任何 key）
python pipeline/build_snapshot.py --mock-acled --date 2026-10-03   :: 全 mock（离线联调）
python pipeline/build_snapshot.py --copy-to ..\the-seikcha\webapp\public\snapshots
```

无需任何凭证：直接 `python pipeline/build_snapshot.py` 即可全真实跑（HDX/GDELT/RSS 全部免账号；--mock-acled 仅离线联调用）。

## 部署（GitHub 全托管）

1. 本仓库 push 到你的 GitHub（公开仓库）；
2. 无需配置任何 Secrets（全链路免账号；如未来恢复 ACLED 官方 API 再添加）；
3. Actions 启用 `daily-info-snapshot`（默认每日 00:40 UTC = 北京 08:40，可手动 workflow_dispatch）；
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
